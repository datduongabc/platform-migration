from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.repositories.project import ProjectRepository
from app.schemas.codegen import ProjectResponse

router = APIRouter()


@router.get("/projects", response_model=List[ProjectResponse])
async def list_user_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the list of projects (meetings) belonging to the authenticated user.
    """
    projects = await ProjectRepository.list_user_projects(
        db, current_user.id, skip, limit
    )

    return projects
