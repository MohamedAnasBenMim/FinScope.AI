import logging

from app.config import Settings
from app.db import Document, IngestionJob
from app.errors import ApplicationError
from app.storage import LocalStorageProvider
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def document_dict(doc: Document, details: bool = False) -> dict:
    data = {
        name: getattr(doc, name)
        for name in (
            "id",
            "original_filename",
            "mime_type",
            "extension",
            "checksum",
            "size",
            "status",
            "document_type",
            "classification_confidence",
            "page_count",
            "created_at",
            "updated_at",
        )
    }
    if details:
        data.update(
            extraction_metadata=doc.extraction_metadata,
            structured_data=doc.structured_data,
            blocks=doc.normalized_data.get("blocks", []),
        )
    return data


def job_dict(job: IngestionJob) -> dict:
    return {
        key: getattr(job, key)
        for key in (
            "id",
            "document_id",
            "status",
            "progress",
            "stage",
            "error",
            "started_at",
            "completed_at",
            "created_at",
        )
    }


def require_document(session: Session, document_id: str, lock: bool = False) -> Document:
    statement = select(Document).where(Document.id == document_id)
    if lock:
        statement = statement.with_for_update()
    doc = session.scalar(statement)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return doc


def latest_job(session: Session, document_id: str) -> IngestionJob | None:
    return session.scalar(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )


class DocumentService:
    def __init__(self, config: Settings, storage: LocalStorageProvider):
        self.config = config
        self.storage = storage

    async def upload(self, files: list[UploadFile], session: Session) -> dict:
        accepted, errors = [], []
        for upload in files:
            stored = None
            try:
                stored = await self.storage.save(upload)
                existing = session.scalar(
                    select(Document)
                    .where(Document.checksum == stored.checksum)
                    .order_by(Document.created_at)
                    .limit(1)
                )
                if existing and self.config.DUPLICATE_BEHAVIOR != "allow":
                    self.storage.delete(stored.key)
                    if self.config.DUPLICATE_BEHAVIOR == "reject":
                        errors.append(
                            {
                                "filename": stored.filename,
                                "error": "Duplicate upload.",
                                "code": "DuplicateDocument",
                                "status_code": 409,
                            }
                        )
                    else:
                        job = latest_job(session, existing.id)
                        accepted.append(
                            {
                                "document_id": existing.id,
                                "job_id": job.id if job else None,
                                "filename": stored.filename,
                                "duplicate": True,
                                "status": existing.status,
                            }
                        )
                    continue
                doc = Document(
                    original_filename=stored.filename,
                    stored_filename=stored.key,
                    mime_type=stored.mime_type,
                    extension=stored.extension,
                    checksum=stored.checksum,
                    size=stored.size,
                    dedup_key=None if self.config.DUPLICATE_BEHAVIOR == "allow" else stored.checksum,
                )
                session.add(doc)
                try:
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    self.storage.delete(stored.key)
                    existing = session.scalar(select(Document).where(Document.dedup_key == stored.checksum))
                    if existing is None:
                        raise
                    if self.config.DUPLICATE_BEHAVIOR == "reject":
                        errors.append(
                            {
                                "filename": stored.filename,
                                "error": "Duplicate upload.",
                                "code": "DuplicateDocument",
                                "status_code": 409,
                            }
                        )
                    else:
                        job = latest_job(session, existing.id)
                        accepted.append(
                            {
                                "document_id": existing.id,
                                "job_id": job.id if job else None,
                                "filename": stored.filename,
                                "duplicate": True,
                                "status": existing.status,
                            }
                        )
                    continue
                job = IngestionJob(document_id=doc.id)
                session.add(job)
                session.commit()
                accepted.append(
                    {
                        "document_id": doc.id,
                        "job_id": job.id,
                        "filename": doc.original_filename,
                        "duplicate": False,
                        "status": doc.status,
                    }
                )
                logger.info("document_upload", extra={"document_id": doc.id, "job_id": job.id})
            except ApplicationError as exc:
                session.rollback()
                if stored:
                    self.storage.delete(stored.key)
                errors.append(
                    {
                        "filename": upload.filename,
                        "error": str(exc),
                        "code": type(exc).__name__,
                        "status_code": exc.status_code,
                    }
                )
            except Exception:
                session.rollback()
                if stored:
                    self.storage.delete(stored.key)
                logger.error("document_upload_failed", extra={"error_type": "StorageOrDatabaseError"})
                errors.append(
                    {
                        "filename": upload.filename,
                        "error": "Storage or database failure; retry upload.",
                        "code": "UploadFailed",
                        "status_code": 503,
                    }
                )
            finally:
                await upload.close()
        return {"documents": accepted, "errors": errors}
