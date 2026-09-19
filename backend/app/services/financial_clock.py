"""User-scoped financial clock backed by the stored IANA timezone."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.utils.financial_time import financial_today


async def get_user_timezone(db: AsyncSession, user_id: str) -> str:
    timezone_name = await db.scalar(select(User.timezone).where(User.id == user_id))
    if timezone_name is None:
        raise LookupError("User not found")
    return timezone_name


async def user_financial_today(
    db: AsyncSession,
    user_id: str,
    *,
    now_utc: datetime | None = None,
) -> date:
    return financial_today(
        await get_user_timezone(db, user_id),
        now_utc=now_utc,
    )
