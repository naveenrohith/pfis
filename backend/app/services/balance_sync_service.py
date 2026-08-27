"""Provider-neutral orchestration for connected balance refreshes.

This module deliberately stops at the connector boundary.  A bank or Account
Aggregator adapter supplies observations; the coordinator owns account
authorization, cursor recovery, source-health failure state, and audit events.
No provider credentials or payment operations are implemented here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSource, FinancialAccount
from app.models.sync import ConnectorAuditEvent
from app.services.balance_observation_service import BalanceObservationService
from app.services.balance_provider_mapping_service import BalanceProviderMappingService
from app.services.card_position_observation_service import CardPositionObservationService
from app.services.connectors.base import BalanceConnector, BalanceObservationBatch, ConnectorCursor
from app.services.connectors.errors import classify_connector_exception, public_connector_error


@dataclass(frozen=True)
class BalanceSyncResult:
    source_type: str
    financial_account_ids: list[str]
    observations_ingested: int
    card_observations_ingested: int
    coverage_complete: bool
    error_types: list[str]
    cursor_advanced: bool


class BalanceSyncService:
    """Run one read-only connector refresh for mapped financial accounts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def run(
        self,
        user_id: str,
        connector: BalanceConnector,
        account_ids: list[str],
        *,
        cursor: ConnectorCursor | None = None,
        provider_type: str | None = None,
    ) -> BalanceSyncResult:
        accounts = await self._owned_accounts(user_id, account_ids)
        if len(accounts) != len(set(account_ids)):
            raise LookupError("One or more financial accounts were not found")
        provider_account_ids = await self._provider_account_ids(
            user_id,
            accounts,
            provider_type,
        )
        unmapped = [account.id for account in accounts if not provider_account_ids.get(account.id)]
        if unmapped:
            raise ValueError("Map every financial account to its provider account before syncing")

        source_type = str(getattr(connector, "source_type", "connector"))[:50]
        starting_cursor = cursor or await self._resume_cursor(
            user_id,
            [account.id for account in accounts],
            provider_account_ids,
        )
        await self._audit(
            user_id,
            source_type,
            "balance_sync_started",
            {
                "account_count": len(accounts),
                "cursor_present": starting_cursor.opaque_token is not None,
            },
        )

        try:
            batch = await connector.fetch_balance_observations(
                user_id,
                [account.id for account in accounts],
                starting_cursor,
            )
            batch.validate_for_accounts({account.id for account in accounts})
            batch = self._scope_batch(batch, accounts, provider_account_ids)
            observation_service = BalanceObservationService(self.db)
            responses = await observation_service.ingest_batch(user_id, batch)
            card_responses = await CardPositionObservationService(self.db).ingest_batch(
                user_id,
                batch.card_observations,
                coverage_complete=batch.coverage_complete and not batch.errors,
                provider_account_ids=provider_account_ids,
            )
            error_types = [error.error_type.value for error in batch.errors]
            await self._audit(
                user_id,
                source_type,
                "balance_sync_completed",
                {
                    "account_count": len(accounts),
                    "observations": len(responses),
                    "card_observations": len(card_responses),
                    "coverage_complete": batch.coverage_complete,
                    "error_types": error_types,
                    "cursor_advanced": batch.cursor.opaque_token is not None,
                },
            )
            return BalanceSyncResult(
                source_type=source_type,
                financial_account_ids=[account.id for account in accounts],
                observations_ingested=len(responses),
                card_observations_ingested=len(card_responses),
                coverage_complete=batch.coverage_complete and not batch.errors,
                error_types=error_types,
                cursor_advanced=batch.cursor.opaque_token is not None,
            )
        except Exception as exc:
            error_type = classify_connector_exception(exc)
            public_error = public_connector_error(error_type, provider_name="balance provider")
            await self._record_failure(
                user_id,
                [account.id for account in accounts],
                error_code=f"balance_sync_{error_type.value}",
                cursor=starting_cursor.opaque_token,
            )
            await self._audit(
                user_id,
                source_type,
                "balance_sync_failed",
                {"error_type": error_type.value, "error": public_error},
            )
            raise

    async def _owned_accounts(
        self,
        user_id: str,
        account_ids: list[str],
    ) -> list[FinancialAccount]:
        normalized = list(dict.fromkeys(account_ids))
        if not normalized:
            raise ValueError("At least one financial account is required")
        return list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.id.in_(normalized),
                    )
                )
            ).all()
        )

    def _scope_batch(
        self,
        batch: BalanceObservationBatch,
        accounts: list[FinancialAccount],
        provider_account_ids: dict[str, str],
    ) -> BalanceObservationBatch:
        """Make missing/partial provider facts fail closed for every account."""

        # Kept as a small local boundary so connector implementations cannot
        # accidentally ingest an account outside the requested owned set or
        # claim complete freshness when a provider omitted one account.
        requested = {account.id for account in accounts}
        observed_ids = {item.financial_account_id for item in batch.observations}
        card_observed_ids = {item.financial_account_id for item in batch.card_observations}
        unexpected_ids = (observed_ids | card_observed_ids) - requested
        if unexpected_ids:
            raise ValueError("Balance connector returned an unrequested account")
        for observation in batch.observations:
            expected_source_account_id = provider_account_ids[observation.financial_account_id]
            if observation.source_account_id != expected_source_account_id:
                raise ValueError("Balance connector returned a mismatched provider account")
        for card_observation in batch.card_observations:
            expected_source_account_id = provider_account_ids[card_observation.financial_account_id]
            if card_observation.source_account_id != expected_source_account_id:
                raise ValueError("Card connector returned a mismatched provider account")
            account = next(
                account
                for account in accounts
                if account.id == card_observation.financial_account_id
            )
            if account.account_type != "credit_card":
                raise ValueError("Card observations require a credit-card account")
        missing_ids = requested - observed_ids
        affected_ids = sorted(
            requested if batch.errors else set(batch.affected_account_ids) | missing_ids
        )
        coverage_complete = batch.coverage_complete and not missing_ids
        return replace(
            batch,
            coverage_complete=coverage_complete,
            affected_account_ids=affected_ids,
        )

    async def _provider_account_ids(
        self,
        user_id: str,
        accounts: list[FinancialAccount],
        provider_type: str | None,
    ) -> dict[str, str]:
        account_ids = [account.id for account in accounts]
        mapped: dict[str, str] = {}
        if provider_type:
            mapped = await BalanceProviderMappingService(self.db).account_provider_ids(
                user_id,
                provider_type,
                account_ids,
            )
        return {
            account.id: mapped.get(account.id) or account.connector_account_id or ""
            for account in accounts
        }

    async def _resume_cursor(
        self,
        user_id: str,
        account_ids: list[str],
        provider_account_ids: dict[str, str] | None = None,
    ) -> ConnectorCursor:
        rows = list(
            (
                await self.db.scalars(
                    select(AccountBalanceSource).where(
                        AccountBalanceSource.user_id == user_id,
                        AccountBalanceSource.financial_account_id.in_(account_ids),
                        AccountBalanceSource.source == "connector",
                    )
                )
            ).all()
        )
        if provider_account_ids:
            expected_source_ids = set(provider_account_ids.values())
            rows = [row for row in rows if row.source_account_id in expected_source_ids]
        tokens = {row.cursor_token for row in rows if row.cursor_token}
        # A single provider cursor can safely resume a multi-account batch. If
        # source rows disagree, fail open to a fresh provider request rather
        # than replaying one account's cursor against another account.
        return (
            ConnectorCursor(opaque_token=next(iter(tokens)))
            if len(tokens) == 1
            else ConnectorCursor()
        )

    async def _record_failure(
        self,
        user_id: str,
        account_ids: list[str],
        *,
        error_code: str,
        cursor: str | None,
    ) -> None:
        await BalanceObservationService(self.db).record_failure(
            user_id,
            account_ids,
            error_code=error_code,
            cursor=cursor,
        )

    async def _audit(
        self,
        user_id: str,
        source_type: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        self.db.add(
            ConnectorAuditEvent(
                user_id=user_id,
                connector_type=source_type,
                connector_account_id=None,
                event_type=event_type,
                payload_json=json.dumps(payload, separators=(",", ":")),
                created_at=datetime.now(UTC),
            )
        )
        await self.db.commit()
