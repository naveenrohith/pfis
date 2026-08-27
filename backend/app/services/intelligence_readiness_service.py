"""Build a user-scoped view of the evidence gates behind PFIS intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import CardPaymentIntent, StatementLine
from app.models.forecast import AccountBalanceForecastOutcome, AccountBalanceForecastSnapshot
from app.models.temporal_history import TemporalSourceSnapshot
from app.models.transaction import Transaction
from app.schemas.operational import (
    ForecastReadiness,
    IntelligenceReadinessGate,
    IntelligenceReadinessResponse,
    IntelligenceReadinessStatus,
    ReconciliationQualityResponse,
    TemporalHistoryReadiness,
)
from app.services.anomaly_adjudication_service import AnomalyAdjudicationService
from app.services.intelligence_service import IntelligenceService
from app.services.recommendation_evaluation_service import RecommendationEvaluationService
from app.services.reconciliation_quality_service import ReconciliationQualityService

MIN_FORECAST_PERIODS = 3
MIN_FORECAST_INTERVAL_COVERAGE_PCT = 70.0
MAX_FORECAST_MAPE_PCT = 20.0
MIN_TRANSACTION_HISTORY_COVERAGE_PCT = 95.0
MIN_DAILY_FORECAST_OUTCOMES = 3


@dataclass(frozen=True)
class DailyForecastMetrics:
    """Prospective account-path evidence observed for one user."""

    snapshot_count: int
    outcome_count: int
    interval_coverage_pct: float | None
    mean_absolute_error: float | None


class IntelligenceReadinessService:
    """Expose evidence status without turning missing proof into confidence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def report(self, user_id: str) -> IntelligenceReadinessResponse:
        intelligence = IntelligenceService(self.db)
        coverage = await intelligence.source_coverage(user_id)
        backtest = await intelligence.cash_flow_backtest(user_id, months=6)
        daily = await self._daily_forecast_metrics(user_id)
        temporal_history = await self._temporal_history(user_id)
        reconciliation_report = await ReconciliationQualityService(self.db).report(user_id)
        anomaly_summary = await AnomalyAdjudicationService(self.db).summary(user_id)
        recommendation_report = await RecommendationEvaluationService(
            self.db
        ).effectiveness_report()

        eligible_horizons = [
            horizon
            for horizon in backtest.horizons
            if horizon.eligible_periods >= MIN_FORECAST_PERIODS
            and horizon.median_absolute_percentage_error is not None
        ]
        maximum_mape = max(
            (
                horizon.median_absolute_percentage_error
                for horizon in eligible_horizons
                if horizon.median_absolute_percentage_error is not None
            ),
            default=0.0,
        )
        interval_coverage = min(
            (
                horizon.interval_coverage_pct
                for horizon in eligible_horizons
                if horizon.interval_coverage_pct is not None
            ),
            default=0.0,
        )
        forecast = ForecastReadiness(
            evaluated_months=backtest.evaluated_months,
            eligible_horizons=len(eligible_horizons),
            interval_coverage_floor_pct=round(interval_coverage, 2),
            maximum_mape_pct=round(maximum_mape, 2),
            temporal_evidence_evaluated=backtest.temporal_evidence_evaluated,
            transaction_history_coverage_pct=backtest.transaction_history_coverage_pct,
            category_mix_supported_periods=int(
                getattr(backtest, "category_mix_supported_periods", 0)
            ),
            daily_snapshot_count=daily.snapshot_count,
            daily_outcome_count=daily.outcome_count,
            daily_interval_coverage_pct=daily.interval_coverage_pct,
            daily_mean_absolute_error=daily.mean_absolute_error,
        )

        gates = [
            self._source_gate(coverage.overall_score),
            self._temporal_gate(temporal_history),
            self._forecast_gate(forecast),
            self._reconciliation_gate(reconciliation_report),
            self._recommendation_gate(recommendation_report.evidence_status),
            self._anomaly_gate(anomaly_summary),
            IntelligenceReadinessGate(
                key="representative_release",
                label="Representative release evidence",
                status="deferred",
                summary="Parser cohorts, hosted operations, and cross-user forecast/recommendation evidence are release-level proof, not personal-account signals.",
                next_step="Run the strict intelligence release gate with production-safe cohort artifacts before promoting rules.",
                target="pipeline",
                evidence=[
                    "No user-facing score is inferred from synthetic or sanitized fixtures.",
                    "Hosted incident and drift evidence remains deployment-owned.",
                ],
            ),
        ]
        evidence_readiness_score = self._score(gates)
        overall_status = self._overall_status(gates)

        return IntelligenceReadinessResponse(
            as_of=datetime.now(UTC),
            overall_status=overall_status,
            evidence_readiness_score=evidence_readiness_score,
            source_coverage_score=coverage.overall_score,
            temporal_history=temporal_history,
            forecast=forecast,
            reconciliation=ReconciliationQualityService.readiness(reconciliation_report),
            recommendation_evidence_status=self._status_for_recommendations(
                recommendation_report.evidence_status
            ),
            gates=gates,
            assumptions=[
                "This is a readiness and recovery view, not a claim that PFIS has reached 70% intelligence.",
                "User-scoped history measures records PFIS has observed; it cannot prove an external provider is complete.",
                "Forward-only snapshots improve future evaluation coverage but cannot reconstruct prior knowledge.",
                "Reconciliation quality is bounded by rows, statement lines, and verified balance snapshots PFIS has observed.",
                "Representative release gates remain aggregate and privacy-protected.",
                "Daily account-path outcomes are exact-date verified observations; missing points are not imputed.",
            ],
        )

    async def _daily_forecast_metrics(self, user_id: str) -> DailyForecastMetrics:
        snapshot_count = int(
            await self.db.scalar(
                select(func.count(AccountBalanceForecastSnapshot.id)).where(
                    AccountBalanceForecastSnapshot.user_id == user_id
                )
            )
            or 0
        )
        outcomes = list(
            (
                await self.db.scalars(
                    select(AccountBalanceForecastOutcome).where(
                        AccountBalanceForecastOutcome.user_id == user_id
                    )
                )
            ).all()
        )
        interval_values = [
            bool(outcome.interval_covered)
            for outcome in outcomes
            if outcome.interval_covered is not None
        ]
        interval_coverage_pct = (
            round(sum(interval_values) / len(interval_values) * 100.0, 2)
            if interval_values
            else None
        )
        mean_absolute_error = (
            round(
                sum(float(outcome.absolute_error) for outcome in outcomes) / len(outcomes),
                2,
            )
            if outcomes
            else None
        )
        return DailyForecastMetrics(
            snapshot_count=snapshot_count,
            outcome_count=len(outcomes),
            interval_coverage_pct=interval_coverage_pct,
            mean_absolute_error=mean_absolute_error,
        )

    async def _temporal_history(self, user_id: str) -> TemporalHistoryReadiness:
        transaction_rows = int(
            await self.db.scalar(
                select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
            )
            or 0
        )
        transaction_snapshots = int(
            await self.db.scalar(
                select(func.count(func.distinct(TemporalSourceSnapshot.source_id))).where(
                    TemporalSourceSnapshot.user_id == user_id,
                    TemporalSourceSnapshot.source_type == "transaction",
                )
            )
            or 0
        )
        account_rows = int(
            await self.db.scalar(
                select(func.count(FinancialAccount.id)).where(FinancialAccount.user_id == user_id)
            )
            or 0
        )
        account_snapshots = int(
            await self.db.scalar(
                select(func.count(func.distinct(TemporalSourceSnapshot.source_id))).where(
                    TemporalSourceSnapshot.user_id == user_id,
                    TemporalSourceSnapshot.source_type == "financial_account",
                )
            )
            or 0
        )
        statement_line_rows = int(
            await self.db.scalar(
                select(func.count(StatementLine.id)).where(StatementLine.user_id == user_id)
            )
            or 0
        )
        statement_line_snapshots = int(
            await self.db.scalar(
                select(func.count(func.distinct(TemporalSourceSnapshot.source_id))).where(
                    TemporalSourceSnapshot.user_id == user_id,
                    TemporalSourceSnapshot.source_type == "statement_line",
                )
            )
            or 0
        )
        card_payment_intent_rows = int(
            await self.db.scalar(
                select(func.count(CardPaymentIntent.id)).where(CardPaymentIntent.user_id == user_id)
            )
            or 0
        )
        card_payment_intent_snapshots = int(
            await self.db.scalar(
                select(func.count(func.distinct(TemporalSourceSnapshot.source_id))).where(
                    TemporalSourceSnapshot.user_id == user_id,
                    TemporalSourceSnapshot.source_type == "card_payment_intent",
                )
            )
            or 0
        )

        return TemporalHistoryReadiness(
            transaction_rows=transaction_rows,
            transaction_snapshots=min(transaction_snapshots, transaction_rows),
            transaction_coverage_pct=self._coverage(transaction_snapshots, transaction_rows),
            account_rows=account_rows,
            account_snapshots=min(account_snapshots, account_rows),
            account_coverage_pct=self._coverage(account_snapshots, account_rows),
            statement_line_rows=statement_line_rows,
            statement_line_snapshots=min(statement_line_snapshots, statement_line_rows),
            statement_line_coverage_pct=self._coverage(
                statement_line_snapshots, statement_line_rows
            ),
            card_payment_intent_rows=card_payment_intent_rows,
            card_payment_intent_snapshots=min(
                card_payment_intent_snapshots, card_payment_intent_rows
            ),
            card_payment_intent_coverage_pct=self._coverage(
                card_payment_intent_snapshots, card_payment_intent_rows
            ),
        )

    @staticmethod
    def _coverage(captured: int, total: int) -> float:
        return round(captured / total * 100.0, 2) if total else 100.0

    @staticmethod
    def _source_gate(score: int) -> IntelligenceReadinessGate:
        if score >= 80:
            return IntelligenceReadinessGate(
                key="source_coverage",
                label="Observed source coverage",
                status="ready",
                summary=f"Observed source coverage is {score}/100 for this workspace.",
                next_step="Keep the connector current and resolve new source gaps as they appear.",
                target="inbox",
                evidence=["Coverage is weighted across Gmail, ledger, accounts, and processing."],
            )
        return IntelligenceReadinessGate(
            key="source_coverage",
            label="Observed source coverage",
            status="collecting",
            summary=f"Only {score}/100 of the observed source contract is currently covered.",
            next_step="Connect or sync the declared source, import more history, and confirm account identities.",
            target="inbox",
            evidence=["Observed records are not the same as provider-complete history."],
        )

    @staticmethod
    def _temporal_gate(history: TemporalHistoryReadiness) -> IntelligenceReadinessGate:
        transaction_ready = history.transaction_coverage_pct >= 100
        account_ready = history.account_coverage_pct >= 100
        statement_ready = history.statement_line_coverage_pct >= 100
        payment_intent_ready = history.card_payment_intent_coverage_pct >= 100
        if transaction_ready and account_ready and statement_ready and payment_intent_ready:
            status: IntelligenceReadinessStatus = "ready"
            summary = "All currently observed transaction, account, issuer-line, and card-payment-intent rows have immutable source snapshots."
            next_step = "Keep normal mutation hooks enabled so future changes append new evidence."
        else:
            status = "collecting"
            summary = (
                f"Temporal history covers {history.transaction_coverage_pct:.0f}% of transactions and "
                f"{history.account_coverage_pct:.0f}% of account rows, plus "
                f"{history.statement_line_coverage_pct:.0f}% of issuer lines and "
                f"{history.card_payment_intent_coverage_pct:.0f}% of card-payment intentions."
            )
            next_step = "Preview and capture the forward-only baseline in Data & settings, including issuer lines when available."
        return IntelligenceReadinessGate(
            key="temporal_history",
            label="Historical evidence coverage",
            status=status,
            summary=summary,
            next_step=next_step,
            target="settings",
            evidence=[
                f"Transactions: {history.transaction_snapshots}/{history.transaction_rows} rows",
                f"Accounts: {history.account_snapshots}/{history.account_rows} rows",
                f"Issuer lines: {history.statement_line_snapshots}/{history.statement_line_rows} rows",
                "Card-payment intentions: "
                f"{history.card_payment_intent_snapshots}/{history.card_payment_intent_rows} rows",
                "Baseline capture is forward-only.",
            ],
        )

    @staticmethod
    def _forecast_gate(forecast: ForecastReadiness) -> IntelligenceReadinessGate:
        if forecast.eligible_horizons == 0:
            return IntelligenceReadinessGate(
                key="forecast_calibration",
                label="Forecast calibration",
                status="collecting",
                summary="There is not yet a sufficient rolling history to evaluate a forecast horizon.",
                next_step="Keep settled history and temporal snapshots accruing until at least three comparable periods mature.",
                target="analytics",
                evidence=[f"Evaluated months: {forecast.evaluated_months}"],
            )
        daily_outcomes_missing = forecast.daily_outcome_count < MIN_DAILY_FORECAST_OUTCOMES
        daily_intervals_missing = (
            forecast.daily_outcome_count > 0 and forecast.daily_interval_coverage_pct is None
        )
        daily_intervals_below_floor = (
            forecast.daily_interval_coverage_pct is not None
            and forecast.daily_interval_coverage_pct < MIN_FORECAST_INTERVAL_COVERAGE_PCT
        )
        failing = (
            forecast.maximum_mape_pct > MAX_FORECAST_MAPE_PCT
            or forecast.interval_coverage_floor_pct < MIN_FORECAST_INTERVAL_COVERAGE_PCT
            or not forecast.temporal_evidence_evaluated
            or forecast.transaction_history_coverage_pct < MIN_TRANSACTION_HISTORY_COVERAGE_PCT
            or daily_outcomes_missing
            or daily_intervals_missing
            or daily_intervals_below_floor
        )
        evidence_only = daily_outcomes_missing or daily_intervals_missing
        status: IntelligenceReadinessStatus = (
            "collecting" if evidence_only else "blocked" if failing else "ready"
        )
        return IntelligenceReadinessGate(
            key="forecast_calibration",
            label="Forecast calibration",
            status=status,
            summary=(
                f"{forecast.eligible_horizons} horizon(s) evaluated; maximum MAPE {forecast.maximum_mape_pct:.1f}% and minimum interval coverage {forecast.interval_coverage_floor_pct:.1f}%. "
                f"Daily accountability has {forecast.daily_outcome_count} exact-date outcome(s) from {forecast.daily_snapshot_count} frozen snapshot(s)."
            ),
            next_step=(
                "Keep the forecast in evidence mode and collect at least three exact-date verified daily outcomes before promotion."
                if evidence_only
                else (
                    "Keep the forecast in evidence mode and collect better temporal history before promotion."
                    if failing
                    else "Continue prospective snapshots and outcome evaluation to protect calibration over time."
                )
            ),
            target="analytics",
            evidence=[
                f"Temporal evidence evaluated: {'yes' if forecast.temporal_evidence_evaluated else 'no'}",
                f"Transaction history coverage: {forecast.transaction_history_coverage_pct:.1f}%",
                f"Category-mix supported periods: {forecast.category_mix_supported_periods}",
                f"Daily interval coverage: {forecast.daily_interval_coverage_pct if forecast.daily_interval_coverage_pct is not None else 'not evaluated'}",
                f"Daily mean absolute error: {forecast.daily_mean_absolute_error if forecast.daily_mean_absolute_error is not None else 'not evaluated'}",
                "Daily outcomes are workspace evidence; representative release proof remains aggregate and privacy-protected.",
            ],
        )

    @staticmethod
    def _recommendation_gate(evidence_status: str) -> IntelligenceReadinessGate:
        status: IntelligenceReadinessStatus = (
            "ready" if evidence_status == "available" else "collecting"
        )
        return IntelligenceReadinessGate(
            key="recommendation_outcomes",
            label="Recommendation outcomes",
            status=status,
            summary=(
                "Privacy-safe recommendation cohorts have cleared their minimum evidence threshold."
                if status == "ready"
                else "Recommendation outcomes are still below the privacy-safe cohort threshold."
            ),
            next_step=(
                "Monitor measured impact and reported direction separately."
                if status == "ready"
                else "Collect immutable outcomes from enough independent users before adapting ranking rules."
            ),
            target="guidance",
            evidence=["Small cohorts remain hidden by design."],
        )

    @staticmethod
    def _anomaly_gate(summary: dict[str, int]) -> IntelligenceReadinessGate:
        count = summary.get("total", 0)
        if count:
            return IntelligenceReadinessGate(
                key="anomaly_quality",
                label="Anomaly adjudication",
                status="collecting",
                summary=(
                    f"{count} user-owned anomaly decision(s) are captured, but release-quality evidence still requires a protected cross-user cohort."
                ),
                next_step="Continue adjudicating expected and material departures, then export aggregate cases through the protected evaluator.",
                target="insights",
                evidence=[
                    f"Expected: {summary.get('expected', 0)}",
                    f"Material: {summary.get('material', 0)}",
                    f"Insufficient evidence: {summary.get('insufficient_evidence', 0)}",
                    "Release gate: minimum 50 adjudicated cases",
                ],
            )
        return IntelligenceReadinessGate(
            key="anomaly_quality",
            label="Anomaly adjudication",
            status="deferred",
            summary="Runtime anomaly prompts are bounded, but no explicit adjudication has been captured in this workspace.",
            next_step="Use the anomaly review controls to label departures as expected, material, or insufficient evidence.",
            target="insights",
            evidence=[
                "Ruleset: pfis-anomaly-2 (24-month robust baseline with same-calendar-month seasonality)",
                "Release gate: minimum 50 adjudicated cases",
            ],
        )

    @staticmethod
    def _reconciliation_gate(report: ReconciliationQualityResponse) -> IntelligenceReadinessGate:
        status: IntelligenceReadinessStatus = report.status
        if status == "ready":
            summary = f"Observed ledger and statement evidence is resolved at {report.evidence_score}/100."
            next_step = (
                "Keep review outcomes and verified balance snapshots current as new sources arrive."
            )
        elif status == "blocked":
            summary = f"{report.unexplained_movements} balance movement(s) remain unexplained after observed ledger activity."
            next_step = "Resolve unexplained movements and duplicate candidates before using downstream intelligence as settled truth."
        else:
            summary = f"Observed reconciliation evidence is {report.evidence_score}/100 with {report.unresolved_items} unresolved item(s)."
            next_step = "Review pending transactions and statement lines, then capture a second verified balance snapshot."
        return IntelligenceReadinessGate(
            key="reconciliation_quality",
            label="Cross-source reconciliation",
            status=status,
            summary=summary,
            next_step=next_step,
            target="review",
            evidence=[
                f"Transaction review coverage: {report.transaction_review_coverage_pct:.1f}%",
                f"Statement resolution coverage: {report.statement_resolution_coverage_pct:.1f}%",
                f"Account reconciliation coverage: {report.account_reconciliation_coverage_pct:.1f}%",
                f"Duplicate candidate groups: {report.duplicate_candidate_groups}",
            ],
        )

    @staticmethod
    def _status_for_recommendations(evidence_status: str) -> IntelligenceReadinessStatus:
        return "ready" if evidence_status == "available" else "collecting"

    @staticmethod
    def _score(gates: list[IntelligenceReadinessGate]) -> int:
        weights = {
            "source_coverage": 20,
            "temporal_history": 15,
            "forecast_calibration": 25,
            "reconciliation_quality": 15,
            "recommendation_outcomes": 15,
            "anomaly_quality": 5,
            "representative_release": 5,
        }
        status_values = {"ready": 100, "collecting": 50, "blocked": 0, "deferred": 0}
        return round(
            sum(weights.get(gate.key, 0) * status_values[gate.status] for gate in gates) / 100
        )

    @staticmethod
    def _overall_status(gates: list[IntelligenceReadinessGate]) -> IntelligenceReadinessStatus:
        statuses = {gate.status for gate in gates}
        if "blocked" in statuses:
            return "blocked"
        if "collecting" in statuses:
            return "collecting"
        if "deferred" in statuses:
            return "deferred"
        return "ready"
