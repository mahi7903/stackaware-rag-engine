from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from openai import OpenAI
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.models.query_log import QueryLog

from uuid import uuid4
from pypdf import PdfReader
from docx import Document as DocxDocument
from app.models.document import Document
from app.models.uploaded_file import UploadedFile

#imports for version uploads documents
import re
from app.models.document_version import DocumentVersion
# for SHA256 and skip reembedding hashlib import 
import hashlib

router = APIRouter(tags=["Stack Tools"])

#helper for documents upload version
def _make_doc_key(original_filename: str) -> str:
    """
    Intent: turn a filename into a stable doc_key (same logical document across versions).
    This is deliberately simple + predictable for v1, so we don't break existing flows.
    """
    base = os.path.splitext(original_filename)[0].strip().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base)
    return base.strip("-") or "document"

# Small helpers (kept local on purpose)


def _env_openai_client() -> tuple[OpenAI, str]:
    """
    I’m keeping OpenAI setup in one place so future changes (models, keys)
    won’t force me to edit multiple endpoints.
    """
    # Project convention: .env lives at project root (one level above backend/)
    load_dotenv("../.env")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY missing in .env")

    embed_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    client = OpenAI(api_key=api_key)
    return client, embed_model


def _chunk_text(text_data: str, chunk_size: int = 1200, overlap: int = 150) -> List[str]:
    """
    Simple chunking for v1:
    - breaks long text into fixed-size chunks
    - uses a small overlap so context isn't cut too harshly
    """
    if not text_data:
        return []

    text_data = text_data.strip()
    if not text_data:
        return []

    chunk_size = max(200, chunk_size)
    overlap = max(0, min(overlap, chunk_size // 2))

    chunks: List[str] = []
    start = 0
    n = len(text_data)

    while start < n:
        end = min(n, start + chunk_size)
        chunk = text_data[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end == n:
            break

        start = end - overlap

    return chunks


def _to_pgvector_literal(vec: list[float]) -> str:
    # pgvector accepts literals like: [0.12,0.34,...]
    return "[" + ",".join(f"{x:.10f}" for x in vec) + "]"



# 1) GET /stack/rag/history/{id}

@router.get("/rag/history/{log_id}")
def rag_history_by_id(
    log_id: int,
    db: Session = Depends(get_db),
):
    """
    Returns a single history record by ID.

    Why this matters:
    - frontend can show a "History list", then open details when user clicks an entry
    - this is also super useful for debugging which sources were used on a past answer
    """
    log = db.query(QueryLog).filter(QueryLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="History item not found")

    return {
        "id": log.id,
        "question": log.question,
        "answer": log.answer,
        "sources": log.sources,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }



# 2) GET /stack/rag/history  (with metadata filtering)

@router.get("/rag/history")
def rag_history_filtered(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),

    # "metadata filters" for v1 (these make the app feel real)
    question_contains: Optional[str] = Query(None, min_length=1, max_length=120),
    answer_contains: Optional[str] = Query(None, min_length=1, max_length=120),

    # When you want "only successful retrievals" vs "no context found"
    has_sources: Optional[bool] = Query(None),

    # Filter by source filename substring (e.g., "fastapi_notes")
    source_contains: Optional[str] = Query(None, min_length=1, max_length=120),

    # Time window filtering (ISO timestamps)
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),

    db: Session = Depends(get_db),
):
    """
    History feed for the frontend.

    v1 decisions (intentional):
    - global history (no user_id yet)
    - filters help you build a better UX quickly (search, tabs like "Answered" / "No context")
    """
    q = db.query(QueryLog)

    # Text search filters
    if question_contains:
        q = q.filter(QueryLog.question.ilike(f"%{question_contains}%"))

    if answer_contains:
        q = q.filter(QueryLog.answer.ilike(f"%{answer_contains}%"))

    # Time window filters
    if created_from:
        q = q.filter(QueryLog.created_at >= created_from)

    if created_to:
        q = q.filter(QueryLog.created_at <= created_to)

    # Sources filters
    #
    # sources is JSONB (list). We use jsonb_array_length to detect empty vs non-empty.
    sources_len = func.jsonb_array_length(QueryLog.sources)

    if has_sources is True:
        q = q.filter(sources_len > 0)
    elif has_sources is False:
        q = q.filter(sources_len == 0)

    # Filter by "source" field inside sources JSON list:
    # For v1, we keep it simple: convert JSON to text and substring match.
    # It's not the most elegant SQL in the world, but it’s reliable + fast enough for v1.
    if source_contains:
        q = q.filter(func.cast(QueryLog.sources, text("TEXT")).ilike(f"%{source_contains}%"))

    logs = (
        q.order_by(QueryLog.id.desc())
         .offset(offset)
         .limit(limit)
         .all()
    )

    return [
        {
            "id": log.id,
            "question": log.question,
            "answer": log.answer,
            "sources": log.sources,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


# 3) POST /stack/documents/upload  (upload + ingest into documents table)
@router.post("/documents/upload")
async def upload_document_and_ingest(
    file: UploadFile = File(...),

    # optional metadata
    title: Optional[str] = Query(None, max_length=200),
    source: Optional[str] = Query(None, max_length=200),

    # chunk tuning
    chunk_size: int = Query(1200, ge=200, le=4000),
    overlap: int = Query(150, ge=0, le=1000),

    db: Session = Depends(get_db),
):
    """
    Upload + ingest documents.

    v2 upgrade:
    - supports .txt / .md / .pdf / .docx
    - saves original file to backend/app/data/uploads/
    - logs upload metadata in uploaded_files table
    - extracts text -> chunk -> embed -> store in documents

    Versioning upgrade :
    - creates/updates a row in document_versions
    - links every stored document chunk to document_versions.id via documents.document_version_id
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(filename).suffix.lower()
    allowed = {".txt", ".md", ".pdf", ".docx"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Only .txt, .md, .pdf, .docx are supported")

    raw_bytes = await file.read()
    
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    doc_key = _make_doc_key(filename)

#  DUPLICATE CHECK GOES RIGHT HERE (before saving to disk)
    existing_active = (
        db.query(DocumentVersion)
        .join(UploadedFile, UploadedFile.id == DocumentVersion.upload_id)
        .filter(
            DocumentVersion.doc_key == doc_key,
            DocumentVersion.is_active == True,  # noqa: E712
            UploadedFile.content_hash == content_hash,
        )
        .order_by(DocumentVersion.version.desc())
        .first()
    )

    if existing_active:
        return {
            "message": "Duplicate upload (same content). Using existing active version.",
            "doc_key": doc_key,
            "upload_id": existing_active.upload_id,
            "document_version_id": existing_active.id,
            "version": existing_active.version,
            "note": "No file saved. No DB rows created. No embeddings regenerated.",
        }

    # 1) Save file to disk (admin-controlled storage)
    uploads_dir = Path(__file__).resolve().parents[1] / "data" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # I generate a safe stored filename to avoid collisions like "notes.txt" overwriting older uploads.
    stored_filename = f"{uuid4().hex}{ext}"
    saved_path = uploads_dir / stored_filename
    saved_path.write_bytes(raw_bytes)

    # Pick defaults for doc metadata (what we store with chunks)
    doc_title = title or Path(filename).stem
    doc_source = source or filename

    # 2) Extract text depending on file type
    try:
        if ext in {".txt", ".md"}:
            text_data = raw_bytes.decode("utf-8", errors="replace")

        elif ext == ".pdf":
            # pypdf reads PDF structure and gives us page text
            reader = PdfReader(str(saved_path))
            pages_text = []
            for p in reader.pages:
                pages_text.append(p.extract_text() or "")
            text_data = "\n\n".join(pages_text)

        elif ext == ".docx":
            # python-docx reads the Word XML and extracts paragraph text
            doc = DocxDocument(str(saved_path))
            paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
            text_data = "\n".join(paras)

        else:
            text_data = ""

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not extract text: {e}")

    text_data = (text_data or "").strip()
    if not text_data:
        raise HTTPException(status_code=400, detail="No readable text found in the uploaded document")

    # 3) Log upload metadata in uploaded_files table
    # 4) Chunk first (no DB changes yet)
    chunks = _chunk_text(text_data, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        raise HTTPException(status_code=400, detail="No usable chunks created from extracted text")

    # 5) Build embeddings first (still no DB changes)
    # Intent: compute embeddings before we touch version state.
    # If OpenAI fails, we never deactivate/delete the old version.
    client, embed_model = _env_openai_client()
    try:
        vec_literals: list[str] = []
        for chunk in chunks:
            emb = client.embeddings.create(model=embed_model, input=chunk).data[0].embedding
            vec_literals.append(_to_pgvector_literal(emb))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    insert_sql = text("""
        INSERT INTO documents
            (title, source, chunk_index, chunk_count, content, embedding, document_version_id)
        VALUES
            (:title, :source, :chunk_index, :chunk_count, :content, (:embedding)::vector(1536), :document_version_id);
    """)

    # 6) ATOMIC DB transaction: upload_row + version flip + delete old chunks + insert new chunks
    try:
        # Intent: one all-or-nothing operation.
        # If anything fails below, old version remains active and its chunks remain intact.
        with db.begin():

            # 6.1) Log upload metadata
            upload_row = UploadedFile(
                original_filename=filename,
                stored_filename=stored_filename,
                content_type=file.content_type,
                size_bytes=len(raw_bytes),
                title=doc_title,
                source=doc_source,
                storage_path=str(saved_path),
                uploaded_by_user_id=None,  # later we can fill this from auth
                content_hash=content_hash,
            )
            db.add(upload_row)
            db.flush()  # gives upload_row.id without committing

            # 6.2) Find current active version (if any)
            active = (
                db.query(DocumentVersion)
                .filter(
                    DocumentVersion.doc_key == doc_key,
                    DocumentVersion.is_active == True,  # noqa: E712
                )
                .order_by(DocumentVersion.version.desc())
                .first()
            )

            next_version = 1
            if active:
                next_version = active.version + 1

                # deactivate old version
                active.is_active = False

                # remove old embeddings/chunks (so only latest remains stored)
                db.query(Document).filter(
                    Document.document_version_id == active.id
                ).delete()

            # 6.3) Create new version row
            new_version = DocumentVersion(
                doc_key=doc_key,
                version=next_version,
                upload_id=upload_row.id,
                is_active=True,
                meta={"original_filename": filename},
            )
            db.add(new_version)
            db.flush()  # gives new_version.id without committing

            # 6.4) Insert chunks for the new version
            chunk_count = len(chunks)
            for i, chunk in enumerate(chunks):
                db.execute(
                    insert_sql,
                    {
                        "title": doc_title,
                        "source": doc_source,
                        "chunk_index": i,
                        "chunk_count": chunk_count,
                        "content": chunk,
                        "embedding": vec_literals[i],
                        "document_version_id": new_version.id,
                    },
                )

        # leaving the 'with db.begin()' block commits automatically

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Upload ingest failed: {e}")

    return {
        "message": "Upload + ingest successful",
        "upload_id": upload_row.id,
        "document_version_id": new_version.id,
        "doc_key": doc_key,
        "version": next_version,
        "original_filename": filename,
        "stored_filename": stored_filename,
        "saved_to": str(saved_path),
        "title": doc_title,
        "source": doc_source,
        "chunks_ingested": len(chunks),
    }

#to get all the uploaded documentslist 
@router.get("/documents")
def list_ingested_documents(
    db: Session = Depends(get_db),
):
    """
    Intent: Admin-only inventory view of what's currently indexed for RAG.
    We return only ACTIVE versions, because that's what retrieval uses.
    """
    rows = db.execute(text("""
        SELECT
            dv.doc_key,
            dv.version,
            dv.created_at,
            uf.original_filename,
            uf.stored_filename,
            uf.uploaded_at,
            COUNT(d.id) AS chunk_count
        FROM document_versions dv
        JOIN uploaded_files uf ON uf.id = dv.upload_id
        LEFT JOIN documents d ON d.document_version_id = dv.id
        WHERE dv.is_active = true
        GROUP BY
            dv.doc_key, dv.version, dv.created_at,
            uf.original_filename, uf.stored_filename, uf.uploaded_at
        ORDER BY dv.created_at DESC;
    """)).mappings().all()

    return [
        {
            "doc_key": r["doc_key"],
            "version": r["version"],
            "chunk_count": int(r["chunk_count"] or 0),
            "original_filename": r["original_filename"],
            "stored_filename": r["stored_filename"],
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
            "version_created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]