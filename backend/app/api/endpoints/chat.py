import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.chat import ChatSession, ChatMessage
from app.models.user import User
from app.models.project import Project
from app.services.access import check_folder_access, check_meeting_access
from app.services.rag import retrieve_context
from app.services.gemini import answer_question, answer_question_with_citations
from app.services.quota import apply_quota_movement, QuotaMovementParams
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatMessageResponse,
    CitationSchema,
)

router = APIRouter()


@router.get("/chat", response_model=ChatResponse)
async def get_chat_history(
    meetingId: Optional[UUID] = Query(None),
    sessionId: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch the most recent chat session + messages for a meeting or session.
    """
    session = None
    if sessionId:
        # Load specific session
        query_session = select(ChatSession).where(ChatSession.id == sessionId)
        result_session = await db.execute(query_session)
        session = result_session.scalars().first()
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found.")
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden.")
    elif meetingId:
        # Resolve single-meeting access
        query_meeting = select(Project).where(Project.id == meetingId)
        result_meeting = await db.execute(query_meeting)
        meeting = result_meeting.scalars().first()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found.")

        # Verify access (owner or shared folder editor/viewer)
        if not await check_meeting_access(db, meeting, current_user.id, "viewer"):
            raise HTTPException(status_code=403, detail="Forbidden.")

        # Find most recent session
        query_session = (
            select(ChatSession)
            .where(
                ChatSession.user_id == current_user.id,
                ChatSession.meeting_id == meetingId,
            )
            .order_by(ChatSession.created_at.desc())
            .limit(1)
        )
        result_session = await db.execute(query_session)
        session = result_session.scalars().first()

    if not session:
        # This handler's response_model=ChatResponse requires a non-null message,
        # so there's no way to represent "no session yet" here — previously this
        # function had no return statement at all on ANY path, which always 500'd
        # on Pydantic response validation. Not currently called by the frontend
        # (which uses /chat/history instead), but a live, broken API surface.
        raise HTTPException(
            status_code=404, detail="No chat session found for the given filters."
        )

    query_msgs = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    )
    result_msgs = await db.execute(query_msgs)
    messages = result_msgs.scalars().all()
    if not messages:
        raise HTTPException(status_code=404, detail="Session has no messages yet.")

    last = messages[-1]
    return ChatResponse(
        sessionId=session.id,
        message=ChatMessageResponse(
            id=last.id,
            session_id=last.session_id,
            role=last.role,
            content=last.content,
            citations=[CitationSchema(**c) for c in (last.citations or [])],
            created_at=last.created_at,
        ),
    )


@router.get("/chat/history")
async def get_chat_history_custom(
    meetingId: Optional[UUID] = Query(None),
    folderId: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get history helper with flexible returns.
    """
    if not meetingId and not folderId:
        return {"sessionId": None, "messages": []}

    if meetingId:
        query_meeting = select(Project).where(Project.id == meetingId)
        result_meeting = await db.execute(query_meeting)
        meeting = result_meeting.scalars().first()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found.")
        if not await check_meeting_access(db, meeting, current_user.id, "viewer"):
            raise HTTPException(status_code=403, detail="Forbidden.")
        query_session = (
            select(ChatSession)
            .where(
                ChatSession.user_id == current_user.id,
                ChatSession.meeting_id == meetingId,
            )
            .order_by(ChatSession.created_at.desc())
            .limit(1)
        )
    else:
        if not await check_folder_access(db, folderId, current_user.id, "viewer"):
            raise HTTPException(status_code=403, detail="Forbidden.")
        query_session = (
            select(ChatSession)
            .where(
                ChatSession.user_id == current_user.id,
                ChatSession.folder_id == folderId,
            )
            .order_by(ChatSession.created_at.desc())
            .limit(1)
        )

    result_session = await db.execute(query_session)
    session = result_session.scalars().first()

    if not session:
        return {"sessionId": None, "messages": []}

    # Fetch messages
    query_msgs = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    )
    result_msgs = await db.execute(query_msgs)
    messages = result_msgs.scalars().all()

    return {
        "sessionId": session.id,
        "messages": [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "created_at": m.created_at,
            }
            for m in messages
        ],
    }


@router.post("/chat", response_model=ChatResponse)
async def post_chat_query(
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit user query to RAG chatbot, charge quota, perform retrieval, generate answer with citations, and save.
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required.")

    meeting_id = payload.meetingId
    folder_id = payload.folderId
    session_id = payload.sessionId

    # 1. Access checking
    meeting = None
    if meeting_id:
        query_meeting = select(Project).where(Project.id == meeting_id)
        result_meeting = await db.execute(query_meeting)
        meeting = result_meeting.scalars().first()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found.")
        if not await check_meeting_access(db, meeting, current_user.id, "viewer"):
            raise HTTPException(status_code=403, detail="Forbidden.")
    elif folder_id:
        if not await check_folder_access(db, folder_id, current_user.id, "viewer"):
            raise HTTPException(status_code=403, detail="Forbidden.")

    # 2. Session resolution
    session = None
    if session_id:
        query_sess = select(ChatSession).where(ChatSession.id == session_id)
        result_sess = await db.execute(query_sess)
        session = result_sess.scalars().first()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found.")
        if session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Forbidden.")
    else:
        # Create new chat session
        title = message[:40] + "..." if len(message) > 40 else message
        session = ChatSession(
            id=uuid.uuid4(),
            user_id=current_user.id,
            meeting_id=meeting_id,
            folder_id=folder_id,
            title=title,
        )
        db.add(session)
        await db.flush()

    # 3. Save user message
    user_msg_id = uuid.uuid4()
    user_message = ChatMessage(
        id=user_msg_id,
        session_id=session.id,
        role="user",
        content=message,
        citations=[],
    )
    db.add(user_message)
    await db.flush()

    # 4. Apply agent quota charge
    charge_result = await apply_quota_movement(
        db,
        QuotaMovementParams(
            user_id=current_user.id,
            delta_audio_seconds=0,
            delta_agent_queries=-1,
            reason="agent_query",
            dedup_key=f"agent:{user_msg_id}:charge",
            allow_overdraw=False,
            meeting_id=meeting_id,
        ),
    )

    if charge_result.status == "insufficient":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient agent queries balance.",
        )

    # 5. Load recent history
    # 4 prior turns (ricotdin parity) — this query already excludes the just-
    # inserted user message via the id != user_msg_id filter, so limit(4) here
    # means 4 prior messages, not 5.
    query_history = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id, ChatMessage.id != user_msg_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(4)
    )
    result_history = await db.execute(query_history)
    history_rows = result_history.scalars().all()
    history = [{"role": r.role, "content": r.content} for r in reversed(history_rows)]

    # 6. Semantic retrieval — scoped to a single meeting, a folder's meetings, or
    # (if neither given) every meeting filter_user_id makes accessible to the caller.
    context_chunks = await retrieve_context(
        db,
        query=message,
        meeting_id=meeting_id,
        user_id=current_user.id,
        folder_id=folder_id,
    )

    # 7. Grounded Gemini Answering
    try:
        if context_chunks:
            gemini_res = await answer_question_with_citations(
                query=message,
                context_chunks=context_chunks,
                history=history,
            )
            # Filter citations to prevent model hallucination, and look up
            # meeting_id/start_ms/end_ms from OUR retrieved chunk data rather than
            # trusting the model's echoed values for them — chunk_id membership was
            # being validated, but the other fields were previously taken verbatim
            # from the model's response, so a model that hallucinated a chunk_id
            # correctly but a different meeting_id/timestamp would have gone
            # through unnoticed.
            chunks_by_id = {str(c.get("id")): c for c in context_chunks if c.get("id")}
            valid_citations = [
                cite for cite in gemini_res.citations if cite.chunk_id in chunks_by_id
            ]
            answer_result = {
                "answer": gemini_res.answer,
                "citations": [
                    {
                        "chunk_id": cite.chunk_id,
                        # meeting_id comes from a raw SQL row (rag.py's mappings()),
                        # which surfaces UUID columns as native uuid.UUID objects —
                        # must stringify before this dict is JSON-serialized into
                        # chat_messages.citations (JSONB), or the insert 500s.
                        "meeting_id": str(chunks_by_id[cite.chunk_id]["meeting_id"]),
                        "start_ms": chunks_by_id[cite.chunk_id]["start_ms"],
                        "end_ms": chunks_by_id[cite.chunk_id]["end_ms"],
                    }
                    for cite in valid_citations
                ],
            }
        elif meeting_id or folder_id:
            answer_result = {
                "answer": "I don't see that discussed in this meeting's transcript context.",
                "citations": [],
            }
        else:
            # General Chat Mode (without specific meeting context)
            general_answer = await answer_question(query=message, context_chunks=[])
            answer_result = {
                "answer": general_answer
                or "Hello! I am your Ricotdin AI Assistant. How can I help you today?",
                "citations": [],
            }
    except Exception as e:
        # Refund agent query if call failed
        await apply_quota_movement(
            db,
            QuotaMovementParams(
                user_id=current_user.id,
                delta_audio_seconds=0,
                delta_agent_queries=1,
                reason="refund",
                dedup_key=f"agent:{user_msg_id}:refund",
                allow_overdraw=False,
                meeting_id=meeting_id,
            ),
        )
        answer_result = {
            "answer": f"Gemini AI Service note: Could not contact Gemini API ({str(e)}). Please verify your GEMINI_API_KEY environment variable.",
            "citations": [],
        }

    # 8. Save assistant message
    assistant_message = ChatMessage(
        id=uuid.uuid4(),
        session_id=session.id,
        role="assistant",
        content=answer_result["answer"],
        citations=answer_result["citations"],
    )
    db.add(assistant_message)
    await db.commit()

    # Refresh objects
    await db.refresh(assistant_message)

    return ChatResponse(
        sessionId=session.id,
        message=ChatMessageResponse(
            id=assistant_message.id,
            session_id=assistant_message.session_id,
            role=assistant_message.role,
            content=assistant_message.content,
            citations=[
                CitationSchema(
                    chunk_id=c["chunk_id"],
                    meeting_id=c["meeting_id"],
                    start_ms=c["start_ms"],
                    end_ms=c["end_ms"],
                )
                for c in assistant_message.citations
            ],
            created_at=assistant_message.created_at,
        ),
    )
