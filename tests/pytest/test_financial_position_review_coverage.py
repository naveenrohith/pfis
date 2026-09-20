"""Coverage for statement payment-candidate and review decision paths."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.schemas.financial_position import StatementLineReviewRequest
from app.services import financial_position_service as module
from app.services.financial_position_service import FinancialPositionService

from tests.pytest.test_financial_position_service_additional_coverage import (
    TODAY,
    _account,
    _statement,
    _statement_line,
)


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)

    def one_or_none(self):
        if len(self.rows) > 1:
            raise AssertionError("expected one row")
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, *, execute_values=(), scalar_values=(), get_values=()):
        self.execute_values = list(execute_values)
        self.scalar_values = list(scalar_values)
        self.get_values = list(get_values)
        self.added = []
        self.commits = 0

    async def execute(self, _statement):
        return self.execute_values.pop(0) if self.execute_values else _Rows()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def get(self, _model, _row_id):
        return self.get_values.pop(0) if self.get_values else None

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        for row in self.added:
            if hasattr(row, "id") and row.id is None:
                row.id = "generated"
            if hasattr(row, "created_at") and row.created_at is None:
                row.created_at = datetime(2026, 9, 20, tzinfo=UTC)
        return None

    async def commit(self):
        for row in self.added:
            if hasattr(row, "created_at") and row.created_at is None:
                row.created_at = datetime(2026, 9, 20, tzinfo=UTC)
        self.commits += 1

    async def refresh(self, _row):
        return None


def _candidate(transaction_id, description, *, day_delta=0, reference_id=None):
    account = _account("bank-1")
    transaction = SimpleNamespace(
        id=transaction_id,
        amount=Decimal("100"),
        transaction_date=TODAY + timedelta(days=day_delta),
        merchant_raw=description,
        merchant_normalized=None,
        reference_id=reference_id,
    )
    return transaction, account


@pytest.mark.asyncio
async def test_card_payment_candidates_ranks_explicit_and_reference_evidence(monkeypatch):
    line = _statement_line(amount="100", description="Credit Card Payment")
    line.card_event = "payment"
    line.reference_id = "REF-1"
    statement = _statement()
    card = _account("card-1", account_type="credit_card", balance_kind="liability")
    explicit, account = _candidate("txn-explicit", "Credit Card Bill Payment", reference_id="REF-1")
    near, near_account = _candidate("txn-near", "Card settlement transfer", day_delta=2)
    blank, blank_account = _candidate("txn-blank", "   ")
    unrelated, unrelated_account = _candidate("txn-unrelated", "Grocery purchase")
    db = _Db(
        execute_values=[
            _Rows([(line, statement, card)]),
            _Rows(
                [
                    (explicit, account),
                    (near, near_account),
                    (blank, blank_account),
                    (unrelated, unrelated_account),
                ]
            ),
        ]
    )
    candidates = await FinancialPositionService(db).card_payment_candidates("user-1", line.id)
    assert [item.transaction_id for item in candidates] == ["txn-explicit", "txn-near"]
    assert candidates[0].match_method == "reference"
    assert "explicit_card_payment_wording" in candidates[0].evidence
    assert candidates[1].match_method == "near_day_amount"

    with pytest.raises(LookupError):
        await FinancialPositionService(_Db(execute_values=[_Rows([])])).card_payment_candidates(
            "user-1", "missing"
        )
    ordinary = _statement_line(amount="100", description="Ordinary")
    ordinary.card_event = "purchase"
    with pytest.raises(ValueError, match="card-payment"):
        await FinancialPositionService(
            _Db(execute_values=[_Rows([(ordinary, statement, card)])])
        ).card_payment_candidates("user-1", ordinary.id)


@pytest.mark.asyncio
async def test_review_statement_line_covers_ignore_match_and_import(monkeypatch):
    monkeypatch.setattr(module, "capture_statement_line_snapshot", _async_noop)
    monkeypatch.setattr(module, "capture_transaction_snapshot", _async_noop)
    line = _statement_line(amount="100", description="Coffee House")
    line.card_event = "purchase"
    statement = _statement()
    card = _account("card-1", account_type="credit_card", balance_kind="liability")

    ignored = await FinancialPositionService(
        _Db(execute_values=[_Rows([(line, statement, card)])])
    ).review_statement_line(
        "user-1", line.id, StatementLineReviewRequest(decision="ignore", note="not spending")
    )
    assert ignored.new_outcome == "ignored_by_rule"

    matched_line = _statement_line(amount="100", description="Coffee House")
    matched_line.card_event = "purchase"
    matched = SimpleNamespace(id="txn-match")
    match_db = _Db(
        execute_values=[_Rows([(matched_line, statement, card)])],
        scalar_values=[matched, None],
    )
    result = await FinancialPositionService(match_db).review_statement_line(
        "user-1",
        matched_line.id,
        StatementLineReviewRequest(decision="match", matched_transaction_id="txn-match"),
    )
    assert result.matched_transaction_id == "txn-match"
    assert result.new_outcome == "matched"

    import_line = _statement_line(amount="100", description="Coffee House")
    import_line.card_event = "purchase"

    class _Transactions:
        def __init__(self, _db):
            pass

        async def create_transaction(self, *_args, **_kwargs):
            return SimpleNamespace(id="txn-imported")

    monkeypatch.setattr(module, "TransactionService", _Transactions)
    monkeypatch.setattr(module, "resolve_merchant", _merchant)
    imported = await FinancialPositionService(
        _Db(execute_values=[_Rows([(import_line, statement, card)])])
    ).review_statement_line("user-1", import_line.id, StatementLineReviewRequest(decision="import"))
    assert imported.matched_transaction_id == "txn-imported"
    assert import_line.review_outcome == "newly_imported"

    with pytest.raises(LookupError):
        await FinancialPositionService(_Db(execute_values=[_Rows([])])).review_statement_line(
            "user-1", "missing", StatementLineReviewRequest(decision="ignore")
        )
    invalid_line = _statement_line()
    invalid_line.card_event = "payment"
    with pytest.raises(ValueError, match="existing ledger"):
        await FinancialPositionService(
            _Db(execute_values=[_Rows([(invalid_line, statement, card)])])
        ).review_statement_line(
            "user-1", invalid_line.id, StatementLineReviewRequest(decision="match")
        )


@pytest.mark.asyncio
async def test_statement_match_record_is_idempotent_and_rejects_conflicts():
    line = _statement_line()
    service = FinancialPositionService(_Db(scalar_values=[None]))
    await service._record_statement_match("user-1", line, "txn-1", "manual", Decimal("0.9"))
    assert len(service.db.added) == 1

    same = SimpleNamespace(statement_line_id=line.id, transaction_id="txn-1")
    assert (
        await FinancialPositionService(_Db(scalar_values=[same]))._record_statement_match(
            "user-1", line, "txn-1", "manual", Decimal("0.9")
        )
        is None
    )
    conflict = SimpleNamespace(statement_line_id="other-line", transaction_id="txn-1")
    with pytest.raises(ValueError, match="already matched"):
        await FinancialPositionService(_Db(scalar_values=[conflict]))._record_statement_match(
            "user-1", line, "txn-1", "manual", Decimal("0.9")
        )


async def _merchant(*_args, **_kwargs):
    return SimpleNamespace(
        normalized_name="Coffee House",
        category_id=None,
        source="test",
        confidence=1.0,
        rule_id=None,
        resolver_version=1,
    )


async def _async_noop(*_args, **_kwargs):
    return None
