from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.rag import retrieve_context
from app.services.gemini import answer_question

router = APIRouter()


class AskQuestionRequest(BaseModel):
    query: str


class AskQuestionResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []


@router.post("/meetings/{id}/ask", response_model=AskQuestionResponse)
async def ask_meeting_question(
    id: UUID,
    payload: AskQuestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    RAG Q&A endpoint: Answer question based on meeting transcript context.
    """
    context_chunks = await retrieve_context(
        db, query=payload.query, meeting_id=id, user_id=current_user.id
    )

    if not context_chunks:
        return AskQuestionResponse(
            answer="No relevant transcript context found for this question.",
            sources=[],
        )

    answer = await answer_question(payload.query, context_chunks)

    return AskQuestionResponse(answer=answer, sources=context_chunks)
