from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.routes import router as api_router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="FinScope.AI — Automated Financial Document Analysis & RAG Platform",
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routes
app.include_router(api_router, prefix="/api")


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
