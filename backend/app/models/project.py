from datetime import datetime
from app.core.database import Base
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
    Float,
    Date,
    Boolean,
)
from sqlalchemy.dialects.postgresql import UUID, ENUM
from sqlalchemy.orm import relationship

MeetingStatusEnum = ENUM(
    "pending", "processing", "done", "failed", name="meeting_status", create_type=False
)
TodoStatusEnum = ENUM(
    "open", "done", "dismissed", name="todo_status", create_type=False
)


class Project(Base):
    """
    Mapped to the public.meetings table representing projects (meetings).
    """

    __tablename__ = "meetings"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String, nullable=False, default="Untitled project")
    status = Column(MeetingStatusEnum, nullable=False, default="pending")
    audio_path = Column(String, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    language = Column(String, nullable=True)

    # AI outputs
    summary = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    error_message = Column(String, nullable=True)

    # Metadata & Flags
    started_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    pinned_at = Column(DateTime(timezone=True), nullable=True)
    source = Column(String, nullable=True, default="recorded")
    storage_provider = Column(String, nullable=True, default="r2")
    folder_id = Column(UUID(as_uuid=True), nullable=True)

    # Relationship back to User
    owner = relationship("User", back_populates="projects")

    # Relationships to children
    segments = relationship(
        "TranscriptSegment",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.segment_index",
    )
    todos = relationship("Todo", back_populates="meeting", cascade="all, delete-orphan")
    calendar_suggestions = relationship(
        "CalendarSuggestion", back_populates="meeting", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    meeting_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    segment_index = Column(Integer, nullable=False)
    speaker = Column(String, nullable=True)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(String, nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    meeting = relationship("Project", back_populates="segments")


class Todo(Base):
    __tablename__ = "todos"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    meeting_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    content = Column(String, nullable=False)
    assignee = Column(String, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(TodoStatusEnum, nullable=False, default="open")
    source_segment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.transcript_segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    meeting = relationship("Project", back_populates="todos")


class CalendarSuggestion(Base):
    __tablename__ = "calendar_suggestions"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    meeting_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.meetings.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String, nullable=False)
    proposed_at = Column(DateTime(timezone=True), nullable=True)
    raw_mention = Column(String, nullable=True)
    source_segment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.transcript_segments.id", ondelete="SET NULL"),
        nullable=True,
    )
    dismissed = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    meeting = relationship("Project", back_populates="calendar_suggestions")
