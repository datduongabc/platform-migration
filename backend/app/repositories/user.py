from uuid import UUID

from app.models.user import Profile, User
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


class UserRepository:
    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: UUID | str) -> User | None:
        query = select(User).where(User.id == user_id)
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        query = select(User).where(User.email == email)
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def list_users(
        db: AsyncSession,
        skip: int,
        limit: int,
        role: str | None = None,
        search: str | None = None,
    ) -> list[User]:
        from sqlalchemy import or_

        query = select(User)
        if role or search:
            query = query.join(Profile)
        if role:
            query = query.where(Profile.role == role)
        if search:
            search_filter = f"%{search}%"
            query = query.where(
                or_(
                    User.email.ilike(search_filter),
                    Profile.username.ilike(search_filter),
                    Profile.display_name.ilike(search_filter),
                )
            )
        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create(
        db: AsyncSession, user_id: UUID, email: str, encrypted_password: str
    ) -> User:
        user = User(id=user_id, email=email, encrypted_password=encrypted_password)
        db.add(user)
        return user


class ProfileRepository:
    @staticmethod
    async def get_by_user_id(db: AsyncSession, user_id: UUID | str) -> Profile | None:
        query = select(Profile).where(Profile.id == user_id)
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def get_by_username(db: AsyncSession, username: str) -> Profile | None:
        query = select(Profile).where(Profile.username == username)
        result = await db.execute(query)
        return result.scalars().first()

    @staticmethod
    async def create(
        db: AsyncSession, user_id: UUID, username: str, role: str = "user"
    ) -> Profile:
        profile = Profile(id=user_id, username=username, role=role)
        db.add(profile)
        return profile
