from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from pathlib import Path
from app.database.db import get_db

from app.auth.security import get_current_user
from app.models.user import User

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.uploaded_file import UploadedFile
from app.routers.stack_tools import _chunk_text, _env_openai_client, _to_pgvector_literal
from app.utils.api_guards import log_info, log_error


# all admin document routes behind login so delete/read actions are not public.
router = APIRouter(
    tags=["Admin Documents"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/documents/{doc_key}")
def get_document_versions(
    doc_key: str,
    db: Session = Depends(get_db),
):
    """
    Intent:
    Return one logical document with all its versions so I can inspect
    what is currently active, what was uploaded before, and how many
    chunks each version has in the vector store.
    """
    rows = db.execute(
        text(
            """
            SELECT
                dv.id,
                dv.doc_key,
                dv.version,
                dv.is_active,
                dv.created_at,
                dv.meta,
                dv.upload_id,
                uf.original_filename,
                uf.stored_filename,
                uf.content_type,
                uf.size_bytes,
                uf.title,
                uf.source,
                uf.storage_path,
                uf.uploaded_at,
                COUNT(d.id) AS chunk_count
            FROM document_versions dv
            JOIN uploaded_files uf
                ON uf.id = dv.upload_id
            LEFT JOIN documents d
                ON d.document_version_id = dv.id
            WHERE dv.doc_key = :doc_key
            GROUP BY
                dv.id,
                dv.doc_key,
                dv.version,
                dv.is_active,
                dv.created_at,
                dv.meta,
                dv.upload_id,
                uf.original_filename,
                uf.stored_filename,
                uf.content_type,
                uf.size_bytes,
                uf.title,
                uf.source,
                uf.storage_path,
                uf.uploaded_at
            ORDER BY dv.version DESC
            """
        ),
        {"doc_key": doc_key},
    ).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # to find the currently active version so I can show a quick summary at the top.
    active_row = next((r for r in rows if r["is_active"]), None)
    return {
        "doc_key": doc_key,
        "summary": {
            # quick admin snapshot so I can inspect one logical document without scanning every version manually.
            "version_count": len(rows),
            "active_version_id": active_row["id"] if active_row else None,
            "active_version_number": active_row["version"] if active_row else None,
            "active_original_filename": active_row["original_filename"] if active_row else None,
            "active_uploaded_at": active_row["uploaded_at"].isoformat() if active_row and active_row["uploaded_at"] else None,
        },
        "versions": [
            {
                "document_version_id": r["id"],
                "doc_key": r["doc_key"],
                "version": r["version"],
                "is_active": r["is_active"],
                "chunk_count": int(r["chunk_count"] or 0),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "meta": r["meta"],
                "upload": {
                    "upload_id": r["upload_id"],
                    "original_filename": r["original_filename"],
                    "stored_filename": r["stored_filename"],
                    "content_type": r["content_type"],
                    "size_bytes": int(r["size_bytes"] or 0),
                    "title": r["title"],
                    "source": r["source"],
                    "storage_path": r["storage_path"],
                    "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
                },
            }
           
            for r in rows
        ],
    }












@router.delete("/documents/{doc_key}")
def delete_document_by_doc_key(
    doc_key: str,
    db: Session = Depends(get_db),
):
    """
    Intent:
    Delete one full logical document across all versions. This removes every
    version row, every linked chunk row, every upload metadata row, and then
    tries to clean up the saved files from disk after the DB commit succeeds.
    """
    version_rows = db.execute(
        text(
            """
            SELECT
                dv.id AS document_version_id,
                dv.version,
                dv.is_active,
                dv.upload_id,
                uf.storage_path,
                uf.original_filename,
                uf.stored_filename
            FROM document_versions dv
            JOIN uploaded_files uf
                ON uf.id = dv.upload_id
            WHERE dv.doc_key = :doc_key
            ORDER BY dv.version DESC
            """
        ),
        {"doc_key": doc_key},
    ).mappings().all()

    if not version_rows:
        raise HTTPException(status_code=404, detail="Document not found")

    deleted_version_ids = [row["document_version_id"] for row in version_rows]
    deleted_upload_ids = [row["upload_id"] for row in version_rows]

    try:
        with db.begin_nested():
            # remove all embedded chunks tied to every version of this logical doc.
            db.execute(
                text(
                    """
                    DELETE FROM documents
                    WHERE document_version_id IN (
                        SELECT id
                        FROM document_versions
                        WHERE doc_key = :doc_key
                    )
                    """
                ),
                {"doc_key": doc_key},
            )

            #remove all version rows for this logical document.
            db.execute(
                text(
                    """
                    DELETE FROM document_versions
                    WHERE doc_key = :doc_key
                    """
                ),
                {"doc_key": doc_key},
            )

            # remove all upload metadata rows linked to those deleted versions.
            db.execute(
                text(
                    """
                    DELETE FROM uploaded_files
                    WHERE id = ANY(:upload_ids)
                    """
                ),
                {"upload_ids": deleted_upload_ids},
            )

        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete document failed: {e}")

    deleted_files_from_disk = []
    failed_files_from_disk = []

    # file cleanup happens after commit so DB state stays the source of truth.
    for row in version_rows:
        storage_path = row["storage_path"]
        if not storage_path:
            continue

        try:
            saved_file = Path(storage_path)
            if saved_file.exists():
                saved_file.unlink()
                deleted_files_from_disk.append(storage_path)
        except Exception:
            failed_files_from_disk.append(storage_path)

    return {
        "message": "Logical document deleted successfully",
        "doc_key": doc_key,
        "deleted_version_ids": deleted_version_ids,
        "deleted_upload_ids": deleted_upload_ids,
        "deleted_versions_count": len(deleted_version_ids),
        "deleted_files_from_disk": deleted_files_from_disk,
        "failed_file_deletes": failed_files_from_disk,
    }









@router.get("/documents")
def list_admin_documents(
    db: Session = Depends(get_db),
):
    """
    Intent:
    Give admin routes their own document inventory view so listing, inspection,
    and deletion all live under the same /documents namespace.
    """
    rows = db.execute(
        text(
            """
            SELECT
                dv.doc_key,
                dv.id AS document_version_id,
                dv.version,
                dv.is_active,
                dv.created_at,
                uf.original_filename,
                uf.stored_filename,
                uf.uploaded_at,
                COUNT(d.id) AS chunk_count
            FROM document_versions dv
            JOIN uploaded_files uf
                ON uf.id = dv.upload_id
            LEFT JOIN documents d
                ON d.document_version_id = dv.id
            WHERE dv.is_active = true
            GROUP BY
                dv.doc_key,
                dv.id,
                dv.version,
                dv.is_active,
                dv.created_at,
                uf.original_filename,
                uf.stored_filename,
                uf.uploaded_at
            ORDER BY dv.created_at DESC
            """
        )
    ).mappings().all()

    return [
        {
            "doc_key": r["doc_key"],
            "document_version_id": r["document_version_id"],
            "version": r["version"],
            "is_active": r["is_active"],
            "chunk_count": int(r["chunk_count"] or 0),
            "original_filename": r["original_filename"],
            "stored_filename": r["stored_filename"],
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
            "version_created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]









@router.post("/documents/reindex/{doc_key}")
def reindex_document_by_doc_key(
    doc_key: str,
    db: Session = Depends(get_db),
):
    """
    Intent:
    Rebuild embeddings for the current active version of one logical document.
    For safety, I only target the active version because that is what retrieval uses.
    """
    active_row = (
        db.query(DocumentVersion)
        .join(UploadedFile, UploadedFile.id == DocumentVersion.upload_id)
        .filter(
            DocumentVersion.doc_key == doc_key,
            DocumentVersion.is_active == True,  # noqa: E712
        )
        .order_by(DocumentVersion.version.desc())
        .first()
    )

    if not active_row:
        raise HTTPException(status_code=404, detail="Active document version not found")
    log_info(
        "reindex_started",
        doc_key=doc_key,
        active_version_id=active_row.id,
        upload_id=active_row.upload_id,
    )

    if not active_row.upload_id:
        raise HTTPException(status_code=400, detail="Active version has no linked upload")

    upload_row = (
        db.query(UploadedFile)
        .filter(UploadedFile.id == active_row.upload_id)
        .first()
    )

    if not upload_row:
        raise HTTPException(status_code=404, detail="Linked upload metadata not found")

    if not upload_row.storage_path:
        raise HTTPException(status_code=400, detail="Upload file path is missing")

    saved_path = Path(upload_row.storage_path)

    if not saved_path.exists():
        raise HTTPException(status_code=404, detail="Uploaded file no longer exists on disk")
    log_info(
        "reindex_file_found",
        doc_key=doc_key,
        storage_path=str(saved_path),
    )

    ext = saved_path.suffix.lower()

    try:
        if ext in {".txt", ".md"}:
            text_data = saved_path.read_text(encoding="utf-8", errors="replace")

        elif ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(saved_path))
            pages_text = []
            for p in reader.pages:
                pages_text.append(p.extract_text() or "")
            text_data = "\n\n".join(pages_text)

        elif ext == ".docx":
            from docx import Document as DocxDocument

            doc = DocxDocument(str(saved_path))
            paras = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
            text_data = "\n".join(paras)

        else:
            raise HTTPException(status_code=400, detail="Unsupported file type for reindex")
    except Exception as e:
        log_error(
            "reindex_text_extraction_failed",
            error=e,
            doc_key=doc_key,
            storage_path=str(saved_path),
        )
        raise HTTPException(status_code=400, detail=f"Could not extract text for reindex: {e}")

    text_data = (text_data or "").strip()
    if not text_data:
        raise HTTPException(status_code=400, detail="No readable text found for reindex")

    chunks = _chunk_text(text_data)
    if not chunks:
        raise HTTPException(status_code=400, detail="No usable chunks created for reindex")

    client, embed_model = _env_openai_client()

    try:
        vec_literals: list[str] = []
        for chunk in chunks:
            emb = client.embeddings.create(model=embed_model, input=chunk).data[0].embedding
            vec_literals.append(_to_pgvector_literal(emb))
    except Exception as e:
        log_error(
            "reindex_embedding_failed",
            error=e,
            doc_key=doc_key,
            chunk_count=len(chunks),
        )
        raise HTTPException(status_code=500, detail=f"Embedding failed during reindex: {e}")

    insert_sql = text("""
        INSERT INTO documents
            (title, source, chunk_index, chunk_count, content, embedding, document_version_id)
        VALUES
            (:title, :source, :chunk_index, :chunk_count, :content, (:embedding)::vector(1536), :document_version_id)
    """)

    deleted_old_chunks = db.query(Document).filter(
        Document.document_version_id == active_row.id
    ).count()

    try:
        with db.begin_nested():
            # clear old chunks first so the active version gets a clean rebuilt embedding set.
            db.query(Document).filter(
                Document.document_version_id == active_row.id
            ).delete()

            chunk_count = len(chunks)

            for i, chunk in enumerate(chunks):
                db.execute(
                    insert_sql,
                    {
                        "title": upload_row.title or upload_row.original_filename or saved_path.stem,
                        "source": upload_row.source or upload_row.original_filename,
                        "chunk_index": i,
                        "chunk_count": chunk_count,
                        "content": chunk,
                        "embedding": vec_literals[i],
                        "document_version_id": active_row.id,
                    },
                )

        db.commit()

    except Exception as e:
        db.rollback()
        log_error(
            "reindex_db_failed",
            error=e,
            doc_key=doc_key,
            active_version_id=active_row.id,
        )
        raise HTTPException(status_code=500, detail=f"Reindex failed: {e}")
    log_info(
        "reindex_completed",
        doc_key=doc_key,
        active_version_id=active_row.id,
        chunk_count=len(chunks),
    )
    return {
        "message": "Document reindexed successfully",
        "doc_key": doc_key,
        "active_version_id": active_row.id,
        "active_version_number": active_row.version,
        "upload_id": upload_row.id,
        "original_filename": upload_row.original_filename,
        "stored_filename": upload_row.stored_filename,
        "deleted_old_chunks": deleted_old_chunks,
        "reindexed_chunk_count": len(chunks),
        "embedding_model": embed_model,
    }











@router.delete("/documents/version/{version_id}")
def delete_document_version(
    version_id: int,
    db: Session = Depends(get_db),
):
    """
    Intent:
    Delete exactly one stored document version without touching other logical
    versions of the same document. If the deleted version was active, I promote
    the newest remaining version to active so retrieval still has one current version.
    """
    version_row = db.execute(
        text(
            """
            SELECT
                dv.id,
                dv.doc_key,
                dv.version,
                dv.is_active,
                dv.upload_id,
                uf.storage_path,
                uf.original_filename,
                uf.stored_filename
            FROM document_versions dv
            JOIN uploaded_files uf
                ON uf.id = dv.upload_id
            WHERE dv.id = :version_id
            """
        ),
        {"version_id": version_id},
    ).mappings().first()

    if not version_row:
        raise HTTPException(status_code=404, detail="Document version not found")

    replacement_version = db.execute(
        text(
            """
            SELECT id, version
            FROM document_versions
            WHERE doc_key = :doc_key
              AND id != :version_id
            ORDER BY version DESC
            LIMIT 1
            """
        ),
        {
            "doc_key": version_row["doc_key"],
            "version_id": version_id,
        },
    ).mappings().first()

    try:
        with db.begin_nested():
            #remove all vector chunks tied to this exact version first.
            db.execute(
                text(
                    """
                    DELETE FROM documents
                    WHERE document_version_id = :version_id
                    """
                ),
                {"version_id": version_id},
            )

            #remove the version row itself after its chunks are gone.
            db.execute(
                text(
                    """
                    DELETE FROM document_versions
                    WHERE id = :version_id
                    """
                ),
                {"version_id": version_id},
            )

            #if this version was the active one, promote the newest remaining version.
            if version_row["is_active"] and replacement_version:
                db.execute(
                    text(
                        """
                        UPDATE document_versions
                        SET is_active = true
                        WHERE id = :replacement_id
                        """
                    ),
                    {"replacement_id": replacement_version["id"]},
                )

            #uploaded_files row belongs to this exact version upload, so it can go too.
            db.execute(
                text(
                    """
                    DELETE FROM uploaded_files
                    WHERE id = :upload_id
                    """
                ),
                {"upload_id": version_row["upload_id"]},
            )

        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Delete version failed: {e}")

    file_deleted = False
    storage_path = version_row["storage_path"]

    # Intent: try to remove the physical file after DB commit so database state stays safe.
    if storage_path:
        try:
            saved_file = Path(storage_path)
            if saved_file.exists():
                saved_file.unlink()
                file_deleted = True
        except Exception:
            file_deleted = False

    return {
        "message": "Document version deleted successfully",
        "deleted_version_id": version_row["id"],
        "doc_key": version_row["doc_key"],
        "deleted_version": version_row["version"],
        "was_active": version_row["is_active"],
        "promoted_version": replacement_version["version"] if version_row["is_active"] and replacement_version else None,
        "deleted_upload_id": version_row["upload_id"],
        "deleted_file_from_disk": file_deleted,
        "original_filename": version_row["original_filename"],
        "stored_filename": version_row["stored_filename"],
    }





