import os
import secrets
import shutil
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.core.security import get_password_hash
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.codegen import UserResponse
from app.services.admin_guards import is_last_admin, is_self_action
from app.services.audit import write_audit_log
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _audit_ctx(request: Request) -> tuple[Optional[str], Optional[str]]:
    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    return ip, agent


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


class RoleUpdateRequest(BaseModel):
    role: str


@router.patch("/admin/users/{id}/role", response_model=UserResponse)
async def update_user_role(
    id: UUID,
    payload: RoleUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    if payload.role not in ("user", "admin"):
        raise HTTPException(status_code=422, detail="role must be 'user' or 'admin'.")

    user = await UserRepository.get_by_id_with_profile(db, id)
    if not user or not user.profile:
        raise HTTPException(status_code=404, detail="User not found")

    if is_self_action(admin.id, id):
        raise HTTPException(
            status_code=403, detail="Admins cannot change their own role."
        )
    if payload.role != "admin" and await is_last_admin(db, user.profile.role):
        raise HTTPException(
            status_code=403, detail="Cannot demote the last remaining admin."
        )

    prev_role = user.profile.role
    user.profile.role = payload.role
    await db.commit()

    ip, agent = _audit_ctx(request)
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="user.role_change",
        target_type="user",
        target_id=str(id),
        metadata={"previous_role": prev_role, "new_role": payload.role},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return await UserRepository.get_by_id_with_profile(db, id)


class StatusUpdateRequest(BaseModel):
    disabled: bool


@router.patch("/admin/users/{id}/status", response_model=UserResponse)
async def update_user_status(
    id: UUID,
    payload: StatusUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = await UserRepository.get_by_id_with_profile(db, id)
    if not user or not user.profile:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.disabled:
        if is_self_action(admin.id, id):
            raise HTTPException(
                status_code=403, detail="Admins cannot disable themselves."
            )
        if await is_last_admin(db, user.profile.role):
            raise HTTPException(
                status_code=403, detail="Cannot disable the last remaining admin."
            )
        user.disabled_at = datetime.now(timezone.utc)
    else:
        user.disabled_at = None

    await db.commit()

    ip, agent = _audit_ctx(request)
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="user.status_change",
        target_type="user",
        target_id=str(id),
        metadata={"disabled": payload.disabled},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return await UserRepository.get_by_id_with_profile(db, id)


class ResetPasswordResponse(BaseModel):
    temporaryPassword: str


@router.post("/admin/users/{id}/reset-password", response_model=ResetPasswordResponse)
async def reset_user_password(
    id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Sets a fresh random password directly (no SMTP/email flow is configured for
    this deployment, unlike ricotdin's recovery-email link). The plaintext is
    returned exactly once in this response for the admin to hand to the user
    out-of-band; it is never stored or logged anywhere.
    """
    user = await UserRepository.get_by_id(db, id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    temp_password = secrets.token_urlsafe(12)
    user.encrypted_password = get_password_hash(temp_password)
    await db.commit()

    ip, agent = _audit_ctx(request)
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="user.reset_password",
        target_type="user",
        target_id=str(id),
        metadata={},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return ResetPasswordResponse(temporaryPassword=temp_password)


@router.delete("/admin/users/{id}")
async def delete_user(
    id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    user = await UserRepository.get_by_id_with_profile(db, id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if is_self_action(admin.id, id):
        raise HTTPException(status_code=403, detail="Admins cannot delete themselves.")
    if user.profile and await is_last_admin(db, user.profile.role):
        raise HTTPException(
            status_code=403, detail="Cannot delete the last remaining admin."
        )

    # Best-effort local storage cleanup (mirrors delete_meeting's pattern) —
    # a failure here is logged but never blocks the account deletion.
    storage_warning = None
    user_dir = os.path.join("uploads", str(id))
    if os.path.isdir(user_dir):
        try:
            shutil.rmtree(user_dir)
        except Exception as e:
            storage_warning = f"Failed to remove local audio directory: {e}"

    # meetings/profile/quota rows cascade via ON DELETE CASCADE from auth.users
    await db.delete(user)
    await db.commit()

    ip, agent = _audit_ctx(request)
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="user.delete",
        target_type="user",
        target_id=str(id),
        metadata={"storage_warning": storage_warning},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"ok": True, "storageWarning": storage_warning}
