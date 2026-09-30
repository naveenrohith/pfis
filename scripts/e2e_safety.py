"""Fail-closed guards shared by the PFIS E2E runner and fixture CLI."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

E2E_DATABASE_PREFIX = "pfis_e2e_"
_RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class E2EGuardError(ValueError):
    """Raised when an E2E operation cannot prove it targets its own database."""


def validate_run_id(run_id: str) -> str:
    """Require a 12-character lowercase hexadecimal run identity."""
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise E2EGuardError("E2E run ID must be exactly 12 lowercase hexadecimal characters")
    return run_id


def e2e_database_name(run_id: str) -> str:
    """Build the only database name owned by one harness run."""
    return f"{E2E_DATABASE_PREFIX}{validate_run_id(run_id)}"


def parse_postgres_target(url: str, *, expected_database: str | None = None) -> tuple[str, str]:
    """Return a decoded loopback hostname and database name from a PostgreSQL URL."""
    if not url:
        raise E2EGuardError("A PostgreSQL URL is required")
    normalized = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if normalized.startswith("postgres://"):
        normalized = normalized.replace("postgres://", "postgresql://", 1)
    parsed = urlsplit(normalized)
    if parsed.scheme != "postgresql" or not parsed.hostname:
        raise E2EGuardError("A PostgreSQL URL with an explicit loopback host is required")
    host = parsed.hostname.lower()
    if host not in _LOOPBACK_HOSTS:
        raise E2EGuardError("E2E database connections are restricted to loopback hosts")
    database = unquote(parsed.path.lstrip("/"))
    if not database or "/" in database:
        raise E2EGuardError("The PostgreSQL URL must identify exactly one database")
    if expected_database is not None and database != expected_database:
        raise E2EGuardError("PostgreSQL URL database does not match the confirmed E2E database")
    return host, database


def validate_fixture_write(
    *,
    env: dict[str, str],
    database_url: str,
    database_name: str,
    run_id: str,
    database_comment: str | None,
) -> None:
    """Authorize fixture writes only after all independent target checks agree."""
    expected_database = e2e_database_name(run_id)
    if database_name != expected_database:
        raise E2EGuardError("Fixture database name does not match the E2E run ID")
    if env.get("PFIS_E2E") != "1":
        raise E2EGuardError("Fixture writes require PFIS_E2E=1")
    if env.get("PFIS_E2E_RUN_ID") != run_id:
        raise E2EGuardError("Fixture run ID does not match PFIS_E2E_RUN_ID")
    if env.get("PFIS_E2E_CONFIRM_DATABASE") != expected_database:
        raise E2EGuardError("Fixture writes require exact disposable database confirmation")
    parse_postgres_target(database_url, expected_database=expected_database)
    expected_comment = f"pfis-e2e-run:{run_id}"
    if database_comment != expected_comment:
        raise E2EGuardError("PostgreSQL database marker does not match this E2E run")


def quote_identifier(value: str) -> str:
    """Quote identifiers after requiring a restrictive SQL identifier alphabet."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise E2EGuardError("Unsafe PostgreSQL identifier")
    return f'"{value}"'


def quote_literal(value: str) -> str:
    """Quote SQL text values for generated one-off administrative statements."""
    return "'" + value.replace("'", "''") + "'"
