from uuid import UUID

from app.models.user import Profile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


def is_self_action(actor_id: UUID | str, target_id: UUID | str) -> bool:
    return str(actor_id) == str(target_id)


async def is_last_admin(db: AsyncSession, target_current_role: str) -> bool:
    """
    True if demoting/disabling/deleting the target would remove the last admin.
    Only meaningful when the target currently IS an admin.
    """
    if target_current_role != "admin":
        return False
    result = await db.execute(
        select(func.count()).select_from(Profile).where(Profile.role == "admin")
    )
    admin_count = result.scalar() or 0
    return admin_count <= 1
