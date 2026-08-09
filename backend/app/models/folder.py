from datetime import datetime
from app.core.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID, ENUM
from sqlalchemy.orm import relationship

FolderRoleEnum = ENUM("viewer", "editor", name="folder_role", create_type=False)


class Folder(Base):
    """
    Mapped to the public.folders table representing folders.
    """

    __tablename__ = "folders"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    position = Column(Integer, nullable=False, default=0)
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
    owner = relationship("User", foreign_keys=[user_id])
    shares = relationship(
        "FolderShare", back_populates="folder", cascade="all, delete-orphan"
    )


class FolderShare(Base):
    """
    Mapped to the public.folder_shares table representing shared folders.
    """

    __tablename__ = "folder_shares"
    __table_args__ = {"schema": "public"}

    id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    folder_id = Column(
        UUID(as_uuid=True),
        ForeignKey("public.folders.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(FolderRoleEnum, nullable=False, default="viewer")
    invited_by = Column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    folder = relationship("Folder", back_populates="shares")
    grantee = relationship("User", foreign_keys=[user_id])
    inviter = relationship("User", foreign_keys=[invited_by])
