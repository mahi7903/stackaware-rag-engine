from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.security import get_current_user
from app.database.db import get_db
from app.models.user import User
from app.schemas.schemas import RagAnswerResponse
from app.utils.rag_mode_service import run_rag_mode


router = APIRouter(prefix="/stack/rag", tags=["RAG Modes"])


@router.post("/decision", response_model=RagAnswerResponse)
def rag_decision_mode(
    q: str = Query(..., min_length=3, max_length=500),
    k: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # I am keeping this route focused on technical decision support so the backend mode stays explicit.
    return run_rag_mode(
        mode="technical_decision_support",
        question=q,
        k=k,
        db=db,
        current_user=current_user,
    )


@router.post("/change-awareness", response_model=RagAnswerResponse)
def rag_change_awareness_mode(
    q: str = Query(..., min_length=3, max_length=500),
    k: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # I am separating change-awareness here so version-risk logic can grow without bloating stack.py.
    return run_rag_mode(
        mode="version_change_awareness",
        question=q,
        k=k,
        db=db,
        current_user=current_user,
    )