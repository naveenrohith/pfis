"""Direct branch coverage for intelligence calculations and evidence labels."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from app.schemas.intelligence import ScenarioRequest
from app.services import intelligence_service as intelligence_module
from app.services.intelligence_service import IntelligenceService


class _Result:
    def __init__(self, rows=(), *, one=None, scalar=None):
        self._rows = list(rows)
        self._one = one
        self._scalar = scalar

    def all(self):
        return list(self._rows)

    def one(self):
        return self._one

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self


class _DB:
    def __init__(self, results=(), scalar_values=()):
        self.results = iter(results)
        self.scalar_values = iter(scalar_values)

    async def execute(self, _statement):
        return next(self.results)

    async def scalar(self, _statement):
        return next(self.scalar_values)


def _transaction(**values):
    defaults = {
        "id": values.get("id", "txn"),
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


def test_module_helpers_and_transaction_effects_cover_financial_semantics():
    assert intelligence_module._prev_month(1, 2026) == (12, 2025)
    assert intelligence_module._prev_month(8, 2026) == (7, 2026)
    assert intelligence_module._pct_change(120, 100) == 20
    assert intelligence_module._pct_change(120, 0) is None
    assert intelligence_module._merchant_key(None) == "Unknown"
    assert intelligence_module._merchant_key("  Cafe  ") == "Cafe"
    assert intelligence_module._shift_month(1, 2026, -2) == (11, 2025)

    base = _transaction()
    assert IntelligenceService._transaction_spend_effect(base, None, currency="INR") == 100
    assert (
        IntelligenceService._transaction_spend_effect(
            _transaction(transaction_type="refund"), None, currency="INR"
        )
        == -100
    )
    for values in (
        {"currency": "USD"},
        {"transaction_status": "pending"},
        {"is_transfer": True},
        {"is_accounting_adjustment": True},
        {"review_outcome": "ignored_by_rule"},
        {"card_event": "payment"},
        {"transaction_type": "credit"},
    ):
        assert (
            IntelligenceService._transaction_spend_effect(
                _transaction(**values), None, currency="INR"
            )
            == 0
        )

    payload = {
        "currency": "INR",
        "transaction_status": "posted",
        "is_transfer": False,
        "is_accounting_adjustment": False,
        "review_outcome": None,
        "card_event": "none",
        "amount": 40,
        "transaction_type": "refund",
        "category_id": "groceries",
    }
    assert IntelligenceService._transaction_spend_effect(base, payload, currency="INR") == -40


def test_daily_spend_for_cutoff_respects_snapshots_and_cutoff():
    transactions = [
        _transaction(id="debit", amount=100, transaction_date=date(2026, 8, 4)),
        _transaction(
            id="refund",
            amount=20,
            transaction_type="refund",
            transaction_date=date(2026, 8, 5),
        ),
        _transaction(
            id="future",
            amount=50,
            transaction_date=date(2026, 8, 6),
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
        ),
        _transaction(
            id="pending",
            amount=90,
            transaction_status="pending",
            transaction_date=date(2026, 8, 7),
        ),
    ]
    daily = IntelligenceService._daily_spend_for_cutoff(
        transactions,
        as_of=date(2026, 8, 10),
        currency="INR",
        snapshots={"refund": {"amount": 10, "transaction_type": "debit"}},
    )

    assert daily[(2026, 8)][4] == 100
    assert daily[(2026, 8)][5] == 10
    assert 6 not in daily[(2026, 8)]
    assert 7 not in daily[(2026, 8)]


def test_category_mix_baseline_from_transactions_covers_history_and_cutoffs():
    transactions = []
    for index, month in enumerate((5, 6, 7), start=1):
        transactions.extend(
            [
                _transaction(
                    id=f"food-{month}",
                    amount=100 + index,
                    category_id="food",
                    transaction_date=date(2026, month, 5),
                ),
                _transaction(
                    id=f"rent-{month}",
                    amount=200 + index,
                    category_id="rent",
                    transaction_date=date(2026, month, 6),
                ),
            ]
        )
    service = IntelligenceService(object())
    baseline, months, status = service._category_mix_baseline_from_transactions(
        transactions,
        {},
        month=8,
        year=2026,
        as_of=date(2026, 8, 31),
        currency="INR",
    )

    assert baseline == 304
    assert months == 3
    assert status == "mix_supported"

    same_month = []
    for year in (2024, 2025):
        same_month.extend(
            [
                _transaction(
                    id=f"same-food-{year}",
                    amount=120,
                    category_id="food",
                    transaction_date=date(year, 8, 5),
                ),
                _transaction(
                    id=f"same-rent-{year}",
                    amount=220,
                    category_id="rent",
                    transaction_date=date(year, 8, 6),
                ),
            ]
        )
    same_month.extend(
        [
            _transaction(
                id="same-extra-food",
                amount=120,
                category_id="food",
                transaction_date=date(2026, 7, 5),
            ),
            _transaction(
                id="same-extra-rent",
                amount=220,
                category_id="rent",
                transaction_date=date(2026, 7, 6),
            ),
        ]
    )
    baseline, months, status = service._category_mix_baseline_from_transactions(
        same_month,
        {},
        month=8,
        year=2026,
        as_of=date(2026, 8, 31),
        currency="INR",
    )
    assert baseline == 340
    assert months == 2
    assert status == "same_month_supported"

    insufficient = service._category_mix_baseline_from_transactions(
        [_transaction(transaction_date=date(2026, 7, 5))],
        {},
        month=8,
        year=2026,
        as_of=date(2026, 8, 31),
        currency="INR",
    )
    assert insufficient == (None, 1, "insufficient_history")


@pytest.mark.asyncio
async def test_database_backed_baseline_and_interval_helpers_cover_empty_and_supported_history():
    rows = [
        SimpleNamespace(
            transaction_date=date(2026, month, 5), category_id=category, spend_effect=amount
        )
        for month in (5, 6, 7)
        for category, amount in (("food", 100), ("rent", 200))
    ]
    service = IntelligenceService(_DB([_Result(rows)]))
    baseline = await service._category_mix_baseline("u1", 8, 2026, [1, 2, 3])
    assert baseline == (300, 3, "mix_supported")

    empty_service = IntelligenceService(_DB([_Result([])]))
    assert await empty_service._category_mix_baseline("u1", 8, 2026, [1, 2, 3]) == (
        None,
        0,
        "insufficient_history",
    )
    assert await empty_service._category_mix_baseline("u1", 8, 2026, [1, 2]) == (
        None,
        0,
        "insufficient_history",
    )

    interval_rows = [
        SimpleNamespace(transaction_date=date(2026, month, 5), spend_effect=100)
        for month in (2, 3, 4, 5)
    ] + [
        SimpleNamespace(transaction_date=date(2026, month, 15), spend_effect=100)
        for month in (2, 3, 4, 5)
    ]
    interval = await IntelligenceService(_DB([_Result(interval_rows)]))._same_cutoff_interval_width(
        "u1", 8, 2026, 7
    )
    assert interval[0] is not None
    assert interval[1] == 4


@pytest.mark.asyncio
async def test_preview_scenario_caps_requested_reductions(monkeypatch):
    service = IntelligenceService(object())

    async def projection(self, user_id, month, year):
        return SimpleNamespace(
            projected_spend=500,
            recurring_commitments=100,
            expected_income=1000,
            projected_net=500,
            assumptions=["Observed history"],
            data_through=date(2026, 8, 20),
        )

    monkeypatch.setattr(IntelligenceService, "cash_flow_projection", projection)
    response = await service.preview_scenario(
        "u1",
        ScenarioRequest(
            month=8,
            year=2026,
            flexible_spend_reduction=1000,
            recurring_reduction=250,
            additional_income=50,
        ),
    )

    assert response.baseline_projected_net == 500
    assert response.effective_flexible_spend_reduction == 400
    assert response.effective_recurring_reduction == 100
    assert response.scenario_projected_spend == 0
    assert response.scenario_projected_net == 1050
    assert response.monthly_impact == 550


@pytest.mark.parametrize(
    ("sync_status", "unprocessed", "latest", "freshness", "summary"),
    [
        ("paused", 0, None, 20, "needs attention"),
        ("idle", 2, None, 20, "still need processing"),
        ("idle", 0, None, 90, "close to the period boundary"),
        ("idle", 0, date(2026, 8, 10), 40, "may be missing"),
        ("not_connected", 0, None, 40, "No live connector"),
        ("idle", 0, None, 40, "No activity"),
    ],
)
def test_data_confidence_breakdown_labels_evidence_state(
    sync_status, unprocessed, latest, freshness, summary
):
    dimensions = IntelligenceService._data_confidence_breakdown(
        coverage_score=90,
        observed_periods=4,
        freshness_score=freshness,
        stale_days=5 if latest else None,
        latest_transaction_date=latest,
        parsing_score=50,
        parse_confidence=0.5,
        merchant_confidence=0.6,
        review_score=90,
        pending_count=1,
        conflict_count=0,
        transaction_count=10,
        latest_sync_at=datetime(2026, 8, 20, tzinfo=UTC),
        sync_status=sync_status,
        sync_age_days=2,
        unprocessed_email_count=unprocessed,
    )

    freshness_dimension = next(item for item in dimensions if item.key == "freshness")
    assert summary in freshness_dimension.summary
    assert dimensions[0].status == "strong"
    assert dimensions[2].status == "limited"
    assert dimensions[0].remediation_label is None
    assert dimensions[2].remediation_target == "review"


@pytest.mark.asyncio
async def test_data_quality_and_spend_maps_cover_empty_connector_and_budget_branches():
    quality_db = _DB(
        [
            _Result(
                one=SimpleNamespace(
                    transaction_count=0,
                    parse_confidence=None,
                    merchant_confidence=None,
                    pending_count=0,
                    conflict_count=0,
                    latest_transaction_date=None,
                )
            )
        ],
        scalar_values=[None, None, 0],
    )
    quality = await IntelligenceService(quality_db)._data_quality_metrics("u1", 8, 2026)
    assert quality["sync_status"] == "not_connected"
    assert quality["parse_confidence"] == 0

    map_db = _DB(
        [
            _Result(
                [
                    SimpleNamespace(merchant="Cafe", total=120),
                    SimpleNamespace(merchant=None, total=None),
                ]
            ),
            _Result([SimpleNamespace(category_id=None, total=80)]),
            _Result([SimpleNamespace(category="Food", total=80)]),
            _Result(
                [
                    SimpleNamespace(
                        category_id="food", merchant="Cafe", total=80, transaction_count=2
                    ),
                    SimpleNamespace(
                        category_id="food", merchant="Second", total=50, transaction_count=1
                    ),
                ]
            ),
        ]
    )
    service = IntelligenceService(map_db)
    assert await service._merchant_spend_map("u1", 8, 2026) == {"cafe": 120.0, "unknown": 0.0}
    assert await service._category_spend_map("u1", 8, 2026) == {None: 80.0}
    assert await service._category_name_spend_map("u1", 8, 2026) == {"Food": 80.0}
    top = await service._category_top_merchants("u1", 8, 2026)
    assert top["food"][0].name == "Cafe"

    budget_service = IntelligenceService(
        _DB(
            [_Result(scalar=None)],
        )
    )

    async def category_spend(self, user_id, month, year):
        return {"food": 120, "zero": 50}

    budget_service.db = _DB(
        [
            _Result(
                [
                    SimpleNamespace(category_id="food", monthly_limit=100),
                    SimpleNamespace(category_id="zero", monthly_limit=0),
                ]
            )
        ]
    )
    budget_service._category_spend_map = category_spend.__get__(budget_service, IntelligenceService)
    adherence = await budget_service._budget_adherence("u1", 8, 2026)
    assert adherence == 90

    no_budget_service = IntelligenceService(_DB([_Result([])]))
    no_budget_service._category_spend_map = category_spend.__get__(
        no_budget_service, IntelligenceService
    )
    assert await no_budget_service._budget_adherence("u1", 8, 2026) is None


@pytest.mark.asyncio
async def test_cash_flow_projection_covers_temporal_and_empirical_calibration(monkeypatch):
    class CategoryRows:
        def all(self):
            return [SimpleNamespace(category_id="food", total=200)]

    class BudgetRows:
        def scalars(self):
            return self

        def all(self):
            return [SimpleNamespace(category_id="food", monthly_limit=500)]

    class BudgetDB:
        def __init__(self):
            self.results = iter([CategoryRows(), BudgetRows()])

        async def execute(self, _statement):
            return next(self.results)

    async def today(_db, _user_id):
        return date(2026, 8, 15)

    async def monthly(self, user_id, month, year):
        return (1000, 200)

    async def timeline(self, user_id, *, range_start, range_end):
        income_events = [
            SimpleNamespace(
                kind="income",
                direction="inflow",
                cadence="monthly",
                state="expected",
                amount=SimpleNamespace(expected=100),
                evidence=[SimpleNamespace(source_type="transaction", role="pattern_observation")],
            )
            for _ in range(3)
        ]
        return SimpleNamespace(
            ruleset_version="temporal-test",
            events=[
                *income_events,
                SimpleNamespace(
                    kind="bill",
                    direction="outflow",
                    cadence="monthly",
                    state="expected",
                    amount=SimpleNamespace(expected=150),
                    evidence=[],
                ),
                SimpleNamespace(
                    kind="bill",
                    direction="outflow",
                    cadence=None,
                    state="conflict",
                    amount=SimpleNamespace(expected=80),
                    evidence=[],
                ),
                SimpleNamespace(
                    kind="noise",
                    direction="other",
                    cadence=None,
                    state="expected",
                    amount=SimpleNamespace(expected=100),
                    evidence=[],
                ),
            ],
        )

    async def category_mix(self, user_id, month, year, historical_spend):
        return (250.0, 3, "mix_supported")

    async def interval(self, user_id, month, year, cutoff_day):
        return (60.0, 4)

    monkeypatch.setattr(intelligence_module, "user_financial_today", today)
    monkeypatch.setattr(IntelligenceService, "monthly_income_spend", monthly)
    monkeypatch.setattr(intelligence_module.TemporalEventService, "timeline", timeline)
    monkeypatch.setattr(IntelligenceService, "_category_mix_baseline", category_mix)
    monkeypatch.setattr(IntelligenceService, "_same_cutoff_interval_width", interval)

    patterns = [
        SimpleNamespace(status="mature", monthly_equivalent=300),
        SimpleNamespace(status="early", monthly_equivalent=50),
        SimpleNamespace(status="missed", monthly_equivalent=25),
    ]
    projection = await IntelligenceService(BudgetDB()).cash_flow_projection(
        "u1",
        8,
        2026,
        recurring_patterns=patterns,
        historical_periods=[(1000, 200), (900, 250), (950, 300), (1000, 350), (900, 250)],
    )

    assert projection.days_elapsed == 15
    assert projection.recurring_commitments == 375
    assert projection.temporal_expected_income == 300
    assert projection.temporal_expected_outflows == 150
    assert projection.temporal_conflicted_outflows == 80
    assert projection.interval_calibration == "same_cutoff_empirical"
    assert projection.interval_calibration_samples == 4
    assert projection.category_mix_status == "mix_supported"
    assert projection.pay_cycle_status == "supported"
    assert projection.temporal_ruleset_version == "temporal-test"
    assert projection.data_sufficiency == "high"


@pytest.mark.asyncio
async def test_cash_flow_projection_covers_past_low_evidence_and_future_paths(monkeypatch):
    class CategoryRows:
        def all(self):
            return []

    class BudgetRows:
        def scalars(self):
            return self

        def all(self):
            return []

    class BudgetDB:
        def __init__(self):
            self.results = iter([CategoryRows(), BudgetRows(), CategoryRows(), BudgetRows()])

        async def execute(self, _statement):
            return next(self.results)

    async def today(_db, _user_id):
        return date(2026, 8, 15)

    async def monthly(self, user_id, month, year):
        return (0, 50)

    async def category_mix(self, user_id, month, year, historical_spend):
        return (None, 0, "insufficient_history")

    async def timeline(self, user_id, *, range_start, range_end):
        return SimpleNamespace(ruleset_version="temporal-test", events=[])

    monkeypatch.setattr(intelligence_module, "user_financial_today", today)
    monkeypatch.setattr(IntelligenceService, "monthly_income_spend", monthly)
    monkeypatch.setattr(IntelligenceService, "_category_mix_baseline", category_mix)
    monkeypatch.setattr(intelligence_module.TemporalEventService, "timeline", timeline)

    past = await IntelligenceService(BudgetDB()).cash_flow_projection(
        "u1", 7, 2026, recurring_patterns=[], historical_periods=[(0, 50)]
    )
    future = await IntelligenceService(BudgetDB()).cash_flow_projection(
        "u1", 9, 2026, recurring_patterns=[], historical_periods=[(0, 50), (0, 80), (0, 100)]
    )

    assert past.days_elapsed == 31
    assert past.interval_calibration == "low_evidence"
    assert past.data_sufficiency == "low"
    assert past.category_mix_status == "not_applicable"
    assert future.days_elapsed == 0
    assert future.projected_spend == 80
    assert future.data_sufficiency == "medium"
    assert future.category_mix_status == "insufficient_history"


@pytest.mark.asyncio
async def test_financial_health_covers_rich_and_empty_quality_states(monkeypatch):
    async def today(_db, _user_id):
        return date(2026, 8, 31)

    async def rich_month(self, user_id, month, year):
        return (2000, 900)

    async def empty_month(self, user_id, month, year):
        return (0, 0)

    async def rich_budget(self, user_id, month, year):
        return 85.0

    async def no_budget(self, user_id, month, year):
        return None

    async def rich_quality(self, user_id, month, year):
        return {
            "transaction_count": 10,
            "parse_confidence": 0.95,
            "merchant_confidence": 0.9,
            "pending_count": 1,
            "conflict_count": 0,
            "latest_transaction_date": date(2026, 8, 29),
            "latest_sync_at": datetime.now(UTC).replace(tzinfo=None),
            "sync_status": "idle",
            "unprocessed_email_count": 0,
        }

    async def empty_quality(self, user_id, month, year):
        return {
            "transaction_count": 0,
            "parse_confidence": 0,
            "merchant_confidence": 0,
            "pending_count": 0,
            "conflict_count": 0,
            "latest_transaction_date": None,
            "latest_sync_at": None,
            "sync_status": "not_connected",
            "unprocessed_email_count": 0,
        }

    async def coverage(self, user_id):
        return SimpleNamespace(overall_score=80, ruleset_version="coverage-test", sources=[])

    monkeypatch.setattr(intelligence_module, "user_financial_today", today)
    monkeypatch.setattr(IntelligenceService, "_data_quality_metrics", rich_quality)
    monkeypatch.setattr(IntelligenceService, "_budget_adherence", rich_budget)
    monkeypatch.setattr(IntelligenceService, "source_coverage", coverage)
    monkeypatch.setattr(IntelligenceService, "monthly_income_spend", rich_month)
    rich = await IntelligenceService(object()).financial_health(
        "u1",
        8,
        2026,
        recurring_patterns=[SimpleNamespace(status="mature", monthly_equivalent=200)],
        historical_periods=[(1800, 700), (1900, 800), (2000, 900), (2100, 1000)],
    )

    monkeypatch.setattr(IntelligenceService, "_data_quality_metrics", empty_quality)
    monkeypatch.setattr(IntelligenceService, "_budget_adherence", no_budget)
    monkeypatch.setattr(IntelligenceService, "monthly_income_spend", empty_month)
    empty = await IntelligenceService(object()).financial_health(
        "u1", 8, 2026, recurring_patterns=[], historical_periods=[]
    )

    assert rich.savings_rate == 55
    assert rich.budget_adherence == 85
    assert rich.data_sufficiency in {"medium", "high"}
    assert any(signal["severity"] == "success" for signal in rich.signals)
    assert empty.score == 0
    assert empty.data_confidence == 0
    assert empty.data_sufficiency == "low"
