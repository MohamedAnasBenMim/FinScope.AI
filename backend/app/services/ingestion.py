import logging

from app.config import Settings
from app.db import Document, IngestionJob, utcnow
from app.errors import ApplicationError
from app.ingestion.classifier import DocumentClassifier
from app.ingestion.extraction import StructuredExtractor
from app.ingestion.parsers import DocumentParser
from app.rag.chunker import FinancialChunker
from app.rag.vector_store import FinancialVectorStore
from app.storage import LocalStorageProvider
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


def process_job(job_id: str, sessions: sessionmaker, config: Settings, store: FinancialVectorStore) -> None:
    document_id = None

    def stage(name: str, progress: int):
        with sessions() as session:
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != "PROCESSING":
                raise RuntimeError("Job no longer active.")
            job.stage, job.progress = name, progress
            session.commit()
        logger.info(name, extra={"document_id": document_id, "job_id": job_id, "stage": name})

    try:
        with sessions() as session:
            job = session.get(IngestionJob, job_id)
            if job is None or job.status != "PROCESSING":
                return
            doc = session.get(Document, job.document_id)
            if doc is None:
                return
            document_id = doc.id
        stage("parsing_start", 10)
        normalized = DocumentParser(config).parse(
            LocalStorageProvider(config).path(doc.stored_filename),
            doc.id,
            doc.original_filename,
            doc.mime_type,
            doc.extension,
        )
        stage("parsing_end", 35)
        if normalized.metadata.get("ocr_used"):
            stage("ocr_complete", 40)
        classification = DocumentClassifier(config.CLASSIFICATION_THRESHOLD).classify(normalized)
        normalized.document_type = classification.document_type
        normalized.classification_confidence = classification.confidence
        stage("classification", 45)
        extracted = StructuredExtractor().extract(normalized)
        stage("structured_extraction", 55)
        chunks = FinancialChunker(config).chunk_document(normalized)
        logger.info("chunk_count", extra={"document_id": document_id, "job_id": job_id, "count": len(chunks)})
        stage("embedding_indexing", 65)
        store.delete_document(document_id)
        store.add_chunks(chunks)
        stage("indexing_complete", 95)
        with sessions() as session:
            active_doc = session.get(Document, document_id)
            active_job = session.get(IngestionJob, job_id)
            if active_doc is None or active_job is None or active_job.status != "PROCESSING":
                store.delete_document(document_id)
                return
            active_doc.normalized_data = normalized.model_dump(mode="json")
            active_doc.structured_data = extracted
            active_doc.extraction_metadata = {
                **normalized.metadata,
                "classification": classification.model_dump(),
                "chunk_count": len(chunks),
            }
            active_doc.document_type = classification.document_type
            active_doc.classification_confidence = classification.confidence
            active_doc.page_count = normalized.page_count
            active_doc.status = active_job.status = "COMPLETED"
            active_job.progress, active_job.stage, active_job.completed_at = 100, "completed", utcnow()
            session.commit()
        logger.info("ingestion_completed", extra={"document_id": document_id, "job_id": job_id})
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, ApplicationError)
            else f"Unexpected ingestion failure ({type(exc).__name__}). Retry reindexing."
        )
        fail_job(job_id, sessions, message)
        logger.error(
            "ingestion_failed",
            extra={"document_id": document_id, "job_id": job_id, "error_type": type(exc).__name__},
        )


def fail_job(job_id: str, sessions: sessionmaker, message: str) -> None:
    with sessions() as session:
        job = session.get(IngestionJob, job_id)
        if job and job.status == "PROCESSING":
            job.status, job.stage, job.error, job.completed_at = "FAILED", "failed", message[:1000], utcnow()
            doc = session.get(Document, job.document_id)
            if doc:
                doc.status = "FAILED"
            session.commit()
