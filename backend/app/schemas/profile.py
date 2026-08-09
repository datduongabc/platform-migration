from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class ProfileResponse(BaseModel):
    id: UUID
    email: Optional[EmailStr] = None
    username: str
    display_name: Optional[str] = None
    avatar_key: Optional[str] = None
    avatar_url: Optional[str] = None
    theme_preference: Optional[str] = None
    role: str
    created_at: datetime
    meeting_count: int = 0
    folder_count: int = 0
    audio_seconds_remaining: float = 0.0
    agent_queries_remaining: int = 0

    model_config = ConfigDict(from_attributes=True)


class ProfileUpdateRequest(BaseModel):
    # No `pattern`/length constraint here on purpose: validation must run AFTER
    # the endpoint normalizes (strip + lowercase) the raw value, not before —
    # otherwise typing "JohnDoe" gets rejected by Pydantic before the endpoint's
    # own normalization logic ever runs. See update_profile in endpoints/profile.py.
    username: Optional[str] = None
    display_name: Optional[str] = Field(None, max_length=50)
    theme_preference: Optional[str] = Field(None, pattern="^(default|luxury|playful)$")
    avatar_key: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(..., min_length=8)


class AvatarUploadRequest(BaseModel):
    contentType: str = Field(..., pattern="^(image/jpeg|image/png|image/webp)$")
    size: int
