from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.auth.tokens import get_current_user
from app.schemas.schemas import StackItemAdd, StackItemOut, TechItemOut
from app.models.profile import TechItem, UserStackItem, UserProfile
from app.schemas.schemas import StackItemAdd, StackItemOut, TechItemOut, StackContextOut #import for relation source of truth between stack/context and userstackitem

#imports for stack embedding route /rag/search
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text
from fastapi import HTTPException, Query
from app.database.database import SessionLocal
#till here

#querry tool endpoint imports 
from typing import List, Optional
from fastapi import Depends
from sqlalchemy.orm import Session

from app.models.query_log import QueryLog


router = APIRouter()


@router.post("/items", response_model=StackItemOut, status_code=status.HTTP_201_CREATED)
def add_stack_item(
    payload: StackItemAdd,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) find the tech by slug (frontend-friendly)
    tech = db.query(TechItem).filter(TechItem.slug == payload.tech_slug).first()
    if not tech:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tech item not found. Use a valid tech_slug.",
        )

    # 2) block duplicates (db also enforces unique constraint, but we give a nice message)
    existing = (
        db.query(UserStackItem)
        .filter(
            UserStackItem.user_id == current_user.id,
            UserStackItem.tech_id == tech.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That tech is already in your stack.",
        )

    # 3) create stack item
    stack_item = UserStackItem(
        user_id=current_user.id,
        tech_id=tech.id,
        version=payload.version,
    )
    db.add(stack_item)
    db.commit()
    db.refresh(stack_item)
        # --- mirror stack into user profile preferences (JSONB) ---
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if not profile:
        # create profile if missing (keeps UX smooth)
        profile = UserProfile(user_id=current_user.id, preferences={})
        db.add(profile)
        db.commit()
        db.refresh(profile)


    # 4) store the profile
    prefs = profile.preferences or {}
    stack_list = prefs.get("stack", [])

    stack_list.append(
        {
            "tech_slug": tech.slug,
            "version": payload.version,
        }
    )

    prefs["stack"] = stack_list
    profile.preferences = prefs
    db.commit()

    # 5) return a clean response (don’t leak internal IDs)
    return StackItemOut(
        tech_slug=tech.slug,
        tech_name=tech.name,
        category=tech.category,
        version=stack_item.version,
    )


@router.get("/my", response_model=list[StackItemOut])
def get_my_stack(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile or not profile.preferences:
        return []

    stack_list = (profile.preferences or {}).get("stack", [])
    if not stack_list:
        return []

    results: list[StackItemOut] = []

    for item in stack_list:
        tech_slug = item.get("tech_slug")
        version = item.get("version")

        if not tech_slug:
            continue

        tech = db.query(TechItem).filter(TechItem.slug == tech_slug).first()
        if not tech:
            # if tech was removed from catalog, we just skip it
            continue

        results.append(
            StackItemOut(
                tech_slug=tech.slug,
                tech_name=tech.name,
                category=tech.category,
                version=version,
            )
        )

    return results

#route to delete the slug
@router.delete("/items/{tech_slug}", status_code=204)
def remove_stack_item(
    tech_slug: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # find tech in catalog
    tech = db.query(TechItem).filter(TechItem.slug == tech_slug).first()
    if not tech:
        raise HTTPException(status_code=404, detail="Tech not found")

    # remove relational entry
    stack_item = (
        db.query(UserStackItem)
        .filter(
            UserStackItem.user_id == current_user.id,
            UserStackItem.tech_id == tech.id,
        )
        .first()
    )

    if not stack_item:
        raise HTTPException(status_code=404, detail="Tech not in your stack")

    db.delete(stack_item)
    db.commit()

    # update profile mirror
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if profile and profile.preferences:
        prefs = profile.preferences
        stack_list = prefs.get("stack", [])

        stack_list = [item for item in stack_list if item.get("tech_slug") != tech_slug]

        prefs["stack"] = stack_list
        profile.preferences = prefs
        db.commit()

    return


#route to list the slug 
@router.get("/tech", response_model=list[TechItemOut])
def list_tech_catalog(db: Session = Depends(get_db)):
    # simple catalog list for dropdowns/search in frontend
    items = db.query(TechItem).order_by(TechItem.category.asc(), TechItem.name.asc()).all()
    return items




#route for relation source of truth between stack/context and userstackitem
@router.get("/context", response_model=StackContextOut)
def get_stack_context(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # source of truth: user_stack_items (relational)
    rows = (
        db.query(UserStackItem, TechItem)
        .join(TechItem, UserStackItem.tech_id == TechItem.id)
        .filter(UserStackItem.user_id == current_user.id)
        .order_by(TechItem.category.asc(), TechItem.name.asc())
        .all()
    )

    stack = [
        StackItemOut(
            tech_slug=tech.slug,
            tech_name=tech.name,
            category=tech.category,
            version=usi.version,
        )
        for (usi, tech) in rows
    ]

    return StackContextOut(stack=stack)



#rag search querry endpoint route

@router.get("/rag/search")
def rag_search(
    q: str = Query(..., min_length=3, max_length=500),
    k: int = Query(5, ge=1, le=10),
):
    """
    Simple RAG retrieval endpoint:
    - embeds the query (OpenAI)
    - searches pgvector (documents.embedding)
    - returns top-k chunks

    I kept it in stack.py for v1 so routing stays simple.
    """

    # Your .env is in project root (one level above backend/)
    load_dotenv("../.env")

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY missing in .env")

    client = OpenAI(api_key=api_key)

    try:
        qvec = client.embeddings.create(model=model, input=q).data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}")

    # Convert list[float] -> pgvector literal
    vec_literal = "[" + ",".join(f"{x:.10f}" for x in qvec) + "]"

    sql = text(
        """
        SELECT id, title, source, chunk_index, chunk_count,
               (embedding <-> (:qvec)::vector(1536)) AS distance,
               LEFT(content, 300) AS preview
        FROM documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <-> (:qvec)::vector(1536)
        LIMIT :k;
        """
    )

    with SessionLocal() as db:
        rows = db.execute(sql, {"qvec": vec_literal, "k": k}).fetchall()

    return {
        "query": q,
        "k": k,
        "results": [
            {
                "id": r.id,
                "title": r.title,
                "source": r.source,
                "chunk_index": r.chunk_index,
                "chunk_count": r.chunk_count,
                "distance": float(r.distance),
                "preview": r.preview,
            }
            for r in rows
        ],
    }



#endpoint to return  an answer using the retrieved documents
@router.post("/rag/answer")
def rag_answer(
    q: str = Query(..., min_length=3, max_length=500),
    k: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),  # <-- needed to write into query_logs
):
    """
    Full RAG pipeline:
    1) Embed the user query
    2) Retrieve top-k document chunks
    3) Send context + question to LLM
    4) Return grounded answer

    I also log every query (even if we found no context),
    so the frontend "History" can show what the user asked.
    """

    load_dotenv("../.env")

    api_key = os.getenv("OPENAI_API_KEY")
    embed_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY missing")

    client = OpenAI(api_key=api_key)

    # 1) Query embedding
    qvec = client.embeddings.create(model=embed_model, input=q).data[0].embedding
    vec_literal = "[" + ",".join(f"{x:.10f}" for x in qvec) + "]"

    # 2) Retrieve top-k rows + distance
    sql = text(
        """
        SELECT id, title, source, chunk_index, chunk_count, content,
               (embedding <-> (:qvec)::vector(1536)) AS distance
        FROM documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <-> (:qvec)::vector(1536)
        LIMIT :k;
        """
    )

    # NOTE: using SessionLocal here is fine for retrieval.
    # I keep it separate from `db` so we don't accidentally override the injected session.
    with SessionLocal() as session:
        rows = session.execute(sql, {"qvec": vec_literal, "k": k}).fetchall()

    # 2.1) Relevance gate
    MAX_DISTANCE = 0.95
    rows = [r for r in rows if float(r.distance) <= MAX_DISTANCE]

    # Build sources once (even if empty). This is what we return + store.
    sources_payload = [
        {
            "id": r.id,
            "title": r.title,
            "source": r.source,
            "chunk_index": r.chunk_index,
            "chunk_count": r.chunk_count,
            "distance": float(r.distance),
        }
        for r in rows
    ]

    # 3) If we have no usable context, still log it (important for product analytics)
    if not rows:
        answer = "I couldn't find relevant context in the indexed documents."

        log = QueryLog(question=q, answer=answer, sources=sources_payload)
        db.add(log)
        db.commit()

        return {
            "question": q,
            "answer": answer,
            "sources": sources_payload,
        }

    context = "\n\n---\n\n".join(r.content for r in rows)

    prompt = f"""
You are a helpful assistant.

Use the provided context to answer the question.
If the context does not contain the answer, say you don't know.

Context:
{context}

Question:
{q}

Answer:
"""

    # 4) Generate answer
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    answer = response.choices[0].message.content

    # ✅ Always log the final output we returned
    log = QueryLog(question=q, answer=answer, sources=sources_payload)
    db.add(log)
    db.commit()

    return {
        "question": q,
        "answer": answer,
        "sources": sources_payload,
    }

#querry tool route for the user's search history 
@router.get("/rag/history")
def rag_history(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """
    History feed for the frontend.

    v1: global history (no user_id column yet).
    Later: we can filter by current_user.id once query_logs has user_id.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    logs = (
        db.query(QueryLog)
        .order_by(QueryLog.id.desc())
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