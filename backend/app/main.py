from fastapi import FastAPI
from app.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Automated Financial Document Analysis & RAG Engine",
)


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "online",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "provider": settings.DEFAULT_LLM_PROVIDER,
        "upload_dir": str(settings.UPLOAD_DIR),
        "chroma_dir": str(settings.CHROMA_DB_DIR),
    }
