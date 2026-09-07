from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT / ".env", ROOT / "backend/.env"), extra="ignore")

    APP_NAME: str = "FinScope.AI"
    APP_VERSION: str = "1.0.0"
    ENV: str = "development"
    DATABASE_URL: str = f"sqlite:///{ROOT}/data/finscope.db"
    UPLOAD_DIR: Path = ROOT / "data/uploads"
    MODEL_CACHE_DIR: Path = ROOT / "data/models"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:8081"]
    MAX_FILE_SIZE: int = Field(30 * 1024 * 1024, gt=0)
    MAX_FILES_PER_UPLOAD: int = Field(20, ge=1, le=100)
    MAX_DOCUMENT_PAGES: int = Field(500, ge=1)
    MAX_SPREADSHEET_CELLS: int = Field(200000, ge=1)
    MAX_IMAGE_PIXELS: int = Field(40000000, ge=1)
    MAX_ARCHIVE_BYTES: int = Field(200 * 1024 * 1024, ge=1)
    DUPLICATE_BEHAVIOR: Literal["reuse", "reject", "allow"] = "reuse"
    CLASSIFICATION_THRESHOLD: float = Field(0.65, ge=0, le=1)
    PARSER_PROVIDER: Literal["native", "docling"] = "native"
    OCR_PROVIDER: Literal["tesseract"] = "tesseract"
    OCR_LANGUAGES: str = "fra+eng"
    OCR_MIN_TEXT_CHARS: int = Field(30, ge=0)
    OCR_TIMEOUT: int = Field(90, gt=0)
    INGESTION_TIMEOUT: int = Field(1200, ge=30)
    WORKER_POLL_INTERVAL: float = Field(1.0, gt=0)
    WORKER_HEARTBEAT_PATH: Path = ROOT / "data/worker.heartbeat"
    CHUNK_WORDS: int = Field(260, ge=30, le=400)
    TABLE_CHUNK_ROWS: int = Field(20, ge=1, le=100)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "finscope_multilingual_v1"
    EMBEDDING_PROVIDER: Literal["local", "api"] = "local"
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"
    EMBEDDING_API_KEY: str | None = None
    EMBEDDING_BASE_URL: str = "https://api.openai.com/v1"
    EMBEDDING_DIMENSIONS: int = Field(384, gt=0)
    EMBEDDING_THREADS: int = Field(2, ge=1)
    EMBEDDING_LOCAL_ONLY: bool = False
    LLM_PROVIDER: Literal["local", "ollama", "openai", "extractive"] = "local"
    LLM_MODEL: str = "finscope-local"
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str = "http://localhost:8082/v1"
    PROVIDER_TIMEOUT: int = Field(180, gt=0)
    RETRIEVAL_TOP_K: int = Field(24, ge=1, le=200)
    RERANK_TOP_K: int = Field(10, ge=1, le=100)
    MIN_RETRIEVAL_SCORE: float = Field(0.05, ge=0, le=1)
    RERANK_ENABLED: bool = True
    RETRIEVAL_DEBUG: bool = False


settings = Settings()
