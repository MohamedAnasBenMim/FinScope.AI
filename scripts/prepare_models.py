from app.config import settings
from app.rag.vector_store import FinancialVectorStore


def main():
    store = FinancialVectorStore(settings)
    store.embeddings.embed(["financial document / document financier"])
    store.ensure_collection()
    print("Multilingual embeddings and Qdrant collection are ready.")


if __name__ == "__main__":
    main()
