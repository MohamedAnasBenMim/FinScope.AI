FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend:/app \
    PIP_NO_CACHE_DIR=1 PIP_DEFAULT_TIMEOUT=180 TOKENIZERS_PARALLELISM=false HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_XET=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements*.txt /app/backend/
RUN pip install -r backend/requirements-dev.txt
RUN useradd --uid 10001 --create-home appuser && mkdir -p /app/data/uploads /app/data/models && chown -R appuser:appuser /app
COPY --chown=appuser:appuser backend/app /app/backend/app
COPY --chown=appuser:appuser backend/migrations /app/backend/migrations
COPY --chown=appuser:appuser alembic.ini pyproject.toml /app/
COPY --chown=appuser:appuser scripts /app/scripts
COPY --chown=appuser:appuser tests /app/tests
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
