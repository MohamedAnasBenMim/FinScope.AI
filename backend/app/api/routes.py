from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from app.config import settings
from app.ingestion.pdf_parser import FinancialPDFParser
from app.rag.chunker import FinancialChunker
from app.rag.vector_store import FinancialVectorStore
from app.tools.calculator import FinancialCalculator
from app.rag.prompts import build_rag_prompt

router = APIRouter()
vector_store = FinancialVectorStore()
calculator = FinancialCalculator()


class QueryRequest(BaseModel):
    query: str
    top_k: int = 3


class CalculateRequest(BaseModel):
    calc_type: str  # "yoy" | "margin"
    param1: str | float
    param2: str | float
    metric_name: str = "Metric"


@router.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Uploads a financial PDF, parses text & tables, and indexes chunks into ChromaDB."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    file_path = settings.UPLOAD_DIR / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # 1. Parse document
    parser = FinancialPDFParser(file_path)
    doc = parser.parse()

    # 2. Chunk document
    chunker = FinancialChunker()
    chunks = chunker.chunk_document(doc)

    # 3. Index into ChromaDB
    vector_store.add_chunks(chunks)

    return {
        "status": "success",
        "filename": file.filename,
        "total_pages": doc.total_pages,
        "indexed_chunks": len(chunks),
        "tables_found": sum(1 for c in chunks if c.is_table)
    }


@router.get("/documents")
async def list_documents():
    """Lists all uploaded documents."""
    files = [f.name for f in settings.UPLOAD_DIR.glob("*.pdf")]
    return {"documents": files, "count": len(files)}


@router.post("/chat/query")
async def query_rag(req: QueryRequest):
    """Hybrid vector search + RAG prompt context builder."""
    retrieved = vector_store.hybrid_search(req.query, top_k=req.top_k)
    prompt = build_rag_prompt(retrieved, req.query)

    citations = [
        {
            "filename": item["metadata"]["filename"],
            "page_number": item["metadata"]["page_number"],
            "is_table": item["metadata"]["is_table"]
        }
        for item in retrieved
    ]

    return {
        "query": req.query,
        "rag_prompt": prompt,
        "retrieved_context": retrieved,
        "citations": citations
    }


@router.post("/analysis/calculate")
async def calculate_metric(req: CalculateRequest):
    """Runs deterministic financial calculation."""
    if req.calc_type == "yoy":
        res = calculator.calculate_yoy_growth(req.param1, req.param2, req.metric_name)
    elif req.calc_type == "margin":
        res = calculator.calculate_profit_margin(req.param1, req.param2)
    else:
        raise HTTPException(status_code=400, detail="Invalid calc_type. Use 'yoy' or 'margin'.")

    return {"status": "success", "result": res}
