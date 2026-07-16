"""
PFIS Database Module
Async SQLAlchemy engine, session factory, and base model.
Swappable between SQLite (prototype) and PostgreSQL (production).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Create async engine — works with both SQLite and PostgreSQL
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    # SQLite needs check_same_thread=False
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
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


async def get_db() -> AsyncSession:
    """Dependency injection for database sessions."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create tables for local/demo runs.

    In the production profile the schema is owned by Alembic migrations
    (`alembic upgrade head`), so ``create_all`` is skipped to avoid divergence
    between the live schema and the migration history.
    """
    if get_settings().is_production:
        logger.info("Production profile: skipping create_all; run 'alembic upgrade head'.")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose engine. Used on shutdown."""
    await engine.dispose()
