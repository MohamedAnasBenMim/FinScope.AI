import pytest

from scripts.generate_test_documents import FIXTURES, generate


@pytest.fixture(scope="session", autouse=True)
def corpus():
    generate()
    return FIXTURES / "documents"


@pytest.fixture(scope="session")
def embeddings():
    from app.config import Settings
    from app.rag.embeddings import LocalEmbeddingProvider

    return LocalEmbeddingProvider(Settings())
