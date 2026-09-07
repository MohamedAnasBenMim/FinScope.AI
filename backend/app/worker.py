"""Durable database queue. Each job runs in a killable child process."""

import argparse
import logging
import subprocess
import sys
import time
from datetime import timedelta

from app.config import settings
from app.db import Document, IngestionJob, SessionLocal, utcnow
from app.logging_config import configure_logging
from app.rag.vector_store import FinancialVectorStore
from app.services.ingestion import fail_job, process_job
from sqlalchemy import select, update

logger = logging.getLogger(__name__)


def claim_job(sessions=SessionLocal) -> str | None:
    with sessions() as session:
        job = session.scalar(
            select(IngestionJob)
            .where(IngestionJob.status == "PENDING")
            .order_by(IngestionJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        claimed = session.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job.id, IngestionJob.status == "PENDING")
            .values(status="PROCESSING", stage="starting", started_at=utcnow())
        )
        if claimed.rowcount != 1:
            session.rollback()
            return None
        transitioned = session.execute(
            update(Document)
            .where(Document.id == job.document_id, Document.status == "PENDING")
            .values(status="PROCESSING")
        )
        if transitioned.rowcount != 1:
            session.rollback()
            return None
        session.commit()
        return job.id


def recover_stale(sessions=SessionLocal):
    cutoff = utcnow() - timedelta(seconds=settings.INGESTION_TIMEOUT + 60)
    with sessions() as session:
        stale = session.scalars(
            select(IngestionJob).where(IngestionJob.status == "PROCESSING", IngestionJob.started_at < cutoff)
        ).all()
        for job in stale:
            job.status, job.stage, job.started_at = "PENDING", "recovered_after_worker_restart", None
            doc = session.get(Document, job.document_id)
            if doc:
                doc.status = "PENDING"
        session.commit()


def heartbeat():
    settings.WORKER_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    settings.WORKER_HEARTBEAT_PATH.touch()


def run():
    while True:
        try:
            heartbeat()
            recover_stale()
            job_id = claim_job()
            if job_id:
                started = time.monotonic()
                # Child does not receive file paths from user input; only a database UUID.
                process = subprocess.Popen([sys.executable, "-m", "app.worker", "--job", job_id])
                try:
                    while process.poll() is None:
                        heartbeat()
                        if time.monotonic() - started > settings.INGESTION_TIMEOUT:
                            process.kill()
                            process.wait()
                            fail_job(
                                job_id,
                                SessionLocal,
                                "Ingestion timed out. Increase INGESTION_TIMEOUT or upload a smaller document.",
                            )
                            break
                        time.sleep(1)
                    if process.returncode:
                        fail_job(
                            job_id,
                            SessionLocal,
                            f"Ingestion process exited with code {process.returncode}; reindex to retry.",
                        )
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
            else:
                time.sleep(settings.WORKER_POLL_INTERVAL)
        except KeyboardInterrupt:
            return
        except Exception as exc:
            logger.error("worker_poll_failed", extra={"error_type": type(exc).__name__})
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        path = settings.WORKER_HEARTBEAT_PATH
        sys.exit(0 if path.exists() and time.time() - path.stat().st_mtime < 30 else 1)
    configure_logging()
    if args.job:
        process_job(args.job, SessionLocal, settings, FinancialVectorStore())
    else:
        run()
