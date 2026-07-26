"""
PFIS Database Module
Async PostgreSQL engine, session factory, and base model.
"""

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def normalize_async_database_url(url: str) -> str:
    """Return an asyncpg URL and reject unsupported database engines."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    raise ValueError("PFIS supports PostgreSQL only")


database_url = normalize_async_database_url(settings.DATABASE_URL)
engine = create_async_engine(
    database_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dependency injection for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Leave schema ownership to Alembic in every environment."""
    logger.info("Database schema is managed by Alembic; create_all is disabled.")


async def close_db():
    """Dispose engine. Used on shutdown."""
    await engine.dispose()
