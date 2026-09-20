"""Deep reconciliation and position-status coverage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.account import AccountBalanceSnapshot
from app.models.transaction import CardEvent, PaymentRail
from app.services import financial_position_service as module
from app.services.financial_position_service import FinancialPositionService

from tests.pytest.test_financial_position_service_additional_coverage import (
    TODAY,
    _account,
    _transaction,
)


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def scalars(self, _statement):
        return _Rows(self.rows.pop(0) if self.rows else [])


def _snapshot(snapshot_id, amount, as_of, *, effective_at=None):
    return AccountBalanceSnapshot(
        id=snapshot_id,
        user_id="user-1",
        financial_account_id="bank-1",
        amount=Decimal(str(amount)),
        currency="INR",
        as_of=as_of,
        source="manual",
        source_record_id=None,
        verified=True,
        observed_at=datetime.combine(as_of, datetime.min.time(), tzinfo=UTC),
        effective_at=effective_at,
    )


@pytest.mark.asyncio
async def test_account_position_reconciles_duplicates_unlinked_pending_and_coverage_risks(
    monkeypatch,
):
    account = _account("bank-1")
    latest = _snapshot("latest", 1000, TODAY - timedelta(days=1))
    previous = _snapshot("previous", 900, TODAY - timedelta(days=4))
    between = [
        _transaction(
            "reviewed",
            amount="20",
            transaction_date=TODAY - timedelta(days=2),
            reviewed=False,
            review_outcome="needs_review",
        ),
        _transaction(
            "unlinked",
            amount="30",
            transaction_date=TODAY - timedelta(days=2),
            rail=PaymentRail.TRANSFER,
            card_event=CardEvent.PAYMENT,
            reviewed=True,
        ),
        _transaction(
            "duplicate-a",
            amount="10",
            transaction_date=TODAY - timedelta(days=3),
            merchant="Duplicate",
        ),
        _transaction(
            "duplicate-b",
            amount="10",
            transaction_date=TODAY - timedelta(days=3),
            merchant="Duplicate",
        ),
    ]
    pending_anchor = _transaction(
        "pending-anchor",
        amount="5",
        transaction_date=TODAY,
        status="pending",
        reviewed=False,
        review_outcome="needs_review",
    )
    service = FinancialPositionService(_Db([[latest, previous], [*between, pending_anchor]]))
    monkeypatch.setattr(service, "_owned_account", _owned(account))
    monkeypatch.setattr(module, "user_financial_today", _today)
    monkeypatch.setattr(service, "_source_coverage_incomplete", _coverage_incomplete)
    monkeypatch.setattr(service, "_balance_source_state", _source_state)
    result = await service.account_position("user-1", account.id)
    assert result.position_status == "needs_review"
    assert result.reconciliation_status == "needs_review"
    assert result.opening_balance == 900.0
    assert result.verified_balance == 1000.0
    assert result.reconciliation_delta is not None
    assert result.review_count >= 4
    assert "pending_activity_excluded" in result.position_reason_codes
    assert "source_coverage_incomplete" in result.position_reason_codes
    assert "balance_observation_overdue" in result.position_reason_codes
    assert any(item.kind == "duplicate_candidate" for item in result.reconciliation_items)
    assert any(item.kind == "unlinked_transfer" for item in result.reconciliation_items)


@pytest.mark.asyncio
async def test_account_position_reports_observation_required_without_verified_snapshot(monkeypatch):
    account = _account("bank-1")
    service = FinancialPositionService(_Db([[], []]))
    monkeypatch.setattr(service, "_owned_account", _owned(account))
    monkeypatch.setattr(module, "user_financial_today", _today)
    result = await service.account_position("user-1", account.id, as_of=TODAY)
    assert result.position_status == "needs_observation"
    assert result.position_reason_codes == ["verified_observation_required"]
    assert result.reconciliation_status == "not_ready"


def _owned(account):
    async def owned(_user_id, _account_id):
        return account

    return owned


async def _today(*_args):
    return TODAY


async def _coverage_incomplete(*_args):
    return True


async def _source_state(*_args):
    return SimpleNamespace(
        coverage_start=datetime(2026, 9, 1, tzinfo=UTC),
        coverage_end=datetime(2026, 9, 19, tzinfo=UTC),
        last_success_at=datetime(2026, 9, 19, tzinfo=UTC),
        coverage_complete=False,
        expected_cadence_minutes=60,
        last_observed_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
