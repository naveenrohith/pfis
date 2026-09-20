"""Helper utilities shared by pytest suites."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.security import create_access_token
from app.utils.financial_time import financial_today
from httpx import AsyncClient


async def create_user(
    client: AsyncClient,
    prefix: str = "user",
    *,
    currency: str = "INR",
    timezone: str = "Asia/Kolkata",
) -> dict:
    suffix = uuid.uuid4().hex[:8]
    response = await client.post(
        "/api/users/",
        json={
            "email": f"{prefix}-{suffix}@pfis.local",
            "name": f"{prefix.title()} {suffix}",
            "currency": currency,
            "timezone": timezone,
        },
    )
    response.raise_for_status()
    return response.json()


async def register_user(client: AsyncClient, prefix: str = "auth") -> tuple[dict, str]:
    suffix = uuid.uuid4().hex[:8]
    password = "Sup3rSecure!"
    response = await client.post(
        "/api/auth/register",
        json={
            "email": f"{prefix}-{suffix}@example.com",
            "name": f"{prefix.title()} {suffix}",
            "password": password,
            "currency": "INR",
        },
    )
    response.raise_for_status()
    payload = response.json()
    return payload["user"], create_access_token(payload["user"]["id"])


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def user_today(user: dict, *, now_utc: datetime | None = None) -> date:
    """Return the test user's financial day independently of the host timezone."""
    return financial_today(user["timezone"], now_utc=now_utc or datetime.now(UTC))
