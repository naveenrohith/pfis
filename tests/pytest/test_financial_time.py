"""User-timezone and financial-day-boundary contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from app.services.financial_clock import user_financial_today
from app.utils.financial_time import financial_today

from tests.pytest.helpers import auth_headers, create_user, register_user

ROOT = Path(__file__).resolve().parents[2]


def test_financial_today_uses_the_requested_iana_boundary():
    instant = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)

    assert financial_today("Asia/Kolkata", now_utc=instant) == date(2026, 7, 31)
    assert financial_today("America/Los_Angeles", now_utc=instant) == date(2026, 7, 30)


def test_financial_today_rejects_a_naive_clock():
    with pytest.raises(ValueError, match="timezone-aware"):
        financial_today("UTC", now_utc=datetime(2026, 7, 30, 20, 0))


async def test_stored_user_timezone_controls_the_financial_day(
    client,
    test_session_factory,
):
    kolkata = await create_user(client, "clock-kolkata", timezone="Asia/Kolkata")
    los_angeles = await create_user(
        client,
        "clock-los-angeles",
        timezone="America/Los_Angeles",
    )
    instant = datetime(2026, 7, 30, 20, 0, tzinfo=UTC)

    async with test_session_factory() as db:
        kolkata_day = await user_financial_today(db, kolkata["id"], now_utc=instant)
        los_angeles_day = await user_financial_today(
            db,
            los_angeles["id"],
            now_utc=instant,
        )

    assert kolkata_day == date(2026, 7, 31)
    assert los_angeles_day == date(2026, 7, 30)


async def test_timezone_update_is_validated_and_user_scoped(client):
    owner, owner_token = await register_user(client, "timezone-owner")
    other, _ = await register_user(client, "timezone-other")

    updated = await client.patch(
        f"/api/users/{owner['id']}",
        json={"timezone": "America/New_York"},
        headers=auth_headers(owner_token),
    )
    invalid = await client.patch(
        f"/api/users/{owner['id']}",
        json={"timezone": "Mars/Olympus_Mons"},
        headers=auth_headers(owner_token),
    )
    null_name = await client.patch(
        f"/api/users/{owner['id']}",
        json={"name": None},
        headers=auth_headers(owner_token),
    )
    null_timezone = await client.patch(
        f"/api/users/{owner['id']}",
        json={"timezone": None},
        headers=auth_headers(owner_token),
    )
    forbidden = await client.patch(
        f"/api/users/{other['id']}",
        json={"timezone": "UTC"},
        headers=auth_headers(owner_token),
    )

    updated.raise_for_status()
    assert updated.json()["timezone"] == "America/New_York"
    assert invalid.status_code == 422
    assert null_name.status_code == 422
    assert null_timezone.status_code == 422
    assert forbidden.status_code == 403


def test_financial_services_do_not_use_the_server_local_calendar_day():
    allowed = {ROOT / "backend" / "app" / "services" / "parser" / "patterns.py"}
    offenders = []
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        if path in allowed:
            continue
        if "date.today()" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
