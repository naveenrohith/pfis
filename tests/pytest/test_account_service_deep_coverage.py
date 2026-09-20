"""Deterministic coverage for account identity, balances, and transfers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.account import AccountBalanceSnapshot, AccountLinkRule
from app.schemas.account import (
    AccountLinkRuleCreate,
    BalanceSnapshotCreate,
    FinancialAccountUpdate,
    TransferCreate,
)
from app.services import account_service as module
from app.services import balance_reconciliation_service
from app.services.account_service import AccountService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar_value = scalar
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return _Rows(self.rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, *, scalar_values=(), scalar_rows=(), execute_values=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]
        self.execute_values = list(execute_values)
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()

    async def execute(self, _statement):
        return self.execute_values.pop(0) if self.execute_values else _Result()

    def add(self, item):
        self.added.append(item)

    def add_all(self, items):
        self.added.extend(items)

    async def flush(self):
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = f"generated-{len(self.added)}"
            if hasattr(item, "created_at") and item.created_at is None:
                item.created_at = datetime(2026, 9, 20, tzinfo=UTC)
            if hasattr(item, "is_active") and item.is_active is None:
                item.is_active = True

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, _item):
        return None


def _account(account_id="account-1", *, active=True, status="unresolved"):
    return SimpleNamespace(
        id=account_id,
        user_id="user-1",
        institution_name="Coverage Bank",
        account_type="bank",
        balance_kind="asset",
        masked_number="****1234",
        currency="INR",
        is_active=active,
        identity_status=status,
        identity_confidence=Decimal("0.350"),
        identity_evidence_json="[]",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 20, tzinfo=UTC),
    )


def test_account_identity_helpers_are_idempotent_and_defensive():
    assert module._expected_balance_kind("bank") == "asset"
    assert module._expected_balance_kind("credit_card") == "liability"
    assert module._expected_balance_kind("unknown") is None
    assert module._balance_kind_label("asset") == "assets"
    assert module._balance_kind_label("liability") == "liabilities"
    assert module._parse_identity_evidence(None) == []
    assert module._parse_identity_evidence("not-json") == []
    assert module._parse_identity_evidence("{}") == []
    assert module._parse_identity_evidence('[{"source_type": "manual"}, "bad"]') == [
        {"source_type": "manual"}
    ]

    account = _account(status="unresolved")
    module._append_identity_evidence(
        account,
        source_type="manual",
        source_id="one",
        role="creation",
        note="confirmed",
        status="inferred",
        confidence=Decimal("0.651"),
    )
    first = account.identity_evidence_json
    module._append_identity_evidence(
        account,
        source_type="manual",
        source_id="one",
        role="creation",
        note="confirmed",
    )
    assert account.identity_evidence_json == first
    assert account.identity_status == "inferred"
    assert account.identity_confidence == Decimal("0.651")


@pytest.mark.asyncio
async def test_link_rules_repair_candidates_reactivate_and_deactivate(monkeypatch):
    account = _account(status="unresolved")
    transaction = SimpleNamespace(
        id="txn-1",
        financial_account_id=None,
        currency="INR",
        account_last4="1234",
        reviewed_flag=False,
        reviewed_at=None,
        review_outcome="newly_imported",
    )
    monkeypatch.setattr(module, "capture_transaction_snapshot", _async_noop)
    monkeypatch.setattr(module, "capture_financial_account_snapshot", _async_noop)
    monkeypatch.setattr(AccountService, "_owned_account", _owned(account))

    async def account_response(_self, row):
        return _account_link_response(row)

    monkeypatch.setattr(AccountService, "_account_response", account_response)
    data = AccountLinkRuleCreate(
        financial_account_id=account.id, evidence_value="1234", currency="INR"
    )
    db = _Db(scalar_values=[None], scalar_rows=[[transaction], []])
    result = await AccountService(db).create_link_rule("user-1", data)
    assert result.repaired_transaction_count == 1
    assert transaction.financial_account_id == account.id
    assert transaction.reviewed_flag is True
    assert db.commits == 1

    existing = AccountLinkRule(
        id="rule-1",
        user_id="user-1",
        financial_account_id=account.id,
        evidence_kind="masked_suffix",
        evidence_value="1234",
        currency="INR",
        is_active=False,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    reactivate_db = _Db(scalar_values=[existing], scalar_rows=[[]])
    reactivated = await AccountService(reactivate_db).create_link_rule("user-1", data)
    assert reactivated.id == "rule-1"
    assert existing.is_active is True
    assert (
        await AccountService(_Db(scalar_values=[None])).deactivate_link_rule("user-1", "missing")
        is False
    )

    deactivate_db = _Db(scalar_values=[existing, account])
    assert await AccountService(deactivate_db).deactivate_link_rule("user-1", "rule-1") is True
    assert existing.is_active is False


@pytest.mark.asyncio
async def test_account_update_and_balance_paths_cover_history_and_connector_retries(monkeypatch):
    account = _account(status="confirmed")
    monkeypatch.setattr(AccountService, "_owned_account", _owned(account))
    monkeypatch.setattr(module, "require_ledger_currency", _async_noop)
    monkeypatch.setattr(module, "capture_financial_account_snapshot", _async_noop)

    async def account_response(_self, row):
        return _account_link_response(row)

    monkeypatch.setattr(
        AccountService,
        "_account_response",
        account_response,
    )
    updated = await AccountService(_Db(scalar_values=[None])).update_account(
        "user-1",
        account.id,
        FinancialAccountUpdate(institution_name="Updated Bank", is_active=False),
    )
    assert updated.id == account.id
    assert account.is_active is False
    assert "identity_update" in account.identity_evidence_json
    assert "status_change" in account.identity_evidence_json

    active = _account(status="confirmed")
    monkeypatch.setattr(AccountService, "_owned_account", _owned(active))
    history_db = _Db(scalar_values=[object()])
    with pytest.raises(ValueError, match="financial history"):
        await AccountService(history_db).update_account(
            "user-1", active.id, FinancialAccountUpdate(currency="USD")
        )

    monkeypatch.setattr(
        balance_reconciliation_service,
        "BalanceReconciliationService",
        _ReconciliationService,
    )
    balance = BalanceSnapshotCreate(
        amount=Decimal("100.00"), as_of=date(2026, 9, 20), source="manual"
    )
    balance_db = _Db(scalar_rows=[[]])
    snapshot = await AccountService(balance_db).add_balance("user-1", active.id, balance)
    assert snapshot.amount == 100.0
    assert balance_db.commits == 1

    existing_snapshot = AccountBalanceSnapshot(
        id="snapshot-1",
        user_id="user-1",
        financial_account_id=active.id,
        amount=Decimal("90.00"),
        currency="INR",
        as_of=date(2026, 9, 19),
        source="connector",
        source_record_id="provider-1",
        verified=True,
        observed_at=datetime(2026, 9, 19, tzinfo=UTC),
        created_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    retry_db = _Db(scalar_values=[existing_snapshot])
    retry = await AccountService(retry_db).add_balance(
        "user-1",
        active.id,
        BalanceSnapshotCreate(
            amount=Decimal("90.00"),
            as_of=date(2026, 9, 19),
            source="connector",
            source_record_id="provider-1",
        ),
    )
    assert retry.id == "snapshot-1"


@pytest.mark.asyncio
async def test_net_worth_and_transfer_paths_cover_historical_points_and_atm_rules(monkeypatch):
    account = _account(status="confirmed")
    liability = _account("card-1", status="confirmed")
    liability.account_type = "credit_card"
    liability.balance_kind = "liability"
    first = SimpleNamespace(
        financial_account_id=account.id,
        amount=Decimal("1000"),
        as_of=date(2026, 9, 1),
        verified=True,
    )
    second = SimpleNamespace(
        financial_account_id=liability.id,
        amount=Decimal("200"),
        as_of=date(2026, 9, 1),
        verified=True,
    )
    monkeypatch.setattr(module, "get_ledger_currency", _async_currency)
    service = AccountService(
        _Db(execute_values=[_Result(rows=[account, liability]), _Result(rows=[first, second])])
    )
    series = await service.net_worth("user-1", as_of=date(2026, 9, 2))
    assert series.net_worth == 800.0
    assert series.current_position_status == "historical"

    empty = await AccountService(_Db(execute_values=[_Result(rows=[])])).net_worth("user-1")
    assert empty.currency == "INR"

    from_account = _account("from")
    to_account = _account("to")
    monkeypatch.setattr(module, "require_ledger_currency", _async_noop)
    monkeypatch.setattr(AccountService, "_owned_account", _owned_by_id(from_account, to_account))
    monkeypatch.setattr(module, "capture_transaction_snapshot", _async_noop)
    monkeypatch.setattr(module.TransactionService, "_invalidate_monthly_summary", _async_noop)
    transfer_db = _Db()
    transfer = await AccountService(transfer_db).create_transfer(
        "user-1",
        TransferCreate(
            from_account_id="from",
            to_account_id="to",
            amount=Decimal("50.00"),
            transaction_date=date(2026, 9, 20),
        ),
    )
    assert transfer.amount == 50.0
    assert len(transfer_db.added) == 2

    with pytest.raises(ValueError, match="ATM withdrawals"):
        await AccountService(transfer_db).create_transfer(
            "user-1",
            TransferCreate(
                from_account_id="from",
                to_account_id="to",
                amount=Decimal("50.00"),
                transaction_date=date(2026, 9, 20),
                payment_rail="atm",
            ),
        )


def _owned(account):
    async def owned(self, _user_id, account_id):
        return account if account_id == account.id else None

    return owned


def _owned_by_id(*accounts):
    by_id = {account.id: account for account in accounts}

    async def owned(self, _user_id, account_id):
        return by_id.get(account_id)

    return owned


def _account_link_response(row):
    return SimpleNamespace(id=row.id)


async def _async_noop(*_args, **_kwargs):
    return None


async def _async_currency(*_args, **_kwargs):
    return "INR"


class _ReconciliationService:
    def __init__(self, _db):
        pass

    async def ensure_for_closing_snapshot(self, *_args):
        return None
