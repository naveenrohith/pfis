"""Direct policy coverage for imported transfer matching and linking."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.models.account import FinancialAccount
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionType,
)
from app.services import transaction_transfer_service as transfer_module
from app.services.transaction_transfer_service import TransactionTransferService


class _Rows:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return self.rows


class _TransferDb:
    def __init__(self, first_rows, second_rows, *, fail_flush: bool = False):
        self.first_rows = list(first_rows)
        self.second_rows = list(second_rows)
        self.fail_flush = fail_flush
        self.scalar_calls = 0
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def scalars(self, _statement):
        self.scalar_calls += 1
        return _Rows(self.first_rows if self.scalar_calls == 1 else self.second_rows)

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        if self.fail_flush:
            raise RuntimeError("flush failed")

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, _item):
        return None


def _account(
    account_id: str,
    *,
    account_type: str = "bank",
    balance_kind: str = "asset",
) -> FinancialAccount:
    return FinancialAccount(
        id=account_id,
        user_id="user-1",
        institution_name=f"Bank {account_id}",
        account_type=account_type,
        balance_kind=balance_kind,
        masked_number=f"****{account_id[-4:]}",
        currency="INR",
        is_active=True,
    )


def _transaction(
    transaction_id: str,
    account_id: str,
    transaction_type: TransactionType,
    *,
    amount: str = "100.00",
    transaction_date: date = date(2026, 9, 20),
    merchant: str = "Self transfer",
    payment_rail: PaymentRail = PaymentRail.TRANSFER,
    payment_method: PaymentMethod = PaymentMethod.BANK_TRANSFER,
    card_event: CardEvent = CardEvent.NONE,
) -> Transaction:
    return Transaction(
        id=transaction_id,
        user_id="user-1",
        financial_account_id=account_id,
        amount=Decimal(amount),
        currency="INR",
        transaction_type=transaction_type,
        payment_method=payment_method,
        payment_rail=payment_rail,
        card_event=card_event,
        transaction_status="completed",
        transaction_date=transaction_date,
        merchant_raw=merchant,
        merchant_normalized=merchant,
        review_outcome="newly_imported",
        reviewed_flag=False,
        is_transfer=False,
        is_accounting_adjustment=False,
    )


async def test_list_candidates_reports_account_transfers_and_ambiguous_pairs():
    bank = _account("bank-1")
    cash = _account("cash-1", account_type="cash")
    debit = _transaction("debit-1", bank.id, TransactionType.DEBIT)
    credit = _transaction("credit-1", cash.id, TransactionType.CREDIT)
    second_credit = _transaction("credit-2", cash.id, TransactionType.CREDIT, amount="100.00")
    db = _TransferDb([bank, cash], [debit, credit, second_credit])

    candidates = await TransactionTransferService(db).list_candidates("user-1", limit=500)

    assert len(candidates) == 2
    assert all(item.kind == "account_transfer" for item in candidates)
    assert all(item.ambiguous for item in candidates)
    assert all("ambiguous_counterparty" in item.reason_codes for item in candidates)
    assert all(item.confidence == pytest.approx(0.58) for item in candidates)


async def test_list_candidates_filters_account_and_handles_empty_or_unknown_accounts():
    service = TransactionTransferService(_TransferDb([], []))
    assert await service.list_candidates("user-1") == []

    with pytest.raises(LookupError, match="Financial account not found"):
        await service.list_candidates("user-1", account_id="missing")


@pytest.mark.parametrize(
    ("debit_account", "credit_account", "credit_event", "rail", "expected_kind"),
    [
        (
            _account("bank-1"),
            _account("card-1", account_type="credit_card", balance_kind="liability"),
            CardEvent.NONE,
            PaymentRail.OTHER,
            "card_payment",
        ),
        (
            _account("bank-1"),
            _account("card-1", account_type="credit_card", balance_kind="liability"),
            CardEvent.PAYMENT,
            PaymentRail.TRANSFER,
            "card_payment",
        ),
        (
            _account("bank-1"),
            _account("cash-1", account_type="cash"),
            CardEvent.NONE,
            PaymentRail.TRANSFER,
            "account_transfer",
        ),
    ],
)
def test_pair_classification_reports_explicit_evidence(
    debit_account,
    credit_account,
    credit_event,
    rail,
    expected_kind,
):
    debit = _transaction(
        "debit",
        debit_account.id,
        TransactionType.DEBIT,
        payment_rail=rail,
    )
    credit = _transaction(
        "credit",
        credit_account.id,
        TransactionType.CREDIT,
        payment_rail=rail,
        card_event=credit_event,
    )

    result = TransactionTransferService._classify_pair(debit, credit, debit_account, credit_account)

    assert result is not None
    assert result[0] == expected_kind
    assert 0 < result[1] <= 0.99
    assert "exact_amount" in result[2]


def test_pair_classification_rejects_unsafe_counterparties_and_transfer_evidence_is_explicit():
    bank = _account("bank-1")
    loan = _account("loan-1", account_type="loan", balance_kind="liability")
    debit = _transaction(
        "debit",
        bank.id,
        TransactionType.DEBIT,
        merchant="grocery",
        payment_rail=PaymentRail.OTHER,
        payment_method=PaymentMethod.OTHER,
    )
    credit = _transaction(
        "credit",
        loan.id,
        TransactionType.CREDIT,
        merchant="grocery",
        payment_rail=PaymentRail.OTHER,
        payment_method=PaymentMethod.OTHER,
    )

    assert TransactionTransferService._classify_pair(debit, credit, bank, loan) is None
    assert not TransactionTransferService._has_transfer_evidence(debit, credit)
    credit.merchant_raw = "NEFT transfer"
    assert TransactionTransferService._has_transfer_evidence(debit, credit)


@pytest.mark.asyncio
async def test_link_pair_updates_both_legs_and_persists_corrections(monkeypatch):
    bank = _account("bank-1")
    cash = _account("cash-1", account_type="cash")
    debit = _transaction("debit", bank.id, TransactionType.DEBIT)
    credit = _transaction("credit", cash.id, TransactionType.CREDIT)
    db = _TransferDb([debit, credit], [bank, cash])

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(transfer_module, "require_ledger_currency", no_op)
    monkeypatch.setattr(transfer_module, "capture_transaction_snapshot", no_op)

    response = await TransactionTransferService(db).link_pair(
        "user-1", debit.id, credit.id, kind="account_transfer"
    )

    assert response.debit_transaction_id == debit.id
    assert response.credit_transaction_id == credit.id
    assert response.amount == 100.0
    assert debit.is_transfer is True
    assert credit.is_transfer is True
    assert debit.transfer_group_id == credit.transfer_group_id
    assert debit.payment_rail == PaymentRail.TRANSFER
    assert len(db.added) >= 8
    assert db.committed is True


@pytest.mark.asyncio
async def test_link_pair_rolls_back_when_persistence_fails(monkeypatch):
    bank = _account("bank-1")
    cash = _account("cash-1", account_type="cash")
    debit = _transaction("debit", bank.id, TransactionType.DEBIT)
    credit = _transaction("credit", cash.id, TransactionType.CREDIT)
    db = _TransferDb([debit, credit], [bank, cash], fail_flush=True)

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(transfer_module, "require_ledger_currency", no_op)
    monkeypatch.setattr(transfer_module, "capture_transaction_snapshot", no_op)

    with pytest.raises(RuntimeError, match="flush failed"):
        await TransactionTransferService(db).link_pair(
            "user-1", debit.id, credit.id, kind="account_transfer"
        )

    assert db.rolled_back is True
    assert db.committed is False
