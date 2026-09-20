"""Focused branch coverage for the transaction service."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.transaction import PaymentMethod, PaymentRail, Transaction, TransactionType
from app.schemas.transaction import TransactionSplitReplace, TransactionUpdate
from app.services import transaction_service as transaction_module
from app.services.transaction_service import (
    DuplicateTransactionError,
    TransactionService,
)


class _Result:
    def __init__(self, *, scalar=None, rows=(), scalars=()):
        self._scalar = scalar
        self._rows = list(rows)
        self._scalars = list(scalars)

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return (
            self._scalar
            if self._scalar is not None
            else (self._scalars[0] if self._scalars else None)
        )

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows if self._rows else self._scalars

    def scalars(self):
        return self


class _Db:
    def __init__(self, results=()):
        self.results = list(results)
        self.added = []
        self.executed = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        self.executed.append(statement)
        return self.results.pop(0) if self.results else _Result()

    async def scalar(self, _statement):
        return None

    async def scalars(self, _statement):
        return self.results.pop(0) if self.results else _Result()

    def add(self, item):
        self.added.append(item)

    def add_all(self, items):
        self.added.extend(items)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, _item, **_kwargs):
        if getattr(_item, "id", None) is None:
            _item.id = f"split-{len(self.added)}"
        if getattr(_item, "created_at", None) is None:
            _item.created_at = datetime(2026, 9, 20, tzinfo=UTC)
        return None


def _txn(txn_id="txn-1", *, amount="100.00", merchant="Coffee", user_id="user-1", **kwargs):
    return Transaction(
        id=txn_id,
        user_id=user_id,
        amount=Decimal(amount),
        currency="INR",
        transaction_type=TransactionType.DEBIT,
        payment_method=PaymentMethod.OTHER,
        payment_rail=PaymentRail.OTHER,
        transaction_status="completed",
        transaction_date=date(2026, 9, 20),
        merchant_raw=merchant,
        merchant_normalized=merchant,
        fingerprint=TransactionService.compute_fingerprint(
            user_id, Decimal(amount), date(2026, 9, 20), merchant, None
        ),
        **kwargs,
    )


def test_static_helpers_normalize_money_enums_and_filters():
    assert TransactionService.compute_fingerprint(
        "u", Decimal("10.004"), date(2026, 1, 2), " Cafe ", None
    ) == TransactionService.compute_fingerprint("u", "10.00", date(2026, 1, 2), "cafe", None)
    assert TransactionService._serialize_correction_value(None) is None
    assert TransactionService._serialize_correction_value(TransactionType.DEBIT) == "debit"

    query = TransactionService._apply_list_filters(
        Transaction.__table__.select(),
        q=" cafe ",
        transaction_type="debit",
        payment_method="upi",
        reviewed=False,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 1, 31),
        amount_min=10,
        amount_max=20,
    )
    sql = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "lower(transactions.merchant_normalized) LIKE '%cafe%'" in sql
    assert "transactions.reviewed_flag IS false" in sql
    assert "transactions.amount >= 10" in sql


@pytest.mark.asyncio
async def test_update_validation_and_transfer_protection(monkeypatch):
    transfer = _txn(is_transfer=True)
    service = TransactionService(_Db())
    monkeypatch.setattr(service, "get_transaction_by_id", lambda _id: _async_value(transfer))

    with pytest.raises(ValueError, match="Transfer ledger fields"):
        await service.update_transaction(transfer.id, TransactionUpdate(amount=20))

    normal = _txn(is_transfer=False)
    service = TransactionService(_Db())
    monkeypatch.setattr(service, "get_transaction_by_id", lambda _id: _async_value(normal))
    with pytest.raises(ValueError, match="Category not found"):
        await service.update_transaction(normal.id, TransactionUpdate(category_id="missing"))


async def _async_value(value):
    return value


async def _async_noop(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_update_correction_marks_reviewed_and_rejects_duplicate(monkeypatch):
    txn = _txn(merchant="Old")
    duplicate = _txn("txn-2", merchant="New")
    db = _Db([_Result(scalars=[duplicate])])
    service = TransactionService(db)
    monkeypatch.setattr(service, "get_transaction_by_id", lambda _id: _async_value(txn))
    monkeypatch.setattr(service, "_invalidate_monthly_summary", lambda *_args: _async_value(None))
    monkeypatch.setattr(service, "_learn_from_correction", lambda *_args: _async_value(None))
    monkeypatch.setattr(transaction_module, "capture_transaction_snapshot", _async_noop)

    with pytest.raises(DuplicateTransactionError, match="duplicate"):
        await service.update_transaction(txn.id, TransactionUpdate(merchant_normalized="New"))
    assert txn.reviewed_flag is True


@pytest.mark.asyncio
async def test_split_ownership_validation_and_success(monkeypatch):
    txn = _txn(amount="100.00")
    db = _Db([_Result(scalars=["category-1"])])
    service = TransactionService(db)
    monkeypatch.setattr(service, "get_transaction_by_id", lambda _id: _async_value(txn))
    data = TransactionSplitReplace.model_validate(
        {
            "splits": [
                {"label": "A", "amount": 40},
                {"label": "B", "amount": 60, "category_id": "category-1"},
            ]
        }
    )
    response = await service.replace_splits("user-1", txn.id, data)
    assert [item.label for item in response] == ["A", "B"]
    assert db.committed is True
    assert len(db.added) == 2

    foreign = _txn(user_id="other")
    monkeypatch.setattr(service, "get_transaction_by_id", lambda _id: _async_value(foreign))
    with pytest.raises(LookupError, match="Transaction not found"):
        await service.replace_splits("user-1", foreign.id, data)

    transfer = _txn(is_transfer=True)
    monkeypatch.setattr(service, "get_transaction_by_id", lambda _id: _async_value(transfer))
    with pytest.raises(ValueError, match="cannot be split"):
        await service.replace_splits("user-1", transfer.id, data)


@pytest.mark.asyncio
async def test_bulk_merchant_correction_and_bulk_update_paths(monkeypatch):
    txn = _txn(merchant="RAW")
    db = _Db([_Result(scalars=[txn])])
    service = TransactionService(db)
    monkeypatch.setattr(service, "upsert_user_merchant_rule", lambda **_kwargs: _async_value(None))
    monkeypatch.setattr(service, "_record_corrections", lambda *_args: _async_value(None))
    monkeypatch.setattr(transaction_module, "capture_transaction_snapshot", _async_noop)
    count = await service.bulk_correct_merchant(
        user_id="user-1",
        current_name="raw",
        normalized_name=" Cafe ",
        category_id=None,
        rule_category_id=None,
        aliases=["alias", ""],
        apply_existing=True,
    )
    assert count == 1
    assert txn.merchant_normalized == "Cafe"
    assert txn.reviewed_flag is True

    empty = await service.bulk_update_transactions(
        "user-1",
        SimpleNamespace(
            transaction_ids=["a", "a"], model_dump=lambda **_: {"transaction_ids": ["a", "a"]}
        ),
    )
    assert empty["requested_count"] == 1
    assert empty["failed"] == [{"transaction_id": "a", "error": "No update fields provided"}]


@pytest.mark.asyncio
async def test_delete_success_and_rollback(monkeypatch):
    txn = _txn()
    db = _Db([_Result(scalar=txn)])
    service = TransactionService(db)
    monkeypatch.setattr(transaction_module, "capture_transaction_snapshot", _async_noop)
    monkeypatch.setattr(service, "_invalidate_monthly_summary", lambda *_args: _async_value(None))
    assert await service.delete_transaction(txn.id) is True
    assert db.committed is True

    failing_db = _Db([_Result(scalar=txn)])
    service = TransactionService(failing_db)

    async def fail_execute(statement):
        if len(failing_db.executed) >= 1:
            raise RuntimeError("delete failed")
        failing_db.executed.append(statement)
        return _Result(scalar=txn)

    failing_db.execute = fail_execute
    with pytest.raises(RuntimeError, match="delete failed"):
        await service.delete_transaction(txn.id)
    assert failing_db.rolled_back is True


@pytest.mark.asyncio
async def test_count_and_monthly_summary_cache_hit_and_invalid_payload(monkeypatch):
    db = _Db([_Result(scalar=3)])
    service = TransactionService(db)
    assert await service.get_transaction_count("user-1", reviewed=False, amount_min=5) == 3

    cached = {
        "_aggregation_contract": "single-ledger-v1",
        "_ledger_currency": "INR",
        "total_spend": 1,
    }
    cache_db = _Db([_Result(scalar=json.dumps(cached))])
    service = TransactionService(cache_db)

    async def ledger_currency(*_args):
        return "INR"

    monkeypatch.setattr(transaction_module, "get_ledger_currency", ledger_currency)
    assert await service.get_monthly_summary("user-1", 9, 2026) == cached

    invalid_db = _Db(
        [
            _Result(scalar="not-json"),
            _Result(scalar=0),
            _Result(scalar=0),
            _Result(scalar=0),
            _Result(rows=()),
            _Result(rows=()),
        ]
    )
    service = TransactionService(invalid_db)
    assert (await service.get_monthly_summary("user-1", 9, 2026))["transaction_count"] == 0
    assert invalid_db.committed is True
