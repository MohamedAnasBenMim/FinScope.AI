import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi
from app.config import settings
from app.rag.chunker import DocumentChunk


class FinancialVectorStore:
    """Manages persistent ChromaDB vector storage and hybrid search (Vector + BM25)."""

    def __init__(self, collection_name: str = "financial_docs"):
        self.client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_DIR))
        # Use sentence-transformers for fast local embeddings
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_fn
        )
        self.bm25 = None
        self.stored_chunks: list[DocumentChunk] = []

    def add_chunks(self, chunks: list[DocumentChunk]):
        """Indexes document chunks into ChromaDB and builds BM25 index."""
        if not chunks:
            return

        documents = [c.content for c in chunks]
        ids = [c.chunk_id for c in chunks]
        metadatas = [
            {
                "filename": c.filename,
                "page_number": c.page_number,
                "is_table": str(c.is_table),
                **c.metadata
            }
            for c in chunks
        ]

        self.collection.add(
            documents=documents,
            ids=ids,
            metadatas=metadatas
        )

        # Build BM25 index for sparse keyword search
        self.stored_chunks.extend(chunks)
        corpus = [c.content.lower().split() for c in self.stored_chunks]
        self.bm25 = BM25Okapi(corpus)

    def hybrid_search(self, query: str, top_k: int = 3) -> list[dict]:
        """Combines Vector Dense Retrieval + BM25 Keyword Search."""
        # 1. Dense Vector Search
        vector_results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )

        results = []
        if vector_results and vector_results.get("documents"):
            for doc, meta in zip(vector_results["documents"][0], vector_results["metadatas"][0]):
                results.append({
                    "content": doc,
                    "metadata": meta,
                    "search_type": "vector_dense"
                })

        # 2. Sparse BM25 Search
        if self.bm25 and len(self.stored_chunks) > 0:
            tokenized_query = query.lower().split()
            bm25_scores = self.bm25.get_scores(tokenized_query)
            top_bm25_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k]

            for idx in top_bm25_indices:
                chunk = self.stored_chunks[idx]
                results.append({
                    "content": chunk.content,
                    "metadata": {
                        "filename": chunk.filename,
                        "page_number": chunk.page_number,
                        "is_table": str(chunk.is_table)
                    },
                    "search_type": "bm25_sparse"
                })

        return results[:top_k]
