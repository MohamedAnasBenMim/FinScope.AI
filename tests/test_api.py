from uuid import uuid4

import pytest
from app.api.dependencies import get_chat_service, get_storage, get_store
from app.config import Settings
from app.db import Base, get_session, make_engine
from app.main import app
from app.rag.vector_store import FinancialVectorStore
from app.services.chat import ChatService
from app.services.ingestion import process_job
from app.storage import LocalStorageProvider
from app.worker import claim_job
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def api(tmp_path, embeddings):
    config = Settings(
        DATABASE_URL=f"sqlite:///{tmp_path}/test.db",
        UPLOAD_DIR=tmp_path / "uploads",
        QDRANT_URL=":memory:",
        LLM_PROVIDER="extractive",
        RETRIEVAL_DEBUG=True,
    )
    engine = make_engine(config.DATABASE_URL)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    store = FinancialVectorStore(config, QdrantClient(":memory:"), embeddings)
    storage = LocalStorageProvider(config)

    def db():
        with sessions() as session:
            yield session

    app.dependency_overrides.update(
        {
            get_session: db,
            get_store: lambda: store,
            get_storage: lambda: storage,
            get_chat_service: lambda: ChatService(config, store),
        }
    )
    with TestClient(app) as client:
        yield client, sessions, store, config
    app.dependency_overrides.clear()
    store.client.close()
    engine.dispose()


def drain(api):
    _, sessions, store, config = api
    while job_id := claim_job(sessions):
        process_job(job_id, sessions, config, store)


def upload(client, corpus, filenames):
    return client.post(
        "/api/documents/upload", files=[("files", (name, (corpus / name).read_bytes())) for name in filenames]
    )


@pytest.mark.integration
def test_multiple_uploads_jobs_extraction_citations_reindex_delete(api, corpus):
    client, _, store, _ = api
    names = ["invoice_fr_01.pdf", "devis_fr_02.xlsx", "bilan_fr_01.pdf", "other_notes.txt"]
    response = upload(client, corpus, names)
    assert response.status_code == 202, response.text
    uploaded = response.json()["documents"]
    assert len(uploaded) == 4
    assert all(row["status"] == "PENDING" for row in uploaded)
    assert client.get(f"/api/jobs/{uploaded[0]['job_id']}").json()["status"] == "PENDING"
    drain(api)
    docs = client.get("/api/documents").json()["documents"]
    assert {doc["original_filename"]: doc["document_type"] for doc in docs} == dict(
        zip(names, ["invoice", "devis", "bilan", "other"])
    )
    assert all(doc["status"] == "COMPLETED" for doc in docs), docs
    invoice_id, quote_id = uploaded[0]["document_id"], uploaded[1]["document_id"]
    extraction = client.get(f"/api/documents/{invoice_id}/extraction").json()
    assert extraction["structured_data"]["total"]["value"] == 1428
    assert extraction["structured_data"]["line_items"][0]["quantity"]["value"] == 2
    answer = client.post(
        "/api/chat/query",
        json={"question": "Quel est le montant TTC de FAC-2026-001 ?", "document_ids": [invoice_id]},
    ).json()
    assert "1428" in answer["answer"], answer
    assert answer["citations"][0]["page"] == 1
    assert answer["citations"][0]["document_id"] == invoice_id
    quote = client.post(
        "/api/chat/query",
        json={"question": "Quelle est la validite du devis DEV-2026-002 ?", "document_ids": [quote_id]},
    ).json()
    assert quote["citations"][0]["sheet"] == "Pricing"
    assert quote["citations"][0]["cell_range"]
    assert quote["citations"][0]["page"] is None
    comparison = client.post(
        "/api/chat/query",
        json={"question": "Compare le devis avec la facture.", "document_ids": [invoice_id, quote_id]},
    ).json()
    assert set(comparison["sources_used"]) == {invoice_id, quote_id}, comparison
    absent = client.post(
        "/api/chat/query", json={"question": "What is the salary of the chief astronaut?"}
    ).json()
    assert absent["insufficient_evidence"] and not absent["citations"]
    missing_ref = client.post("/api/chat/query", json={"question": "What is the total of INV-9999?"}).json()
    assert missing_ref["insufficient_evidence"]
    duplicate = upload(client, corpus, [names[0]]).json()["documents"][0]
    assert duplicate["duplicate"] and duplicate["document_id"] == invoice_id
    reindex = client.post(f"/api/documents/{invoice_id}/reindex")
    assert reindex.status_code == 202
    assert reindex.json()["job_id"] != uploaded[0]["job_id"]
    drain(api)
    assert client.get(f"/api/documents/{invoice_id}/status").json()["status"] == "COMPLETED"
    assert client.get(f"/api/documents/{invoice_id}/file").status_code == 200
    assert client.delete(f"/api/documents/{invoice_id}").status_code == 204
    assert client.get(f"/api/documents/{invoice_id}").status_code == 404
    assert store.hybrid_search("FAC-2026-001", document_ids=[invoice_id]) == []


def test_upload_errors_isolated_and_request_validation(api, corpus):
    client, *_ = api
    response = upload(client, corpus, ["other_notes.txt", "corrupted.pdf", "empty.txt"])
    assert response.status_code == 202
    assert len(response.json()["documents"]) == 1
    assert len(response.json()["errors"]) == 2
    assert client.post("/api/documents/upload", files={"files": ("test.exe", b"hello")}).status_code == 415
    assert client.post("/api/chat/query", json={"question": "   "}).status_code == 422
    assert (
        client.post("/api/chat/query", json={"question": "hi", "document_ids": ["../bad"]}).status_code == 422
    )
    assert client.get("/api/documents/not-a-uuid").status_code == 422
    assert client.get(f"/api/documents/{uuid4()}").status_code == 404
    assert client.get("/api/health").status_code == 200
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize("behavior", ["reject", "allow"])
def test_duplicate_policies(api, corpus, monkeypatch, behavior):
    from app.config import settings

    monkeypatch.setattr(settings, "DUPLICATE_BEHAVIOR", behavior)
    client, *_ = api
    first = upload(client, corpus, ["other_notes.txt"]).json()["documents"][0]
    second = upload(client, corpus, ["other_notes.txt"])
    if behavior == "reject":
        assert second.status_code == 409
    else:
        assert second.status_code == 202
        assert second.json()["documents"][0]["document_id"] != first["document_id"]


@pytest.mark.integration
def test_reject_fabricated_citations_and_injected_instructions(api, corpus):
    from app.rag.llm import BaseLLMProvider, LLMResult

    client, sessions, store, config = api
    upload(client, corpus, ["invoice_fr_01.pdf"])
    drain(api)

    class FabricatingProvider(BaseLLMProvider):
        def answer(self, question, chunks):
            return LLMResult(
                evidence=[
                    {"citation_id": 9999, "quote": "Montant TTC: 1428.00"},
                    {"citation_id": 1, "quote": "Montant TTC: 999999999.00"},
                ]
            )

    with sessions() as session:
        answer = ChatService(config, store, FabricatingProvider()).query(
            "Quel est le montant TTC ?", [], [], session
        )
    assert answer["insufficient_evidence"]
    assert not answer["citations"]


def test_file_count_and_processing_delete_conflict(api, corpus, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MAX_FILES_PER_UPLOAD", 1)
    client, sessions, *_ = api
    assert upload(client, corpus, ["other_notes.txt", "other_resume.pdf"]).status_code == 413
    doc_id = upload(client, corpus, ["other_notes.txt"]).json()["documents"][0]["document_id"]
    assert claim_job(sessions)
    assert client.delete(f"/api/documents/{doc_id}").status_code == 409


@pytest.mark.integration
def test_failed_ocr_job_preserves_other_files(api, corpus):
    client, *_ = api
    response = upload(client, corpus, ["tiny.png", "other_notes.txt"]).json()
    drain(api)
    states = [
        client.get(f"/api/documents/{row['document_id']}/status").json() for row in response["documents"]
    ]
    assert states[0]["status"] == "FAILED"
    assert "too small" in states[0]["job"]["error"]
    assert states[1]["status"] == "COMPLETED"
