"""Helper utilities shared by pytest suites."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def create_user(client: AsyncClient, prefix: str = "user") -> dict:
    suffix = uuid.uuid4().hex[:8]
    response = await client.post(
        "/api/users/",
        json={
            "email": f"{prefix}-{suffix}@pfis.local",
            "name": f"{prefix.title()} {suffix}",
            "currency": "INR",
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
    return payload["user"], payload["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}