"""Automatic Gmail sync scheduler."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.email import GmailAccount
from app.services.connectors.base import ConnectorErrorType
from app.services.connectors.errors import classify_connector_exception
from app.services.gmail.sync_service import sync_gmail_emails_incremental
from app.services.parser.pipeline import process_raw_emails
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_running_account_ids: set[str] = set()
_poll_interval_seconds = 30
_error_cooldown_seconds = 900


def get_running_auto_sync_count() -> int:
    return len(_running_account_ids)


def start_auto_sync_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        return
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    logger.info("Auto-sync scheduler started")


async def stop_auto_sync_scheduler() -> None:
    global _scheduler_task
    if not _scheduler_task:
        return
    _scheduler_task.cancel()
    with suppress(asyncio.CancelledError):
        await _scheduler_task
    _scheduler_task = None
    logger.info("Auto-sync scheduler stopped")


async def run_due_auto_syncs_once() -> int:
    """Run currently due accounts once. Useful for tests and the scheduler loop."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(GmailAccount).where(GmailAccount.auto_sync_enabled.is_(True))
        )
        accounts = result.scalars().all()

    due_accounts = [account for account in accounts if _is_due(account)]
    for account in due_accounts:
        if account.id in _running_account_ids:
            continue
        _schedule_account_sync(account.id)

    return len(due_accounts)


def _schedule_account_sync(gmail_account_id: str) -> asyncio.Task:
    return asyncio.create_task(_run_account_sync(gmail_account_id))


def _is_due(account: GmailAccount) -> bool:
    if account.auto_sync_status == "running":
        return False
    if account.auto_sync_status == "paused":
        return False
    if account.auto_sync_status == "error":
        last_attempt = account.last_sync_started_at or account.last_synced_at
        if last_attempt is None:
            return True
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=UTC)
        cooldown = max(account.auto_sync_interval_seconds or 300, _error_cooldown_seconds)
        return datetime.now(UTC) - last_attempt >= timedelta(seconds=cooldown)
    if account.last_synced_at is None:
        return True

    last_synced = account.last_synced_at
    if last_synced.tzinfo is None:
        last_synced = last_synced.replace(tzinfo=UTC)
    interval = max(account.auto_sync_interval_seconds or 300, 60)
    return datetime.now(UTC) - last_synced >= timedelta(seconds=interval)


async def _scheduler_loop() -> None:
    while True:
        try:
            await run_due_auto_syncs_once()
        except Exception:
            logger.exception("Auto-sync scheduler tick failed")
        await asyncio.sleep(_poll_interval_seconds)


async def _run_account_sync(gmail_account_id: str) -> None:
    if gmail_account_id in _running_account_ids:
        return
    _running_account_ids.add(gmail_account_id)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GmailAccount).where(GmailAccount.id == gmail_account_id)
            )
            account = result.scalar_one_or_none()
            if account is None or not account.auto_sync_enabled:
                return
            user_id = account.user_id

        async with AsyncSessionLocal() as sync_db:
            sync_stats = await sync_gmail_emails_incremental(sync_db, user_id, gmail_account_id)

        await sync_event_manager.broadcast(user_id, "pipeline_started", {})
        async with AsyncSessionLocal() as pipeline_db:
            pipeline_stats = await process_raw_emails(pipeline_db, user_id, limit=500)

        await sync_event_manager.broadcast(
            user_id,
            "transactions_updated",
            {
                "stored": pipeline_stats.get("stored", 0),
                "duplicates": pipeline_stats.get("duplicates", 0),
                "parsed_success": pipeline_stats.get("parsed_success", 0),
            },
        )
        await sync_event_manager.broadcast(
            user_id,
            "sync_completed",
            {
                "sync": _public_sync_stats(sync_stats),
                "pipeline": _public_sync_stats(pipeline_stats),
            },
        )
    except Exception as exc:
        error_type = classify_connector_exception(exc)
        if error_type == ConnectorErrorType.TRANSIENT:
            logger.warning(
                "Automatic sync transient failure for Gmail account %s: %s",
                gmail_account_id,
                exc,
            )
        else:
            logger.exception("Automatic sync failed for Gmail account %s", gmail_account_id)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GmailAccount).where(GmailAccount.id == gmail_account_id)
            )
            account = result.scalar_one_or_none()
            if account:
                account.auto_sync_status = (
                    "paused" if error_type == ConnectorErrorType.PERMANENT else "error"
                )
                account.auto_sync_error = str(exc)
                account.last_sync_started_at = datetime.now(UTC)
                await db.commit()
                await sync_event_manager.broadcast(
                    account.user_id,
                    "sync_failed",
                    {"error": str(exc), "error_type": error_type.value},
                )
    finally:
        _running_account_ids.discard(gmail_account_id)


def _public_sync_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in stats.items()
        if key not in {"errors", "classifications"}
        and isinstance(value, str | int | float | bool | type(None))
    }
