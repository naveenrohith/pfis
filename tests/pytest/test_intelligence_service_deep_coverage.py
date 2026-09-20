"""Deep, deterministic branch coverage for intelligence service read models."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.schemas.intelligence import ScenarioRequest
from app.services import intelligence_service as intelligence_module
from app.services.intelligence_service import IntelligenceService


class _Result:
    def __init__(self, rows=(), *, one=None):
        self._rows = list(rows)
        self._one = one

    def all(self):
        return list(self._rows)

    def one(self):
        return self._one

    def scalars(self):
        return self


class _DB:
    def __init__(self, results=(), scalar_values=(), scalar_rows=()):
        self.results = iter(results)
        self.scalar_values = iter(scalar_values)
        self.scalar_rows = iter(scalar_rows)

    async def execute(self, _statement):
        return next(self.results)

    async def scalar(self, _statement):
        return next(self.scalar_values)

    async def scalars(self, _statement):
        return next(self.scalar_rows)


def _transaction(**values):
    defaults = {
        "id": "txn",
        "currency": "INR",
        "transaction_status": "posted",
        "is_transfer": False,
        "is_accounting_adjustment": False,
        "review_outcome": None,
        "card_event": "none",
        "amount": 100,
        "transaction_type": "debit",
        "transaction_date": date(2026, 8, 5),
        "created_at": datetime(2026, 8, 5, tzinfo=UTC),
        "category_id": "food",
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_data_quality_metrics_clamps_confidence_and_reports_connector_backlog():
    quality_db = _DB(
        [
            _Result(
                one=SimpleNamespace(
                    transaction_count=4,
                    parse_confidence=1.5,
                    merchant_confidence=-0.4,
                    pending_count=2,
                    conflict_count=1,
                    latest_transaction_date=date(2026, 8, 29),
                )
            )
        ],
        scalar_values=[
            SimpleNamespace(auto_sync_status="paused"),
            datetime(2026, 8, 28),
            3,
        ],
    )

    quality = await IntelligenceService(quality_db)._data_quality_metrics("u1", 8, 2026)

    assert quality == {
        "transaction_count": 4,
        "parse_confidence": 1.0,
        "merchant_confidence": 0.0,
        "pending_count": 2,
        "conflict_count": 1,
        "latest_transaction_date": date(2026, 8, 29),
        "latest_sync_at": datetime(2026, 8, 28),
        "sync_status": "paused",
        "unprocessed_email_count": 3,
    }


def test_category_mix_and_interval_helpers_keep_weak_history_explicit():
    transactions = [
        _transaction(
            id=f"food-{month}",
            category_id="food",
            transaction_date=date(2026, month, 5),
        )
        for month in (5, 6, 7)
    ]
    assert IntelligenceService._category_mix_baseline_from_transactions(
        transactions,
        {},
        month=8,
        year=2026,
        as_of=date(2026, 8, 31),
        currency="INR",
    ) == (None, 3, "insufficient_history")


@pytest.mark.asyncio
async def test_same_cutoff_interval_returns_low_evidence_when_fewer_than_three_months():
    rows = [
        SimpleNamespace(transaction_date=date(2026, 7, 5), spend_effect=100),
        SimpleNamespace(transaction_date=date(2026, 7, 20), spend_effect=100),
    ]
    interval = await IntelligenceService(_DB([_Result(rows)]))._same_cutoff_interval_width(
        "u1", 8, 2026, 7
    )
    assert interval == (None, 1)


@pytest.mark.asyncio
async def test_preview_scenario_applies_requested_reductions_without_overcap(monkeypatch):
    async def projection(self, user_id, month, year):
        return SimpleNamespace(
            projected_spend=100,
            recurring_commitments=40,
            expected_income=200,
            projected_net=100,
            assumptions=["Observed history"],
            data_through=date(2026, 8, 20),
        )

    monkeypatch.setattr(IntelligenceService, "cash_flow_projection", projection)
    response = await IntelligenceService(object()).preview_scenario(
        "u1",
        ScenarioRequest(
            month=8,
            year=2026,
            flexible_spend_reduction=10,
            recurring_reduction=5,
            additional_income=20,
        ),
    )

    assert response.effective_flexible_spend_reduction == 10
    assert response.effective_recurring_reduction == 5
    assert response.scenario_projected_spend == 85
    assert response.scenario_projected_net == 135
    assert response.monthly_impact == 35


@pytest.mark.asyncio
async def test_cash_flow_projection_filters_temporal_events_and_uses_robust_history(
    monkeypatch,
):
    class _CategoryRows:
        def all(self):
            return []

    class _BudgetRows:
        def scalars(self):
            return self

        def all(self):
            return []

    async def today(_db, _user_id):
        return date(2026, 8, 15)

    async def monthly(self, user_id, month, year):
        return 1000, 200

    async def timeline(self, user_id, *, range_start, range_end):
        def event(**values):
            return SimpleNamespace(
                amount=SimpleNamespace(expected=values.pop("amount", 100)), **values
            )

        return SimpleNamespace(
            ruleset_version="temporal-deep-test",
            events=[
                event(
                    kind="income",
                    direction="inflow",
                    cadence="monthly",
                    state="overdue",
                    amount=300,
                    evidence=[],
                ),
                event(
                    kind="bill",
                    direction="outflow",
                    cadence="monthly",
                    state="missed",
                    amount=150,
                    evidence=[],
                ),
                event(
                    kind="bill",
                    direction="inflow",
                    cadence=None,
                    state="conflict",
                    amount=80,
                    evidence=[],
                ),
                event(
                    kind="noise",
                    direction="other",
                    cadence=None,
                    state="expected",
                    amount=999,
                    evidence=[],
                ),
                event(
                    kind="empty",
                    direction="outflow",
                    cadence=None,
                    state="expected",
                    amount=None,
                    evidence=[],
                ),
            ],
        )

    async def category_mix(self, user_id, month, year, historical_spend):
        return None, 0, "insufficient_history"

    async def interval(self, user_id, month, year, cutoff_day):
        return None, 0

    monkeypatch.setattr(intelligence_module, "user_financial_today", today)
    monkeypatch.setattr(IntelligenceService, "monthly_income_spend", monthly)
    monkeypatch.setattr(intelligence_module.TemporalEventService, "timeline", timeline)
    monkeypatch.setattr(IntelligenceService, "_category_mix_baseline", category_mix)
    monkeypatch.setattr(IntelligenceService, "_same_cutoff_interval_width", interval)

    projection = await IntelligenceService(
        _DB([_CategoryRows(), _BudgetRows()])
    ).cash_flow_projection(
        "u1",
        8,
        2026,
        recurring_patterns=[],
        historical_periods=[(900, 100), (950, 200), (1000, 300)],
    )

    assert projection.temporal_expected_income == 300
    assert projection.temporal_expected_outflows == 150
    assert projection.temporal_conflicted_outflows == 0
    assert projection.temporal_event_count == 2
    assert projection.temporal_conflict_count == 1
    assert projection.interval_calibration == "robust_history"
    assert projection.pay_cycle_status == "insufficient_history"
    assert projection.projected_spend == 413.33
    assert projection.expected_income == 1300
    assert projection.temporal_ruleset_version == "temporal-deep-test"


@pytest.mark.asyncio
async def test_financial_health_penalizes_stale_erroring_connector_and_review_backlog(monkeypatch):
    async def today(_db, _user_id):
        return date(2026, 8, 31)

    async def monthly(self, user_id, month, year):
        return 100, 90

    async def quality(self, user_id, month, year):
        return {
            "transaction_count": 4,
            "parse_confidence": 0.8,
            "merchant_confidence": 0.7,
            "pending_count": 4,
            "conflict_count": 2,
            "latest_transaction_date": date(2026, 9, 1),
            "latest_sync_at": datetime.now(UTC) - timedelta(days=10),
            "sync_status": "error",
            "unprocessed_email_count": 3,
        }

    async def no_budget(self, user_id, month, year):
        return None

    async def coverage(self, user_id):
        return SimpleNamespace(overall_score=40, ruleset_version="coverage-test", sources=[])

    monkeypatch.setattr(intelligence_module, "user_financial_today", today)
    monkeypatch.setattr(IntelligenceService, "monthly_income_spend", monthly)
    monkeypatch.setattr(IntelligenceService, "_data_quality_metrics", quality)
    monkeypatch.setattr(IntelligenceService, "_budget_adherence", no_budget)
    monkeypatch.setattr(IntelligenceService, "source_coverage", coverage)

    health = await IntelligenceService(object()).financial_health(
        "u1",
        8,
        2026,
        recurring_patterns=[SimpleNamespace(status="early", monthly_equivalent=60)],
        historical_periods=[(0, 0), (0, 0)],
    )

    freshness = next(item for item in health.data_confidence_breakdown if item.key == "freshness")
    assert health.savings_rate == 10
    assert health.budget_adherence is None
    assert health.review_cleanliness == 0
    assert health.spending_volatility == 0
    assert freshness.score <= 35
    assert "needs attention" in freshness.summary
    assert any(
        signal["label"] == "Budget adherence" and signal["severity"] == "info"
        for signal in health.signals
    )


@pytest.mark.asyncio
async def test_source_coverage_marks_truncated_erroring_gmail_and_unresolved_accounts():
    now = datetime.now(UTC)
    sync = SimpleNamespace(
        end_time=now - timedelta(days=9),
        coverage_complete=False,
        coverage_truncated=True,
        coverage_result_size_estimate=250,
    )
    gmail = SimpleNamespace(auto_sync_status="error")
    accounts = [
        SimpleNamespace(
            identity_status="confirmed",
            created_at=datetime(2026, 1, 2),
            updated_at=datetime(2026, 8, 1),
        ),
        SimpleNamespace(
            identity_status="unresolved",
            created_at=datetime(2026, 2, 2),
            updated_at=None,
        ),
    ]
    db = _DB(
        [
            _Result(
                one=SimpleNamespace(
                    raw_count=2,
                    coverage_start=datetime(2026, 1, 1),
                    coverage_end=datetime(2026, 8, 1),
                    processed=1,
                )
            )
        ],
        scalar_values=[SimpleNamespace(id="u1"), gmail, sync, 1],
        scalar_rows=[
            [date(2026, 8, 1), date(2026, 7, 1), date(2026, 6, 1)],
            accounts,
        ],
    )

    coverage = await IntelligenceService(db).source_coverage("u1")
    gmail_source = next(source for source in coverage.sources if source.key == "gmail")
    account_source = next(source for source in coverage.sources if source.key == "accounts")

    assert gmail_source.status == "error"
    assert gmail_source.completeness == "partial"
    assert gmail_source.score < 50
    assert any("truncated" in item for item in gmail_source.limitations)
    assert any("Truncated" in item.value for item in gmail_source.evidence)
    assert account_source.status == "partial"
    assert account_source.score == 50
    assert account_source.remediation_target == "plan"
