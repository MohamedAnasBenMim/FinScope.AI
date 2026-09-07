import re
from abc import ABC, abstractmethod

from app.rag.lexical import tokens


class BaseReranker(ABC):
    @abstractmethod
    def rerank(self, query: str, chunks: list[dict]) -> list[dict]: ...


class LexicalEvidenceReranker(BaseReranker):
    """Transparent bilingual overlap reranker with exact identifier emphasis."""

    def rerank(self, query: str, chunks: list[dict]) -> list[dict]:
        terms = set(tokens(query))
        identifiers = set(re.findall(r"\b[A-Za-z]{2,}[-/]\d[\w/-]*", query.lower()))
        results = []
        for chunk in chunks:
            content_terms = set(tokens(chunk["content"]))
            overlap = len(terms & content_terms) / max(1, len(terms))
            exact = sum(identifier in chunk["content"].lower() for identifier in identifiers) / max(
                1, len(identifiers)
            )
            score = 0.55 * overlap + 0.25 * min(chunk["score"], 1) + 0.20 * exact
            results.append(
                {**chunk, "fusion_score": chunk["score"], "score": score, "lexical_overlap": overlap}
            )
        return sorted(results, key=lambda row: row["score"], reverse=True)
