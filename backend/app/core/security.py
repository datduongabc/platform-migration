from datetime import datetime, timedelta, timezone
from typing import Any, Union

import jwt
from app.core.config import settings
from bcrypt import checkpw, gensalt, hashpw


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt. Returns a decoded utf-8 string.
    """
    return hashpw(password.encode("utf-8"), gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against its hashed version.
    """
    return checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(
    subject: Union[str, Any], expires_delta: timedelta = None
) -> str:
    """
    Create a JWT access token.
    """
    return generate_jwt_token(subject, "access", expires_delta)


def create_refresh_token(
    subject: Union[str, Any], expires_delta: timedelta = None
) -> str:
    """
    Create a JWT refresh token.
    """
    return generate_jwt_token(subject, "refresh", expires_delta)


def decode_token(token: str) -> Union[dict, None]:
    """
    Decode a JWT token and return the payload.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except (jwt.PyJWTError, ValueError):
        return None


# Helper function


def generate_jwt_token(
    subject: Union[str, Any],
    token_type: str,
    expires_delta: timedelta = None,
) -> str:
    """
    Generate a JWT token with custom type and expiration.
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        if token_type == "access":
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                weeks=settings.REFRESH_TOKEN_EXPIRE_WEEKS
            )

    to_encode = {"exp": expire, "sub": str(subject), "type": token_type}

    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
