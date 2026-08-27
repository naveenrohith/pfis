"""Compare hypothetical minimum- and total-due plans across active cards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.schemas.balance_forecast import AccountBalanceForecastResponse
from app.schemas.financial_position import (
    CardDueRunwayResponse,
    CardPaymentScenario,
    CardPortfolioPaymentPlanCard,
    CardPortfolioPaymentPlanFundingPath,
    CardPortfolioPaymentPlanResponse,
    CardPortfolioPaymentPlanStrategy,
)
from app.schemas.intelligence import EvidenceItem
from app.services.balance_forecast_service import BalanceForecastService
from app.services.card_due_runway_service import CardDueRunwayService
from app.services.financial_clock import user_financial_today

RULESET_VERSION = "pfis-card-portfolio-payment-plan-1"
StrategyName = Literal["minimum_due", "total_due"]


@dataclass(frozen=True)
class _CardPlanRow:
    account: FinancialAccount
    runway: CardDueRunwayResponse
    minimum_due_scenario: CardPaymentScenario | None
    total_due_scenario: CardPaymentScenario | None


class CardPortfolioPaymentPlanService:
    """Build a conservative, non-executing comparison of card payment plans."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def compare(self, user_id: str) -> CardPortfolioPaymentPlanResponse:
        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount)
                    .where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.account_type == "credit_card",
                    )
                    .order_by(FinancialAccount.institution_name, FinancialAccount.id)
                )
            ).all()
        )
        as_of = await user_financial_today(self.db, user_id)
        if not accounts:
            empty = self._empty_strategy("minimum_due")
            return CardPortfolioPaymentPlanResponse(
                as_of=as_of,
                state="no_active_cards",
                card_count=0,
                minimum_due_plan=empty,
                total_due_plan=self._empty_strategy("total_due"),
                confidence=0.0,
                reason_codes=["no_active_cards"],
                evidence=[
                    EvidenceItem(
                        label="Card portfolio",
                        value="No active credit cards",
                    )
                ],
                assumptions=[
                    "No payment target can be compared until an active credit-card account is confirmed."
                ],
                ruleset_version=RULESET_VERSION,
            )

        runway_service = CardDueRunwayService(self.db)
        rows: list[_CardPlanRow] = []
        for account in accounts:
            runway = await runway_service.runway(user_id, account.id)
            if runway is None:
                continue
            scenarios = {item.scenario: item for item in runway.payment_scenarios}
            rows.append(
                _CardPlanRow(
                    account=account,
                    runway=runway,
                    minimum_due_scenario=scenarios.get("minimum_due"),
                    total_due_scenario=scenarios.get("total_due"),
                )
            )

        forecasts = await self._funding_forecasts(rows, as_of=as_of, user_id=user_id)
        minimum_plan = await self._build_strategy(
            rows,
            "minimum_due",
            forecasts=forecasts,
            as_of=as_of,
        )
        total_plan = await self._build_strategy(
            rows,
            "total_due",
            forecasts=forecasts,
            as_of=as_of,
        )
        card_rows = [self._card_response(row) for row in rows]
        root_reasons = ["portfolio_payment_plans_composed"]
        if any(
            plan.status
            in {"needs_review", "needs_statement", "needs_payment_account", "unavailable"}
            for plan in (minimum_plan, total_plan)
        ):
            root_reasons.append("portfolio_payment_plan_needs_review")
        if any(plan.status == "at_risk" for plan in (minimum_plan, total_plan)):
            root_reasons.append("portfolio_lower_band_shortfall_present")
        cards_with_statement = sum(
            row.runway.total_due is not None and row.runway.due_date is not None for row in rows
        )
        cards_needing_review = sum(
            row.runway.status
            in {
                "needs_statement",
                "needs_payment_account",
                "needs_funding_anchor",
                "needs_review",
                "due_passed",
            }
            for row in rows
        )
        if cards_needing_review or any(
            plan.status
            in {"needs_review", "needs_statement", "needs_payment_account", "unavailable"}
            for plan in (minimum_plan, total_plan)
        ):
            state: Literal["ready", "partial", "needs_review"] = "needs_review"
        elif any(plan.status == "at_risk" for plan in (minimum_plan, total_plan)):
            state = "partial"
        else:
            state = "ready"
        confidence_values = [row.runway.confidence for row in rows]
        confidence = min(confidence_values) if confidence_values else 0.0
        return CardPortfolioPaymentPlanResponse(
            as_of=as_of,
            state=state,
            card_count=len(rows),
            cards_with_statement=cards_with_statement,
            cards_needing_review=cards_needing_review,
            minimum_due_plan=minimum_plan,
            total_due_plan=total_plan,
            cards=card_rows,
            confidence=confidence,
            reason_codes=list(dict.fromkeys(root_reasons)),
            evidence=[
                EvidenceItem(
                    label="Payment targets",
                    value=(
                        f"{minimum_plan.cards_with_target} minimum-due and "
                        f"{total_plan.cards_with_target} total-due card target(s)"
                    ),
                ),
                EvidenceItem(
                    label="Funding paths",
                    value=(
                        f"{minimum_plan.cards_with_funding_path} minimum-due and "
                        f"{total_plan.cards_with_funding_path} total-due card path(s)"
                    ),
                ),
            ],
            assumptions=[
                "The comparison is a planning read model; PFIS never submits a payment or reserves cash.",
                "Issuer minimum and total due remain statement facts, not live card balances.",
                "Existing planned payment intentions are already present in the funding forecast; only additional hypothetical payments are replayed.",
                "Cards sharing a funding account are evaluated on one shared forecast path so their cash is not independently double-counted.",
                "Rewards, fees, issuer settlement timing, and live available credit are not simulated without explicit verified rules or provider evidence.",
            ],
            ruleset_version=RULESET_VERSION,
        )

    async def _funding_forecasts(
        self,
        rows: list[_CardPlanRow],
        *,
        as_of: date,
        user_id: str,
    ) -> dict[str, AccountBalanceForecastResponse | None]:
        horizons: dict[str, int] = {}
        for row in rows:
            funding_id = row.runway.funding_account_id
            due_date = row.runway.due_date
            if funding_id is None or due_date is None or due_date < as_of:
                continue
            horizon = max(1, (due_date - as_of).days)
            horizons[funding_id] = min(180, max(horizons.get(funding_id, 1), horizon))
        service = BalanceForecastService(self.db)
        forecasts: dict[str, AccountBalanceForecastResponse | None] = {}
        for funding_id, horizon in horizons.items():
            forecasts[funding_id] = await service.forecast(
                user_id,
                funding_id,
                horizon_days=horizon,
            )
        return forecasts

    async def _build_strategy(
        self,
        rows: list[_CardPlanRow],
        strategy: StrategyName,
        *,
        forecasts: dict[str, AccountBalanceForecastResponse | None],
        as_of: date,
    ) -> CardPortfolioPaymentPlanStrategy:
        scenario_rows: list[tuple[_CardPlanRow, CardPaymentScenario]] = []
        for row in rows:
            scenario = self._scenario(row, strategy)
            if scenario is not None:
                scenario_rows.append((row, scenario))
        scenario_values = [scenario for _, scenario in scenario_rows]
        target_total = self._sum_values(scenario.payment_amount for scenario in scenario_values)
        planned_total = self._sum_values(scenario.planned_payment_applied for scenario in scenario_values)
        additional_total = self._sum_values(
            scenario.additional_payment_amount for scenario in scenario_values
        )
        effective_total = self._sum_values(
            scenario.effective_payment_amount for scenario in scenario_values
        )
        remaining_total = self._sum_values(
            scenario.remaining_total_due for scenario in scenario_values
        )
        candidates = [
            (row, scenario)
            for row, scenario in scenario_rows
            if scenario.status != "unavailable"
            and row.runway.funding_account_id is not None
            and row.runway.due_date is not None
            and row.runway.due_date >= as_of
        ]
        grouped: dict[str, list[tuple[_CardPlanRow, CardPaymentScenario]]] = {}
        for row, scenario in candidates:
            funding_id = row.runway.funding_account_id
            if funding_id is not None:
                grouped.setdefault(funding_id, []).append((row, scenario))

        paths: list[CardPortfolioPaymentPlanFundingPath] = []
        for funding_id, group in grouped.items():
            path = self._build_funding_path(
                funding_id,
                group,
                forecast=forecasts.get(funding_id),
            )
            paths.append(path)

        cards_with_funding_path = sum(len(path.card_ids) for path in paths)
        cards_covered = sum(
            path.cards_covered_on_lower_band for path in paths
        )
        cards_at_risk = sum(path.cards_at_risk for path in paths)
        cards_unavailable = len(rows) - cards_with_funding_path
        if not rows or not scenario_values:
            status: Literal[
                "covered",
                "at_risk",
                "needs_statement",
                "needs_payment_account",
                "needs_review",
                "unavailable",
            ] = "unavailable"
        elif not candidates:
            if scenario_rows and all(
                row.runway.funding_account_id is None
                for row, scenario in scenario_rows
            ):
                status = "needs_payment_account"
            elif not scenario_rows:
                status = "needs_statement"
            else:
                status = "needs_review"
        elif cards_at_risk:
            status = "at_risk"
        elif cards_unavailable or any(path.status != "covered" for path in paths):
            status = "needs_review"
        else:
            status = "covered"

        reason_codes = ["portfolio_payment_strategy_composed"]
        if not scenario_values:
            reason_codes.append("payment_target_unavailable")
        if len(scenario_values) < len(rows):
            reason_codes.append("partial_payment_target_coverage")
        if cards_unavailable:
            reason_codes.append("funding_path_unavailable_for_some_cards")
        if any(len(path.card_ids) > 1 for path in paths):
            reason_codes.append("shared_funding_path_replayed")
        if cards_at_risk:
            reason_codes.append("portfolio_lower_band_shortfall")
        if any(path.status == "needs_review" for path in paths):
            reason_codes.append("funding_path_needs_review")

        confidence_values = [row.runway.confidence for row, _ in candidates]
        confidence_values.extend(path.confidence for path in paths)
        confidence = min(confidence_values) if confidence_values else 0.0
        return CardPortfolioPaymentPlanStrategy(
            strategy=strategy,
            status=status,
            issuer_payment_target_total=target_total,
            planned_payment_total=planned_total or 0.0,
            additional_payment_total=additional_total,
            effective_payment_total=effective_total,
            remaining_total_due=remaining_total,
            cards_with_target=len(scenario_values),
            cards_with_funding_path=cards_with_funding_path,
            cards_covered_on_lower_band=cards_covered,
            cards_at_risk=cards_at_risk,
            cards_unavailable=cards_unavailable,
            confidence=confidence,
            reason_codes=list(dict.fromkeys(reason_codes)),
            funding_paths=paths,
        )

    @staticmethod
    def _scenario(row: _CardPlanRow, strategy: StrategyName) -> CardPaymentScenario | None:
        return (
            row.minimum_due_scenario if strategy == "minimum_due" else row.total_due_scenario
        )

    @staticmethod
    def _build_funding_path(
        funding_id: str,
        group: list[tuple[_CardPlanRow, CardPaymentScenario]],
        *,
        forecast: AccountBalanceForecastResponse | None,
    ) -> CardPortfolioPaymentPlanFundingPath:
        labels = [row.runway.funding_account_label for row, _ in group]
        label = next((value for value in labels if value), funding_id)
        card_ids = [row.account.id for row, _ in group]
        assumptions = [
            "The funding forecast already includes existing planned payment intentions; this plan subtracts only additional payment amounts.",
            "The lower band is a conservative planning signal, not a provider live balance or a settlement guarantee.",
        ]
        if len(group) > 1:
            assumptions.append(
                "Multiple cards share this funding path; obligations are replayed in due-date order before coverage is called."
            )
        if forecast is None:
            return CardPortfolioPaymentPlanFundingPath(
                funding_account_id=funding_id,
                funding_account_label=label,
                card_ids=card_ids,
                cards_covered_on_lower_band=0,
                cards_at_risk=0,
                forecast_status="needs_review",
                status="unavailable",
                confidence=0.0,
                reason_codes=["funding_forecast_unavailable"],
                assumptions=assumptions,
            )

        points = {point.date: point for point in forecast.points}
        due_dates = sorted({row.runway.due_date for row, _ in group if row.runway.due_date})
        cumulative_additional = Decimal("0")
        lowest_expected: Decimal | None = None
        lowest_low: Decimal | None = None
        lowest_high: Decimal | None = None
        first_shortfall: date | None = None
        missing_date = False
        lower_after_by_date: dict[date, Decimal] = {}
        for due_date in due_dates:
            point = points.get(due_date)
            if point is None:
                missing_date = True
                continue
            cumulative_additional += sum(
                (
                    Decimal(str(scenario.additional_payment_amount))
                    for row, scenario in group
                    if row.runway.due_date is not None and row.runway.due_date <= due_date
                ),
                Decimal("0"),
            ) - cumulative_additional
            expected = _decimal_or_none(point.expected_balance)
            low = _decimal_or_none(point.low_balance)
            high = _decimal_or_none(point.high_balance)
            if expected is not None:
                after_expected = expected - cumulative_additional
                lowest_expected = (
                    after_expected
                    if lowest_expected is None
                    else min(lowest_expected, after_expected)
                )
            if low is not None:
                after_low = low - cumulative_additional
                lower_after_by_date[due_date] = after_low
                lowest_low = after_low if lowest_low is None else min(lowest_low, after_low)
                if after_low < 0 and first_shortfall is None:
                    first_shortfall = due_date
            if high is not None:
                after_high = high - cumulative_additional
                lowest_high = after_high if lowest_high is None else min(lowest_high, after_high)

        forecast_status = forecast.status
        if missing_date or not due_dates or lowest_low is None:
            status: Literal["covered", "at_risk", "needs_review", "unavailable"] = (
                "needs_review" if forecast_status != "needs_anchor" else "unavailable"
            )
        elif forecast_status != "ready":
            status = "needs_review"
        elif lowest_low < 0:
            status = "at_risk"
        else:
            status = "covered"
        reason_codes = list(forecast.position_reason_codes)
        if missing_date:
            reason_codes.append("due_date_outside_funding_forecast")
        if len(group) > 1:
            reason_codes.append("shared_funding_path")
        if status == "at_risk":
            reason_codes.append("lower_band_cash_shortfall")
        lower_gap = max(Decimal("0"), -(lowest_low or Decimal("0")))
        cards_covered = 0
        cards_at_risk = 0
        for row, _ in group:
            card_due_date = row.runway.due_date
            lower_after = (
                lower_after_by_date.get(card_due_date) if card_due_date is not None else None
            )
            if lower_after is None:
                continue
            if lower_after < 0:
                cards_at_risk += 1
            else:
                cards_covered += 1
        return CardPortfolioPaymentPlanFundingPath(
            funding_account_id=funding_id,
            funding_account_label=label,
            card_ids=card_ids,
            cards_covered_on_lower_band=cards_covered,
            cards_at_risk=cards_at_risk,
            forecast_status=forecast_status,
            status=status,
            starting_balance=forecast.starting_balance,
            starting_balance_as_of=forecast.starting_balance_as_of,
            starting_balance_basis=forecast.starting_balance_basis,
            lowest_expected_balance_after=_float_or_none(lowest_expected),
            lowest_lower_band_balance_after=_float_or_none(lowest_low),
            lowest_upper_band_balance_after=_float_or_none(lowest_high),
            first_lower_band_shortfall_date=first_shortfall,
            lower_band_cash_gap=round(float(lower_gap), 2),
            confidence=forecast.confidence,
            reason_codes=list(dict.fromkeys(reason_codes)),
            assumptions=assumptions,
        )

    @staticmethod
    def _card_response(row: _CardPlanRow) -> CardPortfolioPaymentPlanCard:
        runway = row.runway
        reasons = list(runway.position_reason_codes)
        if runway.status == "needs_statement":
            reasons.append("statement_due_missing")
        if runway.status == "needs_payment_account":
            reasons.append("funding_account_missing")
        if runway.status == "due_passed":
            reasons.append("due_date_passed")
        return CardPortfolioPaymentPlanCard(
            financial_account_id=row.account.id,
            label=row.account.institution_name,
            currency=runway.currency,
            runway_status=runway.status,
            statement_date=runway.statement_date,
            due_date=runway.due_date,
            total_due=runway.total_due,
            minimum_due=runway.minimum_due,
            funding_account_id=runway.funding_account_id,
            funding_account_label=runway.funding_account_label,
            minimum_due_scenario=row.minimum_due_scenario,
            total_due_scenario=row.total_due_scenario,
            confidence=runway.confidence,
            reason_codes=list(dict.fromkeys(reasons)),
            evidence=runway.evidence,
            assumptions=runway.assumptions,
        )

    @staticmethod
    def _empty_strategy(strategy: StrategyName) -> CardPortfolioPaymentPlanStrategy:
        return CardPortfolioPaymentPlanStrategy(
            strategy=strategy,
            status="unavailable",
            confidence=0.0,
            reason_codes=["no_active_cards"],
        )

    @staticmethod
    def _sum_values(values) -> float | None:
        decimals = [Decimal(str(value)) for value in values]
        return round(float(sum(decimals, Decimal("0"))), 2) if decimals else None


def _decimal_or_none(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _float_or_none(value: Decimal | None) -> float | None:
    return round(float(value), 2) if value is not None else None
