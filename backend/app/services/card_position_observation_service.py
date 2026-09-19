"""Persist typed issuer facts for live credit-card positions."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial_position import CardPositionObservation as CardPositionObservationModel
from app.schemas.account import (
    CardPositionObservationCreate,
    CardPositionObservationResponse,
)
from app.services.account_service import AccountService
from app.services.balance_observation_service import BalanceObservationService
from app.services.connectors.base import BalanceObservation, CardPositionObservation


def observation_from_create(
    account_id: str,
    data: CardPositionObservationCreate,
) -> CardPositionObservation:
    """Translate an HTTP envelope into the connector-neutral card contract."""

    observed_at = data.observed_at or datetime.now(UTC)
    return CardPositionObservation(
        financial_account_id=account_id,
        currency=data.currency,
        current_outstanding=data.current_outstanding,
        billed_due=data.billed_due,
        pending_amount=data.pending_amount,
        credit_limit=data.credit_limit,
        available_credit=data.available_credit,
        as_of=data.as_of,
        source_record_id=data.source_record_id,
        observed_at=observed_at,
        source_account_id=data.source_account_id,
        effective_at=data.effective_at,
        expected_cadence_minutes=data.expected_cadence_minutes,
        coverage_start=data.coverage_start,
        coverage_end=data.coverage_end,
        coverage_complete=data.coverage_complete,
    )


class CardPositionObservationService:
    """Store immutable card facts and mirror outstanding into the position ledger."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ingest(
        self,
        user_id: str,
        observation: CardPositionObservation,
        *,
        coverage_complete_override: bool | None = None,
        commit: bool = True,
        expected_provider_account_id: str | None = None,
    ) -> CardPositionObservationResponse:
        account = await AccountService(self.db)._owned_account(
            user_id,
            observation.financial_account_id,
        )
        if account is None:
            raise LookupError("Financial account not found")
        if not account.is_active:
            raise ValueError("Cannot ingest a card observation for an inactive account")
        if account.account_type != "credit_card":
            raise ValueError("Card position observations require a credit-card account")
        if observation.currency.strip().upper() != account.currency:
            raise ValueError("Card observation currency must match the account currency")
        expected_account_id = expected_provider_account_id or account.connector_account_id
        if not expected_account_id:
            raise ValueError("Card provider account mapping is required before ingestion")
        if expected_account_id and observation.source_account_id != expected_account_id:
            raise ValueError("Card observation provider account does not match the mapped account")

        existing = await self.db.scalar(
            select(CardPositionObservationModel).where(
                CardPositionObservationModel.financial_account_id
                == observation.financial_account_id,
                CardPositionObservationModel.source == observation.source,
                CardPositionObservationModel.source_record_id == observation.source_record_id,
            )
        )
        if existing is not None:
            return self._response(existing)

        coverage_complete = (
            observation.coverage_complete
            if coverage_complete_override is None
            else coverage_complete_override
        )
        # The current outstanding is the only card fact allowed to update the
        # generic liability position.  The remaining issuer fields stay on the
        # typed append-only record and are never inferred from it.
        await BalanceObservationService(self.db).ingest(
            user_id,
            self._balance_observation(observation),
            coverage_complete_override=coverage_complete,
            commit=False,
        )
        record = CardPositionObservationModel(
            user_id=user_id,
            financial_account_id=observation.financial_account_id,
            currency=account.currency,
            current_outstanding=observation.current_outstanding,
            billed_due=observation.billed_due,
            pending_amount=observation.pending_amount,
            credit_limit=observation.credit_limit,
            available_credit=observation.available_credit,
            as_of=observation.as_of,
            source=observation.source,
            source_record_id=observation.source_record_id,
            source_account_id=observation.source_account_id,
            observed_at=observation.observed_at,
            effective_at=observation.effective_at,
            expected_cadence_minutes=observation.expected_cadence_minutes,
            coverage_start=observation.coverage_start,
            coverage_end=observation.coverage_end,
            coverage_complete=coverage_complete,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(record)
                await self.db.flush()
        except IntegrityError:
            # A concurrent retry can win the immutable source identity race.
            # Keep the caller's transaction alive and return that first fact.
            persisted = await self.db.scalar(
                select(CardPositionObservationModel).where(
                    CardPositionObservationModel.financial_account_id
                    == observation.financial_account_id,
                    CardPositionObservationModel.source == observation.source,
                    CardPositionObservationModel.source_record_id == observation.source_record_id,
                )
            )
            if persisted is None:
                raise
            if commit:
                await self.db.commit()
            return self._response(persisted)
        if commit:
            await self.db.commit()
            await self.db.refresh(record)
        return self._response(record)

    async def ingest_batch(
        self,
        user_id: str,
        observations: Iterable[CardPositionObservation],
        *,
        coverage_complete: bool = True,
        provider_account_ids: dict[str, str] | None = None,
    ) -> list[CardPositionObservationResponse]:
        responses: list[CardPositionObservationResponse] = []
        try:
            for observation in observations:
                responses.append(
                    await self.ingest(
                        user_id,
                        observation,
                        coverage_complete_override=coverage_complete,
                        commit=False,
                        expected_provider_account_id=(
                            provider_account_ids.get(observation.financial_account_id)
                            if provider_account_ids
                            else None
                        ),
                    )
                )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return responses

    async def latest(
        self,
        user_id: str,
        account_id: str,
    ) -> CardPositionObservationResponse | None:
        account = await AccountService(self.db)._owned_account(user_id, account_id)
        if account is None:
            return None
        record = await self.db.scalar(
            select(CardPositionObservationModel)
            .where(
                CardPositionObservationModel.user_id == user_id,
                CardPositionObservationModel.financial_account_id == account_id,
            )
            .order_by(
                CardPositionObservationModel.as_of.desc(),
                CardPositionObservationModel.effective_at.desc().nulls_last(),
                CardPositionObservationModel.observed_at.desc(),
                CardPositionObservationModel.created_at.desc(),
            )
        )
        return self._response(record) if record is not None else None

    async def list_recent(
        self,
        user_id: str,
        account_id: str,
        *,
        limit: int = 20,
    ) -> list[CardPositionObservationResponse] | None:
        account = await AccountService(self.db)._owned_account(user_id, account_id)
        if account is None:
            return None
        rows = list(
            (
                await self.db.scalars(
                    select(CardPositionObservationModel)
                    .where(
                        CardPositionObservationModel.user_id == user_id,
                        CardPositionObservationModel.financial_account_id == account_id,
                    )
                    .order_by(
                        CardPositionObservationModel.as_of.desc(),
                        CardPositionObservationModel.observed_at.desc(),
                    )
                    .limit(max(1, min(limit, 100)))
                )
            ).all()
        )
        return [self._response(row) for row in rows]

    def _balance_observation(
        self,
        observation: CardPositionObservation,
    ) -> BalanceObservation:
        return BalanceObservation(
            financial_account_id=observation.financial_account_id,
            amount=observation.current_outstanding,
            currency=observation.currency,
            as_of=observation.as_of,
            source_record_id=observation.source_record_id,
            observed_at=observation.observed_at,
            source=observation.source,
            source_account_id=observation.source_account_id,
            effective_at=observation.effective_at,
            expected_cadence_minutes=observation.expected_cadence_minutes,
            coverage_start=observation.coverage_start,
            coverage_end=observation.coverage_end,
            coverage_complete=observation.coverage_complete,
        )

    @staticmethod
    def _response(record: CardPositionObservationModel) -> CardPositionObservationResponse:
        return CardPositionObservationResponse.model_validate(record, from_attributes=True)
