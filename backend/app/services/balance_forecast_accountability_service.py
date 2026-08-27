"""Prospective daily balance forecasts and observed-outcome evaluation."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.forecast import AccountBalanceForecastOutcome, AccountBalanceForecastSnapshot
from app.schemas.balance_forecast import (
    AccountBalanceForecastEvaluationResponse,
    AccountBalanceForecastOutcomeResponse,
    AccountBalanceForecastPoint,
    AccountBalanceForecastSnapshotCreate,
    AccountBalanceForecastSnapshotResponse,
)
from app.schemas.intelligence import DataSufficiency, EvidenceItem
from app.services.balance_forecast_service import BalanceForecastService
from app.services.financial_clock import user_financial_today

OUTCOME_RULESET_VERSION = "pfis-account-balance-forecast-outcome-1"
MINIMUM_CALIBRATION_OUTCOMES = 3
MAXIMUM_MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_PCT = 20.0
MINIMUM_INTERVAL_COVERAGE_PCT = 70.0


class BalanceForecastAccountabilityService:
    """Freeze forecast paths and compare them with later verified observations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_snapshot(
        self,
        user_id: str,
        account_id: str,
        data: AccountBalanceForecastSnapshotCreate,
    ) -> AccountBalanceForecastSnapshotResponse:
        await self._require_account(user_id, account_id)

        today = await user_financial_today(self.db, user_id)
        cutoff_date = data.cutoff_date or today
        if cutoff_date > today:
            raise ValueError("Forecast snapshot cutoff cannot be in the future")
        if (today - cutoff_date).days > 365:
            raise ValueError("Forecast snapshot cutoff cannot be more than 365 days old")

        forecast = await BalanceForecastService(self.db).forecast(
            user_id,
            account_id,
            horizon_days=data.horizon_days,
            as_of=cutoff_date,
        )
        if forecast is None:
            raise LookupError("Financial account not found")

        existing = await self._find_snapshot(
            user_id,
            account_id,
            cutoff_date=forecast.horizon_start,
            horizon_days=forecast.horizon_days,
            ruleset_version=forecast.ruleset_version,
        )
        if existing is not None:
            return self._snapshot_response(existing)

        row = AccountBalanceForecastSnapshot(
            user_id=user_id,
            financial_account_id=account_id,
            currency=forecast.currency,
            balance_kind=forecast.balance_kind,
            cutoff_date=forecast.horizon_start,
            horizon_start=forecast.horizon_start,
            horizon_end=forecast.horizon_end,
            horizon_days=forecast.horizon_days,
            forecast_ruleset_version=forecast.ruleset_version,
            status=forecast.status,
            starting_balance=self._decimal_or_none(forecast.starting_balance),
            starting_balance_as_of=forecast.starting_balance_as_of,
            starting_balance_basis=forecast.starting_balance_basis,
            expected_ending_balance=self._decimal_or_none(forecast.expected_ending_balance),
            expected_change=self._decimal_or_none(forecast.expected_change),
            lowest_expected_balance=self._decimal_or_none(forecast.lowest_expected_balance),
            lowest_expected_date=forecast.lowest_expected_date,
            first_shortfall_date=forecast.first_shortfall_date,
            event_count=forecast.event_count,
            historical_days=forecast.historical_days,
            historical_activity_count=forecast.historical_activity_count,
            coverage_status=forecast.coverage_status,
            position_status=forecast.position_status,
            position_confidence=Decimal(str(forecast.position_confidence)),
            confidence=Decimal(str(forecast.confidence)),
            data_sufficiency=forecast.data_sufficiency,
            position_reason_codes_json=json.dumps(
                forecast.position_reason_codes,
                sort_keys=True,
                separators=(",", ":"),
            ),
            evidence_json=json.dumps(
                [item.model_dump(mode="json") for item in forecast.evidence],
                sort_keys=True,
                separators=(",", ":"),
            ),
            assumptions_json=json.dumps(
                forecast.assumptions,
                sort_keys=True,
                separators=(",", ":"),
            ),
            points_json=json.dumps(
                [point.model_dump(mode="json") for point in forecast.points],
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
                account_id,
                cutoff_date=forecast.horizon_start,
                horizon_days=forecast.horizon_days,
                ruleset_version=forecast.ruleset_version,
            )
            if concurrent is None:
                raise
            row = concurrent
        await self.db.commit()
        await self.db.refresh(row)
        return self._snapshot_response(row)

    async def list_snapshots(
        self,
        user_id: str,
        account_id: str,
    ) -> list[AccountBalanceForecastSnapshotResponse]:
        await self._require_account(user_id, account_id)
        rows = list(
            (
                await self.db.scalars(
                    select(AccountBalanceForecastSnapshot)
                    .where(
                        AccountBalanceForecastSnapshot.user_id == user_id,
                        AccountBalanceForecastSnapshot.financial_account_id == account_id,
                    )
                    .order_by(
                        AccountBalanceForecastSnapshot.cutoff_date.desc(),
                        AccountBalanceForecastSnapshot.created_at.desc(),
                    )
                )
            ).all()
        )
        return [self._snapshot_response(row) for row in rows]

    async def evaluate(
        self,
        user_id: str,
        account_id: str,
    ) -> AccountBalanceForecastEvaluationResponse:
        await self._require_account(user_id, account_id)
        today = await user_financial_today(self.db, user_id)
        snapshots = list(
            (
                await self.db.scalars(
                    select(AccountBalanceForecastSnapshot)
                    .where(
                        AccountBalanceForecastSnapshot.user_id == user_id,
                        AccountBalanceForecastSnapshot.financial_account_id == account_id,
                    )
                    .order_by(AccountBalanceForecastSnapshot.cutoff_date)
                )
            ).all()
        )
        if not snapshots:
            return AccountBalanceForecastEvaluationResponse(
                evaluation_version=OUTCOME_RULESET_VERSION,
                evaluated_count=0,
                already_evaluated_count=0,
                pending_count=0,
                calibration_thresholds=self._calibration_thresholds(),
                outcomes=[],
            )

        snapshot_ids = [row.id for row in snapshots]
        existing_rows = list(
            (
                await self.db.scalars(
                    select(AccountBalanceForecastOutcome).where(
                        AccountBalanceForecastOutcome.user_id == user_id,
                        AccountBalanceForecastOutcome.snapshot_id.in_(snapshot_ids),
                    )
                )
            ).all()
        )
        existing_keys = {(row.snapshot_id, row.target_date) for row in existing_rows}

        dates: set[date] = set()
        points_by_snapshot: dict[str, list[AccountBalanceForecastPoint]] = {}
        for snapshot in snapshots:
            points = [
                AccountBalanceForecastPoint.model_validate(item)
                for item in json.loads(snapshot.points_json)
            ]
            points_by_snapshot[snapshot.id] = points
            dates.update(
                point.date for point in points if snapshot.cutoff_date < point.date <= today
            )

        observations = (
            list(
                (
                    await self.db.scalars(
                        select(AccountBalanceSnapshot)
                        .where(
                            AccountBalanceSnapshot.user_id == user_id,
                            AccountBalanceSnapshot.financial_account_id == account_id,
                            AccountBalanceSnapshot.verified.is_(True),
                            AccountBalanceSnapshot.as_of.in_(dates),
                        )
                        .order_by(
                            AccountBalanceSnapshot.as_of,
                            AccountBalanceSnapshot.observed_at.desc(),
                            AccountBalanceSnapshot.created_at.desc(),
                        )
                    )
                ).all()
            )
            if dates
            else []
        )
        observation_by_date: dict[date, AccountBalanceSnapshot] = {}
        for balance_observation in observations:
            observation_by_date.setdefault(balance_observation.as_of, balance_observation)

        created: list[tuple[AccountBalanceForecastOutcome, AccountBalanceForecastSnapshot]] = []
        already_evaluated_count = 0
        pending_count = 0
        for snapshot in snapshots:
            for point in points_by_snapshot[snapshot.id]:
                if point.date <= snapshot.cutoff_date or point.date > today:
                    continue
                key = (snapshot.id, point.date)
                if key in existing_keys:
                    already_evaluated_count += 1
                    continue
                matched_observation = observation_by_date.get(point.date)
                if matched_observation is None or point.expected_balance is None:
                    pending_count += 1
                    continue
                actual = self._decimal(matched_observation.amount)
                expected = self._decimal(point.expected_balance)
                low = self._decimal_or_none(point.low_balance)
                high = self._decimal_or_none(point.high_balance)
                signed_error = actual - expected
                outcome = AccountBalanceForecastOutcome(
                    user_id=user_id,
                    financial_account_id=account_id,
                    snapshot_id=snapshot.id,
                    target_date=point.date,
                    actual_observation_id=matched_observation.id,
                    actual_source=matched_observation.source,
                    actual_balance=actual,
                    expected_balance=expected,
                    low_balance=low,
                    high_balance=high,
                    signed_error=signed_error,
                    absolute_error=abs(signed_error),
                    interval_covered=(
                        low <= actual <= high if low is not None and high is not None else None
                    ),
                    predicted_risk=point.risk,
                    outcome_ruleset_version=OUTCOME_RULESET_VERSION,
                )
                try:
                    async with self.db.begin_nested():
                        self.db.add(outcome)
                        await self.db.flush()
                except IntegrityError:
                    already_evaluated_count += 1
                    continue
                created.append((outcome, snapshot))

        await self.db.commit()
        all_outcomes = list(
            (
                await self.db.scalars(
                    select(AccountBalanceForecastOutcome).where(
                        AccountBalanceForecastOutcome.user_id == user_id,
                        AccountBalanceForecastOutcome.snapshot_id.in_(snapshot_ids),
                    )
                )
            ).all()
        )
        interval_values = [
            row.interval_covered for row in all_outcomes if row.interval_covered is not None
        ]
        interval_coverage = (
            sum(1 for value in interval_values if value) / len(interval_values) * 100
            if interval_values
            else None
        )
        percentage_errors: list[float] = []
        for row in all_outcomes:
            value = self._percentage_error(row.actual_balance, row.expected_balance)
            if value is not None:
                percentage_errors.append(value)
        median_percentage_error = self._median(percentage_errors)
        calibration_status = self._calibration_status(
            len(all_outcomes),
            median_percentage_error,
            interval_coverage,
        )
        mean_absolute_error = (
            sum((self._decimal(row.absolute_error) for row in all_outcomes), Decimal("0"))
            / Decimal(len(all_outcomes))
            if all_outcomes
            else None
        )
        return AccountBalanceForecastEvaluationResponse(
            evaluation_version=OUTCOME_RULESET_VERSION,
            evaluated_count=len(created),
            already_evaluated_count=already_evaluated_count,
            pending_count=pending_count,
            interval_coverage_pct=(
                round(interval_coverage, 2) if interval_coverage is not None else None
            ),
            mean_absolute_error=(
                round(float(mean_absolute_error), 2) if mean_absolute_error is not None else None
            ),
            median_absolute_percentage_error=(
                round(median_percentage_error, 2) if median_percentage_error is not None else None
            ),
            calibration_status=calibration_status,
            calibration_thresholds=self._calibration_thresholds(),
            outcomes=[self._outcome_response(outcome, snapshot) for outcome, snapshot in created],
        )

    async def list_outcomes(
        self,
        user_id: str,
        account_id: str,
    ) -> list[AccountBalanceForecastOutcomeResponse]:
        rows = list(
            (
                await self.db.execute(
                    select(AccountBalanceForecastOutcome, AccountBalanceForecastSnapshot)
                    .join(
                        AccountBalanceForecastSnapshot,
                        AccountBalanceForecastSnapshot.id
                        == AccountBalanceForecastOutcome.snapshot_id,
                    )
                    .where(
                        AccountBalanceForecastOutcome.user_id == user_id,
                        AccountBalanceForecastOutcome.financial_account_id == account_id,
                    )
                    .order_by(AccountBalanceForecastOutcome.target_date.desc())
                )
            ).all()
        )
        return [self._outcome_response(outcome, snapshot) for outcome, snapshot in rows]

    async def _find_snapshot(
        self,
        user_id: str,
        account_id: str,
        *,
        cutoff_date: date,
        horizon_days: int,
        ruleset_version: str,
    ) -> AccountBalanceForecastSnapshot | None:
        return await self.db.scalar(
            select(AccountBalanceForecastSnapshot).where(
                AccountBalanceForecastSnapshot.user_id == user_id,
                AccountBalanceForecastSnapshot.financial_account_id == account_id,
                AccountBalanceForecastSnapshot.cutoff_date == cutoff_date,
                AccountBalanceForecastSnapshot.horizon_days == horizon_days,
                AccountBalanceForecastSnapshot.forecast_ruleset_version == ruleset_version,
            )
        )

    async def _require_account(self, user_id: str, account_id: str) -> FinancialAccount:
        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
                FinancialAccount.is_active.is_(True),
            )
        )
        if account is None:
            raise LookupError("Financial account not found")
        return account

    @staticmethod
    def _snapshot_response(
        row: AccountBalanceForecastSnapshot,
    ) -> AccountBalanceForecastSnapshotResponse:
        return AccountBalanceForecastSnapshotResponse(
            id=row.id,
            financial_account_id=row.financial_account_id,
            currency=row.currency,
            balance_kind=cast(Literal["asset", "liability"], row.balance_kind),
            cutoff_date=row.cutoff_date,
            horizon_start=row.horizon_start,
            horizon_end=row.horizon_end,
            horizon_days=row.horizon_days,
            forecast_ruleset_version=row.forecast_ruleset_version,
            status=cast(Literal["ready", "needs_anchor", "needs_review"], row.status),
            starting_balance=(
                float(row.starting_balance) if row.starting_balance is not None else None
            ),
            starting_balance_as_of=row.starting_balance_as_of,
            starting_balance_basis=cast(
                Literal["observed", "estimated"] | None, row.starting_balance_basis
            ),
            expected_ending_balance=(
                float(row.expected_ending_balance)
                if row.expected_ending_balance is not None
                else None
            ),
            expected_change=float(row.expected_change) if row.expected_change is not None else None,
            lowest_expected_balance=(
                float(row.lowest_expected_balance)
                if row.lowest_expected_balance is not None
                else None
            ),
            lowest_expected_date=row.lowest_expected_date,
            first_shortfall_date=row.first_shortfall_date,
            event_count=row.event_count,
            historical_days=row.historical_days,
            historical_activity_count=row.historical_activity_count,
            coverage_status=cast(
                Literal["fresh", "due", "overdue", "unknown"], row.coverage_status
            ),
            position_status=row.position_status,
            position_confidence=float(row.position_confidence),
            confidence=float(row.confidence),
            data_sufficiency=cast(DataSufficiency, row.data_sufficiency),
            position_reason_codes=cast(list[str], json.loads(row.position_reason_codes_json)),
            evidence=[EvidenceItem.model_validate(item) for item in json.loads(row.evidence_json)],
            assumptions=cast(list[str], json.loads(row.assumptions_json)),
            points=[
                AccountBalanceForecastPoint.model_validate(item)
                for item in json.loads(row.points_json)
            ],
            created_at=row.created_at,
        )

    @staticmethod
    def _outcome_response(
        outcome: AccountBalanceForecastOutcome,
        snapshot: AccountBalanceForecastSnapshot,
    ) -> AccountBalanceForecastOutcomeResponse:
        return AccountBalanceForecastOutcomeResponse(
            id=outcome.id,
            snapshot_id=snapshot.id,
            financial_account_id=outcome.financial_account_id,
            target_date=outcome.target_date,
            cutoff_date=snapshot.cutoff_date,
            actual_observation_id=outcome.actual_observation_id,
            actual_source=outcome.actual_source,
            actual_balance=float(outcome.actual_balance),
            expected_balance=float(outcome.expected_balance),
            low_balance=float(outcome.low_balance) if outcome.low_balance is not None else None,
            high_balance=float(outcome.high_balance) if outcome.high_balance is not None else None,
            signed_error=float(outcome.signed_error),
            absolute_error=float(outcome.absolute_error),
            interval_covered=outcome.interval_covered,
            predicted_risk=cast(
                Literal["none", "watch", "shortfall", "limit_pressure"],
                outcome.predicted_risk,
            ),
            forecast_ruleset_version=snapshot.forecast_ruleset_version,
            outcome_ruleset_version=outcome.outcome_ruleset_version,
            evaluated_at=outcome.evaluated_at,
        )

    @staticmethod
    def _decimal(value: object) -> Decimal:
        return Decimal(str(value))

    @staticmethod
    def _decimal_or_none(value: object | None) -> Decimal | None:
        return Decimal(str(value)) if value is not None else None

    @staticmethod
    def _percentage_error(actual: Decimal, expected: Decimal) -> float | None:
        denominator = abs(expected)
        if denominator == 0:
            return None
        return float(abs(actual - expected) / denominator * Decimal("100"))

    @staticmethod
    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    @classmethod
    def _calibration_status(
        cls,
        outcome_count: int,
        median_percentage_error: float | None,
        interval_coverage: float | None,
    ) -> Literal["insufficient_sample", "within_threshold", "drift"]:
        if (
            outcome_count < MINIMUM_CALIBRATION_OUTCOMES
            or median_percentage_error is None
            or interval_coverage is None
        ):
            return "insufficient_sample"
        if (
            median_percentage_error > MAXIMUM_MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_PCT
            or interval_coverage < MINIMUM_INTERVAL_COVERAGE_PCT
        ):
            return "drift"
        return "within_threshold"

    @staticmethod
    def _calibration_thresholds() -> dict[str, float]:
        return {
            "maximum_median_absolute_percentage_error_pct": MAXIMUM_MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_PCT,
            "minimum_interval_coverage_pct": MINIMUM_INTERVAL_COVERAGE_PCT,
            "minimum_outcomes": float(MINIMUM_CALIBRATION_OUTCOMES),
        }
