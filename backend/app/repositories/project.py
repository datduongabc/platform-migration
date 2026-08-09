from uuid import UUID
from datetime import datetime
from app.models.folder import FolderShare
from app.models.project import Project, Todo, CalendarSuggestion
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload


class ProjectRepository:
    @staticmethod
    async def list_user_projects(
        db: AsyncSession, user_id: UUID | str, skip: int, limit: int
    ) -> list[Project]:
        # Owned meetings, plus meetings in a folder shared with this user
        # (editor or viewer) — previously this only returned owned meetings, so a
        # shared-folder member could never even see the meeting in their list.
        shared_folder_ids = select(FolderShare.folder_id).where(
            FolderShare.user_id == user_id
        )
        query = (
            select(Project)
            .where(
                or_(
                    Project.user_id == user_id,
                    Project.folder_id.in_(shared_folder_ids),
                )
            )
            .order_by(Project.pinned_at.desc().nullslast(), Project.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, project_id: UUID | str) -> Project | None:
        query = select(Project).where(Project.id == project_id)
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def get_by_id_with_relations(
        db: AsyncSession, project_id: UUID | str
    ) -> Project | None:
        query = (
            select(Project)
            .options(
                selectinload(Project.segments),
                selectinload(Project.todos),
                selectinload(Project.calendar_suggestions),
            )
            .where(Project.id == project_id)
        )
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def create(
        db: AsyncSession,
        project_id: UUID,
        user_id: UUID,
        title: str,
        audio_path: str,
        duration_seconds: int | None = None,
        started_at: datetime | None = None,
        source: str = "recorded",
        storage_provider: str = "r2",
        folder_id: UUID | None = None,
    ) -> Project:
        project = Project(
            id=project_id,
            user_id=user_id,
            title=title,
            status="pending",
            audio_path=audio_path,
            duration_seconds=duration_seconds,
            started_at=started_at or datetime.utcnow(),
            source=source,
            storage_provider=storage_provider,
            folder_id=folder_id,
        )
        db.add(project)
        return project

    @staticmethod
    async def delete(db: AsyncSession, project: Project) -> None:
        await db.delete(project)

    @staticmethod
    async def get_todo_by_id(db: AsyncSession, todo_id: UUID | str) -> Todo | None:
        query = select(Todo).where(Todo.id == todo_id)
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def get_calendar_suggestion_by_id(
        db: AsyncSession, suggestion_id: UUID | str
    ) -> CalendarSuggestion | None:
        query = select(CalendarSuggestion).where(CalendarSuggestion.id == suggestion_id)
        result = await db.execute(query)
        return result.scalars().first()
