"""Branch coverage for card due-date affordability decisions."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services import card_due_runway_service as runway_module
from app.services.card_due_runway_service import CardDueRunwayService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _DB:
    def __init__(self, scalar_values=()):
        self.scalar_values = list(scalar_values)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return _Rows()


TODAY = date(2026, 9, 20)


def _card(**values):
    fields = {
        "financial_account_id": "card-1",
        "currency": "INR",
        "provider_current_outstanding": None,
        "estimated_current_balance": 400.0,
        "provider_credit_limit": None,
        "credit_limit": 2000.0,
        "provider_available_credit": None,
        "available_credit_limit": 1600.0,
        "total_due": 500.0,
        "minimum_due": 50.0,
        "statement_date": date(2026, 9, 1),
        "due_date": date(2026, 9, 25),
        "preferred_payment_account_id": None,
        "planned_payments": [],
        "balance_reason_codes": [],
        "balance_confidence": 0.9,
    }
    fields.update(values)
    return SimpleNamespace(**fields)


def _forecast(
    *,
    status="ready",
    low=700,
    expected=800,
    high=900,
    due_date=TODAY + __import__("datetime").timedelta(days=5),
):
    point = SimpleNamespace(
        date=due_date,
        expected_balance=expected,
        low_balance=low,
        high_balance=high,
    )
    return SimpleNamespace(
        status=status,
        points=[point],
        horizon_start=due_date,
        horizon_end=due_date,
        starting_balance_basis="observed",
        starting_balance_as_of=TODAY,
        position_status="observed",
        confidence=0.8,
        position_reason_codes=[],
    )


def _account(account_id="card-1", *, account_type="credit_card", balance_kind="liability"):
    return SimpleNamespace(
        id=account_id,
        account_type=account_type,
        balance_kind=balance_kind,
        institution_name="Coverage Card",
        masked_number="****1234",
    )


@pytest.mark.asyncio
async def test_runway_handles_missing_and_invalid_card_accounts(monkeypatch):
    service = CardDueRunwayService(_DB([None]))
    assert await service.runway("u1", "missing") is None

    monkeypatch.setattr(runway_module, "user_financial_today", lambda *_: TODAY)
    invalid = CardDueRunwayService(_DB([_account(account_type="bank", balance_kind="asset")]))
    with pytest.raises(ValueError, match="credit-card liability"):
        await invalid.runway("u1", "bank-1")


@pytest.mark.asyncio
async def test_runway_reports_no_statement_and_due_passed(monkeypatch):
    monkeypatch.setattr(runway_module, "user_financial_today", _today)
    monkeypatch.setattr(
        runway_module.FinancialPositionService,
        "card_overview",
        _card_overview(_card(total_due=None, due_date=None)),
    )
    no_statement = await CardDueRunwayService(_DB([_account()])).runway("u1", "card-1")
    assert no_statement.status == "needs_statement"
    assert no_statement.payment_scenarios == []

    passed_card = _card(due_date=date(2026, 9, 10))
    monkeypatch.setattr(
        runway_module.FinancialPositionService,
        "card_overview",
        _card_overview(passed_card),
    )
    passed = await CardDueRunwayService(_DB([_account()])).runway("u1", "card-1")
    assert passed.status == "due_passed"
    assert passed.days_until_due == -10


async def _today(_db, _user_id):
    return TODAY


def _card_overview(card):
    async def fake(self, user_id, account_id):
        return card

    return fake


@pytest.mark.asyncio
async def test_runway_requires_payment_account_and_asset_funding(monkeypatch):
    monkeypatch.setattr(runway_module, "user_financial_today", _today)
    card = _card()
    monkeypatch.setattr(
        runway_module.FinancialPositionService, "card_overview", _card_overview(card)
    )
    missing = await CardDueRunwayService(_DB([_account()])).runway("u1", "card-1")
    assert missing.status == "needs_payment_account"

    card.preferred_payment_account_id = "funding-1"
    monkeypatch.setattr(
        runway_module.FinancialPositionService, "card_overview", _card_overview(card)
    )
    not_asset = await CardDueRunwayService(
        _DB(
            [
                _account(),
                _account("funding-1", account_type="credit_card", balance_kind="liability"),
            ]
        )
    ).runway("u1", "card-1")
    assert not_asset.status == "needs_review"
    assert "funding_account_not_asset" in not_asset.position_reason_codes


@pytest.mark.asyncio
async def test_runway_handles_missing_and_overlong_forecasts(monkeypatch):
    monkeypatch.setattr(runway_module, "user_financial_today", _today)
    card = _card(preferred_payment_account_id="funding-1")
    monkeypatch.setattr(
        runway_module.FinancialPositionService, "card_overview", _card_overview(card)
    )
    funding = _account("funding-1", account_type="bank", balance_kind="asset")

    async def no_forecast(self, *args, **kwargs):
        return None

    monkeypatch.setattr(runway_module.BalanceForecastService, "forecast", no_forecast)
    missing = await CardDueRunwayService(_DB([_account(), funding])).runway("u1", "card-1")
    assert missing.status == "needs_review"
    assert "funding_account_not_found" in missing.position_reason_codes

    async def overlong(self, *args, **kwargs):
        return _forecast(due_date=date(2026, 9, 25))

    card.due_date = date(2027, 4, 1)
    monkeypatch.setattr(runway_module.BalanceForecastService, "forecast", overlong)
    overlong_result = await CardDueRunwayService(_DB([_account(), funding])).runway("u1", "card-1")
    assert overlong_result.status == "needs_review"
    assert "due_horizon_exceeds_forecast" in overlong_result.position_reason_codes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("forecast_status", "low", "expected_status"),
    [
        ("needs_anchor", 700, "needs_funding_anchor"),
        ("ready", 300, "at_risk"),
        ("ready", 700, "covered"),
        ("incomplete", 700, "needs_review"),
    ],
)
async def test_runway_classifies_forecast_and_conservative_coverage(
    monkeypatch, forecast_status, low, expected_status
):
    monkeypatch.setattr(runway_module, "user_financial_today", _today)
    card = _card(preferred_payment_account_id="funding-1")
    funding = _account("funding-1", account_type="bank", balance_kind="asset")
    monkeypatch.setattr(
        runway_module.FinancialPositionService, "card_overview", _card_overview(card)
    )

    async def forecast(self, *args, **kwargs):
        return _forecast(status=forecast_status, low=low, expected=low + 100, high=low + 200)

    async def planned(self, *args, **kwargs):
        return Decimal("100")

    monkeypatch.setattr(runway_module.BalanceForecastService, "forecast", forecast)
    monkeypatch.setattr(CardDueRunwayService, "_planned_payments_before_due", planned)
    result = await CardDueRunwayService(_DB([_account(), funding])).runway("u1", "card-1")

    assert result.status == expected_status
    assert result.planned_payment_total == 100
    assert result.payment_scenarios[0].planned_payment_applied == 50
    assert result.payment_scenarios[1].effective_payment_amount == 500


def test_payment_scenarios_cover_unavailable_and_at_risk_paths():
    unavailable = CardDueRunwayService._payment_scenarios(
        total_due=Decimal("500"),
        minimum_due=None,
        due_date=TODAY,
        planned_payment_total=Decimal("100"),
        expected=None,
        low=None,
        high=None,
    )
    assert len(unavailable) == 1
    assert unavailable[0].status == "unavailable"
    assert CardDueRunwayService._decimal(None) == 0

    at_risk = CardDueRunwayService._payment_scenarios(
        total_due=Decimal("500"),
        minimum_due=Decimal("50"),
        due_date=TODAY,
        planned_payment_total=Decimal("100"),
        expected=Decimal("600"),
        low=Decimal("100"),
        high=Decimal("800"),
    )
    assert at_risk[0].status == "covered"
    assert at_risk[1].status == "at_risk"
    assert at_risk[1].lower_band_cash_gap == 400
