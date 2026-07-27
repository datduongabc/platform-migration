from typing import AsyncGenerator

from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

# Create async engine with pool configuration
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args={
        "prepared_statement_cache_size": 0,
        "statement_cache_size": 0,
    },
)

# Create session factory
async_session_factory = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
