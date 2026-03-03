from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text

from app.database.database import SessionLocal


def main() -> None:
    # You are running from backend/, and .env is in project root
    load_dotenv("../.env")

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in ../.env")

    client = OpenAI(api_key=api_key)

    query = "What is FastAPI used for?"
    qvec = client.embeddings.create(model=model, input=query).data[0].embedding

    # Convert Python list[float] -> pgvector literal string
    vec_literal = "[" + ",".join(f"{x:.10f}" for x in qvec) + "]"

    sql = text(
        """
        SELECT id, title, source, chunk_index, chunk_count,
               (embedding <-> (:qvec)::vector(1536)) AS l2_distance,
               LEFT(content, 140) AS preview
        FROM documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <-> (:qvec)::vector(1536)
        LIMIT 5;
        """
    )

    with SessionLocal() as db:
        count = db.execute(
            text("SELECT COUNT(*) FROM documents WHERE embedding IS NOT NULL;")
        ).scalar_one()
        print("Rows with embeddings:", count)

        rows = db.execute(sql, {"qvec": vec_literal}).fetchall()

    print(f"Query: {query}")
    if not rows:
        print("No rows returned (unexpected).")
        return

    for r in rows:
        print(
            f"- id={r.id} title={r.title} source={r.source} "
            f"dist={float(r.l2_distance):.6f} preview={r.preview!r}"
        )


if __name__ == "__main__":
    main()