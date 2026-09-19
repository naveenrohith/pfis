"""Durable scheduler for evidence-safe raw-email retention."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from app.database import AsyncSessionLocal
from app.services.job_service import create_job, schedule_job
from app.services.retention_service import RAW_EMAIL_RETENTION_POLICY_VERSION

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_initial_delay_seconds = 60
_poll_interval_seconds = 6 * 60 * 60


def start_retention_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        return
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    logger.info("Raw-email retention scheduler started")


async def stop_retention_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None:
        return
    _scheduler_task.cancel()
    with suppress(asyncio.CancelledError):
        await _scheduler_task
    _scheduler_task = None
    logger.info("Raw-email retention scheduler stopped")


async def enqueue_retention_sweep(*, user_id: str | None = None) -> str:
    """Enqueue one durable sweep, deduplicated daily for system-wide runs."""
    now = datetime.now(UTC)
    idempotency_key = None
    if user_id is None:
        idempotency_key = (
            f"retention-v{RAW_EMAIL_RETENTION_POLICY_VERSION}:{now.date().isoformat()}"
        )
    async with AsyncSessionLocal() as db:
        job = await create_job(
            db,
            "raw_email_retention",
            user_id,
            payload={"batch_size": 500},
            idempotency_key=idempotency_key,
        )
    schedule_job(job.id)
    return job.id


async def _scheduler_loop() -> None:
    await asyncio.sleep(_initial_delay_seconds)
    while True:
        try:
            await enqueue_retention_sweep()
        except Exception:
            logger.exception("Raw-email retention scheduler tick failed")
        await asyncio.sleep(_poll_interval_seconds)
