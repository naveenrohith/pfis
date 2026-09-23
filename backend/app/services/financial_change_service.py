"""Durable change replay, retention, and cross-worker WebSocket relay."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import database as database_module
from app.models.financial_change import FinancialChangeCursor, FinancialChangeEvent
from app.schemas.financial_change import (
    FinancialChangeEventResponse,
    FinancialChangePageResponse,
)
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)

FINANCIAL_CHANGE_RETENTION_DAYS = 90
FINANCIAL_CHANGE_PAGE_LIMIT = 500
FINANCIAL_CHANGE_POLL_INTERVAL_SECONDS = 1.0
FINANCIAL_CHANGE_TAIL_BATCH_SIZE = 250


class FinancialChangeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def changes_after(
        self,
        user_id: str,
        after_sequence: int,
        limit: int = 250,
    ) -> FinancialChangePageResponse:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if not 1 <= limit <= FINANCIAL_CHANGE_PAGE_LIMIT:
            raise ValueError(f"limit must be between 1 and {FINANCIAL_CHANGE_PAGE_LIMIT}")

        cursor = await self.db.get(FinancialChangeCursor, user_id)
        current_sequence = cursor.current_sequence if cursor is not None else 0
        oldest_sequence = await self.db.scalar(
            select(func.min(FinancialChangeEvent.sequence)).where(
                FinancialChangeEvent.user_id == user_id
            )
        )
        reset_required = after_sequence > current_sequence or (
            after_sequence < current_sequence
            and (oldest_sequence is None or after_sequence < int(oldest_sequence) - 1)
        )
        if reset_required:
            return FinancialChangePageResponse(
                events=[],
                current_sequence=current_sequence,
                oldest_available_sequence=(
                    int(oldest_sequence) if oldest_sequence is not None else None
                ),
                has_more=False,
                reset_required=True,
            )

        rows = list(
            (
                await self.db.scalars(
                    select(FinancialChangeEvent)
                    .where(
                        FinancialChangeEvent.user_id == user_id,
                        FinancialChangeEvent.sequence > after_sequence,
                    )
                    .order_by(FinancialChangeEvent.sequence)
                    .limit(limit)
                )
            ).all()
        )
        events = [
            FinancialChangeEventResponse.model_validate(row, from_attributes=True) for row in rows
        ]
        next_sequence = events[-1].sequence if events else after_sequence
        return FinancialChangePageResponse(
            events=events,
            current_sequence=current_sequence,
            oldest_available_sequence=(
                int(oldest_sequence) if oldest_sequence is not None else None
            ),
            has_more=next_sequence < current_sequence,
            reset_required=False,
        )


async def prune_financial_change_events(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Delete replay metadata beyond policy while retaining each user high-water mark."""
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    cutoff = instant.astimezone(UTC) - timedelta(days=FINANCIAL_CHANGE_RETENTION_DAYS)
    result = await db.execute(
        delete(FinancialChangeEvent).where(FinancialChangeEvent.created_at < cutoff)
    )
    return max(int(result.rowcount or 0), 0)


class FinancialChangeTailer:
    """Poll committed journal rows once per worker and relay them to local sockets."""

    def __init__(
        self,
        *,
        poll_interval_seconds: float = FINANCIAL_CHANGE_POLL_INTERVAL_SECONDS,
        batch_size: int = FINANCIAL_CHANGE_TAIL_BATCH_SIZE,
    ):
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self._last_event_id = 0
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        async with database_module.AsyncSessionLocal() as db:
            self._last_event_id = int(
                await db.scalar(select(func.max(FinancialChangeEvent.id))) or 0
            )
        self._task = asyncio.create_task(self._run())
        logger.info("Financial change tailer started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Financial change tailer stopped")

    async def poll_once(self) -> int:
        async with database_module.AsyncSessionLocal() as db:
            rows = list(
                (
                    await db.scalars(
                        select(FinancialChangeEvent)
                        .where(FinancialChangeEvent.id > self._last_event_id)
                        .order_by(FinancialChangeEvent.id)
                        .limit(self.batch_size)
                    )
                ).all()
            )
        for row in rows:
            await sync_event_manager.broadcast(
                row.user_id,
                row.event_type,
                {
                    "event_id": row.event_id,
                    "sequence": row.sequence,
                    "domains": row.domains,
                },
            )
            self._last_event_id = row.id
        return len(rows)

    async def _run(self) -> None:
        while True:
            try:
                delivered = await self.poll_once()
                if not delivered:
                    await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Financial change tailer poll failed")
                await asyncio.sleep(self.poll_interval_seconds)


financial_change_tailer = FinancialChangeTailer()
