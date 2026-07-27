import uuid

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

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

    # Check if email already exists
    if await UserRepository.get_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists. Please choose another.",
        )

    # Check if username already exists
    if await ProfileRepository.get_by_username(db, payload.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists. Please choose another.",
        )

    # Hash password and insert user
    new_user = await UserRepository.create(
        db,
        uuid.uuid4(),
        email,
        get_password_hash(payload.password),
    )

    # Insert profile
    await ProfileRepository.create(db, new_user.id, payload.username, role="user")

    # Save session
    await db.flush()
    await db.commit()

    return {"status": "ok", "message": "Account created successfully."}


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
async def login(
    request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)
):
    generic_error = (
        "Invalid credentials. Please check your email or username and password."
    )
    identifier = payload.identifier

    # Resolve identifier to user
    user = None

    if "@" in identifier:
        user = await UserRepository.get_by_email(db, identifier)
    else:
        profile = await ProfileRepository.get_by_username(db, identifier)

        if not profile:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=generic_error
            )

        user = await UserRepository.get_by_id(db, profile.id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=generic_error
        )

    # Eagerly load profile
    user_profile = await ProfileRepository.get_by_user_id(db, user.id)
    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=generic_error
        )

    # Verify password
    if not verify_password(payload.password, user.encrypted_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=generic_error
        )

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
    payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
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

    # Verify user exists
    user = await UserRepository.get_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Eagerly load profile
    user_profile = await ProfileRepository.get_by_user_id(db, user.id)
    if not user_profile:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User profile not found",
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
