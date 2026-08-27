"""Track live ingestion so account erasure can establish a hard write fence."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

_active_user_ingestions: dict[str, set[asyncio.Task]] = {}


class UserUnavailableError(RuntimeError):
    """Raised when ingestion targets an inactive or deleting user."""


@asynccontextmanager
async def tracked_user_ingestion(
    db: AsyncSession,
    user_id: str,
) -> AsyncIterator[None]:
    """Register before checking the fence, closing the deletion/start race."""
    task = asyncio.current_task()
    if task is not None:
        _active_user_ingestions.setdefault(user_id, set()).add(task)
    try:
        await require_ingestion_user(db, user_id)
        yield
    finally:
        if task is not None:
            tasks = _active_user_ingestions.get(user_id)
            if tasks is not None:
                tasks.discard(task)
                if not tasks:
                    _active_user_ingestions.pop(user_id, None)


async def require_ingestion_user(db: AsyncSession, user_id: str) -> None:
    available = await db.scalar(
        select(User.id).where(
            User.id == user_id,
            User.is_active.is_(True),
            User.deletion_started_at.is_(None),
        )
    )
    if available is None:
        raise UserUnavailableError("User is unavailable for ingestion")


async def stop_user_ingestions(user_id: str) -> int:
    """Cancel every registered ingestion before destructive account erasure."""
    current = asyncio.current_task()
    tasks = [
        task
        for task in _active_user_ingestions.get(user_id, set())
        if task is not current and not task.done()
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    return len(tasks)
