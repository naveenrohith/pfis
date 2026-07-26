"""One-time, verified migration from the legacy PFIS SQLite database to PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import Enum, MetaData, Table, create_engine, func, insert, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_SOURCE = BACKEND / "pfis.db"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy the legacy PFIS SQLite data into an empty, Alembic-migrated "
            "PostgreSQL database."
        )
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--target-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL URL. Prefer DATABASE_URL so credentials do not enter shell history.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the migration. Without this flag, only source data is inventoried.",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args()


def sqlite_read_only_url(source: Path) -> str:
    resolved = source.resolve()
    return f"sqlite:///file:{resolved.as_posix()}?mode=ro&uri=true"


def source_inventory(source: Path) -> dict[str, int]:
    engine = create_engine(sqlite_read_only_url(source))
    metadata = MetaData()
    try:
        metadata.reflect(bind=engine)
        with engine.connect() as connection:
            return {
                table.name: int(connection.scalar(select(func.count()).select_from(table)) or 0)
                for table in metadata.sorted_tables
                if table.name != "alembic_version"
            }
    finally:
        engine.dispose()


def require_postgres_url(target_url: str | None) -> str:
    if not target_url:
        raise SystemExit("DATABASE_URL is not set. Set it securely, then rerun with --apply.")
    if target_url.startswith("postgres://"):
        return target_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if target_url.startswith("postgresql://"):
        return target_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if target_url.startswith("postgresql+asyncpg://"):
        return target_url
    raise SystemExit("The migration target must be PostgreSQL.")


def normalize_legacy_row(row: dict, target_table: Table) -> dict:
    """Translate SQLite enum member names to PostgreSQL enum values."""
    normalized = dict(row)
    for column in target_table.columns:
        value = normalized.get(column.name)
        if not isinstance(column.type, Enum) or not isinstance(value, str):
            continue
        if value in column.type.enums:
            continue
        matches = [
            candidate for candidate in column.type.enums if candidate.casefold() == value.casefold()
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Unsupported enum value {value!r} for " f"{target_table.name}.{column.name}"
            )
        normalized[column.name] = matches[0]
    return normalized


def copy_rows(
    target_connection: Connection,
    source_url: str,
    batch_size: int,
) -> dict[str, int]:
    """Copy application tables inside the caller's PostgreSQL transaction."""
    import app.models  # noqa: F401
    from app.database import Base

    if not Base.metadata.tables:
        raise RuntimeError("PFIS ORM metadata is empty; application models were not registered")

    source_engine = create_engine(source_url)
    source_metadata = MetaData()
    migrated: dict[str, int] = {}
    try:
        source_metadata.reflect(bind=source_engine)
        with source_engine.connect() as source_connection:
            for target_table in Base.metadata.sorted_tables:
                source_table = source_metadata.tables.get(target_table.name)
                if source_table is None:
                    raise RuntimeError(f"Legacy database is missing table {target_table.name!r}")

                target_count = int(
                    target_connection.scalar(select(func.count()).select_from(target_table)) or 0
                )
                if target_count:
                    raise RuntimeError(
                        f"Target table {target_table.name!r} is not empty ({target_count} rows)"
                    )

                shared_columns = [
                    column.name for column in target_table.columns if column.name in source_table.c
                ]
                required_missing = [
                    column.name
                    for column in target_table.columns
                    if column.name not in source_table.c
                    and not column.nullable
                    and column.default is None
                    and column.server_default is None
                ]
                if required_missing:
                    raise RuntimeError(
                        f"Legacy table {target_table.name!r} lacks required columns: "
                        + ", ".join(required_missing)
                    )

                result = source_connection.execute(
                    select(*(source_table.c[name] for name in shared_columns))
                )
                copied = 0
                while batch := result.mappings().fetchmany(batch_size):
                    target_connection.execute(
                        insert(target_table),
                        [normalize_legacy_row(dict(row), target_table) for row in batch],
                    )
                    copied += len(batch)

                actual = int(
                    target_connection.scalar(select(func.count()).select_from(target_table)) or 0
                )
                if actual != copied:
                    raise RuntimeError(
                        f"Verification failed for {target_table.name!r}: "
                        f"copied {copied}, found {actual}"
                    )
                migrated[target_table.name] = copied
    finally:
        source_engine.dispose()
    return migrated


async def migrate(source: Path, target_url: str, batch_size: int) -> dict[str, int]:
    if batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    target_engine = create_async_engine(target_url, pool_pre_ping=True)
    try:
        async with target_engine.begin() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "017_gmail_token_expiry":
                raise RuntimeError(
                    "Target schema is not at the expected Alembic head "
                    f"(found {revision!r}, expected '017_gmail_token_expiry')"
                )
            migrated = await connection.run_sync(
                lambda sync_connection: copy_rows(
                    sync_connection,
                    sqlite_read_only_url(source),
                    batch_size,
                )
            )
            expected = source_inventory(source)
            if migrated != expected:
                raise RuntimeError(
                    "Final migration inventory does not match the legacy source; "
                    "the PostgreSQL transaction was rolled back"
                )
            return migrated
    finally:
        await target_engine.dispose()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    if not source.is_file():
        raise SystemExit(f"Legacy SQLite database not found: {source}")

    inventory = source_inventory(source)
    print(f"Legacy source: {source}")
    print(f"Application rows: {sum(inventory.values())}")
    for table, count in inventory.items():
        print(f"  {table}: {count}")

    if not args.apply:
        print("Dry run only. Set DATABASE_URL and pass --apply to migrate.")
        return 0

    migrated = asyncio.run(migrate(source, require_postgres_url(args.target_url), args.batch_size))
    print(f"Migration committed successfully: {sum(migrated.values())} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
