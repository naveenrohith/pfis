"""
PFIS Database Module
Async SQLAlchemy engine, session factory, and base model.
Swappable between SQLite (prototype) and PostgreSQL (production).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

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
    """Create all tables. Used on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in settings.DATABASE_URL:
            table_info = await conn.execute(text("PRAGMA table_info(users)"))
            columns = {row[1] for row in table_info.fetchall()}
            if "password_hash" not in columns:
                await conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"))
            if "is_active" not in columns:
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1"))
            await conn.execute(text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))

            txn_table_info = await conn.execute(text("PRAGMA table_info(transactions)"))
            txn_columns = {row[1] for row in txn_table_info.fetchall()}
            if "reviewed_flag" not in txn_columns:
                await conn.execute(text("ALTER TABLE transactions ADD COLUMN reviewed_flag BOOLEAN DEFAULT 0"))
            if "reviewed_at" not in txn_columns:
                await conn.execute(text("ALTER TABLE transactions ADD COLUMN reviewed_at DATETIME"))
            await conn.execute(
                text(
                    "UPDATE transactions SET reviewed_flag = 1, reviewed_at = COALESCE(reviewed_at, created_at) "
                    "WHERE reviewed_flag IS NULL OR (reviewed_flag = 0 AND confidence_score >= 0.85)"
                )
            )


async def close_db():
    """Dispose engine. Used on shutdown."""
    await engine.dispose()
