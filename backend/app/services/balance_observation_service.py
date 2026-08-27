"""Ingestion and freshness contracts for provider-backed account balances."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSource
from app.schemas.account import (
    BalanceCoverageResponse,
    BalanceObservationCreate,
    BalanceObservationResponse,
)
from app.services.account_service import AccountService
from app.services.connectors.base import BalanceObservation, BalanceObservationBatch


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class BalanceObservationService:
    """Persist provider observations and their non-financial coverage state."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ingest(
        self,
        user_id: str,
        observation: BalanceObservation,
        *,
        coverage_complete_override: bool | None = None,
        commit: bool = True,
    ) -> BalanceObservationResponse:
        """Ingest one append-only observation with retry-safe source identity."""

        if observation.source != "connector":
            raise ValueError("Provider balance observations must use source=connector")
        data = BalanceObservationCreate(
            amount=observation.amount,
            currency=observation.currency,
            as_of=observation.as_of,
            source_record_id=observation.source_record_id,
            source_account_id=observation.source_account_id,
            observed_at=observation.observed_at,
            effective_at=observation.effective_at,
            expected_cadence_minutes=observation.expected_cadence_minutes,
            coverage_start=observation.coverage_start,
            coverage_end=observation.coverage_end,
            coverage_complete=(
                observation.coverage_complete
                if coverage_complete_override is None
                else coverage_complete_override
            ),
        )
        snapshot = await AccountService(self.db).add_balance(
            user_id,
            observation.financial_account_id,
            # Provider observations are explicitly verified source facts.  The
            # estimate remains separate in FinancialPositionService.
            data.to_balance_snapshot_create(),
            commit=False,
        )
        if snapshot is None:
            raise LookupError("Financial account not found")

        state = await self._upsert_source_state(
            user_id,
            observation,
            coverage_complete=(
                observation.coverage_complete
                if coverage_complete_override is None
                else coverage_complete_override
            ),
        )
        if commit:
            await self.db.commit()
        return BalanceObservationResponse(
            snapshot=snapshot, coverage=self._coverage_response(state)
        )

    async def ingest_batch(
        self,
        user_id: str,
        batch: BalanceObservationBatch,
    ) -> list[BalanceObservationResponse]:
        """Ingest a connector response while preserving per-record idempotency."""

        responses: list[BalanceObservationResponse] = []
        try:
            for observation in batch.observations:
                if observation.source != batch.source:
                    raise ValueError("Observation source must match the connector batch source")
                responses.append(
                    await self.ingest(
                        user_id,
                        observation,
                        coverage_complete_override=batch.coverage_complete,
                        commit=False,
                    )
                )

            affected_ids = set(batch.affected_account_ids)
            affected_ids.update(item.financial_account_id for item in batch.observations)
            if batch.cursor.opaque_token is not None:
                for observation in batch.observations:
                    state = await self._ensure_source_state(
                        user_id,
                        observation.financial_account_id,
                        batch.source,
                        observation.source_account_id or "",
                    )
                    state.cursor_token = batch.cursor.opaque_token

            if batch.errors or not batch.coverage_complete:
                # A provider may return no balance fact at all when a refresh
                # fails.  Keep that failure visible in source health, and make
                # the next position calculation fail closed.  Error messages
                # are intentionally not persisted because they can contain
                # provider identifiers or response fragments.
                error_code = (
                    f"connector_batch_{batch.errors[0].error_type.value}"
                    if batch.errors
                    else "connector_batch_incomplete"
                )
                for account_id in affected_ids:
                    if not account_id:
                        continue
                    state = await self._ensure_source_state(
                        user_id,
                        account_id,
                        batch.source,
                    )
                    state.coverage_complete = False
                    state.last_error_code = error_code
                    if batch.cursor.opaque_token is not None:
                        state.cursor_token = batch.cursor.opaque_token

            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return responses

    async def record_failure(
        self,
        user_id: str,
        account_ids: list[str],
        *,
        source: str = "connector",
        error_code: str = "connector_sync_failed",
        cursor: str | None = None,
    ) -> None:
        """Persist a connector failure even when no balance fact was returned."""

        try:
            for account_id in set(account_ids):
                state = await self._ensure_source_state(user_id, account_id, source)
                state.coverage_complete = False
                state.last_error_code = error_code[:80]
                if cursor is not None:
                    state.cursor_token = cursor
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def list_coverage(
        self,
        user_id: str,
        account_id: str,
        *,
        source: str | None = None,
    ) -> list[BalanceCoverageResponse] | None:
        account = await AccountService(self.db)._owned_account(user_id, account_id)
        if account is None:
            return None
        statement = select(AccountBalanceSource).where(
            AccountBalanceSource.user_id == user_id,
            AccountBalanceSource.financial_account_id == account_id,
        )
        if source is not None:
            statement = statement.where(AccountBalanceSource.source == source)
        rows = list(
            (
                await self.db.scalars(
                    statement.order_by(
                        AccountBalanceSource.source, AccountBalanceSource.source_account_id
                    )
                )
            ).all()
        )
        return [self._coverage_response(row) for row in rows]

    async def _upsert_source_state(
        self,
        user_id: str,
        observation: BalanceObservation,
        *,
        coverage_complete: bool,
    ) -> AccountBalanceSource:
        source_account_id = observation.source_account_id or ""
        state = await self.db.scalar(
            select(AccountBalanceSource).where(
                AccountBalanceSource.user_id == user_id,
                AccountBalanceSource.financial_account_id == observation.financial_account_id,
                AccountBalanceSource.source == observation.source,
                AccountBalanceSource.source_account_id == source_account_id,
            )
        )
        if state is None:
            state = AccountBalanceSource(
                user_id=user_id,
                financial_account_id=observation.financial_account_id,
                source=observation.source,
                source_account_id=source_account_id,
            )
            self.db.add(state)
            await self.db.flush()

        observed_at = _as_utc(observation.observed_at)
        current_observed_at = (
            _as_utc(state.last_observed_at) if state.last_observed_at is not None else None
        )
        # Provider retries and late-arriving history must not move the source
        # cursor backwards or make an old complete response hide a newer gap.
        if current_observed_at is None or observed_at >= current_observed_at:
            state.expected_cadence_minutes = observation.expected_cadence_minutes
            state.coverage_start = observation.coverage_start
            state.coverage_end = observation.coverage_end
            state.coverage_complete = coverage_complete
            state.last_observed_at = observed_at
            state.last_effective_at = (
                _as_utc(observation.effective_at) if observation.effective_at is not None else None
            )
            state.last_success_at = observed_at
            state.last_source_record_id = observation.source_record_id
            state.last_error_code = None
        return state

    async def _ensure_source_state(
        self,
        user_id: str,
        account_id: str,
        source: str,
        source_account_id: str = "",
    ) -> AccountBalanceSource:
        """Return a source-health row even when a batch has no balance fact."""

        state = await self.db.scalar(
            select(AccountBalanceSource).where(
                AccountBalanceSource.user_id == user_id,
                AccountBalanceSource.financial_account_id == account_id,
                AccountBalanceSource.source == source,
                AccountBalanceSource.source_account_id == source_account_id,
            )
        )
        if state is None:
            state = AccountBalanceSource(
                user_id=user_id,
                financial_account_id=account_id,
                source=source,
                source_account_id=source_account_id,
                coverage_complete=False,
            )
            self.db.add(state)
            await self.db.flush()
        return state

    def _coverage_response(
        self,
        state: AccountBalanceSource,
        *,
        now: datetime | None = None,
    ) -> BalanceCoverageResponse:
        instant = _as_utc(now or datetime.now(UTC))
        last_success = _as_utc(state.last_success_at) if state.last_success_at is not None else None
        expected_next_at = None
        freshness_status: Literal["fresh", "due", "overdue", "unknown"] = "unknown"
        reason_codes: list[str] = []
        if last_success is not None and state.expected_cadence_minutes:
            cadence = timedelta(minutes=state.expected_cadence_minutes)
            expected_next_at = last_success + cadence
            if instant <= expected_next_at:
                freshness_status = "fresh"
            elif instant <= expected_next_at + cadence:
                freshness_status = "due"
                reason_codes.append("balance_observation_due")
            else:
                freshness_status = "overdue"
                reason_codes.append("balance_observation_overdue")
        if not state.coverage_complete:
            reason_codes.append("source_coverage_incomplete")
        if state.last_error_code:
            reason_codes.append(state.last_error_code)
        return BalanceCoverageResponse(
            financial_account_id=state.financial_account_id,
            source=state.source,
            source_account_id=state.source_account_id or None,
            expected_cadence_minutes=state.expected_cadence_minutes,
            expected_next_at=expected_next_at,
            coverage_start=state.coverage_start,
            coverage_end=state.coverage_end,
            coverage_complete=state.coverage_complete,
            last_observed_at=state.last_observed_at,
            last_effective_at=state.last_effective_at,
            last_success_at=state.last_success_at,
            last_source_record_id=state.last_source_record_id,
            last_error_code=state.last_error_code,
            freshness_status=freshness_status,
            reason_codes=list(dict.fromkeys(reason_codes)),
        )


def observation_from_create(
    account_id: str,
    data: BalanceObservationCreate,
) -> BalanceObservation:
    """Translate the HTTP envelope into the connector-neutral contract."""

    observed_at = data.observed_at or datetime.now(UTC)
    return BalanceObservation(
        financial_account_id=account_id,
        amount=data.amount,
        currency=data.currency,
        as_of=data.as_of,
        source_record_id=data.source_record_id,
        observed_at=observed_at,
        source="connector",
        source_account_id=data.source_account_id,
        effective_at=data.effective_at,
        expected_cadence_minutes=data.expected_cadence_minutes,
        coverage_start=data.coverage_start,
        coverage_end=data.coverage_end,
        coverage_complete=data.coverage_complete,
    )
