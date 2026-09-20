"""Direct branch coverage for historical cash-flow backtesting."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.services import intelligence_service as module
from app.services.intelligence_service import IntelligenceService


class _Result:
    def __init__(self, rows=(), *, one=None):
        self.rows = list(rows)
        self.one_value = one

    def all(self):
        return list(self.rows)

    def one(self):
        return self.one_value


class _Db:
    def __init__(self, transactions):
        self.transactions = transactions

    async def execute(self, _statement):
        return _Result(one=SimpleNamespace(currency="INR", timezone="UTC"))

    async def scalars(self, _statement):
        return _Result(self.transactions)


def _transaction(*, identifier, year, month, day, category, amount=100, status="posted"):
    return SimpleNamespace(
        id=identifier,
        currency="INR",
        transaction_status=status,
        is_transfer=False,
        is_accounting_adjustment=False,
        review_outcome=None,
        card_event="none",
        amount=amount,
        transaction_type="debit",
        transaction_date=date(year, month, day),
        created_at=datetime(year, month, day, 12, tzinfo=UTC),
        category_id=category,
    )


@pytest.mark.asyncio
async def test_cash_flow_backtest_evaluates_cutoffs_and_retains_evidence(monkeypatch):
    transactions = []
    months = [(2025, month) for month in range(11, 13)]
    months.extend((2026, month) for month in range(1, 8))
    for year, month in months:
        amount = 100 if (year, month) >= (2026, 5) else 1000
        transactions.extend(
            [
                _transaction(
                    identifier=f"food-{year}-{month}",
                    year=year,
                    month=month,
                    day=5,
                    category="food",
                    amount=amount,
                ),
                _transaction(
                    identifier=f"rent-{year}-{month}",
                    year=year,
                    month=month,
                    day=20,
                    category="rent",
                    amount=amount,
                ),
            ]
        )
    transactions.append(
        _transaction(
            identifier="pending",
            year=2026,
            month=7,
            day=10,
            category="food",
            status="pending",
        )
    )

    async def today(_db, _user_id):
        return date(2026, 8, 31)

    async def snapshots(_db, *, user_id, timezone, as_of):
        del user_id, timezone, as_of
        return {
            ("transaction", transaction.id): {
                "currency": "INR",
                "transaction_status": "posted",
                "is_transfer": False,
                "is_accounting_adjustment": False,
                "review_outcome": None,
                "card_event": "none",
                "amount": transaction.amount,
                "transaction_type": transaction.transaction_type,
                "category_id": transaction.category_id,
            }
            for transaction in transactions
        }

    async def timeline(
        self,
        user_id,
        *,
        range_start,
        range_end,
        as_of,
        historical_safe,
    ):
        del self, user_id, range_start, range_end, historical_safe
        return SimpleNamespace(
            events=[
                SimpleNamespace(
                    amount=SimpleNamespace(expected=40),
                    expected_date=as_of + timedelta(days=1),
                    direction="outflow",
                    state="expected",
                ),
                SimpleNamespace(
                    amount=SimpleNamespace(expected=15),
                    expected_date=as_of + timedelta(days=2),
                    direction="outflow",
                    state="conflict",
                ),
                SimpleNamespace(
                    amount=SimpleNamespace(expected=80),
                    expected_date=as_of,
                    direction="outflow",
                    state="expected",
                ),
                SimpleNamespace(
                    amount=SimpleNamespace(expected=90),
                    expected_date=as_of + timedelta(days=1),
                    direction="inflow",
                    state="expected",
                ),
                SimpleNamespace(
                    amount=SimpleNamespace(expected=None),
                    expected_date=as_of + timedelta(days=1),
                    direction="outflow",
                    state="expected",
                ),
            ]
        )

    monkeypatch.setattr(module, "user_financial_today", today)
    monkeypatch.setattr(module, "historical_source_snapshots", snapshots)
    monkeypatch.setattr(module.TemporalEventService, "timeline", timeline)

    report = await IntelligenceService(_Db(transactions)).cash_flow_backtest(
        "user-1", months=3, cutoff_days=(7, 40)
    )

    assert report.requested_months == 3
    assert report.evaluated_months == 3
    assert report.excluded_months == []
    assert report.temporal_evidence_evaluated is True
    assert report.temporal_evidence_periods == 6
    assert report.temporal_event_count == 6
    assert report.transaction_history_evaluated is True
    assert report.transaction_history_cutoffs == 6
    assert report.transaction_history_coverage_pct == 100.0
    assert report.category_mix_supported_periods == 6
    assert report.category_mix_applied_periods == 6
    assert report.settled_transaction_count == len(transactions) - 1
    assert report.unsettled_transaction_count == 1
    assert [item.cutoff_day for item in report.horizons] == [7, 40]
    assert all(item.eligible_periods == 3 for item in report.horizons)
    assert all(item.weighted_absolute_percentage_error is not None for item in report.horizons)


@pytest.mark.asyncio
async def test_cash_flow_backtest_excludes_missing_history_and_empty_horizons(monkeypatch):
    async def today(_db, _user_id):
        return date(2026, 8, 31)

    monkeypatch.setattr(module, "user_financial_today", today)
    report = await IntelligenceService(_Db([])).cash_flow_backtest(
        "user-1", months=2, cutoff_days=(7,)
    )

    assert report.evaluated_months == 0
    assert len(report.excluded_months) == 2
    assert {item.reason for item in report.excluded_months} == {"insufficient_prior_history"}
    assert report.horizons[0].eligible_periods == 0


@pytest.mark.asyncio
async def test_cash_flow_backtest_excludes_months_without_observed_spend(monkeypatch):
    transactions = [
        _transaction(
            identifier=f"history-{year}-{month}",
            year=year,
            month=month,
            day=5,
            category="food",
        )
        for year, month in [(2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4)]
    ]

    async def today(_db, _user_id):
        return date(2026, 8, 31)

    monkeypatch.setattr(module, "user_financial_today", today)
    report = await IntelligenceService(_Db(transactions)).cash_flow_backtest(
        "user-1", months=3, cutoff_days=(7,)
    )

    assert report.evaluated_months == 0
    assert len(report.excluded_months) == 3
    assert {item.reason for item in report.excluded_months} == {"no_observed_spend"}
