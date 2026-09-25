"""Deterministic Financial Horizon read model composed from existing services."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.schemas.balance_forecast import AccountBalanceForecastResponse
from app.schemas.financial_horizon import (
    FinancialHorizonAmountSummary,
    FinancialHorizonCurrentPosition,
    FinancialHorizonEvent,
    FinancialHorizonLowestPoint,
    FinancialHorizonResponse,
    FinancialHorizonRiskSignal,
    FinancialHorizonSourceHealth,
    FinancialHorizonStatus,
)
from app.schemas.financial_position import AccountPositionResponse, CashPlanResponse
from app.services.balance_forecast_service import BalanceForecastService
from app.services.card_due_runway_service import CardDueRunwayService
from app.services.card_portfolio_upcoming_service import CardPortfolioUpcomingStateService
from app.services.financial_clock import user_financial_today
from app.services.financial_position_service import FinancialPositionService
from app.services.ledger_currency import get_ledger_currency

RULESET_VERSION = "pfis-horizon-1"


class FinancialHorizonService:
    """Build the server-owned Financial Horizon without learned models or LLMs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def horizon(self, user_id: str, *, days: int = 30) -> FinancialHorizonResponse:
        horizon_days = max(7, min(days, 90))
        as_of = await user_financial_today(self.db, user_id)
        horizon_end = as_of + timedelta(days=horizon_days)
        currency = await get_ledger_currency(self.db, user_id)
        position_service = FinancialPositionService(self.db)

        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount)
                    .where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                    )
                    .order_by(FinancialAccount.institution_name, FinancialAccount.id)
                )
            ).all()
        )
        positions = [
            position
            for position in [
                await position_service.account_position(user_id, account.id) for account in accounts
            ]
            if position is not None
        ]
        cash_plan = await position_service.cash_plan(user_id)

        events = await self._events(
            user_id,
            as_of=as_of,
            horizon_end=horizon_end,
            position_service=position_service,
        )
        source_health = self._source_health(positions)
        risk_signals = self._base_risks(
            cash_plan,
            positions,
            source_health,
            as_of=as_of,
        )

        forecast = await self._primary_forecast(
            user_id,
            cash_plan,
            horizon_days=horizon_days,
        )
        lowest_point, unavailable_reason = self._lowest_point(forecast)
        if forecast is None:
            unavailable_reason = unavailable_reason or "cash_plan_primary_account_required"
        elif forecast.first_shortfall_date is not None:
            risk_signals.append(
                FinancialHorizonRiskSignal(
                    code="low_coverage",
                    severity="danger",
                    label="Projected cash shortfall",
                    detail="The funding forecast lower band crosses below zero in this horizon.",
                    date=forecast.first_shortfall_date,
                    source="balance_forecast",
                )
            )

        for account in accounts:
            if account.account_type != "credit_card":
                continue
            due_risk = await self._card_due_risk(user_id, account.id)
            if due_risk is not None:
                risk_signals.append(due_risk)

        missing_evidence = self._missing_evidence(
            accounts=accounts,
            positions=positions,
            cash_plan=cash_plan,
            forecast=forecast,
            lowest_reason=unavailable_reason,
        )
        status = self._status(
            missing_evidence=missing_evidence,
            risk_signals=risk_signals,
            source_health=source_health,
            cash_plan=cash_plan,
            forecast=forecast,
        )

        return FinancialHorizonResponse(
            as_of=as_of,
            horizon_days=horizon_days,
            current_position=self._current_position(currency, positions, cash_plan),
            events=sorted(events, key=lambda item: (item.date, item.source, item.id)),
            lowest_projected_point=lowest_point,
            lowest_projected_point_unavailable_reason=(
                None if lowest_point else unavailable_reason
            ),
            risk_signals=risk_signals,
            source_health=source_health,
            status=status,
            missing_evidence=list(dict.fromkeys(missing_evidence)),
            ruleset_version=RULESET_VERSION,
        )

    async def _events(
        self,
        user_id: str,
        *,
        as_of: date,
        horizon_end: date,
        position_service: FinancialPositionService,
    ) -> list[FinancialHorizonEvent]:
        events: list[FinancialHorizonEvent] = []
        cash_plan = await position_service.cash_plan(user_id)
        if (
            cash_plan.next_income_date is not None
            and as_of <= cash_plan.next_income_date <= horizon_end
            and cash_plan.primary_financial_account_id
        ):
            events.append(
                FinancialHorizonEvent(
                    id=f"cash-plan:income:{cash_plan.primary_financial_account_id}:{cash_plan.next_income_date}",
                    date=cash_plan.next_income_date,
                    label="Confirmed next income",
                    amount=None,
                    direction="in",
                    source="cash_plan",
                    source_id=cash_plan.primary_financial_account_id,
                    status="planned",
                    confidence=0.9,
                    reason_codes=["cash_plan_next_income"],
                )
            )

        commitments = await position_service.list_commitments(user_id)
        for item in commitments:
            if not item.is_active or not (as_of <= item.due_date <= horizon_end):
                continue
            events.append(
                FinancialHorizonEvent(
                    id=f"commitment:{item.id}",
                    date=item.due_date,
                    label=item.label,
                    amount=float(item.amount),
                    direction="out",
                    source="commitment",
                    source_id=item.id,
                    status="verified" if item.confirmed else "provisional",
                    confidence=self._commitment_confidence(item.source_kind, item.confirmed),
                    reason_codes=[
                        "confirmed_commitment" if item.confirmed else "unconfirmed_commitment",
                        f"source_{item.source_kind}",
                    ],
                )
            )

        liability_overview = await position_service.liability_overview(user_id)
        for liability in liability_overview.liabilities:
            if (
                liability.next_due_date is None
                or liability.monthly_due is None
                or not (as_of <= liability.next_due_date <= horizon_end)
            ):
                continue
            events.append(
                FinancialHorizonEvent(
                    id=f"liability:{liability.id}:{liability.next_due_date}",
                    date=liability.next_due_date,
                    label=liability.label,
                    amount=liability.monthly_due,
                    direction="out",
                    source="liability",
                    source_id=liability.id,
                    status="verified" if liability.complete_schedule else "provisional",
                    confidence=liability.source_confidence
                    or (1.0 if liability.complete_schedule else 0.72),
                    reason_codes=[f"liability_schedule_{liability.schedule_status}"],
                )
            )

        cards = await CardPortfolioUpcomingStateService(self.db).upcoming(user_id)
        for card_event in cards.events:
            if as_of <= card_event.date <= horizon_end:
                direction: Literal["in", "out", "neutral"] = (
                    "out"
                    if card_event.event_type in {"payment_due", "planned_payment"}
                    else "neutral"
                )
                events.append(
                    FinancialHorizonEvent(
                        id=f"card-upcoming:{card_event.id}",
                        date=card_event.date,
                        label=card_event.label,
                        amount=float(card_event.amount) if card_event.amount is not None else None,
                        direction=direction,
                        source="card_upcoming",
                        source_id=card_event.id,
                        status=card_event.status if card_event.status != "observed" else "verified",
                        confidence=card_event.confidence,
                        reason_codes=list(card_event.reason_codes),
                    )
                )
        return self._dedupe_events(events)

    async def _primary_forecast(
        self, user_id: str, cash_plan: CashPlanResponse, *, horizon_days: int
    ) -> AccountBalanceForecastResponse | None:
        if not cash_plan.primary_financial_account_id:
            return None
        return await BalanceForecastService(self.db).forecast(
            user_id,
            cash_plan.primary_financial_account_id,
            horizon_days=horizon_days,
        )

    def _lowest_point(
        self, forecast: AccountBalanceForecastResponse | None
    ) -> tuple[FinancialHorizonLowestPoint | None, str | None]:
        if forecast is None:
            return None, "cash_plan_primary_account_required"
        if forecast.status != "ready":
            return None, f"forecast_{forecast.status}"
        if (
            not forecast.points
            or forecast.lowest_expected_balance is None
            or forecast.lowest_expected_date is None
        ):
            return None, "forecast_path_unavailable"
        if forecast.data_sufficiency == "low" and forecast.event_count == 0:
            return None, "forecast_low_data"
        point = next(
            (item for item in forecast.points if item.date == forecast.lowest_expected_date),
            None,
        )
        return (
            FinancialHorizonLowestPoint(
                date=forecast.lowest_expected_date,
                expected_balance=forecast.lowest_expected_balance,
                low_balance=point.low_balance if point is not None else None,
                high_balance=point.high_balance if point is not None else None,
                confidence=forecast.confidence,
                source_account_id=forecast.financial_account_id,
            ),
            None,
        )

    async def _card_due_risk(
        self, user_id: str, account_id: str
    ) -> FinancialHorizonRiskSignal | None:
        try:
            runway = await CardDueRunwayService(self.db).runway(user_id, account_id)
        except (LookupError, ValueError):
            return None
        if runway is None:
            return None
        if runway.status == "at_risk":
            return FinancialHorizonRiskSignal(
                code="card_due_shortfall",
                severity="danger",
                label="Card due may be short funded",
                detail="The conservative funding forecast does not cover the issuer total due.",
                date=runway.due_date,
                amount=runway.lower_band_cash_gap or runway.expected_cash_gap,
                source="card_due_runway",
            )
        if runway.status in {"needs_payment_account", "needs_funding_anchor", "needs_review"}:
            return FinancialHorizonRiskSignal(
                code="unfunded_commitment",
                severity="warning",
                label="Card due funding is not proven",
                detail=f"Card due runway status is {runway.status}; PFIS will not treat it as covered.",
                date=runway.due_date,
                amount=runway.total_due,
                source="card_due_runway",
            )
        return None

    def _current_position(
        self,
        currency: str,
        positions: list[AccountPositionResponse],
        cash_plan: CashPlanResponse,
    ) -> FinancialHorizonCurrentPosition:
        verified_assets = sum(
            item.verified_balance or 0.0
            for item in positions
            if item.balance_kind == "asset" and item.verified_balance is not None
        )
        verified_liabilities = sum(
            item.verified_balance or 0.0
            for item in positions
            if item.balance_kind == "liability" and item.verified_balance is not None
        )
        provisional_assets = sum(
            item.estimated_balance or 0.0
            for item in positions
            if item.balance_kind == "asset"
            and item.estimated_balance is not None
            and item.status != "observed"
        )
        provisional_liabilities = sum(
            item.estimated_balance or 0.0
            for item in positions
            if item.balance_kind == "liability"
            and item.estimated_balance is not None
            and item.status != "observed"
        )
        reason_codes: list[str] = []
        for position in positions:
            reason_codes.extend(position.reason_codes)
            reason_codes.extend(position.position_reason_codes)
        return FinancialHorizonCurrentPosition(
            currency=currency,
            account_count=len(positions),
            verified=FinancialHorizonAmountSummary(
                assets=round(verified_assets, 2),
                liabilities=round(verified_liabilities, 2),
                net=round(verified_assets - verified_liabilities, 2),
            ),
            provisional=FinancialHorizonAmountSummary(
                assets=round(provisional_assets, 2),
                liabilities=round(provisional_liabilities, 2),
                net=round(provisional_assets - provisional_liabilities, 2),
            ),
            cash_plan_readiness=cash_plan.readiness,
            safe_to_spend=cash_plan.flexible_money,
            safe_to_spend_basis=cash_plan.balance_basis,
            reason_codes=list(dict.fromkeys(reason_codes)),
        )

    def _source_health(
        self, positions: list[AccountPositionResponse]
    ) -> list[FinancialHorizonSourceHealth]:
        rows: list[FinancialHorizonSourceHealth] = []
        for position in positions:
            status: Literal["fresh", "due", "overdue", "unknown", "incomplete", "review"]
            if position.status == "stale" or position.position_status == "stale":
                status = "overdue"
            elif position.status in {"needs_review", "incomplete"} or position.position_status in {
                "needs_review",
                "incomplete",
            }:
                status = "review"
            elif position.coverage_complete is False:
                status = "incomplete"
            else:
                status = position.coverage_status
            rows.append(
                FinancialHorizonSourceHealth(
                    source_id=position.financial_account_id,
                    source=position.observed_source or "balance_position",
                    status=status,
                    latest_sync_at=position.latest_sync_at,
                    coverage_start=position.coverage_start,
                    coverage_end=position.coverage_end,
                    coverage_complete=position.coverage_complete,
                    reason_codes=list(
                        dict.fromkeys([*position.reason_codes, *position.position_reason_codes])
                    ),
                )
            )
        return rows

    def _base_risks(
        self,
        cash_plan: CashPlanResponse,
        positions: list[AccountPositionResponse],
        source_health: list[FinancialHorizonSourceHealth],
        *,
        as_of: date,
    ) -> list[FinancialHorizonRiskSignal]:
        risks: list[FinancialHorizonRiskSignal] = []
        if cash_plan.flexible_money is not None and cash_plan.flexible_money < 0:
            risks.append(
                FinancialHorizonRiskSignal(
                    code="unfunded_commitment",
                    severity="danger",
                    label="Commitments exceed safe-to-spend",
                    detail="Cash Plan flexible money is below zero after confirmed commitments and reserves.",
                    date=as_of,
                    amount=abs(cash_plan.flexible_money),
                    source="cash_plan",
                )
            )
        for item in source_health:
            if item.status in {"due", "overdue", "incomplete", "review"}:
                risks.append(
                    FinancialHorizonRiskSignal(
                        code=(
                            "stale_source" if item.status in {"due", "overdue"} else "low_coverage"
                        ),
                        severity="warning",
                        label="Source freshness or coverage needs review",
                        detail=f"{item.source_id} is {item.status}; estimates remain provisional.",
                        source="source_health",
                    )
                )
        if not positions:
            risks.append(
                FinancialHorizonRiskSignal(
                    code="low_coverage",
                    severity="warning",
                    label="No financial positions",
                    detail="PFIS has no active account position evidence for this user.",
                    source="balance_position",
                )
            )
        return risks

    def _missing_evidence(
        self,
        *,
        accounts: list[FinancialAccount],
        positions: list[AccountPositionResponse],
        cash_plan: CashPlanResponse,
        forecast: AccountBalanceForecastResponse | None,
        lowest_reason: str | None,
    ) -> list[str]:
        missing: list[str] = []
        if not accounts:
            missing.append("active_financial_account")
        if not any(position.verified_balance is not None for position in positions):
            missing.append("verified_balance_position")
        if not cash_plan.primary_financial_account_id:
            missing.append("cash_plan_primary_account")
        if cash_plan.readiness != "ready":
            missing.append(f"cash_plan_{cash_plan.readiness}")
        if forecast is None:
            missing.append("balance_forecast")
        elif forecast.status != "ready":
            missing.append(f"balance_forecast_{forecast.status}")
        if lowest_reason is not None:
            missing.append(f"lowest_point_{lowest_reason}")
        return missing

    def _status(
        self,
        *,
        missing_evidence: list[str],
        risk_signals: list[FinancialHorizonRiskSignal],
        source_health: list[FinancialHorizonSourceHealth],
        cash_plan: CashPlanResponse,
        forecast: AccountBalanceForecastResponse | None,
    ) -> FinancialHorizonStatus:
        if any(risk.severity == "danger" for risk in risk_signals):
            return "deficit"
        if any(item.status in {"due", "overdue"} for item in source_health):
            return "stale"
        if (
            "active_financial_account" in missing_evidence
            or "verified_balance_position" in missing_evidence
            or forecast is None
            or (forecast.status == "needs_anchor" if forecast is not None else False)
        ):
            return "low_data"
        if cash_plan.readiness != "ready" or risk_signals or missing_evidence:
            return "attention"
        return "healthy"

    @staticmethod
    def _commitment_confidence(source_kind: str, confirmed: bool) -> float:
        if not confirmed:
            return 0.55
        if source_kind in {"connector", "statement"}:
            return 0.98
        if source_kind == "email":
            return 0.86
        return 0.9

    @staticmethod
    def _dedupe_events(events: list[FinancialHorizonEvent]) -> list[FinancialHorizonEvent]:
        seen: set[tuple[date, str, float | None, str]] = set()
        result: list[FinancialHorizonEvent] = []
        for event in events:
            key = (event.date, event.label.casefold(), event.amount, event.source_id or "")
            if key in seen:
                continue
            seen.add(key)
            result.append(event)
        return result
