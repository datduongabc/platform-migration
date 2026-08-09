from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class FolderCreateRequest(BaseModel):
    name: str = Field(..., max_length=100)


class FolderUpdateRequest(BaseModel):
    name: str = Field(..., max_length=100)


class FolderReorderRequest(BaseModel):
    order: List[UUID]


class FolderShareCreateRequest(BaseModel):
    identifier: str
    role: str = Field(..., pattern="^(editor|viewer)$")


class FolderShareUpdateRequest(BaseModel):
    role: str = Field(..., pattern="^(editor|viewer)$")


class FolderResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    position: int
    created_at: datetime
    updated_at: datetime
    myRole: str
    ownerUsername: Optional[str] = None
    memberCount: int = 0

    model_config = ConfigDict(from_attributes=True)


class FolderListResponse(BaseModel):
    folders: List[FolderResponse]


class FolderMemberResponse(BaseModel):
    userId: UUID
    username: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class FolderMemberListResponse(BaseModel):
    members: List[FolderMemberResponse]
