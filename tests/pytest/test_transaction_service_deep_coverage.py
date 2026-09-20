"""Deep deterministic coverage for transaction lifecycle branches."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.transaction import CardEvent, PaymentMethod, PaymentRail, TransactionType
from app.schemas.transaction import AtmCashLinkRequest, TransactionCreate, TransactionUpdate
from app.services import transaction_service as module
from app.services.transaction_service import DuplicateTransactionError, TransactionService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar_value = scalar
        self.rows = list(rows)

    def scalar(self):
        return self.scalar_value

    def scalar_one_or_none(self):
        return self.scalar_value

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)

    def scalars(self):
        return _Rows(self.rows)


class _Db:
    def __init__(self, *, execute_values=(), scalar_values=(), scalar_rows=(), get_values=None):
        self.execute_values = list(execute_values)
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]
        self.get_values = dict(get_values or {})
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshes = 0
        self.fail_flush = None

    async def execute(self, _statement):
        return self.execute_values.pop(0) if self.execute_values else _Result()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()

    async def get(self, model, item_id):
        if item_id in self.get_values:
            return self.get_values[item_id]
        for item in self.added:
            if isinstance(item, model):
                return item
        return None

    def add(self, item):
        self.added.append(item)

    def add_all(self, items):
        self.added.extend(items)

    async def flush(self):
        if self.fail_flush is not None:
            raise self.fail_flush
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = f"generated-{len(self.added)}"

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, _item, **_kwargs):
        self.refreshes += 1


def _account(account_id="account-1", *, account_type="bank", currency="INR"):
    return SimpleNamespace(
        id=account_id,
        user_id="user-1",
        currency=currency,
        account_type=account_type,
        is_active=True,
    )


def _transaction(transaction_id="txn-1", **values):
    defaults = {
        "id": transaction_id,
        "user_id": "user-1",
        "amount": Decimal("100"),
        "currency": "INR",
        "transaction_type": TransactionType.DEBIT,
        "payment_method": PaymentMethod.OTHER,
        "payment_rail": PaymentRail.OTHER,
        "card_event": CardEvent.NONE,
        "transaction_status": "completed",
        "transaction_date": date(2026, 9, 20),
        "merchant_raw": "Coffee",
        "merchant_normalized": "Coffee",
        "category_id": None,
        "account_last4": None,
        "reference_id": None,
        "confidence_score": 0.5,
        "reviewed_flag": False,
        "reviewed_at": None,
        "parser_version": 1,
        "merchant_resolution_source": "parser",
        "merchant_resolution_confidence": 0.5,
        "merchant_rule_id": None,
        "merchant_resolver_version": 1,
        "fingerprint": "fingerprint",
        "source_email_id": None,
        "source_kind": "manual",
        "source_identifier": None,
        "review_outcome": "newly_imported",
        "tags_json": "[]",
        "tags": [],
        "financial_account_id": "account-1",
        "transfer_group_id": None,
        "is_transfer": False,
        "is_accounting_adjustment": False,
        "ledger_subtype": None,
        "created_at": datetime(2026, 9, 20, tzinfo=UTC),
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


async def _no_op(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_create_transaction_resolves_accounts_and_handles_integrity_duplicates(monkeypatch):
    monkeypatch.setattr(module, "require_ledger_currency", _no_op)
    monkeypatch.setattr(module, "capture_transaction_snapshot", _no_op)
    monkeypatch.setattr(module, "capture_financial_account_snapshot", _no_op)

    account = _account()
    db = _Db(
        execute_values=[_Result(scalar=None), _Result(scalar=account)],
        scalar_values=["category-1", "raw-email-1"],
        get_values={"account-1": account},
    )
    service = TransactionService(db)
    monkeypatch.setattr(service, "_invalidate_monthly_summary", _no_op)
    data = TransactionCreate(
        amount=Decimal("125"),
        transaction_type="debit",
        merchant_raw="Coffee",
        merchant_normalized="Coffee",
        category_id="category-1",
        source_email_id="raw-email-1",
        financial_account_id="account-1",
        transaction_date=date(2026, 9, 20),
        confidence_score=0.95,
    )
    created = await service.create_transaction("user-1", data)
    assert created.reviewed_flag is True
    assert created.financial_account_id == "account-1"
    assert db.commits == 1

    hint_db = _Db(
        execute_values=[_Result(scalar=None), _Result(scalar=None)],
        scalar_values=[None],
        scalar_rows=[[]],
    )
    hint_service = TransactionService(hint_db)
    monkeypatch.setattr(hint_service, "_invalidate_monthly_summary", _no_op)
    hinted = await hint_service.create_transaction(
        "user-1",
        data.model_copy(
            update={
                "category_id": None,
                "source_email_id": None,
                "financial_account_id": None,
                "account_last4": "1234",
                "confidence_score": 0.99,
            }
        ),
    )
    assert hinted.review_outcome == "needs_review"
    assert hinted.reviewed_flag is False
    assert hinted.financial_account_id is not None

    failing = _Db(execute_values=[_Result(scalar=None)])
    failing.fail_flush = module.IntegrityError("duplicate", {}, RuntimeError("constraint"))
    failing.scalar_values = ["existing-transaction"]
    failing_service = TransactionService(failing)
    monkeypatch.setattr(failing_service, "_invalidate_monthly_summary", _no_op)
    with pytest.raises(DuplicateTransactionError, match="Duplicate transaction"):
        await failing_service.create_transaction(
            "user-1",
            data.model_copy(
                update={
                    "category_id": None,
                    "source_email_id": None,
                    "financial_account_id": None,
                }
            ),
        )
    assert failing.rollbacks == 1


@pytest.mark.asyncio
async def test_atm_cash_link_covers_idempotent_and_new_transfer_paths(monkeypatch):
    monkeypatch.setattr(module, "require_ledger_currency", _no_op)
    monkeypatch.setattr(module, "capture_transaction_snapshot", _no_op)
    source = _account("bank-1")
    cash = _account("cash-1", account_type="cash")
    observed = _transaction(
        "atm-1",
        financial_account_id="bank-1",
        payment_rail=PaymentRail.ATM,
        merchant_normalized="ATM",
    )
    db = _Db(
        scalar_values=[observed, cash],
        get_values={"bank-1": source},
    )
    service = TransactionService(db)
    monkeypatch.setattr(service, "_invalidate_monthly_summary", _no_op)
    linked = await service.link_atm_withdrawal_to_cash(
        "user-1", "atm-1", AtmCashLinkRequest(cash_account_id="cash-1")
    )
    assert linked.payment_rail == "atm"
    assert observed.is_transfer is True
    assert len(db.added) == 3
    assert db.commits == 1

    debit = _transaction("debit", transaction_type=TransactionType.DEBIT)
    credit = _transaction("credit", transaction_type=TransactionType.CREDIT)
    existing = _transaction(
        "existing",
        is_transfer=True,
        transfer_group_id="group-1",
        transaction_type=TransactionType.DEBIT,
    )
    existing_db = _Db(scalar_values=[existing], scalar_rows=[[debit, credit]])
    idempotent = await TransactionService(existing_db).link_atm_withdrawal_to_cash(
        "user-1", "existing", AtmCashLinkRequest(cash_account_id="cash-1")
    )
    assert idempotent.transfer_group_id == "group-1"
    assert idempotent.credit_transaction_id == "credit"


@pytest.mark.asyncio
async def test_update_and_email_statement_reconciliation_cover_mutation_evidence(monkeypatch):
    txn = _transaction("txn-update", merchant_normalized="Old", category_id=None)
    account = _account()
    db = _Db(
        execute_values=[_Result(scalar=None)],
        scalar_values=["category-1", account],
    )
    service = TransactionService(db)
    monkeypatch.setattr(service, "get_transaction_by_id", lambda _id: _value(txn))
    monkeypatch.setattr(service, "_record_corrections", _no_op)
    monkeypatch.setattr(
        service,
        "_learn_from_correction",
        lambda *_args: _value(SimpleNamespace(confidence=1.0, id="rule-1")),
    )
    monkeypatch.setattr(service, "_invalidate_monthly_summary", _no_op)
    monkeypatch.setattr(module, "capture_transaction_snapshot", _no_op)
    updated = await service.update_transaction(
        txn.id,
        TransactionUpdate(
            merchant_normalized="New",
            category_id="category-1",
            financial_account_id="account-1",
            tags=["food", "Food", ""],
            reviewed_flag=True,
        ),
    )
    assert updated is txn
    assert txn.merchant_resolution_source == "user_rule"
    assert txn.tags_json == '["food"]'
    assert db.commits == 1

    statement = _transaction(
        "statement-1",
        source_kind="statement",
        source_email_id=None,
        reference_id="REF-1",
        merchant_raw="Coffee Shop",
        merchant_normalized="Coffee Shop",
    )
    line = SimpleNamespace(id="line-1", review_outcome="needs_review")
    reconciliation_db = _Db(
        scalar_rows=[[statement], [statement]],
        scalar_values=[line, None],
    )
    reconciliation = TransactionService(reconciliation_db)
    monkeypatch.setattr(module, "capture_statement_line_snapshot", _no_op)
    monkeypatch.setattr(module, "capture_transaction_snapshot", _no_op)
    email_data = TransactionCreate(
        amount=Decimal("100"),
        transaction_type="debit",
        merchant_raw="Coffee Shop",
        merchant_normalized="Coffee Shop",
        reference_id="REF-1",
        source_email_id="email-1",
        transaction_date=date(2026, 9, 20),
    )
    with pytest.raises(DuplicateTransactionError, match="matched an existing"):
        await reconciliation._reconcile_email_with_statement(
            user_id="user-1", financial_account_id="account-1", data=email_data
        )
    assert statement.source_email_id == "email-1"
    assert line.review_outcome == "matched"
    assert reconciliation_db.added


async def _value(value):
    return value
