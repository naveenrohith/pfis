"""Production-database smoke tests, enabled by the PostgreSQL CI job."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.database import Base, normalize_async_database_url
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]


def _migration_head() -> str:
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


def test_database_url_normalization_supports_common_deployment_urls():
    assert normalize_async_database_url("postgres://user:pass@db/pfis") == (
        "postgresql+asyncpg://user:pass@db/pfis"
    )
    assert normalize_async_database_url("postgresql://user:pass@db/pfis") == (
        "postgresql+asyncpg://user:pass@db/pfis"
    )
    with pytest.raises(ValueError, match="PostgreSQL only"):
        normalize_async_database_url("sqlite:///./pfis.db")


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
            migrated_columns = await connection.run_sync(
                lambda sync_connection: {
                    table_name: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns(table_name)
                    }
                    for table_name in Base.metadata.tables
                }
            )
    finally:
        await engine.dispose()

    assert revision == _migration_head()
    assert set(Base.metadata.tables) <= table_names
    assert migrated_columns == {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }
