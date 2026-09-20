"""Direct branch coverage for card utilization history calculations."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services import card_utilization_history_service as history_module
from app.services.card_utilization_history_service import CardUtilizationHistoryService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, *, scalar_values=(), row_values=()):
        self.scalar_values = list(scalar_values)
        self.row_values = list(row_values)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return _Rows(self.row_values.pop(0) if self.row_values else ())


TODAY = date(2026, 9, 20)


def _account(*, account_type="credit_card"):
    return SimpleNamespace(id="card-1", user_id="user-1", account_type=account_type)


def _statement(
    statement_id="statement-1",
    *,
    statement_date=TODAY,
    total_due=Decimal("400"),
    credit_limit=Decimal("1000"),
    currency="INR",
):
    return SimpleNamespace(
        id=statement_id,
        statement_date=statement_date,
        total_due=total_due,
        credit_limit=credit_limit,
        currency=currency,
    )


def _transaction(
    transaction_id,
    transaction_date,
    *,
    amount="100",
    transaction_type="debit",
    status="completed",
    reviewed=True,
    review_outcome="newly_imported",
    accounting=False,
):
    return SimpleNamespace(
        id=transaction_id,
        transaction_date=transaction_date,
        transaction_timestamp=None,
        amount=Decimal(amount),
        transaction_type=transaction_type,
        transaction_status=status,
        reviewed_flag=reviewed,
        review_outcome=review_outcome,
        is_accounting_adjustment=accounting,
    )


@pytest.mark.parametrize(
    ("balance", "limit", "target", "expected"),
    [
        (Decimal("100"), Decimal("1000"), Decimal("30"), "within_target"),
        (Decimal("400"), Decimal("1000"), Decimal("30"), "over_target"),
        (Decimal("1000"), Decimal("1000"), Decimal("90"), "over_limit"),
        (Decimal("100"), Decimal("1000"), None, "within_limit"),
        (None, Decimal("1000"), Decimal("30"), "unavailable"),
        (Decimal("100"), Decimal("0"), Decimal("30"), "unavailable"),
    ],
)
def test_point_classifies_utilization_and_missing_issuer_facts(balance, limit, target, expected):
    point = CardUtilizationHistoryService._point(
        as_of=TODAY,
        basis="issuer_statement",
        statement_id="statement-1",
        balance=balance,
        credit_limit=limit,
        target=target,
        source_transaction_count=0,
        confidence=0.8,
        reason_codes=[],
    )

    assert point.status == expected
    assert point.balance == (float(balance) if balance is not None else None)


def test_trend_covers_missing_history_statement_delta_and_current_estimate():
    point = CardUtilizationHistoryService._point
    assert CardUtilizationHistoryService._trend([], []) == (
        "unavailable",
        "unavailable",
        None,
    )
    first = point(
        as_of=TODAY - timedelta(days=30),
        basis="issuer_statement",
        statement_id="first",
        balance=Decimal("100"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=0,
        confidence=1,
        reason_codes=[],
    )
    higher = point(
        as_of=TODAY - timedelta(days=10),
        basis="issuer_statement",
        statement_id="higher",
        balance=Decimal("140"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=0,
        confidence=1,
        reason_codes=[],
    )
    lower = point(
        as_of=TODAY,
        basis="ledger_estimate",
        statement_id="latest",
        balance=Decimal("70"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=1,
        confidence=0.8,
        reason_codes=[],
    )
    stable = point(
        as_of=TODAY,
        basis="issuer_statement",
        statement_id="stable",
        balance=Decimal("110"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=0,
        confidence=1,
        reason_codes=[],
    )

    assert CardUtilizationHistoryService._trend([first], []) == (
        "insufficient_history",
        "issuer_statements",
        None,
    )
    assert CardUtilizationHistoryService._trend([first, higher], []) == (
        "worsening",
        "issuer_statements",
        4.0,
    )
    assert CardUtilizationHistoryService._trend([first, stable], []) == (
        "stable",
        "issuer_statements",
        1.0,
    )
    assert CardUtilizationHistoryService._trend([first], [lower]) == (
        "improving",
        "issuer_to_current_estimate",
        -3.0,
    )


@pytest.mark.asyncio
async def test_history_rejects_missing_and_non_card_accounts():
    with pytest.raises(LookupError, match="Financial account not found"):
        await CardUtilizationHistoryService(_Db()).history("user-1", "missing")

    with pytest.raises(ValueError, match="credit-card account"):
        await CardUtilizationHistoryService(
            _Db(scalar_values=[_account(account_type="bank")])
        ).history("user-1", "bank-1")


@pytest.mark.asyncio
async def test_history_reports_statement_evidence_without_target_or_daily_rows(monkeypatch):
    async def today(_db, _user_id):
        return TODAY

    monkeypatch.setattr(history_module, "user_financial_today", today)
    service = CardUtilizationHistoryService(
        _Db(
            scalar_values=[_account(), None],
            row_values=[
                [
                    _statement(
                        total_due=None,
                        credit_limit=Decimal("0"),
                    )
                ]
            ],
        )
    )

    result = await service.history("user-1", "card-1")

    assert result.trend == "unavailable"
    assert result.daily_points == []
    assert "statement_total_due_missing" in result.statement_points[0].reason_codes
    assert "statement_credit_limit_missing" in result.statement_points[0].reason_codes
    assert "utilization_target_not_configured" in result.reason_codes


@pytest.mark.asyncio
async def test_daily_points_excludes_pending_activity_and_floors_negative_balance(
    monkeypatch,
):
    async def today(_db, _user_id):
        return TODAY

    monkeypatch.setattr(history_module, "user_financial_today", today)
    statement = _statement(
        statement_date=TODAY - timedelta(days=2),
        total_due=Decimal("100"),
        credit_limit=Decimal("1000"),
    )
    rows = [
        _transaction(
            "credit",
            TODAY - timedelta(days=1),
            amount="200",
            transaction_type="credit",
            reviewed=False,
        ),
        _transaction(
            "pending",
            TODAY - timedelta(days=1),
            amount="50",
            transaction_type="debit",
            status="pending",
        ),
    ]
    service = CardUtilizationHistoryService(_Db(row_values=[rows]))

    points, reasons = await service._daily_points(
        "user-1",
        "card-1",
        statement,
        as_of=TODAY,
        target=Decimal("30"),
        daily_limit=3,
    )

    assert len(points) == 2
    assert points[0].balance == 0
    assert "balance_floor_applied" in points[0].reason_codes
    assert "pending_activity_excluded" in points[0].reason_codes
    assert "unreviewed_activity_included" in points[0].reason_codes
    assert reasons == {
        "balance_floor_applied",
        "pending_activity_excluded",
        "unreviewed_activity_included",
    }
