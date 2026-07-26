"""Migration discipline tests for the PostgreSQL-only PFIS persistence layer."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.database import Base, normalize_async_database_url
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def temporary_postgres_database() -> Iterator[str]:
    """Create an isolated PostgreSQL database for a complete Alembic run."""
    source_url = os.getenv("POSTGRES_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not source_url:
        pytest.skip("A PostgreSQL test service is required")

    parsed = make_url(normalize_async_database_url(source_url))
    database_name = f"pfis_migration_{uuid.uuid4().hex}"

    async def create_database() -> None:
        connection = await asyncpg.connect(
            host=parsed.host,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database="postgres",
        )
        try:
            await connection.execute(f'CREATE DATABASE "{database_name}"')
        finally:
            await connection.close()

    async def drop_database() -> None:
        connection = await asyncpg.connect(
            host=parsed.host,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database="postgres",
        )
        try:
            await connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                database_name,
            )
            await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        finally:
            await connection.close()

    asyncio.run(create_database())
    database_url = parsed.set(database=database_name).render_as_string(hide_password=False)
    try:
        yield database_url
    finally:
        asyncio.run(drop_database())


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    config.attributes["database_url"] = database_url
    return config


def test_alembic_revision_ids_fit_portable_version_column():
    scripts = ScriptDirectory.from_config(
        alembic_config("postgresql+asyncpg://unused:unused@localhost/unused")
    )
    assert all(len(revision.revision) <= 32 for revision in scripts.walk_revisions())


def test_migrations_use_portable_boolean_server_defaults():
    migration_dir = ROOT / "backend" / "alembic" / "versions"
    source = "\n".join(path.read_text(encoding="utf-8") for path in migration_dir.glob("*.py"))

    assert 'server_default=sa.text("1")' not in source
    assert 'server_default=sa.text("0")' not in source


def test_alembic_head_matches_orm_and_database_constraints():
    """A clean PostgreSQL migration must match the complete ORM contract."""
    with temporary_postgres_database() as database_url:
        command.upgrade(alembic_config(database_url), "head")

        async def inspect_schema() -> dict:
            engine = create_async_engine(database_url)
            try:
                async with engine.connect() as connection:

                    def collect(sync_connection) -> dict:
                        inspector = inspect(sync_connection)
                        tables = [
                            name
                            for name in inspector.get_table_names()
                            if name != "alembic_version"
                        ]
                        return {
                            "columns": {
                                table: {column["name"] for column in inspector.get_columns(table)}
                                for table in tables
                            },
                            "merchant_unique": {
                                item["name"]
                                for item in inspector.get_unique_constraints("user_merchant_rules")
                            },
                            "merchant_indexes": {
                                item["name"]
                                for item in inspector.get_indexes("user_merchant_rules")
                            },
                            "budget_unique": {
                                item["name"] for item in inspector.get_unique_constraints("budgets")
                            },
                            "gmail_unique": {
                                item["name"]
                                for item in inspector.get_unique_constraints("gmail_accounts")
                            },
                            "operational_indexes": {
                                item["name"]
                                for table in ("raw_emails", "sync_runs")
                                for item in inspector.get_indexes(table)
                            },
                        }

                    result = await connection.run_sync(collect)
                    result["revision"] = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    return result
            finally:
                await engine.dispose()

        schema = asyncio.run(inspect_schema())

    orm_columns = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }
    assert schema["columns"] == orm_columns
    assert schema["revision"] == "017_gmail_token_expiry"
    assert "uq_user_merchant_rule_descriptor" in schema["merchant_unique"]
    assert {
        "ix_user_merchant_rules_user_id",
        "ix_user_merchant_rules_user_name",
    } <= schema["merchant_indexes"]
    assert "uq_budgets_user_category" in schema["budget_unique"]
    assert {
        "uq_gmail_accounts_user",
        "uq_gmail_accounts_google_account",
    } <= schema["gmail_unique"]
    assert {
        "ix_raw_emails_user_received",
        "ix_sync_runs_user_started",
    } <= schema["operational_indexes"]


def test_payment_method_orm_type_matches_portable_migration_contract():
    payment_method_type = Base.metadata.tables["transactions"].c.payment_method.type

    assert payment_method_type.native_enum is False
    assert payment_method_type.length == 20


def test_native_enum_values_match_postgres_migration_contract():
    expected = {
        ("background_jobs", "status"): ["queued", "running", "completed", "failed"],
        ("sync_runs", "status"): ["running", "completed", "failed"],
        ("transactions", "transaction_type"): ["debit", "credit", "refund"],
    }

    for (table_name, column_name), values in expected.items():
        assert Base.metadata.tables[table_name].c[column_name].type.enums == values


def test_money_columns_use_fixed_scale_numeric_storage():
    expected = {
        ("transactions", "amount"),
        ("budgets", "monthly_limit"),
        ("account_balance_snapshots", "amount"),
        ("goals", "target_amount"),
    }

    for table_name, column_name in expected:
        column_type = Base.metadata.tables[table_name].c[column_name].type
        assert column_type.precision == 18
        assert column_type.scale == 2
