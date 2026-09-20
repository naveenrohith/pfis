"""Direct branch coverage for card planning read models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.schemas.financial_position import CardSpendRoutingRequest
from app.services import card_portfolio_payment_plan_service as portfolio_module
from app.services import card_spend_routing_service as routing_module
from app.services.card_portfolio_payment_plan_service import (
    CardPortfolioPaymentPlanService,
    _CardPlanRow,
)
from app.services.card_spend_routing_service import CardSpendRoutingService, _build_candidate


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def scalars(self, _statement):
        return _Rows(self.rows)


def _runway(*, funding="bank-1", due=date(2026, 10, 1), status="ready", confidence=0.8):
    return SimpleNamespace(
        funding_account_id=funding,
        funding_account_label="Plan Bank",
        due_date=due,
        status=status,
        confidence=confidence,
        total_due=1000.0,
        minimum_due=100.0,
        currency="INR",
        statement_date=date(2026, 9, 1),
        position_reason_codes=[],
        evidence=[],
        assumptions=[],
    )


def _scenario(amount=100, additional=100, *, status="eligible"):
    return SimpleNamespace(
        payment_amount=float(amount),
        planned_payment_applied=0.0,
        additional_payment_amount=float(additional),
        effective_payment_amount=float(additional),
        remaining_total_due=0.0,
        status=status,
    )


def _row(*, funding="bank-1", due=date(2026, 10, 1), scenario=None):
    account = SimpleNamespace(id=f"card-{funding}-{due.day}", institution_name="Plan Card")
    runway = _runway(funding=funding, due=due)
    return _CardPlanRow(
        account=account,
        runway=runway,
        minimum_due_scenario=scenario,
        total_due_scenario=scenario,
    )


def _forecast(*, status="ready", low=1000, missing_date=False):
    due = date(2026, 10, 1)
    points = (
        []
        if missing_date
        else [
            SimpleNamespace(
                date=due,
                expected_balance=1200,
                low_balance=low,
                high_balance=1300,
            )
        ]
    )
    return SimpleNamespace(
        status=status,
        points=points,
        position_reason_codes=["forecast_evidence"],
        starting_balance=1500.0,
        starting_balance_as_of=date(2026, 9, 20),
        starting_balance_basis="observed",
        confidence=0.8,
    )


@pytest.mark.asyncio
async def test_portfolio_compare_empty_and_funding_path_statuses(monkeypatch):
    monkeypatch.setattr(portfolio_module, "user_financial_today", _today)
    empty = await CardPortfolioPaymentPlanService(_Db()).compare("user-1")
    assert empty.state == "no_active_cards"
    assert empty.minimum_due_plan.status == "unavailable"

    row = _row(scenario=_scenario())
    covered = CardPortfolioPaymentPlanService._build_funding_path(
        "bank-1", [(row, row.minimum_due_scenario)], forecast=_forecast()
    )
    assert covered.status == "covered"
    assert covered.cards_covered_on_lower_band == 1

    at_risk = CardPortfolioPaymentPlanService._build_funding_path(
        "bank-1", [(row, row.minimum_due_scenario)], forecast=_forecast(low=50)
    )
    assert at_risk.status == "at_risk"
    assert at_risk.cards_at_risk == 1

    missing = CardPortfolioPaymentPlanService._build_funding_path(
        "bank-1",
        [(row, row.minimum_due_scenario)],
        forecast=_forecast(status="needs_anchor", missing_date=True),
    )
    assert missing.status == "unavailable"
    assert "due_date_outside_funding_forecast" in missing.reason_codes

    unavailable = CardPortfolioPaymentPlanService._build_funding_path(
        "bank-1", [(row, row.minimum_due_scenario)], forecast=None
    )
    assert unavailable.status == "unavailable"
    strategy = await CardPortfolioPaymentPlanService(_Db())._build_strategy(
        [row],
        "minimum_due",
        forecasts={"bank-1": _forecast()},
        as_of=date(2026, 9, 20),
    )
    assert strategy.status == "covered"


@pytest.mark.asyncio
async def test_card_spend_preview_covers_recommendation_and_review_states(monkeypatch):
    monkeypatch.setattr(routing_module, "user_financial_today", _today)
    monkeypatch.setattr(routing_module, "get_ledger_currency", _currency)
    account = SimpleNamespace(id="card-1", institution_name="Ready Card", currency="INR")

    async def ready_overview(_self, _user_id, _account_id):
        return _overview()

    monkeypatch.setattr(routing_module.FinancialPositionService, "card_overview", ready_overview)
    service = CardSpendRoutingService(_Db([account]))
    response = await service.preview(
        "user-1",
        CardSpendRoutingRequest(amount=Decimal("100"), category="groceries", priority="balanced"),
    )
    assert response.state == "ready"
    assert response.recommended_card_id == "card-1"
    assert response.options[0].status == "recommended"

    async def missing_overview(_self, _user_id, _account_id):
        return _overview(
            current=None, limit=None, projection_available=False, balance_status="needs_review"
        )

    monkeypatch.setattr(routing_module.FinancialPositionService, "card_overview", missing_overview)
    review = await CardSpendRoutingService(_Db([account])).preview(
        "user-1",
        CardSpendRoutingRequest(amount=Decimal("100"), category=None, priority="rewards"),
    )
    assert review.state == "needs_review"
    assert review.recommended_card_id is None

    mismatch = _build_candidate(
        SimpleNamespace(id="usd-card", institution_name="USD Card", currency="USD"),
        _overview(current="100", limit="1000"),
        amount=Decimal("100"),
        category=None,
        ledger_currency="INR",
    )
    assert mismatch.option.status == "needs_review"
    assert "currency_mismatch" in mismatch.option.reason_codes


def _overview(
    *,
    current="500",
    limit="5000",
    projection_available=True,
    balance_status="observed",
):
    projection = SimpleNamespace(
        status="available" if projection_available else "unavailable",
        projected_balance=700.0 if projection_available else None,
        confidence=0.8,
    )
    return SimpleNamespace(
        provider_current_outstanding=None,
        estimated_current_balance=(float(current) if current is not None else None),
        credit_limit=(float(limit) if limit is not None else None),
        provider_credit_limit=None,
        reward_rules=[{"label": "Everywhere", "rate_pct": 2}],
        next_statement_projection=projection,
        utilization_target_pct=40.0,
        balance_status=balance_status,
        balance_confidence=0.8,
    )


async def _today(_db, _user_id):
    return date(2026, 9, 20)


async def _currency(_db, _user_id):
    return "INR"
