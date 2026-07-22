"""Connector-driven ingestion coordinator."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
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
from app.services.ingestion.persistence import persist_source_records
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)
MAX_TRANSIENT_ATTEMPTS = 3


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
        sync_run = SyncRun(user_id=user_id, status=SyncStatus.RUNNING)
        self.db.add(sync_run)
        await self.db.commit()
        await self.db.refresh(sync_run)
        sync_run_id = sync_run.id
        started_at = datetime.now(UTC)

        try:
            account = await self._get_gmail_account(user_id, gmail_account_id)
            await sync_event_manager.broadcast(user_id, "sync_started", {"mode": mode.value})
            await self._audit(user_id, account.id, "sync_started", {"mode": mode.value})
            account.auto_sync_status = "running"
            account.auto_sync_error = None
            account.last_sync_started_at = sync_run.start_time
            await self.db.commit()

            connector = GmailConnector(account)
            batch = await self._fetch_with_retry(connector, user_id, account, mode, max_results)
            if batch.metrics.get("credentials_refreshed"):
                await self._audit(user_id, gmail_account_id, "token_refreshed", {})
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
                },
            )

            persist_stats = await persist_source_records(
                self.db,
                user_id,
                SourceType.GMAIL,
                batch.records,
            )
            persist_stats["emails_fetched"] = int(batch.metrics.get("fetched", len(batch.records)))
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
            account.last_synced_at = now
            account.last_sync_started_at = sync_run.start_time
            account.last_history_id = batch.cursor.history_id
            account.auto_sync_status = "idle"
            account.auto_sync_error = None
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
            await self._handle_failure(sync_run_id, user_id, gmail_account_id, exc)
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
            select(GmailAccount).where(
                GmailAccount.id == gmail_account_id,
                GmailAccount.user_id == user_id,
            )
        )
        if account is not None:
            account.auto_sync_status = (
                "paused" if error_type == ConnectorErrorType.PERMANENT else "error"
            )
            account.auto_sync_error = public_error
            account.last_sync_started_at = sync_run.start_time
        sync_run.status = SyncStatus.FAILED
        sync_run.end_time = datetime.now(UTC)
        sync_run.emails_failed = 1
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
        await domain_event_dispatcher.publish(
            DomainEvent(
                "ConnectorHealthChanged",
                user_id,
                SourceType.GMAIL,
                {
                    "status": account.auto_sync_status if account is not None else "error",
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


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"errors", "classifications"}
        and isinstance(value, str | int | float | bool | type(None) | dict)
    }
