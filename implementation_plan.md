# FinScope.AI implementation plan

Inspection: FastAPI/Pydantic backend, React/Vite frontend, working pdfplumber
PDF tables and calculator, incomplete Chroma/BM25 retrieval. No database models,
migrations, queue, Docker files, or automated assertions. Existing user changes
in the API and frontend are incorporated into this work.

1. Preserve FastAPI, React, PDF extraction, and calculator. Add configuration,
   SQLAlchemy/Alembic metadata, safe storage, and a durable SQL ingestion queue.
   PostgreSQL in Compose; SQLite for isolated tests.
2. Normalize PDF, images, Office, spreadsheets, CSV, text, Markdown, and HTML.
   Add French/English Tesseract OCR, native cell/formula provenance, limits, and
   optional Docling conversion. Native parsers remain the default to reuse the
   working PDF parser and avoid mandatory layout model downloads.
3. Implement evidence-based classification, Pydantic financial extraction,
   arithmetic warnings, and deterministic section/table/page-aware chunks.
4. Replace incomplete Chroma/BM25 with persistent Qdrant dense/sparse vectors,
   RRF fusion, filters, reranking, and multilingual local/API embeddings.
5. Implement Ollama/OpenAI-compatible providers, evidence validation, precise
   citations, multi-document queries, and an explicit extractive operating mode.
6. Integrate upload progress, jobs, extraction details, filters, chat, and source
   links in the existing React application; retain the calculator.
7. Generate bilingual fixtures, test each completed layer, run evaluation and
   the full suite, build/lint frontend, launch Compose, exercise mixed uploads,
   and verify persistence after restart.

Executed results will be recorded in docs/verification.md and README.md.
