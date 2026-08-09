import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import get_password_hash, verify_password
from app.models.user import User, Profile
from app.schemas.profile import (
    ProfileResponse,
    ProfileUpdateRequest,
    ChangePasswordRequest,
    AvatarUploadRequest,
)

router = APIRouter()

ALLOWED_CONTENT_TYPES = ["image/jpeg", "image/png", "image/webp"]
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB
EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get current user profile data, counts, and quota balances.
    """
    # Fetch profiles table row
    query_profile = select(Profile).where(Profile.id == current_user.id)
    result_profile = await db.execute(query_profile)
    profile = result_profile.scalars().first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    # Count meetings
    meeting_count_query = await db.execute(
        text("SELECT COUNT(*) FROM public.meetings WHERE user_id = :user_id"),
        {"user_id": current_user.id},
    )
    meeting_count = meeting_count_query.scalar() or 0

    # Count folders
    folder_count_query = await db.execute(
        text("SELECT COUNT(*) FROM public.folders WHERE user_id = :user_id"),
        {"user_id": current_user.id},
    )
    folder_count = folder_count_query.scalar() or 0

    # Get quota wallet details
    wallet_query = await db.execute(
        text(
            "SELECT audio_seconds_remaining, agent_queries_remaining FROM public.quota_wallets WHERE user_id = :user_id"
        ),
        {"user_id": current_user.id},
    )
    wallet = wallet_query.fetchone()
    audio_remaining = float(wallet[0]) if wallet else 0.0
    queries_remaining = int(wallet[1]) if wallet else 0

    # Serve avatar local URL
    avatar_url = None
    if profile.avatar_key:
        avatar_url = f"/uploads/{profile.avatar_key}"

    return ProfileResponse(
        id=current_user.id,
        email=current_user.email,
        username=profile.username,
        display_name=profile.display_name,
        avatar_key=profile.avatar_key,
        avatar_url=avatar_url,
        theme_preference=profile.theme_preference,
        role=profile.role,
        created_at=profile.created_at,
        meeting_count=meeting_count,
        folder_count=folder_count,
        audio_seconds_remaining=audio_remaining,
        agent_queries_remaining=queries_remaining,
    )


@router.patch("/profile")
async def update_profile(
    payload: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update profile username, display_name, theme_preference, avatar_key.
    """
    # Fetch profiles table row
    query_profile = select(Profile).where(Profile.id == current_user.id)
    result_profile = await db.execute(query_profile)
    profile = result_profile.scalars().first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    fields_set = payload.model_fields_set
    if not fields_set:
        raise HTTPException(status_code=400, detail="No updatable fields provided.")

    updates_made = False

    # --- username: normalize BEFORE validating, not after ---
    if "username" in fields_set and payload.username is not None:
        username_clean = payload.username.strip().lower()
        if not re.match(r"^[a-z0-9_-]{3,30}$", username_clean):
            raise HTTPException(
                status_code=422,
                detail="Username must be 3-30 characters: lowercase letters, digits, underscore, or hyphen.",
            )
        if username_clean != profile.username:
            query_exist = select(Profile).where(Profile.username == username_clean)
            result_exist = await db.execute(query_exist)
            if result_exist.scalars().first():
                raise HTTPException(
                    status_code=409, detail="Username is already taken."
                )
            profile.username = username_clean
            updates_made = True

    # --- display_name ---
    if "display_name" in fields_set and payload.display_name is not None:
        display_clean = payload.display_name.strip()
        profile.display_name = display_clean if display_clean else None
        updates_made = True

    # --- theme_preference: model_fields_set lets an explicit `null` clear it back
    # to the default, distinct from the field being omitted entirely. Checking
    # `is not None` alone (the previous behavior) made both cases identical, so
    # a client could never intentionally reset the theme.
    if "theme_preference" in fields_set:
        profile.theme_preference = payload.theme_preference
        updates_made = True

    # --- avatar_key: same explicit-null-clears semantics as theme_preference. ---
    if "avatar_key" in fields_set:
        if profile.avatar_key and profile.avatar_key != payload.avatar_key:
            old_path = os.path.join("uploads", profile.avatar_key)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        profile.avatar_key = payload.avatar_key if payload.avatar_key else None
        updates_made = True

    if not updates_made:
        raise HTTPException(status_code=400, detail="No updatable fields provided.")

    await db.commit()
    return {"ok": True}


@router.post("/profile/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update password with current password confirmation.
    """
    # Validate current password
    if not verify_password(payload.currentPassword, current_user.encrypted_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    if payload.newPassword == payload.currentPassword:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be different from current password.",
        )

    # Hash and update
    current_user.encrypted_password = get_password_hash(payload.newPassword)
    await db.commit()

    return {"ok": True}


@router.post("/profile/avatar")
async def request_avatar_upload(
    payload: AvatarUploadRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    Validates avatar file size and mimeType, returns local upload URL and key.
    """
    if payload.contentType not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"contentType must be one of: {', '.join(ALLOWED_CONTENT_TYPES)}.",
        )

    if payload.size > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Avatar must be smaller than {MAX_AVATAR_BYTES / 1024 / 1024} MB.",
        )

    ext = EXT_MAP[payload.contentType]
    avatar_key = f"avatars/{current_user.id}{ext}"
    base_url = str(request.base_url).rstrip("/")
    upload_url = f"{base_url}/api/v1/profile/avatar/upload"

    return {"uploadUrl": upload_url, "avatarKey": avatar_key}


@router.put("/profile/avatar/upload")
async def upload_avatar_file(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Receive raw binary avatar file upload, save locally, and update avatar_key.
    """
    # Fetch profiles table row
    query_profile = select(Profile).where(Profile.id == current_user.id)
    result_profile = await db.execute(query_profile)
    profile = result_profile.scalars().first()

    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    # Read binary bytes from body
    body_bytes = await request.body()
    if len(body_bytes) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")

    # Guess extension from content-type header
    ct = request.headers.get("content-type", "image/png")
    ext = EXT_MAP.get(ct, ".png")

    # Ensure uploads/avatars/ exists
    os.makedirs(os.path.join("uploads", "avatars"), exist_ok=True)
    avatar_key = f"avatars/{current_user.id}{ext}"
    save_path = os.path.join("uploads", avatar_key)

    # Save
    with open(save_path, "wb") as f:
        f.write(body_bytes)

    # Update database
    profile.avatar_key = avatar_key
    await db.commit()

    return {"ok": True, "avatarKey": avatar_key, "avatarUrl": f"/uploads/{avatar_key}"}


class ModelPreferenceRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


@router.get("/profile/preferences")
async def get_model_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.ai.registry import list_registered_ai_models
    from app.services.ai.resolve import load_generation_config

    query_profile = select(Profile).where(Profile.id == current_user.id)
    result_profile = await db.execute(query_profile)
    profile = result_profile.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    _, allowed_models = await load_generation_config(db)
    registered = {(e.provider, e.model) for e in list_registered_ai_models()}
    # Only surface allow-listed models that are still resolvable in code —
    # an admin could allow-list a model no longer registered.
    visible_models = [
        m
        for m in allowed_models
        if (m.get("provider"), m.get("model")) in registered
    ]

    return {
        "provider": profile.default_provider,
        "model": profile.default_model,
        "allowedModels": visible_models,
    }


@router.patch("/profile/preferences")
async def update_model_preferences(
    payload: ModelPreferenceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.services.ai.resolve import is_model_allowed, load_generation_config

    query_profile = select(Profile).where(Profile.id == current_user.id)
    result_profile = await db.execute(query_profile)
    profile = result_profile.scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    if payload.provider is None and payload.model is None:
        profile.default_provider = None
        profile.default_model = None
        await db.commit()
        return {"ok": True, "provider": None, "model": None}

    if not payload.provider or not payload.model:
        raise HTTPException(
            status_code=400,
            detail="provider and model must both be set, or both omitted to clear the preference.",
        )

    _, allowed_models = await load_generation_config(db)
    if not is_model_allowed(payload.provider, payload.model, allowed_models):
        raise HTTPException(
            status_code=400, detail="That provider/model is not currently allowed."
        )

    profile.default_provider = payload.provider
    profile.default_model = payload.model
    await db.commit()

    return {"ok": True, "provider": payload.provider, "model": payload.model}
