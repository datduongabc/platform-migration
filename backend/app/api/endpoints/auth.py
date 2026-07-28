import asyncio
import uuid

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.repositories.user import ProfileRepository, UserRepository
from app.schemas.codegen import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    Token,
    TokenRefreshResponse,
)
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(
    request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_db)
):
    # Normalize and validate email
    try:
        email = validate_email(payload.email, check_deliverability=False).normalized
    except EmailNotValidError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid email address: {str(e)}",
        )

    # Checking if email already existed
    existing_user = await UserRepository.get_by_email(db, email)

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists. Please choose another.",
        )

    # Checking if username already existed
    existing_profile = await ProfileRepository.get_by_username(db, payload.username)

    if existing_profile:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists. Please choose another.",
        )

    # Hash password in worker thread to prevent blocking event loop
    hashed_password = await asyncio.to_thread(get_password_hash, payload.password)

    # Insert user
    new_user = await UserRepository.create(
        db,
        uuid.uuid4(),
        email,
        hashed_password,
    )

    # Insert profile
    await ProfileRepository.create(db, new_user.id, payload.username, role="user")

    # Save session
    await db.commit()

    return {"status": "ok", "message": "Account created successfully."}


# Dummy hash for constant-time password comparison when user is not found
# Prevent user enumeration
DUMMY_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeg6Lruj3vjPGga31lW"


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)
):
    generic_error = (
        "Invalid credentials. Please check your email or username and password."
    )

    identifier = payload.identifier

    if "@" in identifier:
        user = await UserRepository.get_by_email_with_profile(db, identifier)
    else:
        user = await UserRepository.get_by_username_with_profile(db, identifier)

    # Always execute verify_password even if user is missing
    target_hash = user.encrypted_password if user and user.profile else DUMMY_HASH

    # This action is offloaded to a thread to avoid blocking the event loop
    is_password_match = await asyncio.to_thread(
        verify_password, payload.password, target_hash
    )

    if not user or not user.profile or not is_password_match:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=generic_error
        )

    user_profile = user.profile

    # Create access and refresh tokens
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user_id": str(user.id),
        "email": user.email,
        "username": user_profile.username,
        "role": user_profile.role,
    }


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(
    request: Request, payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
    decoded = decode_token(payload.refresh_token)

    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = decoded.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token claims",
        )

    user = await UserRepository.get_by_id_with_profile(db, user_id)
    if not user or not user.profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Create new access and refresh tokens
    new_access_token = create_access_token(subject=user.id)
    new_refresh_token = create_refresh_token(subject=user.id)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(request: Request):
    return {"status": "ok", "message": "Logged out successfully."}
