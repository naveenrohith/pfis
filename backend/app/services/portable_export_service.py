"""Versioned, privacy-safe portable data export."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import IO, Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from sqlalchemy import Table, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.database import Base
from app.models.user import User

PORTABLE_EXPORT_SCHEMA_VERSION = 16

# Every table containing owned, derived, or shared user-visible data is explicit.
# The inventory test fails when a new model is added without an export decision.
PORTABLE_EXPORT_TABLES = frozenset(
    {
        "anomaly_adjudications",
        "account_balance_snapshots",
        "account_balance_sources",
        "account_link_rules",
        "auth_identities",
        "background_jobs",
        "balance_provider_connections",
        "balance_provider_account_mappings",
        "card_position_observations",
        "budgets",
        "card_calendar_events",
        "card_disputes",
        "card_payment_intents",
        "card_preferences",
        "cash_flow_forecast_outcomes",
        "cash_flow_forecast_snapshots",
        "account_balance_forecast_outcomes",
        "account_balance_forecast_snapshots",
        "account_balance_reconciliations",
        "cash_plans",
        "categories",
        "commitments",
        "connector_audit_events",
        "credit_card_statements",
        "deposit_account_statements",
        "deposit_statement_lines",
        "deposit_statement_line_review_decisions",
        "dashboard_preferences",
        "financial_accounts",
        "gmail_accounts",
        "goals",
        "health_checklist_items",
        "household_expenses",
        "household_members",
        "household_settlements",
        "households",
        "liabilities",
        "liability_schedule_items",
        "monthly_summaries",
        "parse_failures",
        "pipeline_events",
        "raw_emails",
        "recommendation_states",
        "recommendation_outcomes",
        "reserve_plans",
        "roadmap_bills",
        "statement_imports",
        "statement_analysis_reviews",
        "statement_line_matches",
        "statement_line_review_decisions",
        "statement_lines",
        "sync_runs",
        "temporal_event_decisions",
        "temporal_source_snapshots",
        "transaction_splits",
        "transactions",
        "user_corrections",
        "user_merchant_rules",
        "users",
    }
)

PORTABLE_EXPORT_EXCLUDED_TABLES = {
    "auth_sessions": "Session and CSRF hashes are security credentials, not portable records.",
    "oauth_states": "OAuth state, verifier, nonce, and browser-token hashes are transient secrets.",
    "merchants": "The global merchant seed library is product reference data, not user-owned data.",
    "financial_change_cursors": "Operational replay position is metadata, not portable financial data.",
    "financial_change_events": "Operational invalidation hints are metadata, not portable financial data.",
}

PORTABLE_EXPORT_EXCLUDED_COLUMNS = {
    "users": frozenset({"password_hash"}),
    "gmail_accounts": frozenset({"access_token_ref", "refresh_token_ref"}),
    "background_jobs": frozenset({"lease_owner", "lease_expires_at"}),
}

SECRET_COLUMN_NAMES = frozenset(
    {
        "password_hash",
        "token_hash",
        "csrf_token_hash",
        "access_token_ref",
        "refresh_token_ref",
        "browser_token_hash",
        "code_verifier_ref",
        "nonce_ref",
    }
)

_SHARED_HOUSEHOLD_TABLES = frozenset(
    {"households", "household_members", "household_expenses", "household_settlements"}
)
_JSON_TEXT_COLUMNS = frozenset(
    {
        "diagnostic_json",
        "evidence_json",
        "assumptions_json",
        "eligible_transaction_ids_json",
        "excluded_transaction_ids_json",
        "favorites_json",
        "payload_json",
        "points_json",
        "position_reason_codes_json",
        "result_json",
        "reward_rules_json",
        "resolution_json",
        "splits_json",
        "tags_json",
        "widgets_json",
    }
)
_SHARED_USER_COLUMNS = frozenset(
    {
        "owner_user_id",
        "user_id",
        "created_by_user_id",
        "payer_user_id",
        "from_user_id",
        "to_user_id",
    }
)
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass
class PortableExportArtifact:
    filename: str
    stream: IO[bytes]
    size_bytes: int
    manifest: dict[str, Any]


def portable_export_inventory() -> dict[str, str]:
    inventory = dict.fromkeys(PORTABLE_EXPORT_TABLES, "included")
    inventory.update(
        {
            table_name: f"excluded: {reason}"
            for table_name, reason in PORTABLE_EXPORT_EXCLUDED_TABLES.items()
        }
    )
    return inventory


async def build_portable_export(
    db: AsyncSession,
    user_id: str,
    *,
    exported_at: datetime | None = None,
) -> PortableExportArtifact:
    """Build a ZIP with one deterministic JSONL file per export entity."""
    user = await db.get(User, user_id)
    if user is None:
        raise LookupError("User not found")

    instant = exported_at or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)

    aliases = await _shared_household_aliases(db, user_id)
    # Ownership passes to StreamingResponse, whose iterator closes the file.
    stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")  # noqa: SIM115
    archive = ZipFile(stream, mode="w", compression=ZIP_DEFLATED, compresslevel=6)
    entities: list[dict[str, Any]] = []

    try:
        for table_name in sorted(PORTABLE_EXPORT_TABLES):
            table = Base.metadata.tables[table_name]
            rows = await _fetch_rows(db, table, user_id)
            records = [_portable_record(table_name, dict(row), aliases) for row in rows]
            payload = await asyncio.to_thread(_encode_json_lines, records)
            path = f"data/{table_name}.jsonl"
            await asyncio.to_thread(_write_zip_entry, archive, path, payload)
            entities.append(
                {
                    "name": table_name,
                    "path": path,
                    "scope": _table_scope(table_name),
                    "record_count": len(records),
                    "fields": _exported_fields(table),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )

        manifest = {
            "schema_version": PORTABLE_EXPORT_SCHEMA_VERSION,
            "format": "PFIS portable export",
            "exported_at": instant.isoformat().replace("+00:00", "Z"),
            "app_version": get_settings().APP_VERSION,
            "user": {
                "id": user.id,
                "ledger_currency": user.currency,
                "timezone": user.timezone,
            },
            "archive": {
                "entity_format": "newline-delimited JSON (JSONL)",
                "record_count": sum(entity["record_count"] for entity in entities),
                "entity_count": len(entities),
            },
            "entities": entities,
            "privacy": {
                "shared_household_identifiers": (
                    "Other members use stable archive-local aliases; private ledgers are excluded."
                ),
                "excluded_tables": PORTABLE_EXPORT_EXCLUDED_TABLES,
                "excluded_columns": {
                    table_name: sorted(columns)
                    for table_name, columns in PORTABLE_EXPORT_EXCLUDED_COLUMNS.items()
                },
                "credential_material_included": False,
            },
        }
        manifest_payload = await asyncio.to_thread(
            json.dumps,
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        await asyncio.to_thread(
            _write_zip_entry,
            archive,
            "manifest.json",
            f"{manifest_payload}\n".encode(),
        )
    except Exception:
        await asyncio.to_thread(archive.close)
        stream.close()
        raise

    await asyncio.to_thread(archive.close)
    stream.seek(0, 2)
    size_bytes = stream.tell()
    stream.seek(0)
    return PortableExportArtifact(
        filename=f"pfis-portable-export-{instant.date().isoformat()}.zip",
        stream=stream,
        size_bytes=size_bytes,
        manifest=manifest,
    )


async def _fetch_rows(
    db: AsyncSession,
    table: Table,
    user_id: str,
) -> list[Any]:
    predicate = _table_filter(table, user_id)
    primary_key = list(table.primary_key.columns)
    statement = select(table).where(predicate)
    if primary_key:
        statement = statement.order_by(*primary_key)
    result = await db.execute(statement)
    return list(result.mappings().all())


def _table_filter(table: Table, user_id: str) -> ColumnElement[bool]:
    tables = Base.metadata.tables
    household_ids = _household_ids_for_user(user_id)
    if table.name == "users":
        return table.c.id == user_id
    if table.name == "categories":
        return true()
    if table.name in _SHARED_HOUSEHOLD_TABLES:
        if table.name == "households":
            return table.c.id.in_(household_ids)
        return table.c.household_id.in_(household_ids)
    if table.name == "parse_failures":
        owned_email_ids = select(tables["raw_emails"].c.id).where(
            tables["raw_emails"].c.user_id == user_id
        )
        return table.c.email_id.in_(owned_email_ids)
    if table.name == "user_corrections":
        owned_transaction_ids = select(tables["transactions"].c.id).where(
            tables["transactions"].c.user_id == user_id
        )
        return table.c.transaction_id.in_(owned_transaction_ids)
    if "user_id" in table.c:
        return table.c.user_id == user_id
    raise AssertionError(f"Portable export table {table.name} has no ownership filter")


async def _shared_household_aliases(db: AsyncSession, user_id: str) -> dict[str, str]:
    tables = Base.metadata.tables
    household_ids = _household_ids_for_user(user_id)
    member_ids = (
        await db.scalars(
            select(tables["household_members"].c.user_id)
            .where(tables["household_members"].c.household_id.in_(household_ids))
            .distinct()
            .order_by(tables["household_members"].c.user_id)
        )
    ).all()
    aliases = {user_id: user_id}
    other_ids = [member_id for member_id in member_ids if member_id != user_id]
    aliases.update(
        {
            member_id: f"shared-member-{index:03d}"
            for index, member_id in enumerate(other_ids, start=1)
        }
    )
    return aliases


def _household_ids_for_user(user_id: str):
    tables = Base.metadata.tables
    return (
        select(tables["households"].c.id)
        .where(tables["households"].c.owner_user_id == user_id)
        .union(
            select(tables["household_members"].c.household_id).where(
                tables["household_members"].c.user_id == user_id,
                tables["household_members"].c.left_at.is_(None),
            )
        )
    )


def _portable_record(
    table_name: str,
    row: dict[str, Any],
    shared_aliases: dict[str, str],
) -> dict[str, Any]:
    for column in PORTABLE_EXPORT_EXCLUDED_COLUMNS.get(table_name, frozenset()):
        row.pop(column, None)

    for column_name in _JSON_TEXT_COLUMNS:
        value = row.get(column_name)
        if not isinstance(value, str):
            continue
        with suppress(json.JSONDecodeError):
            row[column_name] = json.loads(value)

    if table_name in _SHARED_HOUSEHOLD_TABLES:
        for column_name in _SHARED_USER_COLUMNS:
            value = row.get(column_name)
            if isinstance(value, str):
                row[column_name] = shared_aliases.get(value, "shared-member-unknown")
        splits = row.get("splits_json")
        if isinstance(splits, dict):
            row["splits_json"] = {
                shared_aliases.get(str(member_id), "shared-member-unknown"): amount
                for member_id, amount in sorted(splits.items())
            }

    return {key: _serialize_value(value) for key, value in row.items()}


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_serialize_value(item) for item in value]
    return value


def _encode_json_lines(records: list[dict[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            + b"\n"
        )
        for record in records
    )


def _write_zip_entry(archive: ZipFile, path: str, payload: bytes) -> None:
    info = ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, payload, compress_type=ZIP_DEFLATED, compresslevel=6)


def _exported_fields(table: Table) -> list[str]:
    excluded = PORTABLE_EXPORT_EXCLUDED_COLUMNS.get(table.name, frozenset())
    fields = [column.name for column in table.columns if column.name not in excluded]
    assert not SECRET_COLUMN_NAMES.intersection(fields)
    return fields


def _table_scope(table_name: str) -> str:
    if table_name in _SHARED_HOUSEHOLD_TABLES:
        return "shared_annotations"
    if table_name == "categories":
        return "reference"
    return "owned"
