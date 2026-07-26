"""Safety tests for the one-time SQLite-to-PostgreSQL importer."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import Column, Enum, MetaData, String, Table, create_engine, text

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_sqlite_to_postgres.py"


def load_migration_module():
    spec = importlib.util.spec_from_file_location("pfis_legacy_database_migration", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_source_inventory_reads_legacy_database_without_writing(tmp_path):
    module = load_migration_module()
    source = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{source.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO users (id) VALUES ('user-1'), ('user-2')"))
    finally:
        engine.dispose()
    original_bytes = source.read_bytes()

    assert module.source_inventory(source) == {"users": 2}
    assert source.read_bytes() == original_bytes


@pytest.mark.parametrize(
    ("provided", "expected"),
    [
        (
            "postgres://user:pass@db/pfis",
            "postgresql+asyncpg://user:pass@db/pfis",
        ),
        (
            "postgresql://user:pass@db/pfis",
            "postgresql+asyncpg://user:pass@db/pfis",
        ),
        (
            "postgresql+asyncpg://user:pass@db/pfis",
            "postgresql+asyncpg://user:pass@db/pfis",
        ),
    ],
)
def test_require_postgres_url_normalizes_supported_urls(provided, expected):
    module = load_migration_module()
    assert module.require_postgres_url(provided) == expected


@pytest.mark.parametrize("provided", [None, "", "sqlite:///pfis.db", "mysql://db/pfis"])
def test_require_postgres_url_rejects_missing_or_unsupported_targets(provided):
    module = load_migration_module()
    with pytest.raises(SystemExit):
        module.require_postgres_url(provided)


def test_normalize_legacy_row_translates_enum_member_names():
    module = load_migration_module()
    table = Table(
        "jobs",
        MetaData(),
        Column("id", String),
        Column("status", Enum("queued", "running", "completed", "failed")),
    )

    assert module.normalize_legacy_row(
        {"id": "job-1", "status": "COMPLETED"},
        table,
    ) == {"id": "job-1", "status": "completed"}


def test_normalize_legacy_row_rejects_unknown_enum_values():
    module = load_migration_module()
    table = Table(
        "jobs",
        MetaData(),
        Column("status", Enum("queued", "completed")),
    )

    with pytest.raises(RuntimeError, match="Unsupported enum value"):
        module.normalize_legacy_row({"status": "abandoned"}, table)


def test_supabase_configuration_leaves_schema_and_seed_ownership_to_alembic():
    config = (SCRIPT.parents[1] / "supabase" / "config.toml").read_text(encoding="utf-8")
    migrations = config.split("[db.migrations]", 1)[1].split("[db.seed]", 1)[0]
    seed = config.split("[db.seed]", 1)[1].split("[db.network_restrictions]", 1)[0]

    assert "enabled = false" in migrations
    assert "enabled = false" in seed
