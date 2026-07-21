"""Database behavior that must be consistent in local and production runtimes."""

from __future__ import annotations

import pytest
from app.models.sync import Budget
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.mark.asyncio
async def test_sqlite_test_runtime_enforces_foreign_keys(test_session_factory):
    async with test_session_factory() as session:
        session.add(
            Budget(
                user_id="missing-user",
                category_id="missing-category",
                monthly_limit=100,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        enabled = await session.scalar(text("PRAGMA foreign_keys"))

    assert enabled == 1
