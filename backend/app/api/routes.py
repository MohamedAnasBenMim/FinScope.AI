import time
from typing import Annotated
from uuid import UUID

import httpx
from app.api.dependencies import get_chat_service, get_storage, get_store
from app.api.schemas import CalculateRequest, DocumentType, QueryRequest
from app.config import settings
from app.db import Document, IngestionJob, get_session
from app.ingestion.validation import MIMES
from app.rag.vector_store import FinancialVectorStore
from app.services.chat import ChatService
from app.services.documents import DocumentService, document_dict, job_dict, latest_job, require_document
from app.storage import LocalStorageProvider
from app.tools.calculator import FinancialCalculator
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

router = APIRouter()
DB = Annotated[Session, Depends(get_session)]
Store = Annotated[FinancialVectorStore, Depends(get_store)]
Storage = Annotated[LocalStorageProvider, Depends(get_storage)]


@router.post("/documents/upload", status_code=202, tags=["Documents"])
async def upload_documents(
    session: DB,
    storage: Storage,
    files: list[UploadFile] | None = File(None),
    file: UploadFile | None = File(None),
):
    uploads = (files or []) + ([file] if file else [])
    if not uploads:
        raise HTTPException(422, "Provide files as multipart/form-data using the files field.")
    if len(uploads) > settings.MAX_FILES_PER_UPLOAD:
        for upload in uploads:
            await upload.close()
        raise HTTPException(413, f"Maximum {settings.MAX_FILES_PER_UPLOAD} files per upload.")
    result = await DocumentService(settings, storage).upload(uploads, session)
    status = 202 if result["documents"] else result["errors"][0]["status_code"]
    return JSONResponse(jsonable_encoder(result), status_code=status)


@router.get("/documents", tags=["Documents"])
def list_documents(
    session: DB,
    document_type: DocumentType | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    statement = select(Document)
    if document_type:
        statement = statement.where(Document.document_type == document_type)
    count = session.scalar(select(func.count()).select_from(statement.subquery()))
    documents = session.scalars(
        statement.order_by(Document.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return {
        "documents": [document_dict(doc) for doc in documents],
        "count": count,
        "offset": offset,
        "limit": limit,
    }


@router.get("/documents/{document_id}", tags=["Documents"])
def get_document(document_id: UUID, session: DB):
    return document_dict(require_document(session, str(document_id)), details=True)


@router.get("/documents/{document_id}/status", tags=["Documents"])
def document_status(document_id: UUID, session: DB):
    doc = require_document(session, str(document_id))
    job = latest_job(session, doc.id)
    return {"document_id": doc.id, "status": doc.status, "job": job_dict(job) if job else None}


@router.get("/jobs/{job_id}", tags=["Jobs"])
def job_status(job_id: UUID, session: DB):
    job = session.get(IngestionJob, str(job_id))
    if not job:
        raise HTTPException(404, "Job not found.")
    return job_dict(job)


@router.get("/documents/{document_id}/extraction", tags=["Documents"])
def extraction(document_id: UUID, session: DB):
    doc = require_document(session, str(document_id))
    return {
        "document_id": doc.id,
        "status": doc.status,
        "document_type": doc.document_type,
        "classification": doc.extraction_metadata.get("classification"),
        "structured_data": doc.structured_data,
        "processing_metadata": doc.extraction_metadata,
    }


@router.get("/documents/{document_id}/file", tags=["Documents"])
def download_file(document_id: UUID, session: DB, storage: Storage):
    doc = require_document(session, str(document_id))
    path = storage.path(doc.stored_filename)
    if not path.exists():
        raise HTTPException(404, "Stored file is missing.")
    # Never render uploaded HTML/scripts in the application's origin.
    inline = doc.mime_type == "application/pdf" or doc.mime_type.startswith("image/")
    return FileResponse(
        path,
        media_type=doc.mime_type,
        filename=doc.original_filename,
        content_disposition_type="inline" if inline else "attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.delete("/documents/{document_id}", status_code=204, tags=["Documents"])
def delete_document(document_id: UUID, session: DB, storage: Storage, store: Store):
    doc = require_document(session, str(document_id), lock=True)
    if doc.status == "PROCESSING":
        raise HTTPException(409, "Document is processing. Wait for completion before deletion.")
    doc.status = "DELETING"
    session.execute(
        update(IngestionJob)
        .where(IngestionJob.document_id == doc.id, IngestionJob.status == "PENDING")
        .values(status="FAILED", error="Document deleted.", stage="deleted")
    )
    session.commit()
    store.delete_document(doc.id)
    storage.delete(doc.stored_filename)
    session.execute(delete(IngestionJob).where(IngestionJob.document_id == doc.id))
    session.delete(doc)
    session.commit()
    return Response(status_code=204)


@router.post("/documents/{document_id}/reindex", status_code=202, tags=["Documents"])
def reindex_document(document_id: UUID, session: DB):
    doc = require_document(session, str(document_id), lock=True)
    if doc.status in ("PROCESSING", "PENDING"):
        job = latest_job(session, doc.id)
        return {"document_id": doc.id, "job_id": job.id if job else None, "status": doc.status}
    if doc.status == "DELETING":
        raise HTTPException(409, "Document deletion is in progress; retry deletion.")
    doc.status = "PENDING"
    job = IngestionJob(document_id=doc.id)
    session.add(job)
    session.commit()
    return {"document_id": doc.id, "job_id": job.id, "status": doc.status}


@router.post("/chat/query", tags=["Chat"])
def chat(req: QueryRequest, session: DB, service: Annotated[ChatService, Depends(get_chat_service)]):
    return service.query(
        req.question, [str(id) for id in req.document_ids], req.document_types, session, req.debug
    )


@router.post("/analysis/calculate", tags=["Analysis"])
def calculate(req: CalculateRequest):
    calculator = FinancialCalculator()
    try:
        result = (
            calculator.calculate_yoy_growth(req.param1, req.param2, req.metric_name)
            if req.calc_type == "yoy"
            else calculator.calculate_profit_margin(req.param1, req.param2)
        )
        return {"status": "success", "result": result}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/health", tags=["Health"])
def health():
    return {"status": "healthy", "version": settings.APP_VERSION}


@router.get("/capabilities", tags=["Health"])
def capabilities():
    return {
        "supported_formats": list(MIMES),
        "max_file_size": settings.MAX_FILE_SIZE,
        "max_files_per_upload": settings.MAX_FILES_PER_UPLOAD,
        "llm_provider": settings.LLM_PROVIDER,
        "document_types": ["invoice", "devis", "bilan", "other"],
    }


@router.get("/ready", tags=["Health"])
def ready(session: DB, store: Store):
    checks = {}
    try:
        session.execute(text("SELECT 1 FROM documents LIMIT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        store.client.get_collections()
        checks["qdrant"] = True
    except Exception:
        checks["qdrant"] = False
    path = settings.WORKER_HEARTBEAT_PATH
    checks["worker"] = path.exists() and time.time() - path.stat().st_mtime < 30
    if settings.LLM_PROVIDER == "ollama":
        try:
            response = httpx.get(settings.LLM_BASE_URL.rstrip("/") + "/api/tags", timeout=3)
            response.raise_for_status()
            checks["llm"] = any(model["name"] == settings.LLM_MODEL for model in response.json()["models"])
        except (httpx.HTTPError, ValueError, KeyError):
            checks["llm"] = False
    elif settings.LLM_PROVIDER in ("local", "openai"):
        try:
            response = httpx.get(
                settings.LLM_BASE_URL.rstrip("/") + "/models",
                timeout=3,
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"} if settings.LLM_API_KEY else {},
            )
            response.raise_for_status()
            checks["llm"] = any(model["id"] == settings.LLM_MODEL for model in response.json()["data"])
        except (httpx.HTTPError, ValueError, KeyError):
            checks["llm"] = False
    else:
        checks["llm"] = settings.LLM_PROVIDER == "extractive" or bool(settings.LLM_API_KEY)
    status = all(checks.values())
    return JSONResponse({"ready": status, "checks": checks}, status_code=200 if status else 503)
