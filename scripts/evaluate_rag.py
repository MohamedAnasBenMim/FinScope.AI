"""Evaluate actual parsers, OCR, embeddings and Qdrant independently of LLM wording.

Default: isolated temporary SQLite/Qdrant data; no application documents are changed.
--llm also evaluates the configured live LLM through the same grounded chat service.
"""

import argparse
import json
import tempfile
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.config import Settings
from app.db import Base, Document, make_engine
from app.ingestion.classifier import DocumentClassifier
from app.ingestion.extraction import StructuredExtractor
from app.ingestion.parsers import DocumentParser
from app.ingestion.validation import validate_file
from app.rag.chunker import FinancialChunker
from app.rag.vector_store import FinancialVectorStore
from app.services.chat import ChatService
from qdrant_client import QdrantClient
from sqlalchemy.orm import sessionmaker

from scripts.generate_test_documents import FIXTURES, ROOT, generate


def evaluate(use_llm: bool = False) -> dict:
    truth = generate()
    config = Settings()
    if not use_llm:
        config = config.model_copy(update={"LLM_PROVIDER": "extractive"})
    questions = json.loads((ROOT / "tests/evaluation/rag_questions.json").read_text())
    with tempfile.TemporaryDirectory(prefix="finscope-evaluation-") as directory:
        engine = make_engine(f"sqlite:///{directory}/evaluation.db")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(engine, expire_on_commit=False)
        vector_config = config.model_copy(update={"QDRANT_URL": ":local:", "QDRANT_COLLECTION": "evaluation"})
        store = FinancialVectorStore(vector_config, QdrantClient(path=f"{directory}/qdrant"))
        parsed, classified, values_correct, values_total = 0, 0, 0, 0
        failures = []
        for filename, expected in truth.items():
            try:
                path = FIXTURES / "documents" / filename
                mime, extension = validate_file(path, filename, config)
                document_id = str(uuid5(NAMESPACE_URL, "finscope-evaluation/" + filename))
                normalized = DocumentParser(config).parse(path, document_id, filename, mime, extension)
                parsed += 1
                classification = DocumentClassifier(config.CLASSIFICATION_THRESHOLD).classify(normalized)
                classified += classification.document_type == expected["document_type"]
                normalized.document_type = classification.document_type
                extraction = StructuredExtractor().extract(normalized)
                for field, expected_value in expected.items():
                    if field in ("document_type", "page"):
                        continue
                    values_total += 1
                    actual = (extraction.get(field) or {}).get("value")
                    values_correct += actual == expected_value
                    if actual != expected_value:
                        failures.append(
                            {
                                "filename": filename,
                                "field": field,
                                "expected": expected_value,
                                "actual": actual,
                            }
                        )
                store.add_chunks(FinancialChunker(config).chunk_document(normalized))
                with sessions() as session:
                    session.add(
                        Document(
                            id=document_id,
                            original_filename=filename,
                            stored_filename=filename,
                            mime_type=mime,
                            extension=extension,
                            checksum="synthetic",
                            size=path.stat().st_size,
                            status="COMPLETED",
                            document_type=classification.document_type,
                            classification_confidence=classification.confidence,
                            normalized_data=normalized.model_dump(mode="json"),
                            structured_data=extraction,
                        )
                    )
                    session.commit()
            except Exception as exc:
                failures.append({"filename": filename, "error": f"{type(exc).__name__}: {exc}"})
                # A failed parse/extraction counts as incorrect for every expected field.
                values_total += sum(field not in ("document_type", "page") for field in expected)
        hits = {1: 0, 3: 0, 5: 0}
        citation_correct = citation_total = answered = 0
        rows = []
        for entry in questions:
            found = store.hybrid_search(entry["question"], top_k=config.RETRIEVAL_TOP_K)
            for k in hits:
                hits[k] += any(
                    chunk["metadata"]["filename"] == entry["expected_document"] for chunk in found[:k]
                )
            with sessions() as session:
                answer = ChatService(config, store).query(entry["question"], [], [], session)
            answered += not answer["insufficient_evidence"]
            # Each question needs at least one correct source/location; no-citation responses score zero.
            citation_total += 1
            correct = any(
                c["filename"] == entry["expected_document"]
                and (entry.get("expected_page") is None or c["page"] == entry["expected_page"])
                and (entry.get("expected_sheet") is None or c["sheet"] == entry["expected_sheet"])
                and (not entry.get("expected_cell_range") or c["cell_range"] == entry["expected_cell_range"])
                for c in answer["citations"]
            )
            citation_correct += correct
            rows.append(
                {
                    "question": entry["question"],
                    "expected_document": entry["expected_document"],
                    "top_document": found[0]["metadata"]["filename"] if found else None,
                    "citation_correct": correct,
                    "answer": answer["answer"],
                }
            )
        result = {
            "documents": len(truth),
            "parsed": parsed,
            "questions": len(questions),
            "classification_accuracy": classified / len(truth),
            **{f"retrieval_hit@{k}": hits[k] / len(questions) for k in hits},
            "citation_accuracy": citation_correct / max(1, citation_total),
            "structured_extraction_accuracy": values_correct / max(1, values_total),
            "answer_coverage": answered / len(questions),
            "answer_provider": config.LLM_PROVIDER,
            "failures": failures,
            "question_results": rows,
        }
        store.client.close()
        engine.dispose()
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--llm", action="store_true", help="Include the configured LLM; requires a running model service."
    )
    parser.add_argument("--output", type=Path, help="Write metrics and per-question results as JSON.")
    arguments = parser.parse_args()
    metrics = evaluate(arguments.llm)
    print(
        json.dumps(
            {k: v for k, v in metrics.items() if k != "question_results"}, indent=2, ensure_ascii=False
        )
    )
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    if (
        metrics["parsed"] != metrics["documents"]
        or metrics["classification_accuracy"] < 0.9
        or metrics["retrieval_hit@3"] < 0.8
        or metrics["citation_accuracy"] < 0.8
    ):
        raise SystemExit(1)
