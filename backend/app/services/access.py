from uuid import UUID

from app.models.folder import Folder, FolderShare
from app.models.project import Project
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


async def check_folder_access(
    db: AsyncSession,
    folder_id: UUID | str,
    user_id: UUID | str,
    min_role: str = "viewer",
) -> bool:
    """
    Returns True if the user_id owns the folder or has a share row with role >= min_role.
    """
    # 1. Fetch folder
    query_folder = select(Folder).where(Folder.id == folder_id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        return False
    if folder.user_id == user_id:
        return True  # folder owner

    # 2. Check shares
    query_share = select(FolderShare).where(
        FolderShare.folder_id == folder_id, FolderShare.user_id == user_id
    )
    result_share = await db.execute(query_share)
    share = result_share.scalars().first()

    if not share:
        return False
    if min_role == "viewer":
        return True  # editor and viewer both pass viewer check
    return share.role == "editor"


async def check_meeting_access(
    db: AsyncSession, meeting: Project, user_id: UUID | str, min_role: str = "viewer"
) -> bool:
    """
    Returns True if user_id can access the meeting at min_role level.
    """
    if meeting.user_id == user_id:
        return True
    if not meeting.folder_id:
        return False
    return await check_folder_access(db, meeting.folder_id, user_id, min_role)


async def get_meeting_role(
    db: AsyncSession, meeting: Project, user_id: UUID | str
) -> str:
    """
    Returns the user's effective role for a meeting ('owner', 'editor', 'viewer').
    """
    if meeting.user_id == user_id:
        return "owner"
    if not meeting.folder_id:
        return "viewer"

    # Fetch folder
    query_folder = select(Folder).where(Folder.id == meeting.folder_id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        return "viewer"
    if folder.user_id == user_id:
        return "owner"

    # Check share role
    query_share = select(FolderShare).where(
        FolderShare.folder_id == meeting.folder_id, FolderShare.user_id == user_id
    )
    result_share = await db.execute(query_share)
    share = result_share.scalars().first()

    if not share:
        return "viewer"
    return share.role
