from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.user import User


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # Role lives on Profile.role, not User — User has no `role` column/attribute.
    # Reading current_user.role here raised AttributeError on every call, so every
    # endpoint in this router 500'd unconditionally regardless of caller.
    if not current_user.profile or current_user.profile.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return current_user
