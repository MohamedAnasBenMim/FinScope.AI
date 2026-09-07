from uuid import uuid4

import pytest
from app.config import Settings
from app.ingestion.normalized import NormalizedBlock, NormalizedDocument
from app.rag.chunker import DocumentChunk, FinancialChunker
from app.rag.lexical import sparse_vector, tokens
from app.rag.vector_store import FinancialVectorStore
from qdrant_client import QdrantClient


def test_structure_chunking():
    doc = NormalizedDocument(
        document_id=str(uuid4()),
        filename="accounts.xlsx",
        mime_type="text/plain",
        extension=".xlsx",
        blocks=[
            NormalizedBlock(
                text="Account | Amount",
                type="spreadsheet",
                sheet_name="Balance Sheet",
                table_id="t1",
                cell_range="A12:B18",
                metadata={
                    "row_start": 12,
                    "header_rows": 1,
                    "rows": [
                        ["Account", "Amount"],
                        ["Assets", "100"],
                        ["Cash", "50"],
                        ["Equity", "100"],
                        ["Revenue", "200"],
                    ],
                },
            )
        ],
    ).assign_ids()
    chunks = FinancialChunker(Settings(TABLE_CHUNK_ROWS=2)).chunk_document(doc)
    assert len(chunks) == 2
    assert all("Account" in c.content and c.metadata["sheet_name"] == "Balance Sheet" for c in chunks)
    assert chunks[0].metadata["cell_range"] == "A13:B14"
    assert chunks[1].metadata["cell_range"] == "A15:B16"
    assert chunks[1].metadata["header_cell_range"] == "A12:B12"
    assert all(c.metadata["page_start"] is None for c in chunks)
    assert [c.chunk_id for c in chunks] == [
        c.chunk_id for c in FinancialChunker(Settings(TABLE_CHUNK_ROWS=2)).chunk_document(doc)
    ]


def test_sparse_identifiers_and_bilingual_concepts():
    assert "inv-2026-0042" in tokens("Total of INV-2026-0042")
    assert sparse_vector("facture").indices == sparse_vector("invoice").indices
    assert sparse_vector("INV-42").indices != sparse_vector("INV-43").indices


def make_chunks():
    return [
        DocumentChunk(
            chunk_id=str(uuid4()),
            content=text,
            metadata={
                "document_id": str(index),
                "filename": filename,
                "document_type": document_type,
                "page_start": page,
                "page_end": page,
                "sheet_name": sheet,
                "cell_range": cells,
            },
        )
        for index, (text, filename, document_type, page, sheet, cells) in enumerate(
            [
                (
                    "FACTURE: INV-2026-0042\nSupplier: ABC\nMontant TTC: 1428.00 EUR",
                    "invoice.pdf",
                    "invoice",
                    2,
                    None,
                    None,
                ),
                (
                    "DEVIS: DEV-2026-002\nValidite: 30 jours\nMontant TTC: 1200 EUR",
                    "quote.xlsx",
                    "devis",
                    None,
                    "Pricing",
                    "A1:B4",
                ),
                (
                    "BILAN 2025\nResultat net: 250000 EUR\nChiffre d’affaires: 1420000 EUR",
                    "report.pdf",
                    "bilan",
                    7,
                    None,
                    None,
                ),
                (
                    "Birds migrate during the winter. Oak trees grow along the river.",
                    "notes.txt",
                    "other",
                    None,
                    None,
                    None,
                ),
            ]
        )
    ]


@pytest.mark.integration
def test_real_hybrid_filters_delete_and_restart(tmp_path, embeddings):
    config = Settings(QDRANT_URL=":local:", QDRANT_COLLECTION="test-hybrid", MIN_RETRIEVAL_SCORE=0)
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    store = FinancialVectorStore(config, client, embeddings)
    chunks = make_chunks()
    store.add_chunks(chunks)
    found = store.hybrid_search("What is the total of INV-2026-0042?")
    assert found[0]["metadata"]["filename"] == "invoice.pdf"
    assert found[0]["metadata"]["page_start"] == 2
    assert all(
        c["metadata"]["document_type"] == "devis"
        for c in store.hybrid_search("total", document_types=["devis"])
    )
    assert all(
        c["metadata"]["document_id"] == "2" for c in store.hybrid_search("net income", document_ids=["2"])
    )
    assert store.hybrid_search("net income 2025")[0]["metadata"]["filename"] == "report.pdf"
    points, _ = client.scroll(store.collection, with_vectors=True)
    assert all("lexical" in p.vector and store.dense_name in p.vector for p in points)
    client.close()
    restarted = FinancialVectorStore(config, QdrantClient(path=str(tmp_path / "qdrant")), embeddings)
    assert restarted.hybrid_search("INV-2026-0042")[0]["metadata"]["filename"] == "invoice.pdf"
    restarted.delete_document("0")
    assert restarted.hybrid_search("INV-2026-0042", document_ids=["0"]) == []
    restarted.client.close()
