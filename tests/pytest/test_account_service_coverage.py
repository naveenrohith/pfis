"""Deterministic coverage for account aggregation policy branches."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.services import account_service as account_module
from app.services import financial_clock
from app.services.account_service import (
    AccountService,
    _append_identity_evidence,
    _balance_kind_label,
    _expected_balance_kind,
    _parse_identity_evidence,
)
from app.services.financial_position_service import FinancialPositionService


class _Result:
    def __init__(self, rows=(), scalar_value=None):
        self.rows = list(rows)
        self.scalar_value = scalar_value

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.scalar_value


class _AccountDb:
    def __init__(self, *, execute_results=()):
        self.execute_results = list(execute_results)

    async def execute(self, _statement):
        return self.execute_results.pop(0)


def _account(account_id: str, balance_kind: str = "asset") -> FinancialAccount:
    return FinancialAccount(
        id=account_id,
        user_id="user-1",
        institution_name=f"Account {account_id}",
        account_type="bank" if balance_kind == "asset" else "loan",
        balance_kind=balance_kind,
        masked_number="****3001",
        currency="INR",
        is_active=True,
        identity_status="confirmed",
        identity_confidence=Decimal("1.000"),
        identity_evidence_json="[]",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 19, tzinfo=UTC),
    )


def _snapshot(account_id: str, amount: str, snapshot_date: date, verified: bool = True):
    return AccountBalanceSnapshot(
        id=f"snapshot-{account_id}-{snapshot_date}",
        user_id="user-1",
        financial_account_id=account_id,
        amount=Decimal(amount),
        currency="INR",
        as_of=snapshot_date,
        source="manual",
        source_record_id=None,
        verified=verified,
        observed_at=datetime.combine(snapshot_date, datetime.min.time(), tzinfo=UTC),
        created_at=datetime.combine(snapshot_date, datetime.min.time(), tzinfo=UTC),
    )


def test_account_identity_helpers_keep_evidence_deduplicated_and_typed():
    assert _expected_balance_kind("bank") == "asset"
    assert _expected_balance_kind("cash") == "asset"
    assert _expected_balance_kind("investment") == "asset"
    assert _expected_balance_kind("credit_card") == "liability"
    assert _expected_balance_kind("loan") == "liability"
    assert _expected_balance_kind("pay_later") == "liability"
    assert _expected_balance_kind("unknown") is None
    assert _balance_kind_label("asset") == "assets"
    assert _balance_kind_label("liability") == "liabilities"
    assert _parse_identity_evidence(None) == []
    assert _parse_identity_evidence("not-json") == []
    assert _parse_identity_evidence("{}") == []
    assert _parse_identity_evidence('[{"source_id": "one"}, "ignore"]') == [{"source_id": "one"}]

    account = _account("identity")
    account.identity_evidence_json = "not-json"
    _append_identity_evidence(
        account,
        source_type="manual",
        source_id="identity-1",
        role="creation",
        note="confirmed",
        status="confirmed",
        confidence=Decimal("0.8764"),
    )
    first = _parse_identity_evidence(account.identity_evidence_json)
    _append_identity_evidence(
        account,
        source_type="manual",
        source_id="identity-1",
        role="creation",
        note="confirmed",
    )
    assert len(_parse_identity_evidence(account.identity_evidence_json)) == 1
    assert first[0]["source_id"] == "identity-1"
    assert account.identity_status == "confirmed"
    assert account.identity_confidence == Decimal("0.876")


@pytest.mark.asyncio
async def test_net_worth_service_builds_current_and_historical_series(monkeypatch):
    today = date(2026, 9, 19)
    asset = _account("asset")
    liability = _account("liability", balance_kind="liability")
    snapshots = [
        _snapshot("asset", "1000", today - timedelta(days=1)),
        _snapshot("asset", "1100", today),
        _snapshot("liability", "400", today),
        _snapshot("asset", "999", today, verified=False),
        _snapshot("asset", "900", today + timedelta(days=1)),
    ]
    db = _AccountDb(
        execute_results=[
            _Result(rows=[asset, liability]),
            _Result(rows=snapshots),
        ]
    )

    async def fake_ledger(_db, user_id):
        assert user_id == "user-1"
        return "INR"

    async def fake_today(_db, user_id):
        assert user_id == "user-1"
        return today

    positions = {
        "asset": SimpleNamespace(
            observed_as_of=today,
            position_status="observed",
            estimated_balance=Decimal("1100"),
            position_reason_codes=[],
            position_confidence=Decimal("0.95"),
        ),
        "liability": SimpleNamespace(
            observed_as_of=today,
            position_status="estimated",
            estimated_balance=Decimal("400"),
            position_reason_codes=[],
            position_confidence=Decimal("0.80"),
        ),
    }

    async def fake_position(self, user_id, account_id, *, as_of=None):
        assert user_id == "user-1"
        assert as_of is None
        return positions[account_id]

    monkeypatch.setattr(account_module, "get_ledger_currency", fake_ledger)
    monkeypatch.setattr(financial_clock, "user_financial_today", fake_today)
    monkeypatch.setattr(FinancialPositionService, "account_position", fake_position)

    series = await AccountService(db).net_worth("user-1")

    assert series.currency == "INR"
    assert series.assets == 1100
    assert series.liabilities == 400
    assert series.net_worth == 700
    assert series.current_position_status == "estimated"
    assert series.current_position_confidence == 0.8
    assert series.current_position_as_of == today
    assert series.points[-1].date == today

    historical_db = _AccountDb(
        execute_results=[
            _Result(rows=[asset]),
            _Result(
                rows=[
                    _snapshot("asset", "800", today - timedelta(days=2)),
                    _snapshot("asset", "900", today),
                    _snapshot("asset", "1000", today + timedelta(days=1)),
                ]
            ),
        ]
    )
    historical = await AccountService(historical_db).net_worth(
        "user-1", as_of=today - timedelta(days=1)
    )
    assert historical.current_position_status == "historical"
    assert historical.as_of == today - timedelta(days=2)
    assert historical.assets == 800
    assert historical.liabilities == 0


@pytest.mark.asyncio
async def test_net_worth_service_fails_closed_for_unavailable_positions(monkeypatch):
    today = date(2026, 9, 19)
    accounts = [
        _account("missing"),
        _account("unobserved"),
        _account("stale"),
        _account("review"),
        _account("no-estimate"),
        _account("reasoned"),
    ]
    db = _AccountDb(execute_results=[_Result(rows=accounts), _Result(rows=[])])

    async def fake_ledger(_db, user_id):
        return "INR"

    async def fake_today(_db, user_id):
        return today

    positions = {
        "missing": None,
        "unobserved": SimpleNamespace(
            observed_as_of=None,
            position_status="needs_observation",
            estimated_balance=None,
            position_reason_codes=["verified_observation_required"],
            position_confidence=Decimal("0.2"),
        ),
        "stale": SimpleNamespace(
            observed_as_of=today - timedelta(days=10),
            position_status="observed",
            estimated_balance=Decimal("100"),
            position_reason_codes=[],
            position_confidence=Decimal("0.5"),
        ),
        "review": SimpleNamespace(
            observed_as_of=today,
            position_status="needs_review",
            estimated_balance=Decimal("100"),
            position_reason_codes=["needs_review"],
            position_confidence=Decimal("0.4"),
        ),
        "no-estimate": SimpleNamespace(
            observed_as_of=today,
            position_status="observed",
            estimated_balance=None,
            position_reason_codes=[],
            position_confidence=Decimal("0.3"),
        ),
        "reasoned": SimpleNamespace(
            observed_as_of=today,
            position_status="observed",
            estimated_balance=Decimal("100"),
            position_reason_codes=["manual_review"],
            position_confidence=Decimal("0.6"),
        ),
    }

    async def fake_position(self, user_id, account_id, *, as_of=None):
        return positions[account_id]

    monkeypatch.setattr(account_module, "get_ledger_currency", fake_ledger)
    monkeypatch.setattr(financial_clock, "user_financial_today", fake_today)
    monkeypatch.setattr(FinancialPositionService, "account_position", fake_position)

    series = await AccountService(db).net_worth("user-1")

    assert series.current_position_status == "needs_review"
    assert series.current_position_confidence == 0.2
    assert set(series.current_position_reason_codes) == {
        "account_position_unavailable",
        "verified_observation_required",
        "stale_verified_observation",
        "needs_review",
        "estimated_position_unavailable",
        "manual_review",
    }


@pytest.mark.asyncio
async def test_net_worth_service_returns_ledger_currency_without_accounts(monkeypatch):
    async def fake_ledger(_db, user_id):
        return "USD"

    monkeypatch.setattr(account_module, "get_ledger_currency", fake_ledger)
    service = AccountService(_AccountDb(execute_results=[_Result(rows=[])]))
    series = await service.net_worth("user-1")
    assert series.currency == "USD"
    assert series.points == []
