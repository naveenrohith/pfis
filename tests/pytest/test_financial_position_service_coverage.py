"""Deterministic policy coverage for financial-position calculations."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.financial_position import CreditCardStatement, StatementLine
from app.models.transaction import CardEvent, PaymentRail, Transaction, TransactionType
from app.services.financial_position_service import (
    FinancialPositionService,
    _build_card_emi_plans,
    _card_activity_signals,
    _is_non_spend_payment_evidence,
)


def _account(
    *,
    account_id: str = "account-1",
    account_type: str = "bank",
    balance_kind: str = "asset",
) -> FinancialAccount:
    return FinancialAccount(
        id=account_id,
        user_id="user-1",
        institution_name="Coverage Bank",
        account_type=account_type,
        balance_kind=balance_kind,
        masked_number="****1001",
        currency="INR",
        is_active=True,
    )


def _transaction(
    *,
    transaction_id: str = "transaction-1",
    amount: str = "100.00",
    transaction_date: date = date(2026, 9, 10),
    transaction_timestamp: datetime | None = None,
    status: str = "completed",
    card_event: CardEvent = CardEvent.NONE,
) -> Transaction:
    return Transaction(
        id=transaction_id,
        user_id="user-1",
        amount=Decimal(amount),
        currency="INR",
        transaction_type=TransactionType.DEBIT,
        payment_rail=PaymentRail.OTHER,
        card_event=card_event,
        transaction_status=status,
        transaction_date=transaction_date,
        transaction_timestamp=transaction_timestamp,
        merchant_raw="Coverage merchant",
        merchant_normalized="Coverage merchant",
        financial_account_id="account-1",
    )


def _statement(statement_id: str = "statement-1") -> CreditCardStatement:
    return CreditCardStatement(
        id=statement_id,
        user_id="user-1",
        statement_import_id=f"import-{statement_id}",
        financial_account_id="card-1",
        statement_date=date(2026, 9, 15),
        period_start=date(2026, 8, 16),
        period_end=date(2026, 9, 15),
        due_date=date(2026, 10, 5),
        total_due=Decimal("500.00"),
        minimum_due=Decimal("50.00"),
        credit_limit=Decimal("5000.00"),
        currency="INR",
    )


def _line(
    line_id: str,
    *,
    description: str = "SHOP / ONLINE",
    amount: str = "100.00",
    transaction_date: date = date(2026, 9, 1),
    transaction_type: str = "debit",
    component_kind: str = "ordinary",
    issuer_plan_reference: str | None = None,
    installment_number: int | None = None,
    statement_id: str = "statement-1",
    line_number: int = 1,
) -> StatementLine:
    return StatementLine(
        id=line_id,
        user_id="user-1",
        credit_card_statement_id=statement_id,
        line_number=line_number,
        transaction_date=transaction_date,
        description=description,
        amount=Decimal(amount),
        transaction_type=transaction_type,
        component_kind=component_kind,
        issuer_plan_reference=issuer_plan_reference,
        installment_number=installment_number,
        review_outcome="needs_review",
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (("CC bill-pay", None), True),
        (("Credit card bill payment", "monthly repayment"), True),
        (("CHEQ DIGITAL", None), True),
        (("LazyPay repayment", None), True),
        (("PAYLATER repayment", None), True),
        (("ordinary grocery purchase", None), False),
        ((None, "ordinary transfer"), False),
    ],
)
def test_non_spend_payment_evidence_is_explicit_and_fail_closed(values, expected):
    assert _is_non_spend_payment_evidence(*values) is expected


def test_snapshot_cutoffs_use_effective_timestamps_and_fail_closed_for_unknown_order():
    service = FinancialPositionService(None)  # type: ignore[arg-type]
    opening = AccountBalanceSnapshot(
        id="opening",
        user_id="user-1",
        financial_account_id="account-1",
        amount=Decimal("1000"),
        currency="INR",
        as_of=date(2026, 9, 10),
        effective_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
    )
    closing = AccountBalanceSnapshot(
        id="closing",
        user_id="user-1",
        financial_account_id="account-1",
        amount=Decimal("1100"),
        currency="INR",
        as_of=date(2026, 9, 12),
        effective_at=datetime(2026, 9, 12, 12, tzinfo=UTC),
    )

    assert not service._transaction_after_snapshot(
        _transaction(transaction_date=date(2026, 9, 10)), opening
    )
    assert service._transaction_after_snapshot(
        _transaction(transaction_date=date(2026, 9, 11)), opening
    )
    assert not service._transaction_after_snapshot(
        _transaction(transaction_date=date(2026, 9, 10)), None
    )
    assert service._transaction_after_snapshot(
        _transaction(transaction_timestamp=datetime(2026, 9, 10, 13, tzinfo=UTC)), opening
    )
    assert not service._transaction_after_snapshot(
        _transaction(transaction_timestamp=datetime(2026, 9, 10, 11, tzinfo=UTC)), opening
    )
    assert service._transaction_between_snapshots(
        _transaction(transaction_timestamp=datetime(2026, 9, 12, 12, tzinfo=UTC)),
        opening,
        closing,
    )
    assert not service._transaction_between_snapshots(
        _transaction(transaction_date=date(2026, 9, 12)), opening, closing
    )

    closing_without_timestamp = AccountBalanceSnapshot(
        id="closing-date-only",
        user_id="user-1",
        financial_account_id="account-1",
        amount=Decimal("1100"),
        currency="INR",
        as_of=date(2026, 9, 12),
    )
    assert service._transaction_between_snapshots(
        _transaction(transaction_date=date(2026, 9, 12)), opening, closing_without_timestamp
    )


@pytest.mark.parametrize(
    ("last_success", "cadence", "now", "expected"),
    [
        (None, 60, datetime(2026, 9, 20, 12, tzinfo=UTC), "unknown"),
        (
            datetime(2026, 9, 20, 11, tzinfo=UTC),
            None,
            datetime(2026, 9, 20, 12, tzinfo=UTC),
            "unknown",
        ),
        (datetime(2026, 9, 20, 11, tzinfo=UTC), 60, datetime(2026, 9, 20, 12, tzinfo=UTC), "fresh"),
        (
            datetime(2026, 9, 20, 10, 59, tzinfo=UTC),
            60,
            datetime(2026, 9, 20, 12, tzinfo=UTC),
            "due",
        ),
        (
            datetime(2026, 9, 20, 9, 59, tzinfo=UTC),
            60,
            datetime(2026, 9, 20, 12, tzinfo=UTC),
            "overdue",
        ),
    ],
)
def test_coverage_status_distinguishes_unknown_fresh_due_and_overdue(
    last_success, cadence, now, expected
):
    state = type(
        "State", (), {"last_success_at": last_success, "expected_cadence_minutes": cadence}
    )()
    assert FinancialPositionService._coverage_status(state, now=now) == expected


def test_card_emi_plan_groups_issuer_components_and_marks_preclosure():
    statement = _statement()
    lines = [
        _line(
            "purchase",
            description="ONLINE STORE",
            amount="1200",
            transaction_date=date(2026, 8, 20),
            component_kind="emi_conversion_purchase",
            line_number=1,
        ),
        _line(
            "credit",
            amount="1200",
            transaction_date=date(2026, 8, 21),
            transaction_type="credit",
            component_kind="emi_conversion_credit",
            line_number=2,
        ),
        _line(
            "fee",
            amount="20",
            transaction_date=date(2026, 8, 22),
            component_kind="emi_processing_fee",
            issuer_plan_reference="plan-1",
            line_number=3,
        ),
        _line(
            "principal",
            amount="100",
            component_kind="emi_principal",
            installment_number=2,
            issuer_plan_reference="plan-1",
            line_number=4,
        ),
        _line(
            "interest",
            amount="10",
            component_kind="emi_interest",
            installment_number=2,
            issuer_plan_reference="plan-1",
            line_number=5,
        ),
        _line(
            "tax",
            amount="2",
            component_kind="emi_tax",
            installment_number=2,
            issuer_plan_reference="plan-1",
            line_number=6,
        ),
        _line(
            "preclose-principal",
            amount="50",
            component_kind="emi_preclosure_principal",
            issuer_plan_reference="plan-2",
            line_number=7,
        ),
        _line(
            "preclose-interest",
            amount="5",
            component_kind="emi_preclosure_interest",
            issuer_plan_reference="plan-2",
            line_number=8,
        ),
        _line(
            "unlinked",
            amount="75",
            component_kind="emi_conversion_purchase",
            transaction_date=date(2026, 9, 4),
            statement_id="statement-1",
            line_number=9,
        ),
        _line(
            "unmatched-credit",
            amount="76",
            transaction_type="credit",
            component_kind="emi_conversion_credit",
            transaction_date=date(2026, 9, 5),
            line_number=10,
        ),
    ]

    plans = _build_card_emi_plans([statement], lines)

    assert {plan.issuer_plan_reference for plan in plans} == {
        "plan-1",
        "plan-2",
        "unlinked-unlinked",
    }
    plan = next(item for item in plans if item.issuer_plan_reference == "plan-1")
    assert plan.merchant == "Store"
    assert plan.latest_principal == 100.0
    assert plan.latest_interest == 10.0
    assert plan.latest_tax == 2.0
    assert plan.latest_fees == 20.0
    assert plan.latest_installment_amount == 112.0
    assert plan.status == "active"
    assert plan.evidence_line_count == 6

    preclosed = next(item for item in plans if item.issuer_plan_reference == "plan-2")
    assert preclosed.status == "preclosed"
    assert preclosed.latest_principal == 50.0


def test_card_activity_signals_report_duplicates_high_value_and_pending_reversal():
    first = _line("line-1", description="Coffee House", amount="600", line_number=1)
    second = _line("line-2", description="COFFEE-HOUSE", amount="600", line_number=2)
    small = _line("line-3", description="Small shop", amount="10", line_number=3)
    pending_reversal = _transaction(
        transaction_id="reversal-1",
        amount="300",
        card_event=CardEvent.REVERSAL,
        status="pending",
    )

    signals = _card_activity_signals([first, second, small], Decimal("5000"), [pending_reversal])
    signal_types = {signal.signal_type for signal in signals}

    assert signal_types == {"duplicate_candidate", "high_value", "pending_reversal"}
    assert any(signal.id == "duplicate:line-1" for signal in signals)
    assert any(signal.id == "high-value:line-1" for signal in signals)
    assert any(signal.id == "pending-reversal:reversal-1" for signal in signals)
    assert _card_activity_signals([], None, []) == []


def test_card_activity_signals_ignore_completed_reversals_and_non_debit_lines():
    credit_line = _line(
        "credit-line",
        amount="600",
        transaction_type="credit",
        line_number=1,
    )
    signals = _card_activity_signals([credit_line], Decimal("5000"), [])

    assert signals == []
