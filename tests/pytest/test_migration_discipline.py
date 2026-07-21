"""Migration discipline tests for the PFIS persistence layer."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.config import get_settings
from app.database import Base
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[2]


def test_alembic_revision_ids_fit_portable_version_column():
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    assert all(len(revision.revision) <= 32 for revision in scripts.walk_revisions())


def test_migrations_use_portable_boolean_server_defaults():
    """PostgreSQL rejects integer defaults on BOOLEAN columns."""
    migration_dir = ROOT / "backend" / "alembic" / "versions"
    source = "\n".join(path.read_text(encoding="utf-8") for path in migration_dir.glob("*.py"))

    assert 'server_default=sa.text("1")' not in source
    assert 'server_default=sa.text("0")' not in source


def test_alembic_baseline_matches_orm_table_columns(tmp_path, monkeypatch):
    """Alembic-created schema must match the ORM table/column contract.

    Tests use ``Base.metadata.create_all`` for speed, but production/shared
    environments use Alembic. This test catches model changes that forget to
    update migrations.
    """
    db_path = tmp_path / "pfis-alembic.db"
    async_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    sync_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", async_url)
    get_settings.cache_clear()

    alembic_cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", async_url)

    try:
        command.upgrade(alembic_cfg, "head")

        engine = create_engine(sync_url)
        try:
            inspector = inspect(engine)
            migrated_columns = {
                table_name: {column["name"] for column in inspector.get_columns(table_name)}
                for table_name in inspector.get_table_names()
                if table_name != "alembic_version"
            }
            merchant_rule_unique_names = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("user_merchant_rules")
            }
            merchant_rule_index_names = {
                index["name"] for index in inspector.get_indexes("user_merchant_rules")
            }
            budget_unique_names = {
                constraint["name"] for constraint in inspector.get_unique_constraints("budgets")
            }
            gmail_unique_names = {
                constraint["name"]
                for constraint in inspector.get_unique_constraints("gmail_accounts")
            }
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

    orm_columns = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }

    assert migrated_columns == orm_columns
    assert "uq_user_merchant_rule_descriptor" in merchant_rule_unique_names
    assert {
        "ix_user_merchant_rules_user_id",
        "ix_user_merchant_rules_user_name",
    } <= merchant_rule_index_names
    assert "uq_budgets_user_category" in budget_unique_names
    assert {
        "uq_gmail_accounts_user",
        "uq_gmail_accounts_google_account",
    } <= gmail_unique_names


def test_merchant_migration_repairs_local_create_all_partial_schema(tmp_path, monkeypatch):
    """Migration 013 must repair a hot-reloaded local database.

    A running development server can see the new ORM model before Alembic is
    rerun. ``create_all`` then creates ``user_merchant_rules`` but cannot add
    the new columns to the existing transactions table. The migration must
    tolerate and complete that partial state without deleting local data.
    """
    db_path = tmp_path / "pfis-partial-merchant-schema.db"
    async_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    sync_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", async_url)
    get_settings.cache_clear()
    alembic_cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", async_url)

    try:
        command.upgrade(alembic_cfg, "012_financial_rhythm")
        engine = create_engine(sync_url)
        try:
            Base.metadata.create_all(engine)
            inspector = inspect(engine)
            assert "user_merchant_rules" in inspector.get_table_names()
            assert "merchant_resolution_source" not in {
                column["name"] for column in inspector.get_columns("transactions")
            }
        finally:
            engine.dispose()

        command.upgrade(alembic_cfg, "head")
        engine = create_engine(sync_url)
        try:
            inspector = inspect(engine)
            transaction_columns = {
                column["name"] for column in inspector.get_columns("transactions")
            }
            with engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

    assert revision == "015_financial_integrity"
    assert {
        "merchant_resolution_source",
        "merchant_resolution_confidence",
        "merchant_rule_id",
        "merchant_resolver_version",
    } <= transaction_columns


def test_operational_composite_indexes_are_migrated(tmp_path, monkeypatch):
    """Ingestion and sync history keep the report-backed query paths indexed."""
    db_path = tmp_path / "pfis-operational-indexes.db"
    async_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    sync_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", async_url)
    get_settings.cache_clear()

    alembic_cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", async_url)

    try:
        command.upgrade(alembic_cfg, "head")
        engine = create_engine(sync_url)
        try:
            inspector = inspect(engine)
            index_names = {
                index["name"]
                for table_name in ("raw_emails", "sync_runs")
                for index in inspector.get_indexes(table_name)
            }
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

    assert "ix_raw_emails_user_received" in index_names
    assert "ix_sync_runs_user_started" in index_names


def test_payment_method_orm_type_matches_portable_migration_contract():
    """Keep the ORM compatible with the VARCHAR column in migration 006."""
    payment_method_type = Base.metadata.tables["transactions"].c.payment_method.type

    assert payment_method_type.native_enum is False
    assert payment_method_type.length == 20


def test_money_columns_use_fixed_scale_numeric_storage():
    """Ledger values must never use binary floating-point persistence."""
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


def test_financial_account_backfill_supports_existing_non_null_created_at(tmp_path, monkeypatch):
    """Migration 009 must backfill databases previously initialized from ORM metadata."""
    db_path = tmp_path / "pfis-existing-account-table.db"
    async_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    sync_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", async_url)
    get_settings.cache_clear()
    alembic_cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", async_url)

    try:
        command.upgrade(alembic_cfg, "008_operational_indexes")
        engine = create_engine(sync_url)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        CREATE TABLE financial_accounts (
                            id VARCHAR(36) PRIMARY KEY,
                            user_id VARCHAR(36) NOT NULL,
                            institution_name VARCHAR(160) NOT NULL,
                            account_type VARCHAR(40) NOT NULL,
                            masked_number VARCHAR(32) NOT NULL,
                            currency VARCHAR(3) NOT NULL,
                            connector_account_id VARCHAR(36),
                            is_active BOOLEAN NOT NULL,
                            created_at DATETIME NOT NULL,
                            CONSTRAINT uq_financial_accounts_user_masked UNIQUE (user_id, masked_number),
                            FOREIGN KEY(user_id) REFERENCES users (id)
                        )
                        """
                    )
                )
                connection.execute(
                    text("CREATE TABLE _alembic_tmp_transactions (id VARCHAR(36) PRIMARY KEY)")
                )
                connection.execute(
                    text(
                        "INSERT INTO users (id, email, name, currency, is_active) "
                        "VALUES ('migration-user', 'migration@example.com', 'Migration User', 'INR', 1)"
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO transactions
                        (id, user_id, amount, currency, transaction_type, transaction_date,
                         account_last4, confidence_score, parser_version, reviewed_flag, payment_method,
                         transaction_status)
                        VALUES
                        ('migration-transaction', 'migration-user', 100, 'INR', 'debit', '2026-07-01',
                         '1234', 0.9, 1, 1, 'other', 'completed')
                        """
                    )
                )
        finally:
            engine.dispose()

        command.upgrade(alembic_cfg, "head")
        engine = create_engine(sync_url)
        try:
            with engine.connect() as connection:
                account = connection.execute(
                    text(
                        "SELECT id, created_at FROM financial_accounts "
                        "WHERE user_id = 'migration-user' AND masked_number = '****1234'"
                    )
                ).one()
                linked_account_id = connection.execute(
                    text(
                        "SELECT financial_account_id FROM transactions "
                        "WHERE id = 'migration-transaction'"
                    )
                ).scalar_one()
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

    assert account.created_at is not None
    assert linked_account_id == account.id
