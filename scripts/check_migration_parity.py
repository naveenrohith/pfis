"""Verify that PFIS developer and E2E PostgreSQL databases share Alembic head."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import normalize_async_database_url  # noqa: E402


def configured_database_url() -> str:
    if value := os.getenv("DATABASE_URL"):
        return value
    env_file = ROOT / "backend" / ".env"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABASE_URL is not configured")


def database_url_for(database_url: str, database_name: str) -> str:
    """Replace only the database component while retaining connection settings."""

    return make_url(database_url).set(database=database_name).render_as_string(hide_password=False)


def repository_head() -> str:
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no current head")
    return head


async def current_revision(database_url: str) -> str | None:
    engine = create_async_engine(normalize_async_database_url(database_url))
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()


async def check_parity(database_names: list[str]) -> dict[str, object]:
    configured_url = configured_database_url()
    head = repository_head()
    revisions = {
        name: await current_revision(database_url_for(configured_url, name))
        for name in database_names
    }
    return {
        "schema_version": "pfis-migration-parity-1",
        "repository_head": head,
        "databases": revisions,
        "status": "passed" if all(value == head for value in revisions.values()) else "failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="append", dest="databases")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    configured_name = make_url(configured_database_url()).database
    database_names = args.databases or [configured_name, "pfis_e2e"]
    report = asyncio.run(check_parity(database_names))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
