"""Account-level daily balance forecasting from the canonical position model.

This service intentionally stays deterministic and evidence-labelled.  It does
not attempt to manufacture a provider balance: the path starts at the latest
observed/estimated position, applies explicit dated evidence, and uses a small
settled-activity baseline only as a clearly marked uncertainty-bearing signal.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import (
    CardPaymentIntent,
    CashPlan,
    Commitment,
    CreditCardStatement,
    Liability,
    LiabilityScheduleItem,
)
from app.models.transaction import CardEvent, Transaction
from app.schemas.balance_forecast import (
    AccountBalanceForecastPoint,
    AccountBalanceForecastResponse,
    ForecastRisk,
    ForecastStatus,
)
from app.schemas.intelligence import DataSufficiency, EvidenceItem
from app.services.financial_clock import user_financial_today
from app.services.financial_position_service import FinancialPositionService
from app.services.transaction_aggregates import (
    balance_transaction_eligible,
    signed_balance_movement,
)

RULESET_VERSION = "pfis-account-balance-forecast-1"
HISTORY_WINDOW_DAYS = 180
BASELINE_RANGE_WIDTH = Decimal("0.35")


@dataclass(frozen=True)
class _ForecastEvent:
    event_date: date
    amount: Decimal
    increases_balance: bool
    confidence: Decimal
    evidence_id: str


class BalanceForecastService:
    """Build a daily path for one owned financial account."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def forecast(
        self,
        user_id: str,
        account_id: str,
        *,
        horizon_days: int = 30,
        as_of: date | None = None,
    ) -> AccountBalanceForecastResponse | None:
        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
                FinancialAccount.is_active.is_(True),
            )
        )
        if account is None:
            return None

        horizon_days = max(1, min(horizon_days, 180))
        horizon_start = as_of or await user_financial_today(self.db, user_id)
        horizon_end = horizon_start + timedelta(days=horizon_days)
        position = await FinancialPositionService(self.db).account_position(
            user_id, account_id, as_of=as_of
        )
        starting_balance: Decimal | None = None
        starting_basis: str | None = None
        starting_as_of: date | None = None
        if position is not None:
            if position.estimated_balance is not None:
                starting_balance = self._decimal(position.estimated_balance)
                starting_basis = "estimated"
                starting_as_of = position.estimated_as_of
            elif position.verified_balance is not None:
                starting_balance = self._decimal(position.verified_balance)
                starting_basis = "observed"
                starting_as_of = position.balance_as_of

        position_status = position.position_status if position is not None else "needs_observation"
        position_confidence = position.position_confidence if position is not None else 0.0
        coverage_status = position.coverage_status if position is not None else "unknown"
        observed_anchor_as_of = position.observed_as_of if position is not None else None
        position_reasons = (
            list(position.position_reason_codes)
            if position is not None
            else ["verified_observation_required"]
        )
        if (
            observed_anchor_as_of is not None
            and horizon_start - observed_anchor_as_of > timedelta(days=7)
            and "balance_observation_stale" not in position_reasons
        ):
            position_reasons.append("balance_observation_stale")
            if position_status in {"observed", "estimated"}:
                position_status = "stale"
        forecast_status = self._forecast_status(starting_balance, position_status)

        history_start = horizon_start - timedelta(days=HISTORY_WINDOW_DAYS)
        transactions = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.financial_account_id == account_id,
                        Transaction.currency == account.currency,
                        Transaction.transaction_date >= history_start,
                        Transaction.transaction_date <= horizon_start,
                    )
                )
            ).all()
        )
        settled_activity = [
            transaction
            for transaction in transactions
            if balance_transaction_eligible(transaction)
            and not transaction.is_transfer
            and not transaction.is_accounting_adjustment
            and transaction.card_event != CardEvent.PAYMENT
            and transaction.reviewed_flag
            and transaction.review_outcome != "needs_review"
        ]
        history_days = (horizon_start - history_start).days + 1
        history_increase = Decimal("0")
        history_decrease = Decimal("0")
        for transaction in settled_activity:
            movement = signed_balance_movement(transaction, account.balance_kind)
            if movement >= 0:
                history_increase += movement
            else:
                history_decrease += -movement

        # Do not forecast a behavioural baseline from a tiny sample.  Explicit
        # dated evidence remains useful even when the account has no history.
        baseline_enabled = len(settled_activity) >= 3
        baseline_daily_increase = (
            history_increase / Decimal(history_days) if baseline_enabled else Decimal("0")
        )
        baseline_daily_decrease = (
            history_decrease / Decimal(history_days) if baseline_enabled else Decimal("0")
        )

        events = await self._dated_events(
            user_id,
            account,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            as_of=as_of,
        )
        events_by_day: dict[date, list[_ForecastEvent]] = defaultdict(list)
        for event in events:
            # The starting point already includes eligible settled activity
            # through today.  Future dates are the only safe place to apply a
            # planned event; this prevents same-day double counting.
            if event.event_date > horizon_start:
                events_by_day[event.event_date].append(event)

        if starting_balance is None:
            return AccountBalanceForecastResponse(
                financial_account_id=account.id,
                account_type=account.account_type,
                institution_name=account.institution_name,
                masked_number=account.masked_number,
                currency=account.currency,
                balance_kind=cast(Literal["asset", "liability"], account.balance_kind),
                status="needs_anchor",
                horizon_start=horizon_start,
                horizon_end=horizon_end,
                horizon_days=horizon_days,
                starting_balance=None,
                starting_balance_as_of=None,
                starting_balance_basis=None,
                expected_ending_balance=None,
                expected_change=None,
                lowest_expected_balance=None,
                lowest_expected_date=None,
                first_shortfall_date=None,
                event_count=len(events),
                historical_days=history_days,
                historical_activity_count=len(settled_activity),
                coverage_status=coverage_status,
                position_status=position_status,
                position_confidence=position_confidence,
                confidence=0.0,
                data_sufficiency="low",
                position_reason_codes=position_reasons,
                assumptions=[
                    "A verified or provider-observed balance is required before PFIS can draw a numeric future path.",
                    "Transaction history and dated obligations remain visible as evidence but do not become a balance without an anchor.",
                ],
                evidence=[
                    EvidenceItem(label="Starting position", value="No verified observation"),
                    EvidenceItem(
                        label="Dated evidence",
                        value=f"{len(events)} future event(s) found",
                    ),
                ],
                points=[],
                ruleset_version=RULESET_VERSION,
            )

        points: list[AccountBalanceForecastPoint] = []
        current = starting_balance
        scheduled_increase_total = Decimal("0")
        scheduled_decrease_total = Decimal("0")
        baseline_increase_total = Decimal("0")
        baseline_decrease_total = Decimal("0")
        lowest_expected: Decimal | None = None
        lowest_date: date | None = None
        first_shortfall: date | None = None
        credit_limit = await self._credit_limit(user_id, account, as_of=as_of)

        for offset in range(horizon_days + 1):
            current_date = horizon_start + timedelta(days=offset)
            day_events = events_by_day.get(current_date, [])
            scheduled_increase = sum(
                (event.amount for event in day_events if event.increases_balance),
                Decimal("0"),
            )
            scheduled_decrease = sum(
                (event.amount for event in day_events if not event.increases_balance),
                Decimal("0"),
            )

            # An explicit dated event takes precedence over a history-derived
            # daily rate on that side, preventing salary/payment double counts.
            baseline_increase = (
                baseline_daily_increase
                if baseline_enabled and not any(event.increases_balance for event in day_events)
                else Decimal("0")
            )
            baseline_decrease = (
                baseline_daily_decrease
                if baseline_enabled and not any(not event.increases_balance for event in day_events)
                else Decimal("0")
            )
            if offset > 0:
                current += scheduled_increase - scheduled_decrease
                current += baseline_increase - baseline_decrease

            # The interval is intentionally a numeric uncertainty band, not a
            # provider claim.  Behavioural history is the dominant uncertainty;
            # dated events widen it according to their confidence.
            uncertainty = (baseline_increase + baseline_decrease) * BASELINE_RANGE_WIDTH
            uncertainty += sum(
                (
                    event.amount
                    * (Decimal("1") - max(Decimal("0"), min(event.confidence, Decimal("1"))))
                    * Decimal("0.5")
                    for event in day_events
                ),
                Decimal("0"),
            )
            expected = current
            low = expected - uncertainty
            high = expected + uncertainty
            if account.balance_kind == "liability":
                expected = max(expected, Decimal("0"))
                low = max(low, Decimal("0"))
                high = max(high, Decimal("0"))

            if offset > 0:
                scheduled_increase_total += scheduled_increase
                scheduled_decrease_total += scheduled_decrease
                baseline_increase_total += baseline_increase
                baseline_decrease_total += baseline_decrease

            risk_reasons: list[str] = []
            risk: ForecastRisk = "none"
            if account.balance_kind == "asset" and low < 0:
                risk = "shortfall"
                risk_reasons.append("projected_cash_shortfall")
                first_shortfall = first_shortfall or current_date
            elif (
                account.balance_kind == "liability"
                and credit_limit is not None
                and high > credit_limit
            ):
                risk = "limit_pressure"
                risk_reasons.append("projected_credit_limit_pressure")
            elif forecast_status == "needs_review":
                risk = "watch"
                risk_reasons.extend(position_reasons or ["position_needs_review"])

            if lowest_expected is None or expected < lowest_expected:
                lowest_expected = expected
                lowest_date = current_date
            points.append(
                AccountBalanceForecastPoint(
                    date=current_date,
                    expected_balance=self._rounded_float(expected),
                    low_balance=self._rounded_float(low),
                    high_balance=self._rounded_float(high),
                    scheduled_increase=self._required_float(scheduled_increase),
                    scheduled_decrease=self._required_float(scheduled_decrease),
                    baseline_increase=self._required_float(baseline_increase),
                    baseline_decrease=self._required_float(baseline_decrease),
                    event_count=len(day_events),
                    evidence_ids=[event.evidence_id for event in day_events],
                    risk=risk,
                    risk_reasons=list(dict.fromkeys(risk_reasons)),
                )
            )

        expected_ending = points[-1].expected_balance if points else None
        expected_change = (
            Decimal(str(expected_ending)) - starting_balance
            if expected_ending is not None
            else None
        )
        history_sufficiency = self._data_sufficiency(
            len(settled_activity), history_days, baseline_enabled
        )
        event_confidence = (
            sum((event.confidence for event in events), Decimal("0")) / Decimal(len(events))
            if events
            else Decimal("0")
        )
        confidence = min(
            Decimal("0.95"),
            max(
                Decimal("0.05"),
                self._decimal(position_confidence) * Decimal("0.60")
                + (Decimal("0.20") if baseline_enabled else Decimal("0"))
                + event_confidence * Decimal("0.20"),
            ),
        )
        assumptions = [
            "The path starts at PFIS's observed or transaction-derived estimated position; it is not a provider live balance.",
            "Only settled, non-transfer, non-accounting activity informs the historical baseline; pending and unreviewed rows are not silently applied.",
            "Confirmed commitments, mapped card-payment intentions, explicit income plans, and sourced liability schedules are dated evidence—not guaranteed settlement.",
            "The low/high band represents uncertainty in behavioural and dated evidence; it is not an issuer available-balance or credit-limit calculation.",
        ]
        if baseline_enabled:
            assumptions.append(
                f"The behavioural baseline uses {len(settled_activity)} settled account events across a {history_days}-day lookback."
            )
        else:
            assumptions.append(
                "There are fewer than three settled account events in the lookback, so the path uses dated evidence only."
            )
        if forecast_status == "needs_review":
            assumptions.append(
                "The starting position has coverage or reconciliation limitations; forecast risk remains reviewable rather than silently safe."
            )

        return AccountBalanceForecastResponse(
            financial_account_id=account.id,
            account_type=account.account_type,
            institution_name=account.institution_name,
            masked_number=account.masked_number,
            currency=account.currency,
            balance_kind=cast(Literal["asset", "liability"], account.balance_kind),
            status=cast(ForecastStatus, forecast_status),
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            horizon_days=horizon_days,
            starting_balance=self._rounded_float(starting_balance),
            starting_balance_as_of=starting_as_of,
            starting_balance_basis=cast(Literal["observed", "estimated"], starting_basis),
            expected_ending_balance=expected_ending,
            expected_change=self._rounded_float(expected_change),
            lowest_expected_balance=self._rounded_float(lowest_expected),
            lowest_expected_date=lowest_date,
            first_shortfall_date=first_shortfall,
            scheduled_increase_total=self._required_float(scheduled_increase_total),
            scheduled_decrease_total=self._required_float(scheduled_decrease_total),
            baseline_increase_total=self._required_float(baseline_increase_total),
            baseline_decrease_total=self._required_float(baseline_decrease_total),
            event_count=len(events),
            historical_days=history_days,
            historical_activity_count=len(settled_activity),
            coverage_status=coverage_status,
            position_status=position_status,
            position_confidence=position_confidence,
            confidence=self._required_float(confidence),
            data_sufficiency=cast(DataSufficiency, history_sufficiency),
            position_reason_codes=position_reasons,
            assumptions=assumptions,
            evidence=[
                EvidenceItem(
                    label="Starting position",
                    value=(f"{starting_basis} · {starting_as_of or horizon_start}"),
                ),
                EvidenceItem(
                    label="Settled history",
                    value=f"{len(settled_activity)} eligible event(s) · {history_days}-day lookback",
                ),
                EvidenceItem(
                    label="Dated evidence",
                    value=f"{len(events)} event(s) across the {horizon_days}-day horizon",
                ),
                EvidenceItem(
                    label="Coverage",
                    value=f"{coverage_status} · {position_status}",
                ),
            ],
            points=points,
            ruleset_version=RULESET_VERSION,
        )

    async def _dated_events(
        self,
        user_id: str,
        account: FinancialAccount,
        *,
        horizon_start: date,
        horizon_end: date,
        as_of: date | None,
    ) -> list[_ForecastEvent]:
        events: list[_ForecastEvent] = []
        cutoff_at = datetime.combine(
            horizon_start,
            time.max,
            tzinfo=UTC,
        )
        cash_plan = await self.db.scalar(
            select(CashPlan).where(
                CashPlan.user_id == user_id,
                CashPlan.primary_financial_account_id == account.id,
                *([CashPlan.updated_at <= cutoff_at] if as_of is not None else []),
            )
        )
        if (
            account.balance_kind == "asset"
            and cash_plan is not None
            and cash_plan.next_income_date is not None
            and cash_plan.next_income_amount is not None
            and horizon_start < cash_plan.next_income_date <= horizon_end
        ):
            events.append(
                _ForecastEvent(
                    event_date=cash_plan.next_income_date,
                    amount=self._decimal(cash_plan.next_income_amount),
                    increases_balance=True,
                    confidence=Decimal("0.90"),
                    evidence_id=f"cash_plan:{cash_plan.id}:income",
                )
            )

        commitments = list(
            (
                await self.db.scalars(
                    select(Commitment).where(
                        Commitment.user_id == user_id,
                        Commitment.is_active.is_(True),
                        Commitment.confirmed.is_(True),
                        *([Commitment.created_at <= cutoff_at] if as_of is not None else []),
                        Commitment.due_date > horizon_start,
                        Commitment.due_date <= horizon_end,
                    )
                )
            ).all()
        )
        # Keep the global-commitment branch in Python: a commitment with no
        # funding account belongs to the configured Cash Plan account only.
        for commitment in commitments:
            if commitment.financial_account_id not in {None, account.id}:
                continue
            if commitment.financial_account_id is None and (
                cash_plan is None or cash_plan.primary_financial_account_id != account.id
            ):
                continue
            if account.balance_kind != "asset":
                continue
            events.append(
                _ForecastEvent(
                    event_date=commitment.due_date,
                    amount=self._decimal(commitment.amount),
                    increases_balance=False,
                    confidence=(
                        Decimal("0.98")
                        if commitment.source_kind in {"statement", "connector"}
                        else Decimal("0.90")
                    ),
                    evidence_id=f"commitment:{commitment.id}",
                )
            )

        payment_intents = list(
            (
                await self.db.scalars(
                    select(CardPaymentIntent).where(
                        CardPaymentIntent.user_id == user_id,
                        *([CardPaymentIntent.created_at <= cutoff_at] if as_of is not None else []),
                        CardPaymentIntent.planned_for > horizon_start,
                        CardPaymentIntent.planned_for <= horizon_end,
                        CardPaymentIntent.status == "planned",
                        (CardPaymentIntent.paying_account_id == account.id)
                        | (CardPaymentIntent.financial_account_id == account.id),
                    )
                )
            ).all()
        )
        for intent in payment_intents:
            if account.balance_kind == "asset" and intent.paying_account_id == account.id:
                events.append(
                    _ForecastEvent(
                        event_date=intent.planned_for,
                        amount=self._decimal(intent.amount),
                        increases_balance=False,
                        confidence=Decimal("0.86"),
                        evidence_id=f"card_payment_intent:{intent.id}:funding",
                    )
                )
            elif account.balance_kind == "liability" and intent.financial_account_id == account.id:
                events.append(
                    _ForecastEvent(
                        event_date=intent.planned_for,
                        amount=self._decimal(intent.amount),
                        increases_balance=False,
                        confidence=Decimal("0.86"),
                        evidence_id=f"card_payment_intent:{intent.id}:liability",
                    )
                )

        if account.balance_kind == "liability":
            schedule_rows = list(
                (
                    await self.db.execute(
                        select(LiabilityScheduleItem, Liability)
                        .join(Liability, Liability.id == LiabilityScheduleItem.liability_id)
                        .where(
                            LiabilityScheduleItem.user_id == user_id,
                            Liability.financial_account_id == account.id,
                            Liability.is_active.is_(True),
                            *([Liability.created_at <= cutoff_at] if as_of is not None else []),
                            LiabilityScheduleItem.status == "upcoming",
                            LiabilityScheduleItem.due_date > horizon_start,
                            LiabilityScheduleItem.due_date <= horizon_end,
                        )
                    )
                ).all()
            )
            for item, liability in schedule_rows:
                confidence = item.confidence or (
                    Decimal("0.98") if liability.complete_schedule else Decimal("0.72")
                )
                events.append(
                    _ForecastEvent(
                        event_date=item.due_date,
                        amount=self._decimal(item.installment_amount),
                        increases_balance=False,
                        confidence=self._decimal(confidence),
                        evidence_id=f"liability_schedule:{item.id}",
                    )
                )
        return events

    async def _credit_limit(
        self, user_id: str, account: FinancialAccount, *, as_of: date | None
    ) -> Decimal | None:
        if account.balance_kind != "liability" or account.account_type != "credit_card":
            return None
        statement = await self.db.scalar(
            select(CreditCardStatement)
            .where(
                CreditCardStatement.user_id == user_id,
                CreditCardStatement.financial_account_id == account.id,
                *([CreditCardStatement.statement_date <= as_of] if as_of is not None else []),
            )
            .order_by(CreditCardStatement.statement_date.desc())
            .limit(1)
        )
        return (
            self._decimal(statement.credit_limit) if statement and statement.credit_limit else None
        )

    @staticmethod
    def _forecast_status(starting_balance: Decimal | None, position_status: str) -> ForecastStatus:
        if starting_balance is None:
            return "needs_anchor"
        if position_status in {"needs_review", "incomplete", "stale", "needs_observation"}:
            return "needs_review"
        return "ready"

    @staticmethod
    def _data_sufficiency(
        activity_count: int, history_days: int, baseline_enabled: bool
    ) -> DataSufficiency:
        if baseline_enabled and activity_count >= 30 and history_days >= 120:
            return "high"
        if baseline_enabled:
            return "medium"
        return "low"

    @staticmethod
    def _decimal(value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _rounded_float(value: Decimal | None) -> float | None:
        return round(float(value), 2) if value is not None else None

    @staticmethod
    def _required_float(value: Decimal) -> float:
        return round(float(value), 2)
