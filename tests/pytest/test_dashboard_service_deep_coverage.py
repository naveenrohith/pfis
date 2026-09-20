"""Deterministic coverage for dashboard workspace aggregation helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from app.models.transaction import CardEvent, PaymentRail, TransactionType
from app.schemas.dashboard import ReviewSummary, SyncSummary
from app.services import dashboard_service as module
from app.services.dashboard_service import WorkspaceService


class _Result:
    def __init__(self, *, rows=(), one=None):
        self.rows = list(rows)
        self.one_value = one

    def all(self):
        return list(self.rows)

    def one(self):
        return self.one_value


class _Db:
    def __init__(self, results=()):
        self.results = list(results)

    async def execute(self, _statement):
        return self.results.pop(0) if self.results else _Result()


def _txn(**overrides):
    values = {
        "is_transfer": False,
        "transaction_type": TransactionType.DEBIT,
        "merchant_normalized": "Shop",
        "merchant_raw": "Shop raw",
        "category_id": "category-1",
        "amount": 100,
        "transaction_date": date(2026, 9, 20),
        "payment_method": SimpleNamespace(value="upi"),
        "transaction_status": "posted",
        "confidence_score": 0.8,
        "payment_rail": PaymentRail.UPI,
        "card_event": CardEvent.NONE,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_dashboard_recommendations_rank_and_classify_all_material_paths():
    service = WorkspaceService(None)
    review = ReviewSummary(pending_count=2, low_confidence_count=3, avg_confidence=0.6)
    budgets = [
        {"category": "Rent", "limit": 1000, "actual": 1200, "usage_pct": 120, "status": "over"},
        {"category": "Food", "limit": 1000, "actual": 850, "usage_pct": 85, "status": "warning"},
        {"category": "Other", "limit": 1000, "actual": 100, "usage_pct": 10, "status": "under"},
    ]
    recurring = [{"merchant": "Streaming", "monthly_equivalent": 25, "confidence": 0.9}]
    insights = [{"type": "anomaly", "title": "Unusual", "description": "Review"}]
    recommendations = service._recommendations(
        income=100,
        spend=99,
        budgets=budgets,
        recurring=recurring,
        review=review,
        insights=insights,
    )
    assert {item.type for item in recommendations} == {
        "budget",
        "recurring",
        "review",
        "anomaly",
        "savings",
    }
    ranked = service._rank_recommendations(
        recommendations,
        income=100,
        recurring=recurring,
        review=review,
    )
    assert ranked[0].priority >= ranked[-1].priority
    assert all(item.evidence for item in ranked)
    assert service._expected_impact("unknown")

    assert service._classify_event(_txn(is_transfer=True), None, set()) == "transfer"
    assert (
        service._classify_event(_txn(transaction_type=TransactionType.REFUND), None, set())
        == "refund"
    )
    assert (
        service._classify_event(_txn(transaction_type=TransactionType.CREDIT), None, set())
        == "income"
    )
    assert service._classify_event(_txn(), "Bills", set()) == "bill"
    assert (
        service._classify_event(_txn(merchant_normalized="Stream"), None, {"stream"})
        == "subscription"
    )
    assert service._classify_event(_txn(merchant_normalized="Market"), None, set()) == "shopping"


def test_dashboard_empty_workspace_handles_past_current_and_future_periods():
    sync = SyncSummary(
        latest_status="completed",
        last_synced_at=datetime(2026, 9, 19, tzinfo=UTC).isoformat(),
        processed_total=2,
        unprocessed_total=1,
    )
    past = WorkspaceService._empty_workspace(1, 2026, sync, date(2026, 9, 20))
    assert past.projection.days_elapsed == 31
    assert past.projection.data_through == date(2026, 1, 31)
    current = WorkspaceService._empty_workspace(9, 2026, sync, date(2026, 9, 20))
    assert current.projection.days_elapsed == 20
    assert current.projection.data_through == date(2026, 9, 20)
    future = WorkspaceService._empty_workspace(12, 2026, SyncSummary(), date(2026, 9, 20))
    assert future.projection.days_elapsed == 0
    assert future.projection.data_through is None


@pytest.mark.asyncio
async def test_dashboard_query_helpers_cover_feedback_budgets_timeline_and_sync():
    feedback_rows = [
        ("budget", "accepted", None, "helped"),
        ("budget", "not_relevant", "too_risky", None),
        (None, "accepted", None, "worse"),
    ]
    service = WorkspaceService(_Db([_Result(rows=feedback_rows)]))
    feedback = await service._recommendation_feedback("user-1")
    assert feedback["budget"].completed_outcomes == 1
    assert feedback["budget"].too_risky == 1

    budget_rows = [
        (SimpleNamespace(category_id="cat-1", monthly_limit=100), "Rent"),
        (SimpleNamespace(category_id="cat-2", monthly_limit=0), "Other"),
    ]
    spend_rows = [
        SimpleNamespace(category_id="cat-1", total=80),
        SimpleNamespace(category_id="cat-2", total=5),
    ]
    service = WorkspaceService(_Db([_Result(rows=budget_rows), _Result(rows=spend_rows)]))
    budgets = await service._budget_status("user-1", 9, 2026)
    assert [item["status"] for item in budgets] == ["warning", "under"]
    assert await WorkspaceService(_Db([_Result(rows=[])]))._budget_status("user-1", 9, 2026) == []

    txns = [
        (_txn(merchant_normalized="Rent"), "Rent"),
        (_txn(transaction_type=TransactionType.CREDIT), None),
    ]
    service = WorkspaceService(_Db([_Result(rows=txns)]))
    timeline = await service._timeline("user-1", 9, 2026, {"stream"})
    assert [event.type for event in timeline] == ["bill", "income"]
    assert timeline[0].direction == "out"
    assert timeline[1].direction == "in"

    sync_row = SimpleNamespace(
        latest_status=SimpleNamespace(value="completed"),
        last_synced_at=datetime(2026, 9, 20, tzinfo=UTC),
        total=5,
        processed=3,
    )
    sync = await WorkspaceService(_Db([_Result(one=sync_row)]))._sync_summary("user-1")
    assert sync.latest_status == "completed"
    assert sync.processed_total == 3
    assert sync.unprocessed_total == 2


@pytest.mark.asyncio
async def test_dashboard_empty_workspace_short_circuits_get_workspace(monkeypatch):
    service = WorkspaceService(None)

    async def period(_user_id, _month, _year):
        return {
            "transaction_count": 0,
            "timezone": "UTC",
            "currency": "INR",
            "spend": 0,
            "income": 0,
            "review": ReviewSummary(),
        }

    async def sync(_user_id):
        return SyncSummary()

    monkeypatch.setattr(service, "_period_metrics", period)
    monkeypatch.setattr(service, "_sync_summary", sync)
    monkeypatch.setattr(module, "financial_today", lambda _timezone: date(2026, 9, 20))
    result = await service.get_workspace("user-1", 9, 2026)
    assert result.snapshot.transaction_count == 0
    assert result.timeline == []
