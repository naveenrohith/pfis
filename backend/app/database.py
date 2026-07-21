"""
PFIS Database Module
Async SQLAlchemy engine, session factory, and base model.
Swappable between SQLite (prototype) and PostgreSQL (production).
"""

import logging
from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def normalize_async_database_url(url: str) -> str:
    """Return an async-driver URL for every supported database."""
    if url.startswith("sqlite:///") and "+aiosqlite" not in url:
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Make SQLite enforce the same foreign-key ownership rules as PostgreSQL."""
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


# Create async engine — works with both SQLite and PostgreSQL
database_url = normalize_async_database_url(settings.DATABASE_URL)
engine = create_async_engine(
    database_url,
    echo=settings.DEBUG,
    # SQLite needs check_same_thread=False
    connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
)
enable_sqlite_foreign_keys(engine.sync_engine)

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
