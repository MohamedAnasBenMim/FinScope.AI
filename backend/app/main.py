from contextlib import asynccontextmanager

from app.api.body_limit import UploadBodyLimit
from app.api.routes import router
from app.config import settings
from app.errors import ApplicationError
from app.logging_config import configure_logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Multi-format financial document intelligence with grounded citations.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
app.add_middleware(
    UploadBodyLimit, max_bytes=settings.MAX_FILE_SIZE * settings.MAX_FILES_PER_UPLOAD + 1024 * 1024
)


@app.exception_handler(ApplicationError)
async def application_error(_: Request, exc: ApplicationError):
    return JSONResponse({"detail": str(exc), "code": type(exc).__name__}, status_code=exc.status_code)


@app.middleware("http")
async def request_limits(request: Request, call_next):
    if request.url.path == "/api/documents/upload":
        size = request.headers.get("content-length")
        maximum = settings.MAX_FILE_SIZE * settings.MAX_FILES_PER_UPLOAD + 1024 * 1024
        if size:
            try:
                if int(size) > maximum:
                    return JSONResponse(
                        {"detail": "Upload request exceeds the combined file-size limit."}, status_code=413
                    )
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


app.include_router(router, prefix="/api")


@app.get("/", include_in_schema=False)
def root():
    return {"app": settings.APP_NAME, "docs": "/docs"}


@app.get("/health", include_in_schema=False)
def health_alias():
    return {"status": "healthy"}
