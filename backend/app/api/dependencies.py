from functools import lru_cache

from app.config import settings
from app.rag.vector_store import FinancialVectorStore
from app.services.chat import ChatService
from app.storage import LocalStorageProvider


@lru_cache
def get_store() -> FinancialVectorStore:
    return FinancialVectorStore(settings)


@lru_cache
def get_storage() -> LocalStorageProvider:
    return LocalStorageProvider(settings)


def get_chat_service() -> ChatService:
    return ChatService(settings, get_store())
