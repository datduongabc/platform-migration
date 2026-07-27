from uuid import UUID

from app.models.project import Project
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


class ProjectRepository:
    @staticmethod
    async def list_user_projects(
        db: AsyncSession, user_id: UUID | str, skip: int, limit: int
    ) -> list[Project]:
        query = (
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return list(result.scalars().all())
