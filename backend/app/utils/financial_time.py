"""Validated IANA timezones and deterministic financial-day boundaries."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_USER_TIMEZONE = "Asia/Kolkata"


def validate_timezone_name(value: str) -> str:
    """Normalize and validate an IANA timezone name."""
    candidate = value.strip()
    if not candidate:
        raise ValueError("Timezone is required")
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Timezone must be a valid IANA timezone") from exc
    return candidate


def financial_today(
    timezone_name: str,
    *,
    now_utc: datetime | None = None,
) -> date:
    """Return the calendar day at the user's financial boundary."""
    instant = now_utc or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Financial clock input must be timezone-aware")
    return instant.astimezone(ZoneInfo(timezone_name)).date()
