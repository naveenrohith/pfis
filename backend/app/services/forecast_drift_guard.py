"""Deterministic forecast drift checks over matured outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.forecast import (
    AccountBalanceForecastOutcome,
    AccountBalanceForecastSnapshot,
    CashFlowForecastOutcome,
    CashFlowForecastSnapshot,
)

FORECAST_DRIFT_RULESET_VERSION = "pfis-forecast-drift-guard-1"
FORECAST_DRIFT_MINIMUM_OUTCOMES = 3
FORECAST_DRIFT_MAXIMUM_MAPE_PCT = 20.0
FORECAST_DRIFT_MINIMUM_INTERVAL_COVERAGE_PCT = 70.0
FORECAST_DRIFT_REASON_CODE = "forecast_drift_guard"
RECENT_OUTCOME_LIMIT_PER_HORIZON = 12

DriftStatus = Literal["insufficient_evidence", "healthy", "degraded"]


@dataclass(frozen=True)
class ForecastDriftHorizonMetric:
    horizon: str
    matured_outcomes: int
    mean_absolute_percentage_error: float | None
    interval_coverage_pct: float | None
    status: DriftStatus


@dataclass(frozen=True)
class ForecastDriftStatus:
    ruleset_version: str
    status: DriftStatus
    reason_code: str
    minimum_outcomes: int
    maximum_mape_pct: float
    minimum_interval_coverage_pct: float
    horizons: list[ForecastDriftHorizonMetric]

    @property
    def degraded(self) -> bool:
        return self.status == "degraded"


class ForecastDriftGuard:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def account_balance_status(
        self, user_id: str, account_id: str | None = None
    ) -> ForecastDriftStatus:
        query = (
            select(AccountBalanceForecastOutcome, AccountBalanceForecastSnapshot)
            .join(
                AccountBalanceForecastSnapshot,
                AccountBalanceForecastSnapshot.id == AccountBalanceForecastOutcome.snapshot_id,
            )
            .where(AccountBalanceForecastOutcome.user_id == user_id)
            .order_by(AccountBalanceForecastOutcome.evaluated_at.desc())
        )
        if account_id is not None:
            query = query.where(AccountBalanceForecastOutcome.financial_account_id == account_id)
        rows = list((await self.db.execute(query)).all())
        grouped: dict[str, list[AccountBalanceForecastOutcome]] = {}
        for outcome, snapshot in rows:
            horizon = max(1, (outcome.target_date - snapshot.cutoff_date).days)
            key = f"{horizon}d"
            grouped.setdefault(key, [])
            if len(grouped[key]) < RECENT_OUTCOME_LIMIT_PER_HORIZON:
                grouped[key].append(outcome)
        return self._status_from_groups(
            {
                key: [
                    (
                        self._percentage_error(row.actual_balance, row.expected_balance),
                        row.interval_covered,
                    )
                    for row in values
                ]
                for key, values in grouped.items()
            }
        )

    async def cash_flow_status(self, user_id: str) -> ForecastDriftStatus:
        rows = list(
            (
                await self.db.execute(
                    select(CashFlowForecastOutcome, CashFlowForecastSnapshot)
                    .join(
                        CashFlowForecastSnapshot,
                        CashFlowForecastSnapshot.id == CashFlowForecastOutcome.snapshot_id,
                    )
                    .where(CashFlowForecastOutcome.user_id == user_id)
                    .order_by(CashFlowForecastOutcome.evaluated_at.desc())
                )
            ).all()
        )
        grouped: dict[str, list[CashFlowForecastOutcome]] = {}
        for outcome, snapshot in rows:
            horizon = (
                snapshot.target_year * 12
                + snapshot.target_month
                - (snapshot.cutoff_date.year * 12 + snapshot.cutoff_date.month)
            )
            key = f"{max(0, horizon)}m"
            grouped.setdefault(key, [])
            if len(grouped[key]) < RECENT_OUTCOME_LIMIT_PER_HORIZON:
                grouped[key].append(outcome)
        return self._status_from_groups(
            {
                key: [
                    (
                        (
                            float(row.spend_absolute_percentage_error)
                            if row.spend_absolute_percentage_error is not None
                            else None
                        ),
                        row.spend_range_covered,
                    )
                    for row in values
                ]
                for key, values in grouped.items()
            }
        )

    @classmethod
    def _status_from_groups(
        cls, grouped: dict[str, list[tuple[float | None, bool | None]]]
    ) -> ForecastDriftStatus:
        horizons = [
            cls._horizon_metric(horizon, values) for horizon, values in sorted(grouped.items())
        ]
        if any(item.status == "degraded" for item in horizons):
            status: DriftStatus = "degraded"
        elif horizons and all(item.status == "healthy" for item in horizons):
            status = "healthy"
        else:
            status = "insufficient_evidence"
        return ForecastDriftStatus(
            ruleset_version=FORECAST_DRIFT_RULESET_VERSION,
            status=status,
            reason_code=FORECAST_DRIFT_REASON_CODE,
            minimum_outcomes=FORECAST_DRIFT_MINIMUM_OUTCOMES,
            maximum_mape_pct=FORECAST_DRIFT_MAXIMUM_MAPE_PCT,
            minimum_interval_coverage_pct=FORECAST_DRIFT_MINIMUM_INTERVAL_COVERAGE_PCT,
            horizons=horizons,
        )

    @staticmethod
    def _horizon_metric(
        horizon: str, values: list[tuple[float | None, bool | None]]
    ) -> ForecastDriftHorizonMetric:
        mape_values = [value for value, _covered in values if value is not None]
        coverage_values = [covered for _value, covered in values if covered is not None]
        mape = sum(mape_values) / len(mape_values) if mape_values else None
        coverage = (
            sum(1 for covered in coverage_values if covered) / len(coverage_values) * 100
            if coverage_values
            else None
        )
        if len(values) < FORECAST_DRIFT_MINIMUM_OUTCOMES or mape is None or coverage is None:
            status: DriftStatus = "insufficient_evidence"
        elif mape > FORECAST_DRIFT_MAXIMUM_MAPE_PCT or (
            coverage < FORECAST_DRIFT_MINIMUM_INTERVAL_COVERAGE_PCT
        ):
            status = "degraded"
        else:
            status = "healthy"
        return ForecastDriftHorizonMetric(
            horizon=horizon,
            matured_outcomes=len(values),
            mean_absolute_percentage_error=round(mape, 2) if mape is not None else None,
            interval_coverage_pct=round(coverage, 2) if coverage is not None else None,
            status=status,
        )

    @staticmethod
    def _percentage_error(actual: Decimal, expected: Decimal) -> float | None:
        denominator = abs(expected)
        if denominator == 0:
            return None
        return float(abs(actual - expected) / denominator * Decimal("100"))
