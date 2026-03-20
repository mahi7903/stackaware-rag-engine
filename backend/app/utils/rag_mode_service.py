import os

from dotenv import load_dotenv
from openai import OpenAI
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.query_log import QueryLog
from app.models.user import User
from app.utils.api_guards import log_info, log_error, check_rag_rate_limit
from app.routers.stack import build_stack_context_for_user, normalize_query_for_rag
from app.utils.rag_mode_rules import get_mode_settings, score_row_for_mode
from app.utils.rag_validity import build_validity_statement, build_citation_block
from app.utils.rag_empty_fallback import build_empty_mode_response
def run_rag_mode(
    mode: str,
    question: str,
    k: int,
    db: Session,
    current_user: User,
):
    """
    I am centralising the shared RAG flow here so both backend modes can reuse
    the same retrieval and logging pipeline without duplicating logic.
    """

    load_dotenv("../.env")

    api_key = os.getenv("OPENAI_API_KEY")
    embed_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY missing")

    if mode not in {"technical_decision_support", "version_change_awareness"}:
        raise HTTPException(status_code=400, detail="Unsupported RAG mode")

    client = OpenAI(api_key=api_key)

    try:
        check_rag_rate_limit(current_user.id)
    except Exception as e:
        log_error(
            "rag_mode_rate_limit_exceeded",
            error=e,
            user_id=current_user.id,
            mode=mode,
        )
        raise HTTPException(status_code=429, detail=str(e))

    normalized_q = normalize_query_for_rag(db, current_user.id, question)

    log_info(
        "rag_mode_started",
        user_id=current_user.id,
        mode=mode,
        question=question,
        normalized_query=normalized_q,
        requested_k=k,
    )

    try:
        query_vec = client.embeddings.create(
            model=embed_model,
            input=normalized_q,
        ).data[0].embedding
    except Exception as e:
        log_error(
            "rag_mode_embedding_failed",
            error=e,
            user_id=current_user.id,
            mode=mode,
            question=question,
        )
        raise HTTPException(status_code=502, detail=f"Query embedding failed: {e}")

    vec_literal = "[" + ",".join(f"{x:.10f}" for x in query_vec) + "]"

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

    try:
        rows = db.execute(sql, {"qvec": vec_literal, "k": k}).fetchall()
    except Exception as e:
        log_error(
            "rag_mode_retrieval_failed",
            error=e,
            user_id=current_user.id,
            mode=mode,
            question=question,
            normalized_query=normalized_q,
            requested_k=k,
        )
        raise HTTPException(status_code=500, detail=f"RAG retrieval failed: {e}")

    mode_settings = get_mode_settings(mode)

    max_distance = mode_settings["max_distance"]
    best_match_threshold = mode_settings["best_match_threshold"]
    max_context_rows = mode_settings["max_context_rows"]

    filtered_rows = [r for r in rows if r.distance is not None and r.distance <= max_distance]

    if not filtered_rows:
        answer = build_empty_mode_response(mode)
        sources_payload = []

        log = QueryLog(
            question=question,
            answer=answer,
            sources=sources_payload,
            user_id=current_user.id,
        )
        db.add(log)
        db.commit()

        return {
            "question": question,
            "answer": answer,
            "sources": sources_payload,
            "user_id": current_user.id,
        }


    best_row = min(filtered_rows, key=lambda r: r.distance)

    if best_row.distance > best_match_threshold:
        answer = build_empty_mode_response(mode)
        sources_payload = []

        log_info(
            "rag_mode_best_match_below_threshold",
            user_id=current_user.id,
            mode=mode,
            question=question,
            normalized_query=normalized_q,
            best_distance=float(best_row.distance),
            best_match_threshold=best_match_threshold,
        )

        log = QueryLog(
            question=question,
            answer=answer,
            sources=sources_payload,
            user_id=current_user.id,
        )
        db.add(log)
        db.commit()

        return {
            "question": question,
            "answer": answer,
            "sources": sources_payload,
            "user_id": current_user.id,
        }

    filtered_rows = sorted(
        filtered_rows,
        key=lambda r: score_row_for_mode(mode, r),
    )[:max_context_rows]

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

    validity_statement = build_validity_statement(mode, sources_payload)
    citation_block = build_citation_block(sources_payload)

    context = "\n\n---\n\n".join(r.content for r in filtered_rows)
    stack_context = build_stack_context_for_user(db, current_user.id)





    prompt = build_mode_prompt(
        mode=mode,
        question=question,
        stack_context=stack_context,
        context=context,
        validity_statement=validity_statement,
        citation_block=citation_block,
    )

    try:
        response = client.chat.completions.create(
            model=chat_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        answer = response.choices[0].message.content
    except Exception as e:
        log_error(
            "rag_mode_generation_failed",
            error=e,
            user_id=current_user.id,
            mode=mode,
            question=question,
            selected_chunk_count=len(filtered_rows),
        )
        raise HTTPException(status_code=502, detail=f"Answer generation failed: {e}")

    log_info(
        "rag_mode_completed",
        user_id=current_user.id,
        mode=mode,
        question=question,
        selected_chunk_count=len(filtered_rows),
        returned_source_count=len(sources_payload),
    )

    log = QueryLog(
        question=question,
        answer=answer,
        sources=sources_payload,
        user_id=current_user.id,
    )
    db.add(log)
    db.commit()

    return {
        "question": question,
        "answer": answer,
        "sources": sources_payload,
        "user_id": current_user.id,
    }
def build_no_context_answer(mode: str) -> str:
    """
    I am keeping the fallback message mode-aware so each endpoint still behaves
    like its own backend flow even when retrieval is weak.
    """

    if mode == "technical_decision_support":
        return "I couldn't find enough relevant indexed context to give a safe technical decision yet."

    if mode == "version_change_awareness":
        return "I couldn't find enough indexed version or change-related context to raise a grounded change-awareness warning yet."

    return "I couldn't find relevant context in the indexed documents."

def build_mode_prompt(
    mode: str,
    question: str,
    stack_context: str,
    context: str,
    validity_statement: str,
    citation_block: str,
) -> str:
    """
    I am splitting prompt rules by mode here so the backend behaviour clearly
    matches the milestone instead of looking like one generic RAG flow.
    """

    common_rules = f"""
You are StackAware, a grounded backend RAG assistant.

Important rules:
- Answer using ONLY the retrieved context below.
- Use the user's tech stack as relevance context, not as evidence.
- Do not guess versions, APIs, files, dates, or behaviour that are not supported by context.
- If the context is not enough, clearly say that.
- Use the provided validity statement directly.
- Use the provided citations directly.
- Do not output fake citations.
- Do not invent release windows, as-of dates, or version support claims.

User Tech Stack:
{stack_context}

Retrieved Context:
{context}

User Question:
{question}

Backend Validity Statement:
{validity_statement}

Backend Citations:
{citation_block}
"""

    if mode == "technical_decision_support":
        return common_rules + """

Return the answer in this structure:

Risk & Impact:
- Explain what could break, what matters most, and what tradeoff is visible from context.

Advice:
- Give the safest recommended technical direction based on the retrieved context.

Justification:
- Explain why this advice is the strongest grounded answer from the context.

Safe Alternatives:
- Mention safer or simpler fallback options only if the context supports them.
- If none are supported, say "No supported alternative found in context."

Validity:
- Copy the backend validity statement exactly as provided.

Citations:
- Copy the backend citations exactly as provided.

Keep the answer concise but useful.
"""

    if mode == "version_change_awareness":
        return common_rules + """

Return the answer in this structure:

Change Signal:
- Explain what version, dependency, API, or behaviour change appears relevant from the context.

Risk & Impact:
- Explain what may break, drift, or become outdated because of that change.

Recommended Action:
- Say what the user should check, pin, test, update, or verify next based on context.

Justification:
- Explain why this change warning is supported by the retrieved context.

Validity:
- Copy the backend validity statement exactly as provided.

Citations:
- Copy the backend citations exactly as provided.

Keep the answer concise but useful.
"""

    raise HTTPException(status_code=400, detail="Unsupported RAG mode")