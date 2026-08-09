import os
import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.folder import Folder, FolderShare
from app.models.user import User, Profile
from app.models.project import Project
from app.schemas.folder import (
    FolderCreateRequest,
    FolderUpdateRequest,
    FolderReorderRequest,
    FolderShareCreateRequest,
    FolderShareUpdateRequest,
    FolderResponse,
    FolderListResponse,
    FolderMemberResponse,
    FolderMemberListResponse,
)

router = APIRouter()


def escape_ilike_wildcards(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/folders", response_model=FolderListResponse)
async def list_folders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List owned folders + shared folders (with role annotations).
    """
    # 1. Fetch owned folders sorted by position, then name
    query_owned = (
        select(Folder)
        .where(Folder.user_id == current_user.id)
        .order_by(Folder.position.asc(), Folder.name.asc())
    )
    result_owned = await db.execute(query_owned)
    owned_folders = result_owned.scalars().all()

    # 2. Count members (folder_shares rows) for each owned folder
    member_counts = {}
    if owned_folders:
        owned_ids = [f.id for f in owned_folders]
        query_counts = await db.execute(
            text("""
                SELECT folder_id, COUNT(*) 
                FROM public.folder_shares 
                WHERE folder_id = ANY(:folder_ids) 
                GROUP BY folder_id
            """),
            {"folder_ids": owned_ids},
        )
        for row in query_counts.fetchall():
            member_counts[row[0]] = row[1]

    # Map owned folders response
    folders_list = []
    for f in owned_folders:
        folders_list.append(
            FolderResponse(
                id=f.id,
                user_id=f.user_id,
                name=f.name,
                position=f.position,
                created_at=f.created_at,
                updated_at=f.updated_at,
                myRole="owner",
                ownerUsername=None,
                memberCount=member_counts.get(f.id, 0),
            )
        )

    # 3. Fetch shared folders
    # First get all share rows for this user
    query_shares = select(FolderShare).where(FolderShare.user_id == current_user.id)
    result_shares = await db.execute(query_shares)
    shares = result_shares.scalars().all()

    if shares:
        folder_ids = [s.folder_id for s in shares]
        # Fetch folders that correspond to these folder IDs
        query_shared_folders = (
            select(Folder).where(Folder.id.in_(folder_ids)).order_by(Folder.name.asc())
        )
        result_shared_folders = await db.execute(query_shared_folders)
        shared_folders = result_shared_folders.scalars().all()

        # Fetch owner usernames from profiles
        owner_ids = list(set([f.user_id for f in shared_folders]))
        query_profiles = select(Profile).where(Profile.id.in_(owner_ids))
        result_profiles = await db.execute(query_profiles)
        profiles_map = {p.id: p.username for p in result_profiles.scalars().all()}

        # Map shared folders response
        for sf in shared_folders:
            share_row = next((s for s in shares if s.folder_id == sf.id), None)
            role = share_row.role if share_row else "viewer"
            owner_username = profiles_map.get(sf.user_id)

            folders_list.append(
                FolderResponse(
                    id=sf.id,
                    user_id=sf.user_id,
                    name=sf.name,
                    position=sf.position,
                    created_at=sf.created_at,
                    updated_at=sf.updated_at,
                    myRole=role,
                    ownerUsername=owner_username,
                    memberCount=0,
                )
            )

    return FolderListResponse(folders=folders_list)


@router.post(
    "/folders", response_model=FolderResponse, status_code=status.HTTP_201_CREATED
)
async def create_folder(
    payload: FolderCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new folder. Unique name per user (case-insensitive).
    """
    name_stripped = payload.name.strip()

    # Check duplicate name case-insensitive for this user. escape_ilike_wildcards
    # is required: unescaped `%`/`_` in the name are live SQL wildcards, so e.g.
    # "Q1_Notes" would previously false-positive as a duplicate of "Q1XNotes".
    query_existing = select(Folder).where(
        Folder.user_id == current_user.id,
        Folder.name.ilike(escape_ilike_wildcards(name_stripped), escape="\\"),
    )
    result_existing = await db.execute(query_existing)
    if result_existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'A folder named "{payload.name}" already exists.',
        )

    # Find the maximum position to append new folder at position + 1
    query_max_pos = await db.execute(
        text("SELECT MAX(position) FROM public.folders WHERE user_id = :user_id"),
        {"user_id": current_user.id},
    )
    max_pos = query_max_pos.scalar()
    position = 0 if max_pos is None else max_pos + 1

    folder = Folder(
        id=uuid.uuid4(),
        user_id=current_user.id,
        name=name_stripped,
        position=position,
    )
    db.add(folder)
    try:
        await db.commit()
    except IntegrityError:
        # Backstop against the same race the pre-check can't close: two concurrent
        # creates with the identical name can both pass the SELECT above.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'A folder named "{payload.name}" already exists.',
        )
    await db.refresh(folder)

    return FolderResponse(
        id=folder.id,
        user_id=folder.user_id,
        name=folder.name,
        position=folder.position,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        myRole="owner",
        ownerUsername=None,
        memberCount=0,
    )


@router.put("/folders/reorder")
async def reorder_folders(
    payload: FolderReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Persist drag-and-drop folder order. Only updates owned folders.
    """
    if payload.order:
        now = datetime.utcnow()
        params = [
            {"pos": idx, "now": now, "id": folder_id, "user_id": current_user.id}
            for idx, folder_id in enumerate(payload.order)
        ]
        await db.execute(
            text("""
                UPDATE public.folders 
                SET position = :pos, updated_at = :now 
                WHERE id = :id AND user_id = :user_id
            """),
            params,
        )
        await db.commit()
    return {"ok": True}


@router.patch("/folders/{id}", response_model=FolderResponse)
async def rename_folder(
    id: UUID,
    payload: FolderUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Rename an owned folder. Unique name per user (case-insensitive).
    """
    # Fetch folder
    query_folder = select(Folder).where(Folder.id == id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found."
        )
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")

    name_stripped = payload.name.strip()

    # Check duplicate name case-insensitive (excluding itself)
    query_existing = select(Folder).where(
        Folder.user_id == current_user.id,
        Folder.name.ilike(escape_ilike_wildcards(name_stripped), escape="\\"),
        Folder.id != id,
    )
    result_existing = await db.execute(query_existing)
    if result_existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'A folder named "{payload.name}" already exists.',
        )

    folder.name = name_stripped
    folder.updated_at = datetime.utcnow()
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f'A folder named "{payload.name}" already exists.',
        )
    await db.refresh(folder)

    # Get members count
    query_count = await db.execute(
        text("SELECT COUNT(*) FROM public.folder_shares WHERE folder_id = :folder_id"),
        {"folder_id": id},
    )
    member_count = query_count.scalar() or 0

    return FolderResponse(
        id=folder.id,
        user_id=folder.user_id,
        name=folder.name,
        position=folder.position,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        myRole="owner",
        ownerUsername=None,
        memberCount=member_count,
    )


@router.delete("/folders/{id}")
async def delete_folder(
    id: UUID,
    deleteMeetings: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete folder. If deleteMeetings=true, deletes folder + all meetings inside.
    If deleteMeetings=false, meetings move to Uncategorized (folder_id=NULL).
    """
    # Fetch folder
    query_folder = select(Folder).where(Folder.id == id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found."
        )
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")

    if deleteMeetings:
        # Fetch all meetings in the folder
        query_meetings = select(Project).where(Project.folder_id == id)
        result_meetings = await db.execute(query_meetings)
        meetings = result_meetings.scalars().all()

        for m in meetings:
            # Delete audio from disk if local
            if m.audio_path and os.path.exists(m.audio_path):
                try:
                    os.remove(m.audio_path)
                except Exception:
                    pass
        if meetings:
            meeting_ids = [m.id for m in meetings]
            await db.execute(
                text("DELETE FROM public.meetings WHERE id = ANY(:ids)"),
                {"ids": meeting_ids},
            )
    else:
        # Move meetings to Uncategorized (folder_id=NULL)
        await db.execute(
            text("UPDATE public.meetings SET folder_id = NULL WHERE folder_id = :id"),
            {"id": id},
        )

    # Delete the folder row (cascades to folder_shares)
    await db.delete(folder)
    await db.commit()
    return {"ok": True}


@router.get("/folders/{id}/shares", response_model=FolderMemberListResponse)
async def list_folder_shares(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List members of a folder (owner only).
    """
    # Check folder ownership
    query_folder = select(Folder).where(Folder.id == id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found."
        )
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")

    # Fetch shares
    query_shares = (
        select(FolderShare)
        .where(FolderShare.folder_id == id)
        .order_by(FolderShare.created_at.asc())
    )
    result_shares = await db.execute(query_shares)
    shares = result_shares.scalars().all()

    if not shares:
        return FolderMemberListResponse(members=[])

    # Resolve user IDs to usernames
    user_ids = [s.user_id for s in shares]
    query_profiles = select(Profile).where(Profile.id.in_(user_ids))
    result_profiles = await db.execute(query_profiles)
    profiles_map = {p.id: p.username for p in result_profiles.scalars().all()}

    members_list = []
    for s in shares:
        members_list.append(
            FolderMemberResponse(
                userId=s.user_id,
                username=profiles_map.get(s.user_id, str(s.user_id)),
                role=s.role,
            )
        )

    return FolderMemberListResponse(members=members_list)


@router.post(
    "/folders/{id}/shares",
    response_model=FolderMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_folder_share(
    id: UUID,
    payload: FolderShareCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a member to a folder by email or username (owner only).
    """
    # Check folder ownership
    query_folder = select(Folder).where(Folder.id == id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found."
        )
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")

    identifier = payload.identifier.strip()
    grantee_id = None
    grantee_username = None

    if "@" in identifier:
        # Look up user by email in auth.users
        email = identifier.lower()
        query_user = select(User).where(User.email == email)
        result_user = await db.execute(query_user)
        user = result_user.scalars().first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with that email.",
            )
        grantee_id = user.id

        # Fetch profile username
        query_profile = select(Profile).where(Profile.id == grantee_id)
        result_profile = await db.execute(query_profile)
        prof = result_profile.scalars().first()
        grantee_username = prof.username if prof else str(grantee_id)
    else:
        # Look up profile by username
        username = identifier.replace("@", "").lower().strip()
        query_profile = select(Profile).where(Profile.username == username)
        result_profile = await db.execute(query_profile)
        prof = result_profile.scalars().first()
        if not prof:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with that username.",
            )
        grantee_id = prof.id
        grantee_username = prof.username

    # Validations
    if grantee_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot share a folder with yourself.",
        )
    if grantee_id == folder.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That user is already the folder owner.",
        )

    # Check already shared
    query_share_exists = select(FolderShare).where(
        FolderShare.folder_id == id, FolderShare.user_id == grantee_id
    )
    result_share_exists = await db.execute(query_share_exists)
    if result_share_exists.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That user is already a member of this folder.",
        )

    # Create folder share
    share = FolderShare(
        id=uuid.uuid4(),
        folder_id=id,
        user_id=grantee_id,
        role=payload.role,
        invited_by=current_user.id,
    )
    db.add(share)
    await db.commit()

    return FolderMemberResponse(
        userId=grantee_id,
        username=grantee_username,
        role=payload.role,
    )


@router.patch("/folders/{id}/shares/{grantee_id}")
async def update_folder_share(
    id: UUID,
    grantee_id: UUID,
    payload: FolderShareUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Change a member's role (owner only).
    """
    # Check folder ownership
    query_folder = select(Folder).where(Folder.id == id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found."
        )
    if folder.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")

    # Find the share row
    query_share = select(FolderShare).where(
        FolderShare.folder_id == id, FolderShare.user_id == grantee_id
    )
    result_share = await db.execute(query_share)
    share = result_share.scalars().first()

    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share membership not found.",
        )

    share.role = payload.role
    await db.commit()

    return {"ok": True, "role": share.role}


@router.delete("/folders/{id}/shares/{grantee_id}")
async def remove_folder_share(
    id: UUID,
    grantee_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove a member (folder owner OR the grantee removing themselves).
    """
    # Check folder ownership
    query_folder = select(Folder).where(Folder.id == id)
    result_folder = await db.execute(query_folder)
    folder = result_folder.scalars().first()

    if not folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found."
        )

    is_owner = folder.user_id == current_user.id
    is_self = grantee_id == current_user.id

    if not is_owner and not is_self:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")

    # Find and delete the share row
    query_share = select(FolderShare).where(
        FolderShare.folder_id == id, FolderShare.user_id == grantee_id
    )
    result_share = await db.execute(query_share)
    share = result_share.scalars().first()

    if not share:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share membership not found.",
        )

    await db.delete(share)
    await db.commit()
    return {"ok": True}
