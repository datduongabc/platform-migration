from datetime import datetime

from app.core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship


class Project(Base):
    """
    Mapped to the public.meetings table representing projects.
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
    status = Column(String, nullable=False, default="pending")
    duration_seconds = Column(Integer, nullable=True)

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

    # Relationship back to User
    owner = relationship("User", back_populates="projects")
