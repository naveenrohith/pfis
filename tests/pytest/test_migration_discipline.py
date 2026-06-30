"""Migration discipline tests for the PFIS persistence layer."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.database import Base
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[2]


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
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

    orm_columns = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }

    assert migrated_columns == orm_columns
