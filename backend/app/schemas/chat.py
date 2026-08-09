from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class CitationSchema(BaseModel):
    chunk_id: UUID
    meeting_id: UUID
    start_ms: int
    end_ms: int

    model_config = ConfigDict(from_attributes=True)


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    citations: List[CitationSchema] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    meeting_id: Optional[UUID] = None
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessageResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    message: str
    meetingId: Optional[UUID] = None
    folderId: Optional[UUID] = None
    sessionId: Optional[UUID] = None


class ChatResponse(BaseModel):
    sessionId: UUID
    message: ChatMessageResponse
