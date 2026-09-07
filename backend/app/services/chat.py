import re

from app.config import Settings
from app.db import Document
from app.ingestion.classifier import fold
from app.rag.evidence import relevant_metric, requested_metric_pattern
from app.rag.lexical import tokens
from app.rag.llm import INJECTION_PATTERN, BaseLLMProvider, llm_provider
from app.rag.vector_store import FinancialVectorStore
from sqlalchemy import select
from sqlalchemy.orm import Session

INSUFFICIENT_EN = "The uploaded documents do not provide enough information to answer this question."
INSUFFICIENT_FR = (
    "Les documents importes ne fournissent pas assez d’informations pour repondre a cette question."
)


def location_label(metadata: dict) -> str:
    parts = [metadata["filename"]]
    if metadata.get("page_start") is not None:
        parts.append(f"Page {metadata['page_start']}")
    if metadata.get("sheet_name"):
        parts.append(f"Sheet: {metadata['sheet_name']}")
    if metadata.get("cell_range"):
        parts.append(f"Cells: {metadata['cell_range']}")
    if metadata.get("slide_number"):
        parts.append(f"Slide {metadata['slide_number']}")
    if metadata.get("section") and not metadata.get("sheet_name"):
        parts.append(f"Section: {metadata['section']}")
    if metadata.get("line_start") and metadata.get("page_start") is None:
        parts.append(f"Lines {metadata['line_start']}–{metadata.get('line_end', metadata['line_start'])}")
    return ", ".join(parts)


class ChatService:
    def __init__(
        self, config: Settings, store: FinancialVectorStore, provider: BaseLLMProvider | None = None
    ):
        self.config, self.store = config, store
        self.provider = provider or llm_provider(config)

    def retrieve(self, question: str, documents: list[Document], document_types: list[str]) -> list[dict]:
        if not documents:
            return []
        ids = [doc.id for doc in documents]
        candidates = self.store.hybrid_search(question, document_ids=ids, document_types=document_types)
        comparison = bool(re.search(r"compar|highest|largest|plus (?:eleve|grand)", fold(question)))
        if comparison:
            # Fetch a representative for each compared document; no corpus-wide ranking from a partial top-k.
            for doc in documents[:50]:
                extra = self.store.hybrid_search(
                    question, document_ids=[doc.id], document_types=document_types, top_k=4
                )
                candidates.extend(extra[:2])
        unique = {chunk["chunk_id"]: chunk for chunk in candidates}
        ranked = sorted(unique.values(), key=lambda chunk: chunk["score"], reverse=True)
        if comparison:
            selected, seen = [], set()
            for chunk in ranked:
                if chunk["metadata"]["document_id"] not in seen:
                    selected.append(chunk)
                    seen.add(chunk["metadata"]["document_id"])
            selected_ids = {chunk["chunk_id"] for chunk in selected}
            ranked = selected + [chunk for chunk in ranked if chunk["chunk_id"] not in selected_ids]
        return ranked[: self.config.RERANK_TOP_K]

    def query(
        self,
        question: str,
        document_ids: list[str],
        document_types: list[str],
        session: Session,
        debug: bool = False,
    ) -> dict:
        statement = select(Document).where(Document.status == "COMPLETED")
        if document_ids:
            statement = statement.where(Document.id.in_(document_ids))
        inferred_types = document_types.copy()
        terms = set(tokens(question))
        if not inferred_types:
            inferred_types = [
                name
                for term, name in (("invoice", "invoice"), ("quote", "devis"), ("statement", "bilan"))
                if term in terms
            ]
            if not inferred_types and re.search(
                r"resultat net|net income|revenue|chiffre d.affaires", fold(question)
            ):
                inferred_types = ["bilan"]
        if inferred_types:
            statement = statement.where(Document.document_type.in_(inferred_types))
        documents = list(session.scalars(statement.order_by(Document.created_at)).all())
        identifiers = re.findall(r"\b[A-Za-z]{2,}[-/]\d[\w/-]*", question.lower())
        if identifiers:
            documents = [
                doc
                for doc in documents
                if any(
                    identifier in block.get("text", "").lower()
                    for identifier in identifiers
                    for block in doc.normalized_data.get("blocks", [])
                )
            ]
        years = re.findall(r"\b(?:19|20)\d{2}\b", question)
        if years and inferred_types == ["bilan"]:
            documents = [
                doc
                for doc in documents
                if any(
                    year in str((doc.structured_data.get("reporting_period") or {}).get("value", ""))
                    or any(year in block.get("text", "") for block in doc.normalized_data.get("blocks", []))
                    for year in years
                )
            ]
        chunks = self.retrieve(question, documents, inferred_types)
        french = bool(
            re.search(
                r"\b(quel|quelle|quels|montant|facture|resultat|devis|societe|le|la|les)\b", fold(question)
            )
        )
        response = {
            "answer": INSUFFICIENT_FR if french else INSUFFICIENT_EN,
            "citations": [],
            "sources_used": [],
            "answer_mode": self.config.LLM_PROVIDER,
            "insufficient_evidence": True,
        }
        if debug and self.config.ENV == "development" and self.config.RETRIEVAL_DEBUG:
            response["retrieval_debug"] = {
                "chunks": chunks,
                "fusion": "Qdrant reciprocal rank fusion",
                "filters": inferred_types,
            }
        if not chunks:
            return response
        # Exact references must actually occur; semantic similarity alone cannot prove an identifier.
        if identifiers and not all(
            any(identifier in chunk["content"].lower() for chunk in chunks) for identifier in identifiers
        ):
            return response
        selections = self.provider.answer(question, chunks).evidence
        citations, answer_lines, used = [], [], set()
        for selection in selections:
            if not 1 <= selection.citation_id <= len(chunks):
                continue
            chunk = chunks[selection.citation_id - 1]
            quote = selection.quote.strip()
            if (
                quote not in chunk["content"]
                or INJECTION_PATTERN.search(quote)
                or not relevant_metric(quote, requested_metric_pattern(question))
            ):
                continue
            comparison_value = "compare" in terms and re.search(
                r"(?i)ttc|total|net income|resultat net|revenue|chiffre", quote
            )
            if not comparison_value and not (set(tokens(question)) & set(tokens(quote))):
                continue
            key = (chunk["chunk_id"], quote)
            if key in used:
                continue
            used.add(key)
            meta = chunk["metadata"]
            citation_id = len(citations) + 1
            citation = {
                "citation_id": citation_id,
                "document_id": meta["document_id"],
                "filename": meta["filename"],
                "page": meta.get("page_start"),
                "page_end": meta.get("page_end"),
                "sheet": meta.get("sheet_name"),
                "cell_range": meta.get("cell_range"),
                "section": meta.get("section"),
                "table_id": meta.get("table_id"),
                "slide_number": meta.get("slide_number"),
                "excerpt": quote,
                "score": round(chunk["score"], 6),
                "chunk_id": chunk["chunk_id"],
                "label": location_label(meta),
                "url": f"/api/documents/{meta['document_id']}/file"
                + (f"#page={meta['page_start']}" if meta.get("page_start") else ""),
            }
            citations.append(citation)
            answer_lines.append(f"{meta['filename']}: {quote} [{citation_id}]")
        if citations:
            response.update(
                answer="\n\n".join(answer_lines),
                citations=citations,
                sources_used=list(dict.fromkeys(c["document_id"] for c in citations)),
                insufficient_evidence=False,
            )
        return response
