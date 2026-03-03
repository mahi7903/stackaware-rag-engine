from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.database.database import SessionLocal
from app.models.document import Document

#for vector embedding 
import os
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.sqlalchemy import Vector


# I keep raw docs in app/data so ingestion is repeatable and easy to demo.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Small chunks are better for retrieval. Keeping it simple for v1.
CHUNK_SIZE = 400
CHUNK_OVERLAP = 60

def clean_text(text: str) -> str:
    # Some Windows-created UTF-8 files include a BOM (\ufeff). Strip it + trim spaces.
    return text.replace("\ufeff", "").strip()


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[str] = []
    start = 0
    step = chunk_size - overlap

    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += step

    return chunks


def load_txt_files(data_dir: Path = DATA_DIR) -> list[dict]:
    if not data_dir.exists():
        raise FileNotFoundError(f"Data folder not found: {data_dir}")

    files: list[dict] = []
    for file_path in sorted(data_dir.glob("*.txt")):
        content = file_path.read_text(encoding="utf-8").replace("\ufeff", "").strip()
        if not content:
            continue

        files.append(
            {
                "title": file_path.stem,         # "fastapi_notes"
                "source": file_path.name,        # "fastapi_notes.txt"
                "content": content,
                "source_path": str(file_path),
            }
        )

    return files


def chunks_already_ingested(db, source: str) -> bool:
    exists = db.execute(
        select(Document.id).where(Document.source == source).limit(1)
    ).first()
    return exists is not None


def ingest_as_chunks(raw_files: list[dict]) -> tuple[int, int]:
    """
    Returns (inserted_chunks, skipped_files).
    """
    inserted = 0
    skipped_files = 0

    with SessionLocal() as db:
        for f in raw_files:
            if chunks_already_ingested(db, f["source"]):
                skipped_files += 1
                continue

            chunks = chunk_text(f["content"])
            total = len(chunks)

            for idx, chunk in enumerate(chunks):
                db.add(
                    Document(
                        title=f["title"],
                        source=f["source"],
                        chunk_index=idx,
                        chunk_count=total,
                        content=chunk,
                    )
                )
                inserted += 1

        db.commit()

    return inserted, skipped_files


def embed_missing_rows(limit: int = 50) -> int:
    """
    Embeds rows where embedding is NULL and writes vectors into Postgres.
    """
    # .env is in project root, so from backend/app/utils we go up 3 levels -> backend -> root
    env_path = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(env_path)

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    if not api_key:
        raise RuntimeError(f"OPENAI_API_KEY not found. Checked: {env_path}")

    client = OpenAI(api_key=api_key)

    updated = 0
    with SessionLocal() as db:
        rows = db.execute(
            select(Document).where(Document.embedding.is_(None)).limit(limit)
        ).scalars().all()

        if not rows:
            print("No rows found with embedding IS NULL. Nothing to do.")
            return 0

        for row in rows:
            text = (row.content or "").strip()
            if not text:
                continue

            emb = client.embeddings.create(
                model=model,
                input=text,
            ).data[0].embedding

            # pgvector accepts a plain Python list[float]
            row.embedding = emb
            updated += 1

        db.commit()

    return updated


def main() -> None:
    raw_files = load_txt_files()

    inserted, skipped_files = ingest_as_chunks(raw_files)
    print(f"Raw files found: {len(raw_files)} in {DATA_DIR}")
    print(f"Inserted chunks: {inserted}")
    print(f"Skipped files (already ingested): {skipped_files}")

    updated = embed_missing_rows(limit=200)
    print(f"Embeddings written: {updated}")


if __name__ == "__main__":
    main()