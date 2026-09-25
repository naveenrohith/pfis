"""Card due-date affordability from issuer evidence and a funding forecast."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import CardPaymentIntent
from app.schemas.financial_position import CardDueRunwayResponse, CardPaymentScenario
from app.schemas.intelligence import EvidenceItem
from app.services.balance_forecast_service import BalanceForecastService
from app.services.financial_clock import user_financial_today
from app.services.financial_position_service import FinancialPositionService

RULESET_VERSION = "pfis-card-due-runway-2"

CardDueRunwayStatus = Literal[
    "covered",
    "at_risk",
    "needs_statement",
    "needs_payment_account",
    "needs_funding_anchor",
    "needs_review",
    "due_passed",
]


class _CardDueRunwayPayload(TypedDict):
    financial_account_id: str
    currency: str
    status: CardDueRunwayStatus
    statement_date: date | None
    due_date: date | None
    days_until_due: int | None
    total_due: float | None
    minimum_due: float | None
    estimated_current_outstanding: float | None
    credit_limit: float | None
    issuer_available_credit_limit: float | None
    funding_account_id: str | None
    funding_account_label: str | None
    funding_balance_basis: Literal["observed", "estimated"] | None
    funding_balance_as_of: date | None
    funding_position_status: str | None
    funding_balance_before_due_expected: float | None
    funding_balance_before_due_low: float | None
    funding_balance_before_due_high: float | None
    expected_balance_after_total_due: float | None
    expected_cash_gap: float | None
    lower_band_cash_gap: float | None
    planned_payment_total: float
    expected_total_due_covered: bool | None
    lower_band_total_due_covered: bool | None
    minimum_due_covered_on_lower_band: bool | None
    payment_scenarios: list[CardPaymentScenario]
    confidence: float
    position_reason_codes: list[str]
    evidence: list[EvidenceItem]
    assumptions: list[str]
    ruleset_version: str


class CardDueRunwayService:
    """Compare a card's billed total due with the selected funding path."""

    def __init__(self, db: AsyncSession, *, forecast_service: BalanceForecastService | None = None):
        self.db = db
        self._forecast_service = forecast_service or BalanceForecastService(db)

    async def runway(self, user_id: str, card_account_id: str) -> CardDueRunwayResponse | None:
        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == card_account_id,
                FinancialAccount.user_id == user_id,
                FinancialAccount.is_active.is_(True),
            )
        )
        if account is None:
            return None
        if account.account_type != "credit_card" or account.balance_kind != "liability":
            raise ValueError("Card due runway requires an active credit-card liability account")

        card = await FinancialPositionService(self.db).card_overview(user_id, card_account_id)
        today = await user_financial_today(self.db, user_id)
        current_outstanding = (
            card.provider_current_outstanding
            if card.provider_current_outstanding is not None
            else card.estimated_current_balance
        )
        credit_limit = (
            card.provider_credit_limit
            if card.provider_credit_limit is not None
            else card.credit_limit
        )
        available_credit = (
            card.provider_available_credit
            if card.provider_available_credit is not None
            else card.available_credit_limit
        )
        if card.total_due is None or card.due_date is None:
            return self._without_statement(
                card,
                today,
                current_outstanding=current_outstanding,
                credit_limit=credit_limit,
                available_credit=available_credit,
            )

        due_date = card.due_date
        days_until_due = (due_date - today).days
        funding_account_id = card.preferred_payment_account_id
        funding_source = "card preference"
        if funding_account_id is None:
            explicit_intent = next(
                (
                    intent
                    for intent in card.planned_payments
                    if intent.status == "planned"
                    and intent.paying_account_id is not None
                    and intent.planned_for <= due_date
                ),
                None,
            )
            if explicit_intent is not None:
                funding_account_id = explicit_intent.paying_account_id
                funding_source = "planned payment intention"

        base: _CardDueRunwayPayload = {
            "financial_account_id": card_account_id,
            "currency": card.currency,
            "status": "needs_review",
            "statement_date": card.statement_date,
            "due_date": due_date,
            "days_until_due": days_until_due,
            "total_due": card.total_due,
            "minimum_due": card.minimum_due,
            "estimated_current_outstanding": current_outstanding,
            "credit_limit": credit_limit,
            "issuer_available_credit_limit": available_credit,
            "funding_account_id": funding_account_id,
            "funding_account_label": None,
            "funding_balance_basis": None,
            "funding_balance_as_of": None,
            "funding_position_status": None,
            "funding_balance_before_due_expected": None,
            "funding_balance_before_due_low": None,
            "funding_balance_before_due_high": None,
            "expected_balance_after_total_due": None,
            "expected_cash_gap": None,
            "lower_band_cash_gap": None,
            "planned_payment_total": 0.0,
            "expected_total_due_covered": None,
            "lower_band_total_due_covered": None,
            "minimum_due_covered_on_lower_band": None,
            "payment_scenarios": [],
            "confidence": 0.0,
            "position_reason_codes": list(card.balance_reason_codes),
            "evidence": [
                EvidenceItem(
                    label="Issuer due",
                    value=f"{card.total_due:.2f} due {due_date.isoformat()}",
                ),
                EvidenceItem(
                    label="Current card position",
                    value=(
                        (
                            f"{current_outstanding:.2f} provider outstanding"
                            if card.provider_current_outstanding is not None
                            else f"{current_outstanding:.2f} estimated outstanding"
                        )
                        if current_outstanding is not None
                        else "No verified current outstanding anchor"
                    ),
                ),
            ],
            "assumptions": [
                "Total due and minimum due are issuer-stated statement facts; neither is presented as the live card balance.",
                "A planned payment is a user intention only. PFIS never contacts the bank or issuer.",
            ],
            "ruleset_version": RULESET_VERSION,
        }
        base["payment_scenarios"] = self._payment_scenarios(
            total_due=self._decimal(card.total_due),
            minimum_due=self._decimal(card.minimum_due) if card.minimum_due is not None else None,
            due_date=due_date,
            planned_payment_total=Decimal("0"),
            expected=None,
            low=None,
            high=None,
        )

        if days_until_due < 0:
            base["status"] = "due_passed"
            base["assumptions"].append(
                "The statement due date has passed; settlement status must be confirmed separately."
            )
            return CardDueRunwayResponse(**base)

        if funding_account_id is None:
            base["status"] = "needs_payment_account"
            base["assumptions"].append(
                "Select the bank account that will fund this card before PFIS evaluates affordability."
            )
            return CardDueRunwayResponse(**base)

        funding_account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == funding_account_id,
                FinancialAccount.user_id == user_id,
                FinancialAccount.is_active.is_(True),
            )
        )
        if funding_account is None or funding_account.balance_kind != "asset":
            base["status"] = "needs_review"
            base["position_reason_codes"].append("funding_account_not_asset")
            base["assumptions"].append(
                "The selected funding product is not an active asset account, so PFIS will not call it spendable cash."
            )
            return CardDueRunwayResponse(**base)

        base["funding_account_label"] = (
            f"{funding_account.institution_name} {funding_account.masked_number}"
        )
        base["evidence"].append(
            EvidenceItem(
                label="Funding source", value=f"{base['funding_account_label']} · {funding_source}"
            )
        )
        forecast_horizon = max(1, min(days_until_due, 180))
        forecast = await self._forecast_service.forecast(
            user_id,
            funding_account_id,
            horizon_days=forecast_horizon,
        )
        if forecast is None:
            base["status"] = "needs_review"
            base["position_reason_codes"].append("funding_account_not_found")
            return CardDueRunwayResponse(**base)
        base["funding_balance_basis"] = forecast.starting_balance_basis
        base["funding_balance_as_of"] = forecast.starting_balance_as_of
        base["funding_position_status"] = forecast.position_status
        base["confidence"] = min(card.balance_confidence, forecast.confidence)
        base["position_reason_codes"].extend(forecast.position_reason_codes)
        base["position_reason_codes"] = list(dict.fromkeys(base["position_reason_codes"]))
        base["evidence"].append(
            EvidenceItem(
                label="Funding path",
                value=f"{forecast.status} · {forecast.confidence:.0%} confidence",
            )
        )

        due_point = next(
            (point for point in forecast.points if point.date == due_date),
            forecast.points[0] if forecast.points and due_date == forecast.horizon_start else None,
        )
        if due_point is None or due_date > forecast.horizon_end:
            base["status"] = "needs_review"
            base["position_reason_codes"].append("due_horizon_exceeds_forecast")
            base["assumptions"].append(
                "The due date is beyond the supported 180-day forecast horizon, so PFIS will not extrapolate affordability."
            )
            return CardDueRunwayResponse(**base)

        planned_payment_total = await self._planned_payments_before_due(
            user_id,
            card_account_id,
            funding_account_id,
            today=today,
            due_date=due_date,
        )
        base["planned_payment_total"] = float(planned_payment_total)
        if planned_payment_total:
            base["evidence"].append(
                EvidenceItem(
                    label="Planned payment",
                    value=f"{planned_payment_total:.2f} scheduled before due date",
                )
            )

        expected = self._decimal(due_point.expected_balance) + planned_payment_total
        low = self._decimal(due_point.low_balance) + planned_payment_total
        high = self._decimal(due_point.high_balance) + planned_payment_total
        total_due = self._decimal(card.total_due)
        minimum_due = self._decimal(card.minimum_due) if card.minimum_due is not None else None
        expected_after = expected - total_due
        expected_gap = max(total_due - expected, Decimal("0"))
        lower_gap = max(total_due - low, Decimal("0"))
        base["funding_balance_before_due_expected"] = round(float(expected), 2)
        base["funding_balance_before_due_low"] = round(float(low), 2)
        base["funding_balance_before_due_high"] = round(float(high), 2)
        base["expected_balance_after_total_due"] = round(float(expected_after), 2)
        base["expected_cash_gap"] = round(float(expected_gap), 2)
        base["lower_band_cash_gap"] = round(float(lower_gap), 2)
        base["expected_total_due_covered"] = expected >= total_due
        base["lower_band_total_due_covered"] = low >= total_due
        base["minimum_due_covered_on_lower_band"] = minimum_due is not None and low >= minimum_due
        base["payment_scenarios"] = self._payment_scenarios(
            total_due=total_due,
            minimum_due=minimum_due,
            due_date=due_date,
            planned_payment_total=planned_payment_total,
            expected=expected,
            low=low,
            high=high,
        )
        base["status"] = (
            "needs_funding_anchor"
            if forecast.status == "needs_anchor"
            else (
                "needs_review"
                if forecast.status != "ready"
                else "covered" if low >= total_due else "at_risk"
            )
        )
        base["assumptions"].extend(
            [
                "Affordability uses the lower forecast band: the billed total is considered covered only when the conservative funding path remains above it.",
                "Any scheduled payment intention is added back to show cash available before paying the issuer; it is not treated as completed settlement.",
            ]
        )
        return CardDueRunwayResponse(**base)

    async def _planned_payments_before_due(
        self,
        user_id: str,
        card_account_id: str,
        funding_account_id: str,
        *,
        today: date,
        due_date: date,
    ) -> Decimal:
        rows = list(
            (
                await self.db.scalars(
                    select(CardPaymentIntent).where(
                        CardPaymentIntent.user_id == user_id,
                        CardPaymentIntent.financial_account_id == card_account_id,
                        CardPaymentIntent.paying_account_id == funding_account_id,
                        CardPaymentIntent.status == "planned",
                        CardPaymentIntent.planned_for >= today,
                        CardPaymentIntent.planned_for <= due_date,
                    )
                )
            ).all()
        )
        return sum((self._decimal(row.amount) for row in rows), Decimal("0"))

    @staticmethod
    def _without_statement(
        card,
        today: date,
        *,
        current_outstanding: float | None,
        credit_limit: float | None,
        available_credit: float | None,
    ) -> CardDueRunwayResponse:
        return CardDueRunwayResponse(
            financial_account_id=card.financial_account_id,
            currency=card.currency,
            status="needs_statement",
            statement_date=card.statement_date,
            due_date=card.due_date,
            days_until_due=None,
            total_due=card.total_due,
            minimum_due=card.minimum_due,
            estimated_current_outstanding=current_outstanding,
            credit_limit=credit_limit,
            issuer_available_credit_limit=available_credit,
            funding_account_id=card.preferred_payment_account_id,
            funding_account_label=None,
            funding_balance_basis=None,
            funding_balance_as_of=None,
            funding_position_status=None,
            funding_balance_before_due_expected=None,
            funding_balance_before_due_low=None,
            funding_balance_before_due_high=None,
            expected_balance_after_total_due=None,
            expected_cash_gap=None,
            lower_band_cash_gap=None,
            expected_total_due_covered=None,
            lower_band_total_due_covered=None,
            minimum_due_covered_on_lower_band=None,
            payment_scenarios=[],
            confidence=0.0,
            position_reason_codes=list(card.balance_reason_codes),
            evidence=[
                EvidenceItem(
                    label="Issuer due",
                    value="No statement total due is available",
                )
            ],
            assumptions=[
                "Import or confirm an issuer statement before PFIS evaluates card due affordability.",
                f"As of {today.isoformat()}, no billed due amount was available for this card.",
            ],
            ruleset_version=RULESET_VERSION,
        )

    @staticmethod
    def _decimal(value: object | None) -> Decimal:
        return Decimal(str(value or "0"))

    @classmethod
    def _payment_scenarios(
        cls,
        *,
        total_due: Decimal,
        minimum_due: Decimal | None,
        due_date: date,
        planned_payment_total: Decimal,
        expected: Decimal | None,
        low: Decimal | None,
        high: Decimal | None,
    ) -> list[CardPaymentScenario]:
        """Evaluate issuer payment targets without creating ledger activity.

        ``expected``, ``low``, and ``high`` are the cash path immediately before
        any of the planned card payments are deducted. Existing intentions are
        therefore credited toward each target and the effective hypothetical
        payment is the larger of the target and the already-planned amount.
        """

        targets: list[tuple[Literal["minimum_due", "total_due"], Decimal]] = []
        if minimum_due is not None:
            targets.append(("minimum_due", minimum_due))
        targets.append(("total_due", total_due))

        scenarios: list[CardPaymentScenario] = []
        for scenario, payment_amount in targets:
            planned_applied = min(planned_payment_total, payment_amount)
            additional_payment = max(payment_amount - planned_payment_total, Decimal("0"))
            effective_payment = max(payment_amount, planned_payment_total)
            remaining_total_due = max(total_due - effective_payment, Decimal("0"))

            if expected is None or low is None or high is None:
                scenarios.append(
                    CardPaymentScenario(
                        scenario=scenario,
                        payment_date=due_date,
                        payment_amount=cls._rounded(payment_amount),
                        planned_payment_applied=cls._rounded(planned_applied),
                        additional_payment_amount=cls._rounded(additional_payment),
                        effective_payment_amount=cls._rounded(effective_payment),
                        remaining_total_due=cls._rounded(remaining_total_due),
                        status="unavailable",
                    )
                )
                continue

            expected_gap = max(effective_payment - expected, Decimal("0"))
            lower_gap = max(effective_payment - low, Decimal("0"))
            expected_covered = expected >= effective_payment
            lower_covered = low >= effective_payment
            scenarios.append(
                CardPaymentScenario(
                    scenario=scenario,
                    payment_date=due_date,
                    payment_amount=cls._rounded(payment_amount),
                    planned_payment_applied=cls._rounded(planned_applied),
                    additional_payment_amount=cls._rounded(additional_payment),
                    effective_payment_amount=cls._rounded(effective_payment),
                    remaining_total_due=cls._rounded(remaining_total_due),
                    expected_funding_balance_after=cls._rounded(expected - effective_payment),
                    lower_band_funding_balance_after=cls._rounded(low - effective_payment),
                    upper_band_funding_balance_after=cls._rounded(high - effective_payment),
                    expected_cash_gap=cls._rounded(expected_gap),
                    lower_band_cash_gap=cls._rounded(lower_gap),
                    expected_covered=expected_covered,
                    lower_band_covered=lower_covered,
                    status="covered" if lower_covered else "at_risk",
                )
            )
        return scenarios

    @staticmethod
    def _rounded(value: Decimal) -> float:
        return round(float(value), 2)
