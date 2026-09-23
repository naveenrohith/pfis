"""Connector-driven ingestion coordinator."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import GmailAccount
from app.models.sync import ConnectorAuditEvent, SyncRun, SyncStatus
from app.services.connectors.base import BackfillOptions, ConnectorCursor, ConnectorErrorType
from app.services.connectors.errors import (
    classify_connector_exception,
    public_connector_error,
)
from app.services.connectors.gmail_connector import GmailConnector
from app.services.connectors.source_record import SourceType
from app.services.domain_events import DomainEvent, domain_event_dispatcher
from app.services.financial_change_capture import queue_financial_change
from app.services.ingestion.activity import require_ingestion_user, tracked_user_ingestion
from app.services.ingestion.persistence import persist_source_records
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)
MAX_TRANSIENT_ATTEMPTS = 3
CredentialSnapshot = tuple[str | None, str | None]


class IngestionMode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    CATCH_UP = "catch_up"


class IngestionCoordinator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run_gmail(
        self,
        user_id: str,
        gmail_account_id: str,
        mode: IngestionMode,
        max_results: int | None = 500,
    ) -> dict[str, Any]:
        async with tracked_user_ingestion(self.db, user_id):
            return await self._run_gmail_tracked(user_id, gmail_account_id, mode, max_results)

    async def _run_gmail_tracked(
        self,
        user_id: str,
        gmail_account_id: str,
        mode: IngestionMode,
        max_results: int | None,
    ) -> dict[str, Any]:
        sync_run = SyncRun(user_id=user_id, status=SyncStatus.RUNNING)
        self.db.add(sync_run)
        await self.db.commit()
        await self.db.refresh(sync_run)
        sync_run_id = sync_run.id
        sync_run_start_time = sync_run.start_time
        started_at = datetime.now(UTC)
        credential_snapshot: CredentialSnapshot | None = None
        credential_replaced = False

        try:
            account = await self._get_gmail_account(user_id, gmail_account_id)
            credential_snapshot = (account.access_token_ref, account.refresh_token_ref)
            await sync_event_manager.broadcast(user_id, "sync_started", {"mode": mode.value})
            await self._audit(user_id, account.id, "sync_started", {"mode": mode.value})
            account.auto_sync_status = "running"
            account.auto_sync_error = None
            account.last_sync_started_at = sync_run_start_time
            await self.db.commit()

            connector = GmailConnector(account)
            batch = await self._fetch_with_retry(connector, user_id, account, mode, max_results)
            if batch.metrics.get("credentials_refreshed"):
                refreshed_snapshot = (account.access_token_ref, account.refresh_token_ref)
                refreshed_expiry = account.token_expires_at
                if credential_snapshot is None:
                    raise RuntimeError("Gmail credential refresh did not produce new credentials")

                # GmailConnector updates the in-memory account after a provider
                # refresh. Roll back those ORM mutations before any flush can
                # overwrite a concurrent reconnect, then persist them with the
                # original credential snapshot as the compare-and-set guard.
                await self.db.rollback()
                account = await self._get_gmail_account(user_id, gmail_account_id)
                refreshed_update = (
                    update(GmailAccount)
                    .where(*_credential_conditions(user_id, gmail_account_id, credential_snapshot))
                    .values(
                        access_token_ref=refreshed_snapshot[0],
                        refresh_token_ref=refreshed_snapshot[1],
                        token_expires_at=refreshed_expiry,
                    )
                )
                with self.db.no_autoflush:
                    refreshed_update_result = await self.db.execute(refreshed_update)
                if refreshed_update_result.rowcount == 1:
                    await queue_financial_change(self.db, user_id, {"data"})
                    await self.db.commit()
                    await self.db.refresh(account)
                    credential_snapshot = refreshed_snapshot
                    await self._audit(user_id, gmail_account_id, "token_refreshed", {})
                else:
                    credential_replaced = True
                    await self.db.refresh(account)
                    logger.info("Gmail token refresh skipped after credential replacement")
            await domain_event_dispatcher.publish(
                DomainEvent(
                    "SourceRecordFetched",
                    user_id,
                    SourceType.GMAIL,
                    {"records": len(batch.records), "mode": mode.value},
                )
            )
            await sync_event_manager.broadcast(
                user_id,
                "gmail_checked",
                {
                    "fetched": batch.metrics.get("fetched", len(batch.records)),
                    "fallback": batch.cursor.fallback_used,
                    "coverage_complete": batch.metrics.get("coverage_complete", True),
                    "coverage_truncated": batch.metrics.get("coverage_truncated", False),
                },
            )

            persist_stats = await persist_source_records(
                self.db,
                user_id,
                SourceType.GMAIL,
                batch.records,
            )
            await require_ingestion_user(self.db, user_id)
            persist_stats["emails_fetched"] = int(batch.metrics.get("fetched", len(batch.records)))
            persist_stats["coverage_complete"] = bool(batch.metrics.get("coverage_complete", True))
            persist_stats["coverage_truncated"] = bool(
                batch.metrics.get("coverage_truncated", False)
            )
            persist_stats["coverage_pages"] = int(batch.metrics.get("coverage_pages", 0))
            persist_stats["coverage_result_size_estimate"] = int(
                batch.metrics.get("coverage_result_size_estimate", 0)
            )
            if batch.errors:
                persist_stats["emails_failed"] += len(batch.errors)
                persist_stats["errors"].extend(
                    {
                        "error": connector_error.message,
                        "error_type": connector_error.error_type.value,
                    }
                    for connector_error in batch.errors
                )
            await sync_event_manager.broadcast(
                user_id,
                "emails_stored",
                {
                    "stored": persist_stats["emails_stored"],
                    "duplicates": persist_stats["emails_skipped_duplicate"],
                    "failed": persist_stats["emails_failed"],
                },
            )

            now = datetime.now(UTC)
            if credential_snapshot is None:
                raise RuntimeError("Gmail account credential snapshot unavailable")
            if credential_replaced:
                logger.info("Gmail sync completion skipped after credential replacement")
            else:
                account_update = (
                    update(GmailAccount)
                    .where(*_credential_conditions(user_id, gmail_account_id, credential_snapshot))
                    .values(
                        access_token_ref=account.access_token_ref,
                        refresh_token_ref=account.refresh_token_ref,
                        token_expires_at=account.token_expires_at,
                        last_synced_at=now,
                        last_sync_started_at=sync_run_start_time,
                        last_history_id=batch.cursor.history_id,
                        auto_sync_status="idle",
                        auto_sync_error=None,
                    )
                )
                # A reconnect or another worker may have replaced credentials
                # while Gmail was being fetched. The compare-and-set prevents
                # this stale sync from overwriting the new token or cursor.
                with self.db.no_autoflush:
                    account_update_result = await self.db.execute(account_update)
                if account_update_result.rowcount != 1:
                    logger.info(
                        "Gmail sync completion skipped account update after credential replacement"
                    )
                else:
                    await queue_financial_change(self.db, user_id, {"data"})
                await self.db.refresh(account)
            await domain_event_dispatcher.publish(
                DomainEvent(
                    "ConnectorHealthChanged",
                    user_id,
                    SourceType.GMAIL,
                    {"status": "healthy"},
                )
            )
            sync_run.status = SyncStatus.COMPLETED
            sync_run.end_time = now
            sync_run.emails_fetched = persist_stats["emails_fetched"]
            sync_run.emails_processed = persist_stats["emails_processed"]
            sync_run.emails_failed = persist_stats["emails_failed"]
            sync_run.coverage_complete = bool(persist_stats.get("coverage_complete", True))
            sync_run.coverage_truncated = bool(persist_stats.get("coverage_truncated", False))
            sync_run.coverage_pages = int(persist_stats.get("coverage_pages", 0))
            sync_run.coverage_result_size_estimate = int(
                persist_stats.get("coverage_result_size_estimate", 0)
            )
            sync_run.errors = json.dumps(persist_stats["errors"])
            await self.db.commit()

            stats = {
                **persist_stats,
                "duration_ms": int((now - started_at).total_seconds() * 1000),
                "fallback_used": batch.cursor.fallback_used,
            }
            await self._audit(user_id, gmail_account_id, "sync_completed", stats)
            return stats
        except Exception as exc:
            await self._handle_failure(
                sync_run_id,
                user_id,
                gmail_account_id,
                exc,
                credential_snapshot,
            )
            raise

    async def _fetch_with_retry(
        self,
        connector: GmailConnector,
        user_id: str,
        account: GmailAccount,
        mode: IngestionMode,
        max_results: int | None,
    ):
        attempts = 0
        while True:
            attempts += 1
            try:
                if mode == IngestionMode.INCREMENTAL:
                    return await connector.fetch_incremental(
                        user_id,
                        ConnectorCursor(history_id=account.last_history_id),
                    )
                return await connector.fetch_backfill(
                    user_id, BackfillOptions(max_results=max_results)
                )
            except Exception as exc:
                error_type = classify_connector_exception(exc)
                if error_type == ConnectorErrorType.TRANSIENT and attempts < MAX_TRANSIENT_ATTEMPTS:
                    await asyncio.sleep(0.25 * attempts)
                    continue
                raise

    async def _get_gmail_account(self, user_id: str, gmail_account_id: str) -> GmailAccount:
        result = await self.db.execute(
            select(GmailAccount).where(
                GmailAccount.id == gmail_account_id,
                GmailAccount.user_id == user_id,
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise LookupError("Gmail account not found")
        return account

    async def _handle_failure(
        self,
        sync_run_id: str,
        user_id: str,
        gmail_account_id: str,
        exc: Exception,
        credential_snapshot: CredentialSnapshot | None,
    ) -> None:
        await self.db.rollback()
        error_type = classify_connector_exception(exc)
        public_error = public_connector_error(error_type)
        logger.warning(
            "Gmail sync failed user=%s error_type=%s exception=%s",
            user_id[:8],
            error_type.value,
            type(exc).__name__,
        )
        sync_run = await self.db.scalar(
            select(SyncRun).where(SyncRun.id == sync_run_id, SyncRun.user_id == user_id)
        )
        if sync_run is None:
            logger.error("Gmail sync failure could not find its persisted sync run")
            return
        account = await self.db.scalar(
            select(GmailAccount)
            .where(
                GmailAccount.id == gmail_account_id,
                GmailAccount.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
        account_update_applied = False
        if account is not None and credential_snapshot is not None:
            account_update = (
                update(GmailAccount)
                .where(*_credential_conditions(user_id, gmail_account_id, credential_snapshot))
                .values(
                    auto_sync_status=(
                        "paused" if error_type == ConnectorErrorType.PERMANENT else "error"
                    ),
                    auto_sync_error=public_error,
                    last_sync_started_at=sync_run.start_time,
                )
            )
            with self.db.no_autoflush:
                account_update_result = await self.db.execute(account_update)
            account_update_applied = account_update_result.rowcount == 1
            if account_update_applied:
                await queue_financial_change(self.db, user_id, {"data"})
            await self.db.refresh(account)
        sync_run.status = SyncStatus.FAILED
        sync_run.end_time = datetime.now(UTC)
        sync_run.emails_failed = 1
        sync_run.coverage_complete = False
        sync_run.coverage_truncated = False
        sync_run.errors = json.dumps([{"error": public_error, "error_type": error_type.value}])
        await self.db.commit()
        await self._audit(
            user_id,
            account.id if account is not None else None,
            "sync_failed",
            {"error": public_error, "error_type": error_type.value},
        )
        await domain_event_dispatcher.publish(
            DomainEvent(
                "SyncFailed",
                user_id,
                SourceType.GMAIL,
                {"error_type": error_type.value},
            )
        )
        if account is not None and account_update_applied:
            await domain_event_dispatcher.publish(
                DomainEvent(
                    "ConnectorHealthChanged",
                    user_id,
                    SourceType.GMAIL,
                    {
                        "status": account.auto_sync_status,
                        "error_type": error_type.value,
                    },
                )
            )
        await sync_event_manager.broadcast(
            user_id,
            "sync_failed",
            {"error": public_error, "error_type": error_type.value},
        )

    async def _audit(
        self,
        user_id: str,
        gmail_account_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.db.add(
            ConnectorAuditEvent(
                user_id=user_id,
                connector_type=SourceType.GMAIL.value,
                connector_account_id=gmail_account_id,
                event_type=event_type,
                payload_json=json.dumps(_public_payload(payload)),
            )
        )
        await self.db.commit()


def _credential_conditions(
    user_id: str,
    gmail_account_id: str,
    credential_snapshot: CredentialSnapshot,
) -> list[Any]:
    """Build a compare-and-set predicate for a Gmail account's credentials."""
    access_token_ref, refresh_token_ref = credential_snapshot
    return [
        GmailAccount.id == gmail_account_id,
        GmailAccount.user_id == user_id,
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


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"errors", "classifications"}
        and isinstance(value, str | int | float | bool | type(None) | dict)
    }
