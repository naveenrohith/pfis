"""Production-database smoke tests, enabled by the PostgreSQL CI job."""

from __future__ import annotations

import os

import pytest
from app.database import Base, normalize_async_database_url
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


def test_database_url_normalization_supports_common_deployment_urls():
    assert normalize_async_database_url("postgres://user:pass@db/pfis") == (
        "postgresql+asyncpg://user:pass@db/pfis"
    )
    assert normalize_async_database_url("postgresql://user:pass@db/pfis") == (
        "postgresql+asyncpg://user:pass@db/pfis"
    )
    assert normalize_async_database_url("sqlite:///./pfis.db") == ("sqlite+aiosqlite:///./pfis.db")


@pytest.mark.asyncio
async def test_postgres_migrations_match_runtime_metadata():
    database_url = os.getenv("POSTGRES_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("POSTGRES_TEST_DATABASE_URL is only configured in PostgreSQL CI")

    engine = create_async_engine(normalize_async_database_url(database_url))
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
    finally:
        await engine.dispose()

    assert revision == "014_auth_sessions"
    assert set(Base.metadata.tables) <= table_names
