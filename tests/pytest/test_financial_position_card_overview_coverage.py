"""Direct coverage for card overview statement and roll-forward branches."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services import financial_position_service as service_module
from app.services.financial_position_service import FinancialPositionService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _DB:
    def __init__(self, *, scalar_values=(), scalar_rows=(), execute_rows=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]
        self.execute_rows = [_Rows(rows) for rows in execute_rows]

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()

    async def execute(self, _statement):
        return self.execute_rows.pop(0) if self.execute_rows else _Rows()


TODAY = date(2026, 9, 20)


def _account():
    return SimpleNamespace(
        id="card-1",
        user_id="u1",
        institution_name="Coverage Card",
        account_type="credit_card",
        balance_kind="liability",
        currency="INR",
        masked_number="****1234",
    )


def _position(**values):
    fields = {
        "estimated_balance": 600.0,
        "estimated_as_of": TODAY,
        "observed_balance": 550.0,
        "observed_as_of": TODAY - timedelta(days=1),
        "observed_source": "manual",
        "observed_source_record_id": "balance-1",
        "observed_at": datetime(2026, 9, 19, tzinfo=UTC),
        "observed_effective_at": datetime(2026, 9, 19, tzinfo=UTC),
        "settled_movement_since_observation": 50.0,
        "pending_increase": 10.0,
        "pending_decrease": 2.0,
        "coverage_start": None,
        "coverage_end": None,
        "latest_sync_at": None,
        "coverage_complete": True,
        "coverage_status": "fresh",
        "reconciliation_delta": 0.0,
        "last_reconciled_at": None,
        "position_status": "estimated",
        "position_confidence": 0.8,
        "position_reason_codes": [],
    }
    fields.update(values)
    return SimpleNamespace(**fields)


def _transaction(
    *, event, kind, amount, transaction_date=TODAY - timedelta(days=2), status="settled"
):
    return SimpleNamespace(
        id=f"{event}-{amount}",
        amount=Decimal(str(amount)),
        transaction_type=kind,
        transaction_status=status,
        card_event=event,
        is_transfer=False,
        is_accounting_adjustment=False,
        review_outcome="matched",
        transaction_date=transaction_date,
    )


def _statement(statement_id="statement-1"):
    return SimpleNamespace(
        id=statement_id,
        statement_date=date(2026, 9, 1),
        period_start=date(2026, 8, 2),
        period_end=date(2026, 9, 1),
        due_date=date(2026, 9, 25),
        total_due=Decimal("500"),
        minimum_due=Decimal("50"),
        credit_limit=Decimal("2000"),
        available_credit_limit=Decimal("1500"),
        available_cash_limit=Decimal("500"),
        previous_due=Decimal("300"),
        payments_credits=Decimal("100"),
        purchases_debits=Decimal("400"),
        finance_charges=Decimal("10"),
    )


def _line(statement_id="statement-1"):
    return SimpleNamespace(
        id="line-1",
        credit_card_statement_id=statement_id,
        line_number=1,
        transaction_date=date(2026, 9, 5),
        description="Coffee House",
        amount=Decimal("100"),
        transaction_type="debit",
        card_event="purchase",
        component_kind="ordinary",
        issuer_plan_reference=None,
        installment_number=None,
        merchant_normalized="Coffee House",
        merchant_confidence=0.9,
        review_outcome="matched",
        created_transaction_id="txn-1",
    )


@pytest.mark.asyncio
async def test_card_overview_without_statement_is_explicitly_unavailable(monkeypatch):
    db = _DB(scalar_values=[None, None], scalar_rows=[[], [], [], []])
    service = FinancialPositionService(db)

    async def today(_db, _user_id):
        return TODAY

    async def card_account(self, user_id, account_id):
        return _account()

    async def no_position(self, user_id, account_id):
        return None

    async def no_patterns(self, *args, **kwargs):
        return []

    monkeypatch.setattr(service_module, "user_financial_today", today)
    monkeypatch.setattr(service, "_require_card_account", card_account.__get__(service))
    monkeypatch.setattr(service, "account_position", no_position.__get__(service))
    monkeypatch.setattr(service_module.RecurringPatternService, "analyze", no_patterns)

    response = await service.card_overview("u1", "card-1")

    assert response.latest_statement_id is None
    assert response.total_due is None
    assert response.balance_status == "needs_observation"
    assert response.coverage == {
        "matched": 0,
        "newly_imported": 0,
        "ignored_by_rule": 0,
        "needs_review": 0,
    }
    assert response.statement_history == []
    assert response.next_statement_projection.status == "needs_recent_statement"


@pytest.mark.asyncio
async def test_card_overview_rolls_forward_statement_and_provider_evidence(monkeypatch):
    statement = _statement()
    line = _line()
    payment = _transaction(event="payment", kind="credit", amount=50)
    purchase = _transaction(event="purchase", kind="debit", amount=100)
    refund = _transaction(event="refund", kind="refund", amount=25)
    reversal = _transaction(event="reversal", kind="debit", amount=10, status="pending")
    provider = SimpleNamespace(
        current_outstanding=Decimal("625"),
        billed_due=Decimal("500"),
        pending_amount=Decimal("10"),
        credit_limit=Decimal("2200"),
        available_credit=Decimal("1575"),
        as_of=TODAY,
        source="connector",
        source_record_id="provider-1",
        observed_at=datetime(2026, 9, 20, 10, tzinfo=UTC),
        effective_at=datetime(2026, 9, 20, 9, tzinfo=UTC),
        coverage_start=datetime(2026, 9, 1, tzinfo=UTC),
        coverage_end=datetime(2026, 10, 1, tzinfo=UTC),
        coverage_complete=True,
    )
    preference = SimpleNamespace(
        utilization_target_pct=Decimal("30"),
        preferred_payment_account_id="bank-1",
        reward_rules_json=json.dumps([{"category": "travel", "rate": 2}]),
    )
    planned = SimpleNamespace(
        id="payment-1",
        financial_account_id="card-1",
        amount=Decimal("100"),
        planned_for=date(2026, 9, 23),
        status="planned",
        paying_account_id="bank-1",
        note="planned",
        transfer_group_id=None,
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    calendar = SimpleNamespace(
        id="event-1",
        financial_account_id="card-1",
        event_type="annual_fee",
        label="Annual fee",
        event_date=date(2026, 12, 1),
        source_kind="manual",
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    db = _DB(
        scalar_values=[provider, preference],
        scalar_rows=[
            [statement],
            [payment, purchase, refund],
            [line],
            [planned],
            [calendar],
            [reversal],
            [refund],
        ],
        execute_rows=[[]],
    )
    service = FinancialPositionService(db)

    async def today(_db, _user_id):
        return TODAY

    async def card_account(self, user_id, account_id):
        return _account()

    async def position(self, user_id, account_id):
        return _position()

    async def no_patterns(self, *args, **kwargs):
        return []

    monkeypatch.setattr(service_module, "user_financial_today", today)
    monkeypatch.setattr(service, "_require_card_account", card_account.__get__(service))
    monkeypatch.setattr(service, "account_position", position.__get__(service))
    monkeypatch.setattr(service_module.RecurringPatternService, "analyze", no_patterns)

    response = await service.card_overview("u1", "card-1")

    assert response.latest_statement_id == "statement-1"
    assert response.paid_since_statement == 50
    assert response.unbilled_activity == 75
    assert response.unbilled_activity_increase == 100
    assert response.unbilled_activity_decrease == 25
    assert response.provider_current_outstanding == 625
    assert response.provider_available_credit == 1575
    assert response.statement_utilization_pct == 25
    assert response.estimated_utilization_pct == 30
    assert response.utilization_target_pct == 30
    assert response.reward_rules == [{"category": "travel", "rate": 2}]
    assert response.coverage["matched"] == 1
    assert response.statement_lines[0].description == "Coffee House"
    assert response.planned_payments[0].amount == 100
    assert response.calendar[0].event_type == "annual_fee"
    assert response.activity_signals
    assert response.next_statement_projection.status != "unavailable"
