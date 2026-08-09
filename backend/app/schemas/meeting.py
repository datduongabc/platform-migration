from datetime import datetime, date
from typing import List, Optional, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, field_validator


class MeetingCreateRequest(BaseModel):
    durationSeconds: Optional[int] = None
    startedAt: Optional[str] = None
    source: Optional[str] = "recorded"
    fileExtension: Optional[str] = ".webm"
    mimeType: Optional[str] = "audio/webm"
    folderId: Optional[Union[UUID, str]] = None

    @field_validator("folderId", mode="before")
    @classmethod
    def clean_folder_id(cls, v):
        if not v or v in ("all", "uncategorized", "null", ""):
            return None
        return v


class MeetingCreateResponse(BaseModel):
    meetingId: UUID
    uploadUrl: str
    contentType: str


class TranscriptSegmentSchema(BaseModel):
    id: UUID
    segment_index: int
    speaker: Optional[str]
    start_ms: int
    end_ms: int
    text: str
    confidence: Optional[float]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TodoSchema(BaseModel):
    id: UUID
    content: str
    assignee: Optional[str]
    due_date: Optional[date]
    status: str
    source_segment_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CalendarSuggestionSchema(BaseModel):
    id: UUID
    title: str
    proposed_at: Optional[datetime]
    raw_mention: Optional[str]
    source_segment_id: Optional[UUID]
    dismissed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeetingDetailResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    status: str
    audio_path: Optional[str]
    duration_seconds: Optional[int]
    language: Optional[str]
    summary: Optional[str]
    notes: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    pinned_at: Optional[datetime]
    source: Optional[str]
    storage_provider: Optional[str]
    folder_id: Optional[UUID]
    segments: List[TranscriptSegmentSchema] = []
    todos: List[TodoSchema] = []
    calendar_suggestions: List[CalendarSuggestionSchema] = []

    model_config = ConfigDict(from_attributes=True)


class TodoUpdateRequest(BaseModel):
    status: str


class CalendarSuggestionUpdateRequest(BaseModel):
    dismissed: bool


class MeetingUpdateRequest(BaseModel):
    title: Optional[str] = None
    folder_id: Optional[UUID] = None
