"""Automatic Gmail sync scheduler."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.email import GmailAccount
from app.services.connectors.base import ConnectorErrorType
from app.services.connectors.errors import classify_connector_exception, public_connector_error
from app.services.gmail.sync_service import sync_gmail_emails_incremental
from app.services.parser.pipeline import process_raw_emails
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_running_account_ids: set[str] = set()
_account_tasks: dict[str, asyncio.Task] = {}
_poll_interval_seconds = 30
_error_cooldown_seconds = 900
CredentialSnapshot = tuple[str | None, str | None]


def get_running_auto_sync_count() -> int:
    return len(_running_account_ids)


async def stop_auto_sync_for_account(
    gmail_account_id: str,
) -> bool:
    """Cancel one live auto-sync before connector/account deletion."""
    task = _account_tasks.get(gmail_account_id)
    if task is None or task.done() or task is asyncio.current_task():
        return False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return True


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
    task = asyncio.create_task(_run_account_sync(gmail_account_id))
    _account_tasks[gmail_account_id] = task

    def cleanup(completed: asyncio.Task) -> None:
        if _account_tasks.get(gmail_account_id) is completed:
            _account_tasks.pop(gmail_account_id, None)

    task.add_done_callback(cleanup)
    return task


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

    credential_snapshot: CredentialSnapshot | None = None
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GmailAccount).where(GmailAccount.id == gmail_account_id)
            )
            account = result.scalar_one_or_none()
            if account is None or not account.auto_sync_enabled:
                return
            user_id = account.user_id
            credential_snapshot = (account.access_token_ref, account.refresh_token_ref)

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
        public_error = public_connector_error(error_type)
        logger.warning(
            "Automatic sync failed for Gmail account %s error_type=%s exception=%s",
            gmail_account_id,
            error_type.value,
            type(exc).__name__,
        )
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GmailAccount).where(GmailAccount.id == gmail_account_id)
            )
            account = result.scalar_one_or_none()
            account_update_applied = False
            if account and credential_snapshot is not None:
                account_update = (
                    update(GmailAccount)
                    .where(
                        GmailAccount.id == gmail_account_id,
                        GmailAccount.user_id == account.user_id,
                        *_credential_conditions(credential_snapshot),
                    )
                    .values(
                        auto_sync_status=(
                            "paused" if error_type == ConnectorErrorType.PERMANENT else "error"
                        ),
                        auto_sync_error=public_error,
                        last_sync_started_at=datetime.now(UTC),
                    )
                )
                with db.no_autoflush:
                    account_update_result = await db.execute(account_update)
                account_update_applied = account_update_result.rowcount == 1
                await db.commit()
            if account and account_update_applied:
                await sync_event_manager.broadcast(
                    account.user_id,
                    "sync_failed",
                    {"error": public_error, "error_type": error_type.value},
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


def _credential_conditions(credential_snapshot: CredentialSnapshot) -> list[Any]:
    access_token_ref, refresh_token_ref = credential_snapshot
    return [
        GmailAccount.auto_sync_status != "disconnecting",
        (
            GmailAccount.access_token_ref.is_(None)
            if access_token_ref is None
            else GmailAccount.access_token_ref == access_token_ref
        ),
        (
            GmailAccount.refresh_token_ref.is_(None)
            if refresh_token_ref is None
            else GmailAccount.refresh_token_ref == refresh_token_ref
        ),
    ]
