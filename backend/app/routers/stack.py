from typing import List, Optional
import difflib
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, status
from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.security import get_current_user
from app.database.db import get_db
from app.database.database import SessionLocal
from app.models.profile import TechItem, UserProfile, UserStackItem
from app.models.query_log import QueryLog
from app.models.user import User
from app.schemas.schemas import (
    StackContextOut,
    StackItemAdd,
    StackItemOut,
    TechItemOut,
)
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


    # 4) mirror into profile preferences 
    # I keep relational rows as source of truth, and this JSON stays as a clean fallback mirror.
    prefs = profile.preferences or {}
    stack_list = prefs.get("stack", [])

    if not isinstance(stack_list, list):
        stack_list = []

    updated = False
    cleaned_stack = []

    for item in stack_list:
        if not isinstance(item, dict):
            continue

        item_slug = item.get("tech_slug")
        item_version = item.get("version")

        if item_slug == tech.slug:
            cleaned_stack.append(
                {
                    "tech_slug": tech.slug,
                    "version": payload.version,
                }
            )
            updated = True
        else:
            cleaned_stack.append(
                {
                    "tech_slug": item_slug,
                    "version": item_version,
                }
            )

    if not updated:
        cleaned_stack.append(
            {
                "tech_slug": tech.slug,
                "version": payload.version,
            }
        )

    prefs["stack"] = cleaned_stack
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
    # Intent: relational rows stay the main source of truth for the user's stack.
    stack_rows = (
        db.query(UserStackItem, TechItem)
        .join(TechItem, TechItem.id == UserStackItem.tech_id)
        .filter(UserStackItem.user_id == current_user.id)
        .order_by(TechItem.category.asc(), TechItem.name.asc())
        .all()
    )

    if stack_rows:
        return [
            StackItemOut(
                tech_slug=tech.slug,
                tech_name=tech.name,
                category=tech.category,
                version=stack_item.version,
            )
            for stack_item, tech in stack_rows
        ]

    # Intent: fallback to profile mirror only when relational rows are empty.
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile or not profile.preferences or not isinstance(profile.preferences, dict):
        return []

    stack_list = profile.preferences.get("stack", [])
    if not isinstance(stack_list, list) or not stack_list:
        return []

    results: list[StackItemOut] = []

    for item in stack_list:
        if not isinstance(item, dict):
            continue

        tech_slug = item.get("tech_slug")
        version = item.get("version")

        if not tech_slug:
            continue

        tech = db.query(TechItem).filter(TechItem.slug == tech_slug).first()
        if not tech:
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
    # Intent: keep the JSON fallback clean and safe when a stack item is removed.
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()

    if profile and profile.preferences and isinstance(profile.preferences, dict):
        prefs = profile.preferences
        stack_list = prefs.get("stack", [])

        if not isinstance(stack_list, list):
            stack_list = []

        cleaned_stack = []

        for item in stack_list:
            if not isinstance(item, dict):
                continue

            item_slug = item.get("tech_slug")
            item_version = item.get("version")

            if item_slug == tech_slug:
                continue

            if not item_slug:
                continue

            cleaned_stack.append(
                {
                    "tech_slug": item_slug,
                    "version": item_version,
                }
            )

        prefs["stack"] = cleaned_stack
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Simple RAG retrieval endpoint:
    - embeds the query (OpenAI)
    - searches pgvector (documents.embedding)
    - returns top-k chunks

    I am keeping this aligned with /rag/answer so typo handling stays consistent.
    """

    # Your .env is in project root (one level above backend/)
    load_dotenv("../.env")

    api_key = os.getenv("OPENAI_API_KEY")
    embed_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY missing in .env")

    client = OpenAI(api_key=api_key)

    # Intent: normalize the search query too, so small typos do not hurt retrieval.
    normalized_q = normalize_query_for_rag(db, current_user.id, q)

    try:
        query_vec = client.embeddings.create(
            model=embed_model,
            input=normalized_q
        ).data[0].embedding
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}")

    # Convert list[float] -> pgvector literal
    vec_literal = "[" + ",".join(f"{x:.10f}" for x in query_vec) + "]"

    sql = text(
        """
        SELECT
            id,
            title,
            source,
            chunk_index,
            chunk_count,
            (embedding <-> (:qvec)::vector(1536)) AS distance,
            LEFT(content, 300) AS preview
        FROM documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <-> (:qvec)::vector(1536)
        LIMIT :k;
        """
    )

    rows = db.execute(sql, {"qvec": vec_literal, "k": k}).fetchall()

    return {
        "query": q,
        "normalized_query": normalized_q,
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

def build_stack_context_for_user(db: Session, user_id: int) -> str:
    """
    Intent:
    Build a short stack summary for the RAG prompt.
    Source of truth = relational stack items.
    Fallback = user_profiles.preferences["stack"] only if relational data is empty.
    """

    # 1) Primary source: relational stack items
    stack_rows = (
        db.query(UserStackItem, TechItem)
        .join(TechItem, TechItem.id == UserStackItem.tech_id)
        .filter(UserStackItem.user_id == user_id)
        .order_by(TechItem.category.asc(), TechItem.name.asc())
        .all()
    )

    if stack_rows:
        lines = []
        for stack_item, tech_item in stack_rows:
            version_text = f" {stack_item.version}" if stack_item.version else ""
            lines.append(f"- {tech_item.category}: {tech_item.name}{version_text}")
        return "\n".join(lines)

    # 2) Fallback source: preferences["stack"]
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile and profile.preferences and isinstance(profile.preferences, dict):
        pref_stack = profile.preferences.get("stack", [])
        if isinstance(pref_stack, list) and pref_stack:
            lines = []

            for item in pref_stack:
                if not isinstance(item, dict):
                    continue

                tech_slug = item.get("tech_slug")
                version = item.get("version")

                if not tech_slug:
                    continue

                tech = db.query(TechItem).filter(TechItem.slug == tech_slug).first()

                if tech:
                    version_text = f" {version}" if version else ""
                    lines.append(f"- {tech.category}: {tech.name}{version_text}")
                else:
                    version_text = f" {version}" if version else ""
                    lines.append(f"- unknown: {tech_slug}{version_text}")

            if lines:
                return "\n".join(lines)

    return "No stack information provided by the user yet."


def normalize_query_for_rag(db: Session, user_id: int, raw_query: str) -> str:
    """
    Intent:
    Clean the user's question before embedding so small typos do not hurt retrieval too much.
    This stays lightweight on purpose - I only want helpful normalization, not aggressive rewriting.
    """

    if not raw_query:
        return ""

    # I normalize spacing/casing first so matching stays consistent.
    cleaned = raw_query.strip().lower()
    cleaned = " ".join(cleaned.split())

    # I keep a few fixed replacements for very common mistakes I expect in stack questions.
    common_map = {
        "wiuh": "with",
        "postgre": "postgresql",
        "postgres": "postgresql",
        "postgress": "postgresql",
        "fast api": "fastapi",
        "fast-api": "fastapi",
        "reaxt": "react",
        "recat": "react",
        "javscript": "javascript",
        "node js": "nodejs",
        "node-js": "nodejs",
    }

    for wrong, correct in common_map.items():
        cleaned = cleaned.replace(wrong, correct)

    # I use the user's own stack as the first hint source so normalization stays relevant.
    stack_rows = (
        db.query(UserStackItem, TechItem)
        .join(TechItem, TechItem.id == UserStackItem.tech_id)
        .filter(UserStackItem.user_id == user_id)
        .all()
    )

    stack_terms = []
    for stack_item, tech_item in stack_rows:
        if tech_item and tech_item.name:
            stack_terms.append(tech_item.name.lower())

    # I also add a few global terms so matching still works even if the user's stack is small.
    known_terms = set(stack_terms)
    known_terms.update(
        [
            "fastapi",
            "react",
            "postgresql",
            "python",
            "javascript",
            "docker",
            "sqlalchemy",
            "pgvector",
            "openai",
            "jwt",
        ]
    )

    tokens = cleaned.split()
    normalized_tokens = []

    for token in tokens:
        # Keep exact matches as they are.
        if token in known_terms:
            normalized_tokens.append(token)
            continue

        # Try nearest known term only when the match is strong enough.
        nearest = difflib.get_close_matches(token, list(known_terms), n=1, cutoff=0.82)

        if nearest:
            normalized_tokens.append(nearest[0])
        else:
            normalized_tokens.append(token)

    normalized_query = " ".join(normalized_tokens)

    # Final pass for a few multi-word variants after token cleanup.
    normalized_query = normalized_query.replace("fast api", "fastapi")
    normalized_query = normalized_query.replace("node js", "nodejs")

    return normalized_query


#endpoint to return  an answer using the retrieved documents
@router.post("/rag/answer")
def rag_answer(
    q: str = Query(..., min_length=3, max_length=500),
    k: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),  # <-- needed to write into query_logs
    current_user = Depends(get_current_user)
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
    # Intent: lightly normalize the question so small typos don't weaken retrieval too much
    normalized_q = normalize_query_for_rag(db, current_user.id, q)

    query_vec = client.embeddings.create(
        model=embed_model,
        input=normalized_q
    ).data[0].embedding
    vec_literal = "[" + ",".join(f"{x:.10f}" for x in query_vec) + "]"

    
    # 2) Retrieve top-k rows + distance
    # I am keeping retrieval aligned to the current documents table so RAG works
    # against the schema we already confirmed, without assuming versioning is live yet.
    sql = text(
        """
        SELECT
            d.id,
            d.title,
            d.source,
            d.chunk_index,
            d.chunk_count,
            d.content,
            (d.embedding <-> (:qvec)::vector(1536)) AS distance
        FROM documents d
        WHERE d.embedding IS NOT NULL
        ORDER BY d.embedding <-> (:qvec)::vector(1536)
        LIMIT :k;
        """
    )


    # NOTE: using SessionLocal here is fine for retrieval.
    # I keep it separate from `db` so we don't accidentally override the injected session.
    with SessionLocal() as session:
        rows = session.execute(sql, {"qvec": vec_literal, "k": k}).fetchall()

    # 3) Relevance guard
    # I keep this strict on purpose so the assistant does not answer from weak matches.
    if not rows:
        answer = "I couldn't find relevant context in the indexed documents."
        sources_payload = []

        log = QueryLog(
            question=q,
            answer=answer,
            sources=sources_payload,
            user_id=current_user.id,
        )
        db.add(log)
        db.commit()

        return {
            "question": q,
            "answer": answer,
            "sources": sources_payload,
            "user_id": current_user.id,
        }

    # Intent: keep the guard safe, but not so strict that valid matches get thrown away.
    # My current dataset is still small, so I need a more realistic threshold for now.
    MAX_DISTANCE = 1.10
    BEST_MATCH_THRESHOLD = 0.98
    MAX_CONTEXT_ROWS = 3

    filtered_rows = [r for r in rows if r.distance is not None and r.distance <= MAX_DISTANCE]

    if not filtered_rows:
        answer = "I couldn't find relevant context in the indexed documents."
        sources_payload = []

        log = QueryLog(
            question=q,
            answer=answer,
            sources=sources_payload,
            user_id=current_user.id,
        )
        db.add(log)
        db.commit()

        return {
            "question": q,
            "answer": answer,
            "sources": sources_payload,
            "user_id": current_user.id,
        }

    # The best chunk still needs to be strong enough, otherwise I reject the answer.
    best_row = min(filtered_rows, key=lambda r: r.distance)
    if best_row.distance > BEST_MATCH_THRESHOLD:
        answer = "I couldn't find relevant context in the indexed documents."
        sources_payload = []

        log = QueryLog(
            question=q,
            answer=answer,
            sources=sources_payload,
            user_id=current_user.id,
        )
        db.add(log)
        db.commit()

        return {
            "question": q,
            "answer": answer,
            "sources": sources_payload,
            "user_id": current_user.id,
        }

    # I keep only the strongest chunks so the prompt stays cleaner and more grounded.
    filtered_rows = sorted(filtered_rows, key=lambda r: r.distance)[:MAX_CONTEXT_ROWS]

    # Build sources once. This is what I return and also store in query history.
    sources_payload = [
        {
            "id": r.id,
            "title": r.title,
            "source": r.source,
            "chunk_index": r.chunk_index,
            "chunk_count": r.chunk_count,
            "distance": float(r.distance),
        }
        for r in filtered_rows
    ]

    context = "\n\n---\n\n".join(r.content for r in filtered_rows)

    # Intent: include the user's real stack context so the answer is more relevant to their setup.
    stack_context = build_stack_context_for_user(db, current_user.id)

    # Intent: keep the answer grounded, risk-first, and structured like a decision tool.
    prompt = f"""
    You are StackAware, a technical decision-support assistant.

    Your job:
    - Answer using ONLY the retrieved context below.
    - Use the user's tech stack as relevance context, not as invented evidence.
    - Be careful, specific, and practical.
    - If the retrieved context is not enough, clearly say you do not know.
    - Do not guess versions, files, APIs, or behaviors that are not supported by the context.

    User Tech Stack:
    {stack_context}

    Retrieved Context:
    {context}

    User Question:
    {q}

    Return the answer in this structure:

    Risk & Impact:
    - What could break, what is uncertain, or what matters most here?

    Advice:
    - What is the safest recommended answer based on the retrieved context?

    Justification:
    - Why is this the best answer from the context?

    Safe Alternatives:
    - Mention simpler or safer fallback options if the context supports them.
    - If none are supported by the context, say "No supported alternative found in context."

    Validity:
    - State that the answer is based on the currently retrieved indexed context.
    - If exact version/date detail is missing from context, say that clearly.

    Important rules:
    - Do not mention information outside the retrieved context.
    - Do not say "according to my knowledge" or similar phrases.
    - Do not output fake citations.
    - Keep the answer concise but useful.
    """

    # 4) Generate answer
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    answer = response.choices[0].message.content

    #  Always log the final output we returned
    log = QueryLog(question=q, answer=answer, sources=sources_payload, user_id=current_user.id)
    db.add(log)
    db.commit()

    return {
        "question": q,
        "answer": answer,
        "sources": sources_payload,
        "user_id": current_user.id,  # Intent: show which user this log belongs to
    }

#querry tool route for the user's search history 
@router.get("/rag/history")
def rag_history(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Intent: each user sees only their own history
):
    """
    History feed for the frontend.

    
    Later: we can filter by current_user.id once query_logs has user_id.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    logs = (
    db.query(QueryLog)
    .filter(QueryLog.user_id == current_user.id)
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