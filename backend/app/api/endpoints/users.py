from typing import List
from uuid import UUID

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.user import User
from app.repositories.user import ProfileRepository, UserRepository
from app.schemas.codegen import UserResponse
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/admin/users", response_model=List[UserResponse])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    role: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    users = await UserRepository.list_users(db, skip, limit, role, search)

    if not users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Users not found"
        )

    return users


@router.get("/admin/users/{id}", response_model=UserResponse)
async def get_user_detail(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = await UserRepository.get_by_id_with_profile(db, id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    return user
