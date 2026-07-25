"""Create a PostgreSQL backup, restore it into a disposable database, and verify it."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

CRITICAL_TABLES = (
    "users",
    "transactions",
    "raw_emails",
    "background_jobs",
    "gmail_accounts",
)


def parse_postgres_url(url: str) -> dict[str, str]:
    normalized = url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgres://", "postgresql://", 1
    )
    parsed = urlsplit(normalized)
    database = unquote(parsed.path.lstrip("/"))
    if parsed.scheme != "postgresql" or not parsed.hostname or not database or "/" in database:
        raise ValueError("A PostgreSQL database URL is required")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "sslmode": query.get("sslmode", ["prefer"])[0],
    }


def connection_identity(connection: Mapping[str, str]) -> tuple[str, str, str]:
    return (
        connection["host"].lower(),
        connection["port"],
        connection["database"].lower(),
    )


def pg_environment(connection: Mapping[str, str]) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": connection["host"],
            "PGPORT": connection["port"],
            "PGUSER": connection["user"],
            "PGPASSWORD": connection["password"],
            "PGDATABASE": connection["database"],
            "PGSSLMODE": connection["sslmode"],
        }
    )
    return environment


def async_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


async def snapshot(url: str) -> dict:
    engine = create_async_engine(async_url(url))
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            counts = {}
            for table in CRITICAL_TABLES:
                counts[table] = int(
                    await connection.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0
                )
            return {"alembic_revision": revision, "row_counts": counts}
    finally:
        await engine.dispose()


def collect_snapshot(url: str, label: str) -> dict:
    """Inspect a database without exposing its connection URL on failure."""
    try:
        return asyncio.run(snapshot(url))
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Could not inspect {label} database") from exc


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise ValueError(f"Required PostgreSQL tool is not installed: {name}")
    return path


def run_drill(args: argparse.Namespace) -> dict:
    source = parse_postgres_url(args.source_url)
    restore = parse_postgres_url(args.restore_url)
    if connection_identity(source) == connection_identity(restore):
        raise ValueError("Restore target must not be the source database")
    if args.confirm_restore_database != restore["database"]:
        raise ValueError("Confirmation must exactly match the disposable restore database name")

    pg_dump = require_tool("pg_dump")
    pg_restore = require_tool("pg_restore")
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    backup_path = args.artifact_dir / "pfis-restore-drill.dump"
    source_snapshot_before = collect_snapshot(args.source_url, "source")
    subprocess.run(
        [pg_dump, "--format=custom", "--no-owner", "--no-privileges", f"--file={backup_path}"],
        env=pg_environment(source),
        check=True,
    )
    source_snapshot_after = collect_snapshot(args.source_url, "source")
    if source_snapshot_before != source_snapshot_after:
        raise RuntimeError(
            "Source schema revision or critical row counts changed during backup; "
            "retry during a quiescent window"
        )
    subprocess.run(
        [
            pg_restore,
            "--clean",
            "--if-exists",
            "--single-transaction",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            str(backup_path),
        ],
        env=pg_environment(restore),
        check=True,
    )
    restored_snapshot = collect_snapshot(args.restore_url, "restored")
    if source_snapshot_after != restored_snapshot:
        raise RuntimeError("Restored schema revision or critical row counts do not match source")

    return {
        "status": "passed",
        "completed_at": datetime.now(UTC).isoformat(),
        "source_database": source["database"],
        "restore_database": restore["database"],
        "backup_artifact": str(backup_path),
        **restored_snapshot,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--restore-url", required=True)
    parser.add_argument("--confirm-restore-database", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("restore-evidence.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_drill(args)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Restore drill failed: {exc}") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Restore drill passed; evidence written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
