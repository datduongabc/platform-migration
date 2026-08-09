from datetime import datetime
from app.core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM
from sqlalchemy.orm import relationship

ChatRoleEnum = ENUM("user", "assistant", name="chat_role", create_type=False)


class ChatSession(Base):
    """
    SQLAlchemy model representing a RAG chat session.
    """

    __tablename__ = "chat_sessions"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.meetings.id", ondelete="CASCADE"),
        nullable=True,
    )
    folder_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.folders.id", ondelete="CASCADE"),
        nullable=True,
    )
    title = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """
    SQLAlchemy model representing a message within a chat session.
    """

    __tablename__ = "chat_messages"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(ChatRoleEnum, nullable=False, default="user")  # 'user' or 'assistant'
    content = Column(String, nullable=False)
    citations = Column(JSONB, nullable=False, default=list)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    session = relationship("ChatSession", back_populates="messages")
