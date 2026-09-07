import hashlib
import logging

from app.config import Settings, settings
from app.errors import IndexingFailed
from app.rag.chunker import DocumentChunk
from app.rag.embeddings import BaseEmbeddingProvider, embedding_provider
from app.rag.lexical import sparse_vector
from app.rag.reranker import LexicalEvidenceReranker
from qdrant_client import QdrantClient, models

logger = logging.getLogger(__name__)


class FinancialVectorStore:
    def __init__(
        self,
        config: Settings | None = None,
        client: QdrantClient | None = None,
        embeddings: BaseEmbeddingProvider | None = None,
    ):
        self.config = config or settings
        self.client = client or QdrantClient(
            url=self.config.QDRANT_URL, api_key=self.config.QDRANT_API_KEY, timeout=30
        )
        self.embeddings = embeddings or embedding_provider(self.config)
        # Same-dimensional model changes must not mix incompatible vectors.
        fingerprint = hashlib.sha256(
            f"{self.config.EMBEDDING_PROVIDER}/{self.config.EMBEDDING_MODEL}/{self.embeddings.dimensions}".encode()
        ).hexdigest()[:12]
        self.dense_name = f"dense_{fingerprint}"
        self.collection = self.config.QDRANT_COLLECTION

    def ensure_collection(self):
        if not self.client.collection_exists(self.collection):
            try:
                self.client.create_collection(
                    self.collection,
                    vectors_config={
                        self.dense_name: models.VectorParams(
                            size=self.embeddings.dimensions, distance=models.Distance.COSINE
                        )
                    },
                    sparse_vectors_config={
                        "lexical": models.SparseVectorParams(modifier=models.Modifier.IDF)
                    },
                )
            except Exception:
                # Another API/worker may have created the collection concurrently.
                if not self.client.collection_exists(self.collection):
                    raise
            if not self.config.QDRANT_URL.startswith(":"):
                for field in ("document_id", "document_type", "sheet_name"):
                    self.client.create_payload_index(
                        self.collection, field, models.PayloadSchemaType.KEYWORD, wait=True
                    )
        info = self.client.get_collection(self.collection)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or self.dense_name not in vectors:
            raise IndexingFailed(
                "Collection uses a different embedding model. Set a new QDRANT_COLLECTION and reindex documents."
            )

    def add_chunks(self, chunks: list[DocumentChunk]):
        if not chunks:
            return
        vectors = self.embeddings.embed([chunk.content for chunk in chunks])
        try:
            self.ensure_collection()
            for start in range(0, len(chunks), 32):
                points = [
                    models.PointStruct(
                        id=chunk.chunk_id,
                        vector={self.dense_name: vectors[i], "lexical": sparse_vector(chunk.content)},
                        payload={**chunk.metadata, "text": chunk.content, "chunk_id": chunk.chunk_id},
                    )
                    for i, chunk in enumerate(chunks[start : start + 32], start)
                ]
                self.client.upsert(self.collection, points=points, wait=True)
        except IndexingFailed:
            raise
        except Exception as exc:
            raise IndexingFailed("Qdrant indexing failed. Check search service readiness.") from exc

    @staticmethod
    def metadata_filter(
        document_ids: list[str] | None = None, document_types: list[str] | None = None
    ) -> models.Filter | None:
        conditions = []
        for key, values in (("document_id", document_ids), ("document_type", document_types)):
            if values:
                conditions.append(models.FieldCondition(key=key, match=models.MatchAny(any=values)))
        return models.Filter(must=conditions) if conditions else None

    def hybrid_search(
        self,
        query: str,
        top_k: int | None = None,
        document_ids: list[str] | None = None,
        document_types: list[str] | None = None,
        rerank: bool = True,
    ) -> list[dict]:
        try:
            if not self.client.collection_exists(self.collection):
                return []
            self.ensure_collection()
            dense = self.embeddings.embed([query], query=True)[0]
            sparse = sparse_vector(query)
            limit = top_k or self.config.RETRIEVAL_TOP_K
            filters = self.metadata_filter(document_ids, document_types)
            prefetch = [models.Prefetch(query=dense, using=self.dense_name, filter=filters, limit=limit)]
            if sparse.indices:
                prefetch.append(models.Prefetch(query=sparse, using="lexical", filter=filters, limit=limit))
            response = self.client.query_points(
                self.collection,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=filters,
                limit=limit,
                with_payload=True,
            )
            chunks = [
                {
                    "content": point.payload["text"],
                    "metadata": {k: v for k, v in point.payload.items() if k != "text"},
                    "score": point.score,
                    "chunk_id": str(point.id),
                }
                for point in response.points
            ]
            if rerank and self.config.RERANK_ENABLED:
                chunks = LexicalEvidenceReranker().rerank(query, chunks)
            return [chunk for chunk in chunks if chunk["score"] >= self.config.MIN_RETRIEVAL_SCORE]
        except IndexingFailed:
            raise
        except Exception as exc:
            raise IndexingFailed(
                "Hybrid retrieval failed. Check Qdrant and embedding configuration."
            ) from exc

    def delete_document(self, document_id: str):
        try:
            if self.client.collection_exists(self.collection):
                self.client.delete(
                    self.collection,
                    points_selector=models.FilterSelector(filter=self.metadata_filter([document_id])),
                    wait=True,
                )
        except Exception as exc:
            raise IndexingFailed("Could not remove document vectors from Qdrant; retry deletion.") from exc
