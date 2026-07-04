"""Phase 2: Document upload router for RAG knowledge base."""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from app.services.rag_retriever import rag_retriever
from app.utils.logger import get_logger
import uuid

logger = get_logger("documents")
router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload")
async def upload_document(
    sector: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a document to a sector's knowledge base.

    Supported formats: .txt, .md, .csv
    PDF support requires additional parsing (add PyPDF2/pdfplumber).
    """
    allowed_types = {".txt", ".md", ".csv"}
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

    if ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {allowed_types}",
        )

    content = await file.read()
    text = content.decode("utf-8", errors="ignore")

    if not text.strip():
        raise HTTPException(status_code=400, detail="File is empty")

    doc_id = f"{sector}_{uuid.uuid4().hex[:8]}"

    chunks_added = await rag_retriever.add_document(
        sector=sector,
        doc_id=doc_id,
        content=text,
        metadata={"filename": file.filename},
    )

    logger.info(f"Uploaded {file.filename} to {sector}: {chunks_added} chunks")

    return {
        "status": "uploaded",
        "doc_id": doc_id,
        "filename": file.filename,
        "sector": sector,
        "chunks": chunks_added,
    }


@router.post("/add-text")
async def add_text_document(
    sector: str,
    title: str,
    content: str,
):
    """Add raw text content directly to a sector's knowledge base."""
    doc_id = f"{sector}_{uuid.uuid4().hex[:8]}"

    chunks_added = await rag_retriever.add_document(
        sector=sector,
        doc_id=doc_id,
        content=content,
        metadata={"title": title},
    )

    return {
        "status": "added",
        "doc_id": doc_id,
        "sector": sector,
        "chunks": chunks_added,
    }


@router.delete("/{sector}/{doc_id}")
async def delete_document(sector: str, doc_id: str):
    """Remove a document from the knowledge base."""
    await rag_retriever.delete_document(sector, doc_id)
    return {"status": "deleted", "doc_id": doc_id}


@router.post("/search")
async def search_documents(
    sector: str,
    query: str,
    top_k: int = 3,
):
    """Search the knowledge base (for testing RAG retrieval)."""
    result = await rag_retriever.retrieve(query, sector, top_k)
    return {
        "sector": sector,
        "query": query,
        "chunks": result.chunks,
        "sources": result.sources,
        "total": result.total_chunks,
    }
