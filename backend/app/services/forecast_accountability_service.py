"""Prospective forecast snapshots and idempotent outcome evaluation."""

from __future__ import annotations

import calendar
import json
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.forecast import CashFlowForecastOutcome, CashFlowForecastSnapshot
from app.schemas.intelligence import (
    CashFlowForecastOutcomeResponse,
    CashFlowForecastSnapshotCreate,
    CashFlowForecastSnapshotResponse,
    CashFlowOutcomeEvaluationResponse,
    DataSufficiency,
    EvidenceItem,
)
from app.services.financial_clock import user_financial_today
from app.services.intelligence_service import IntelligenceService
from app.services.knowledge.ruleset_registry import CASH_FLOW, CASH_FLOW_OUTCOME


class ForecastAccountabilityService:
    """Freeze predictions separately from the truth used to evaluate them later."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_snapshot(
        self, user_id: str, data: CashFlowForecastSnapshotCreate
    ) -> CashFlowForecastSnapshotResponse:
        cutoff = await user_financial_today(self.db, user_id)
        current_absolute = cutoff.year * 12 + cutoff.month - 1
        target_absolute = data.year * 12 + data.month - 1
        if target_absolute < current_absolute:
            raise ValueError("Forecast snapshots cannot target a completed month")
        if target_absolute - current_absolute > 12:
            raise ValueError("Forecast snapshots cannot target more than 12 months ahead")

        existing = await self._find_snapshot(
            user_id,
            data.month,
            data.year,
            cutoff,
            CASH_FLOW.version,
        )
        if existing is not None:
            return self._snapshot_response(existing)

        projection = await IntelligenceService(self.db).cash_flow_projection(
            user_id, data.month, data.year
        )
        row = CashFlowForecastSnapshot(
            user_id=user_id,
            target_month=data.month,
            target_year=data.year,
            cutoff_date=cutoff,
            forecast_ruleset_version=projection.ruleset_version,
            temporal_ruleset_version=projection.temporal_ruleset_version,
            projected_spend=Decimal(str(projection.projected_spend)),
            projected_net=Decimal(str(projection.projected_net)),
            projected_range_low=Decimal(str(projection.projected_range_low)),
            projected_range_high=Decimal(str(projection.projected_range_high)),
            expected_income=Decimal(str(projection.expected_income)),
            temporal_expected_income=Decimal(str(projection.temporal_expected_income)),
            temporal_expected_outflows=Decimal(str(projection.temporal_expected_outflows)),
            temporal_conflicted_outflows=Decimal(str(projection.temporal_conflicted_outflows)),
            confidence=Decimal(str(projection.confidence)),
            data_sufficiency=projection.data_sufficiency,
            evidence_json=json.dumps(
                [item.model_dump(mode="json") for item in projection.evidence],
                sort_keys=True,
                separators=(",", ":"),
            ),
            assumptions_json=json.dumps(
                projection.assumptions,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        try:
            async with self.db.begin_nested():
                self.db.add(row)
                await self.db.flush()
        except IntegrityError:
            concurrent = await self._find_snapshot(
                user_id,
                data.month,
                data.year,
                cutoff,
                projection.ruleset_version,
            )
            if concurrent is None:
                raise
            row = concurrent
        await self.db.commit()
        return self._snapshot_response(row)

    async def list_snapshots(
        self,
        user_id: str,
        *,
        month: int | None = None,
        year: int | None = None,
    ) -> list[CashFlowForecastSnapshotResponse]:
        query = select(CashFlowForecastSnapshot).where(CashFlowForecastSnapshot.user_id == user_id)
        if month is not None:
            query = query.where(CashFlowForecastSnapshot.target_month == month)
        if year is not None:
            query = query.where(CashFlowForecastSnapshot.target_year == year)
        rows = list(
            (
                await self.db.scalars(
                    query.order_by(
                        CashFlowForecastSnapshot.cutoff_date.desc(),
                        CashFlowForecastSnapshot.created_at.desc(),
                    )
                )
            ).all()
        )
        return [self._snapshot_response(row) for row in rows]

    async def evaluate_completed(self, user_id: str) -> CashFlowOutcomeEvaluationResponse:
        today = await user_financial_today(self.db, user_id)
        snapshots = list(
            (
                await self.db.scalars(
                    select(CashFlowForecastSnapshot)
                    .where(CashFlowForecastSnapshot.user_id == user_id)
                    .order_by(
                        CashFlowForecastSnapshot.target_year,
                        CashFlowForecastSnapshot.target_month,
                        CashFlowForecastSnapshot.cutoff_date,
                    )
                )
            ).all()
        )
        snapshot_ids = [row.id for row in snapshots]
        existing = (
            {
                row.snapshot_id: row
                for row in (
                    await self.db.scalars(
                        select(CashFlowForecastOutcome).where(
                            CashFlowForecastOutcome.user_id == user_id,
                            CashFlowForecastOutcome.snapshot_id.in_(snapshot_ids),
                        )
                    )
                ).all()
            }
            if snapshot_ids
            else {}
        )
        intelligence = IntelligenceService(self.db)
        created: list[tuple[CashFlowForecastOutcome, CashFlowForecastSnapshot]] = []
        already_evaluated = 0
        ineligible = 0
        for snapshot in snapshots:
            target_end = date(
                snapshot.target_year,
                snapshot.target_month,
                calendar.monthrange(snapshot.target_year, snapshot.target_month)[1],
            )
            if target_end >= today:
                ineligible += 1
                continue
            if snapshot.id in existing:
                already_evaluated += 1
                continue

            actual_income, actual_spend = await intelligence.monthly_income_spend(
                user_id, snapshot.target_month, snapshot.target_year
            )
            projected_spend = snapshot.projected_spend
            actual_spend_decimal = Decimal(str(actual_spend))
            absolute_error = abs(projected_spend - actual_spend_decimal)
            outcome = CashFlowForecastOutcome(
                user_id=user_id,
                snapshot_id=snapshot.id,
                outcome_ruleset_version=CASH_FLOW_OUTCOME.version,
                actual_income=Decimal(str(actual_income)),
                actual_spend=actual_spend_decimal,
                actual_net=Decimal(str(actual_income - actual_spend)),
                spend_absolute_error=absolute_error,
                spend_absolute_percentage_error=(
                    absolute_error / actual_spend_decimal * 100
                    if actual_spend_decimal > 0
                    else None
                ),
                spend_range_covered=(
                    snapshot.projected_range_low
                    <= actual_spend_decimal
                    <= snapshot.projected_range_high
                ),
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(outcome)
                    await self.db.flush()
            except IntegrityError:
                already_evaluated += 1
                continue
            created.append((outcome, snapshot))
        await self.db.commit()
        return CashFlowOutcomeEvaluationResponse(
            evaluation_version=CASH_FLOW_OUTCOME.version,
            evaluated_count=len(created),
            already_evaluated_count=already_evaluated,
            ineligible_count=ineligible,
            outcomes=[self._outcome_response(outcome, snapshot) for outcome, snapshot in created],
        )

    async def list_outcomes(self, user_id: str) -> list[CashFlowForecastOutcomeResponse]:
        rows = (
            await self.db.execute(
                select(CashFlowForecastOutcome, CashFlowForecastSnapshot)
                .join(
                    CashFlowForecastSnapshot,
                    CashFlowForecastSnapshot.id == CashFlowForecastOutcome.snapshot_id,
                )
                .where(
                    CashFlowForecastOutcome.user_id == user_id,
                    CashFlowForecastSnapshot.user_id == user_id,
                )
                .order_by(CashFlowForecastOutcome.evaluated_at.desc())
            )
        ).all()
        return [self._outcome_response(outcome, snapshot) for outcome, snapshot in rows]

    async def _find_snapshot(
        self,
        user_id: str,
        month: int,
        year: int,
        cutoff: date,
        ruleset_version: str,
    ) -> CashFlowForecastSnapshot | None:
        return await self.db.scalar(
            select(CashFlowForecastSnapshot).where(
                CashFlowForecastSnapshot.user_id == user_id,
                CashFlowForecastSnapshot.target_month == month,
                CashFlowForecastSnapshot.target_year == year,
                CashFlowForecastSnapshot.cutoff_date == cutoff,
                CashFlowForecastSnapshot.forecast_ruleset_version == ruleset_version,
            )
        )

    @staticmethod
    def _snapshot_response(
        row: CashFlowForecastSnapshot,
    ) -> CashFlowForecastSnapshotResponse:
        return CashFlowForecastSnapshotResponse(
            id=row.id,
            target_month=row.target_month,
            target_year=row.target_year,
            cutoff_date=row.cutoff_date,
            forecast_ruleset_version=row.forecast_ruleset_version,
            temporal_ruleset_version=row.temporal_ruleset_version,
            projected_spend=float(row.projected_spend),
            projected_net=float(row.projected_net),
            projected_range_low=float(row.projected_range_low),
            projected_range_high=float(row.projected_range_high),
            expected_income=float(row.expected_income),
            temporal_expected_income=float(row.temporal_expected_income),
            temporal_expected_outflows=float(row.temporal_expected_outflows),
            temporal_conflicted_outflows=float(row.temporal_conflicted_outflows),
            confidence=float(row.confidence),
            data_sufficiency=cast(DataSufficiency, row.data_sufficiency),
            evidence=[EvidenceItem.model_validate(item) for item in json.loads(row.evidence_json)],
            assumptions=cast(list[str], json.loads(row.assumptions_json)),
            created_at=row.created_at,
        )

    @staticmethod
    def _outcome_response(
        outcome: CashFlowForecastOutcome,
        snapshot: CashFlowForecastSnapshot,
    ) -> CashFlowForecastOutcomeResponse:
        return CashFlowForecastOutcomeResponse(
            id=outcome.id,
            snapshot_id=snapshot.id,
            target_month=snapshot.target_month,
            target_year=snapshot.target_year,
            cutoff_date=snapshot.cutoff_date,
            forecast_ruleset_version=snapshot.forecast_ruleset_version,
            outcome_ruleset_version=outcome.outcome_ruleset_version,
            projected_spend=float(snapshot.projected_spend),
            projected_range_low=float(snapshot.projected_range_low),
            projected_range_high=float(snapshot.projected_range_high),
            actual_income=float(outcome.actual_income),
            actual_spend=float(outcome.actual_spend),
            actual_net=float(outcome.actual_net),
            spend_absolute_error=float(outcome.spend_absolute_error),
            spend_absolute_percentage_error=(
                float(outcome.spend_absolute_percentage_error)
                if outcome.spend_absolute_percentage_error is not None
                else None
            ),
            spend_range_covered=outcome.spend_range_covered,
            evaluated_at=outcome.evaluated_at,
        )
