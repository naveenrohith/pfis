"""Deterministic service-level coverage for forecast policy branches."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.account import FinancialAccount
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionType,
)
from app.services import balance_forecast_service as forecast_module
from app.services.balance_forecast_service import BalanceForecastService, _ForecastEvent
from app.services.financial_position_service import FinancialPositionService


class _Rows:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return self.rows


class _ForecastDb:
    def __init__(
        self, *, account=None, transactions=(), scalar_values=(), scalar_rows=(), schedule=()
    ):
        self.account = account
        self.transactions = list(transactions)
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [list(rows) for rows in scalar_rows]
        self.schedule = list(schedule)
        self.scalar_calls = 0
        self.scalars_calls = 0
        self.execute_calls = 0

    async def scalar(self, _statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1 and self.account is not None:
            return self.account
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return None

    async def scalars(self, _statement):
        self.scalars_calls += 1
        if self.scalar_rows:
            return _Rows(self.scalar_rows.pop(0))
        return _Rows(self.transactions)

    async def execute(self, _statement):
        self.execute_calls += 1
        return _Rows(self.schedule)


def _account(*, account_id: str = "account-1", balance_kind: str = "asset") -> FinancialAccount:
    return FinancialAccount(
        id=account_id,
        user_id="user-1",
        institution_name="Unit Test Bank",
        account_type="bank" if balance_kind == "asset" else "loan",
        balance_kind=balance_kind,
        masked_number="****1001",
        currency="INR",
        is_active=True,
    )


def _transaction(
    *, transaction_id: str, transaction_type: TransactionType, amount: str
) -> Transaction:
    return Transaction(
        id=transaction_id,
        user_id="user-1",
        financial_account_id="account-1",
        amount=Decimal(amount),
        currency="INR",
        transaction_type=transaction_type,
        payment_method=PaymentMethod.OTHER,
        payment_rail=PaymentRail.OTHER,
        card_event=CardEvent.NONE,
        transaction_status="settled",
        transaction_date=date(2026, 9, 18),
        merchant_raw=transaction_id,
        reviewed_flag=True,
        review_outcome="matched",
        is_transfer=False,
        is_accounting_adjustment=False,
    )


@pytest.mark.asyncio
async def test_forecast_service_core_path_covers_baseline_events_and_review_watch(monkeypatch):
    today = date(2026, 9, 19)
    account = _account()
    transactions = [
        _transaction(transaction_id="debit-1", transaction_type=TransactionType.DEBIT, amount="10"),
        _transaction(transaction_id="debit-2", transaction_type=TransactionType.DEBIT, amount="20"),
        _transaction(
            transaction_id="credit-1", transaction_type=TransactionType.CREDIT, amount="30"
        ),
    ]
    db = _ForecastDb(account=account, transactions=transactions)
    position = SimpleNamespace(
        estimated_balance=Decimal("1000"),
        estimated_as_of=today,
        verified_balance=None,
        balance_as_of=None,
        position_status="needs_review",
        position_confidence=Decimal("0.80"),
        coverage_status="due",
        observed_as_of=today,
        position_reason_codes=["unexplained_balance_movement"],
    )
    events = [
        _ForecastEvent(
            event_date=today + timedelta(days=1),
            amount=Decimal("100"),
            increases_balance=True,
            confidence=Decimal("0.90"),
            evidence_id="income-1",
        ),
        _ForecastEvent(
            event_date=today + timedelta(days=2),
            amount=Decimal("50"),
            increases_balance=False,
            confidence=Decimal("0.50"),
            evidence_id="bill-1",
        ),
    ]

    async def fake_position(self, user_id, account_id, *, as_of=None):
        assert (user_id, account_id, as_of) == ("user-1", "account-1", None)
        return position

    async def fake_today(_db, user_id):
        assert user_id == "user-1"
        return today

    async def fake_events(self, user_id, selected_account, **kwargs):
        assert user_id == "user-1"
        assert selected_account is account
        assert kwargs["horizon_start"] == today
        return events

    async def fake_credit_limit(self, user_id, selected_account, *, as_of):
        assert (user_id, selected_account, as_of) == ("user-1", account, None)
        return None

    monkeypatch.setattr(FinancialPositionService, "account_position", fake_position)
    monkeypatch.setattr(forecast_module, "user_financial_today", fake_today)
    monkeypatch.setattr(BalanceForecastService, "_dated_events", fake_events)
    monkeypatch.setattr(BalanceForecastService, "_credit_limit", fake_credit_limit)

    result = await BalanceForecastService(db).forecast("user-1", "account-1", horizon_days=3)

    assert result is not None
    assert result.status == "needs_review"
    assert result.starting_balance_basis == "estimated"
    assert result.historical_activity_count == 3
    assert result.scheduled_increase_total == 100
    assert result.scheduled_decrease_total == 50
    assert result.data_sufficiency == "medium"
    assert result.points[1].risk == "watch"
    assert result.points[1].risk_reasons == ["unexplained_balance_movement"]
    assert result.points[2].scheduled_decrease == 50
    assert result.confidence > 0


@pytest.mark.asyncio
async def test_forecast_service_fails_closed_without_position_anchor(monkeypatch):
    today = date(2026, 9, 19)
    account = _account()
    db = _ForecastDb(account=account)

    async def fake_position(self, user_id, account_id, *, as_of=None):
        return None

    async def fake_today(_db, user_id):
        return today

    async def fake_events(self, user_id, selected_account, **kwargs):
        return []

    monkeypatch.setattr(FinancialPositionService, "account_position", fake_position)
    monkeypatch.setattr(forecast_module, "user_financial_today", fake_today)
    monkeypatch.setattr(BalanceForecastService, "_dated_events", fake_events)

    result = await BalanceForecastService(db).forecast("user-1", "account-1", horizon_days=0)

    assert result is not None
    assert result.status == "needs_anchor"
    assert result.horizon_days == 1
    assert result.points == []
    assert result.position_reason_codes == ["verified_observation_required"]


@pytest.mark.asyncio
async def test_dated_events_include_asset_evidence_and_liability_schedule_fallbacks():
    today = date(2026, 9, 19)
    asset = _account()
    income = SimpleNamespace(
        id="cash-plan-1",
        primary_financial_account_id=asset.id,
        next_income_date=today + timedelta(days=2),
        next_income_amount=Decimal("1000"),
        updated_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
    )
    commitments = [
        SimpleNamespace(
            id="commitment-statement",
            financial_account_id=asset.id,
            due_date=today + timedelta(days=1),
            amount=Decimal("125"),
            source_kind="statement",
        ),
        SimpleNamespace(
            id="commitment-global",
            financial_account_id=None,
            due_date=today + timedelta(days=3),
            amount=Decimal("75"),
            source_kind="manual",
        ),
        SimpleNamespace(
            id="commitment-other-account",
            financial_account_id="other-account",
            due_date=today + timedelta(days=1),
            amount=Decimal("999"),
            source_kind="manual",
        ),
    ]
    funding_intent = SimpleNamespace(
        id="intent-funding",
        paying_account_id=asset.id,
        financial_account_id="card-account",
        planned_for=today + timedelta(days=2),
        amount=Decimal("200"),
        status="planned",
        created_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
    )
    asset_db = _ForecastDb(
        scalar_values=[income],
        scalar_rows=[commitments, [funding_intent]],
    )
    asset_events = await BalanceForecastService(asset_db)._dated_events(
        "user-1",
        asset,
        horizon_start=today,
        horizon_end=today + timedelta(days=3),
        as_of=today,
    )

    assert [event.evidence_id for event in asset_events] == [
        "cash_plan:cash-plan-1:income",
        "commitment:commitment-statement",
        "commitment:commitment-global",
        "card_payment_intent:intent-funding:funding",
    ]
    assert asset_events[0].increases_balance is True
    assert asset_events[1].confidence == Decimal("0.98")
    assert asset_events[2].confidence == Decimal("0.90")

    liability = _account(account_id="loan-account", balance_kind="liability")
    payment_intent = SimpleNamespace(
        id="intent-liability",
        paying_account_id="bank-account",
        financial_account_id=liability.id,
        planned_for=today + timedelta(days=1),
        amount=Decimal("300"),
        status="planned",
        created_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC),
    )
    incomplete_liability = SimpleNamespace(id="loan-1", complete_schedule=False)
    complete_liability = SimpleNamespace(id="loan-2", complete_schedule=True)
    schedule_rows = [
        (
            SimpleNamespace(
                id="schedule-fallback",
                due_date=today + timedelta(days=2),
                installment_amount=Decimal("400"),
                confidence=None,
                status="upcoming",
            ),
            incomplete_liability,
        ),
        (
            SimpleNamespace(
                id="schedule-explicit",
                due_date=today + timedelta(days=3),
                installment_amount=Decimal("500"),
                confidence=Decimal("0.55"),
                status="upcoming",
            ),
            complete_liability,
        ),
    ]
    liability_db = _ForecastDb(
        scalar_values=[None],
        scalar_rows=[[], [payment_intent]],
        schedule=schedule_rows,
    )
    liability_events = await BalanceForecastService(liability_db)._dated_events(
        "user-1",
        liability,
        horizon_start=today,
        horizon_end=today + timedelta(days=3),
        as_of=None,
    )

    assert [event.evidence_id for event in liability_events] == [
        "card_payment_intent:intent-liability:liability",
        "liability_schedule:schedule-fallback",
        "liability_schedule:schedule-explicit",
    ]
    assert liability_events[1].confidence == Decimal("0.72")
    assert liability_events[2].confidence == Decimal("0.55")


@pytest.mark.asyncio
async def test_credit_limit_returns_only_current_card_limit():
    service = BalanceForecastService(_ForecastDb())
    asset = _account()
    assert await service._credit_limit("user-1", asset, as_of=None) is None

    card = FinancialAccount(
        id="card-1",
        user_id="user-1",
        institution_name="Unit Test Card",
        account_type="credit_card",
        balance_kind="liability",
        masked_number="****1002",
        currency="INR",
        is_active=True,
    )
    statement = SimpleNamespace(credit_limit=Decimal("25000"))
    db = _ForecastDb(scalar_values=[statement])
    assert await BalanceForecastService(db)._credit_limit(
        "user-1", card, as_of=date(2026, 9, 19)
    ) == Decimal("25000")
