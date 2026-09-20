"""Deterministic service coverage for daily forecast accountability workflows."""

import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services import balance_forecast_accountability_service as accountability_module
from app.services.balance_forecast_accountability_service import (
    BalanceForecastAccountabilityService,
)


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return self._rows


class _NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _ServiceDb:
    def __init__(self, *, scalar_values=(), scalar_rows=(), execute_rows=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [list(rows) for rows in scalar_rows]
        self.execute_rows = list(execute_rows)
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return _Rows(self.scalar_rows.pop(0) if self.scalar_rows else self.added)

    async def execute(self, _statement):
        return _Rows(self.execute_rows)

    def begin_nested(self):
        return _NestedTransaction()

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = "generated-row"
            if getattr(row, "evaluated_at", None) is None:
                row.evaluated_at = datetime(2026, 9, 20, 12, 0)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        _row.created_at = datetime(2026, 9, 20, 12, 0)


def _snapshot(*, snapshot_id="snapshot-1", points=(), cutoff=date(2026, 9, 19)):
    return SimpleNamespace(
        id=snapshot_id,
        financial_account_id="account-1",
        currency="INR",
        balance_kind="asset",
        cutoff_date=cutoff,
        horizon_start=cutoff,
        horizon_end=date(2026, 9, 22),
        horizon_days=3,
        forecast_ruleset_version="forecast-1",
        status="ready",
        starting_balance=Decimal("1000"),
        starting_balance_as_of=cutoff,
        starting_balance_basis="observed",
        expected_ending_balance=Decimal("950"),
        expected_change=Decimal("-50"),
        lowest_expected_balance=Decimal("950"),
        lowest_expected_date=date(2026, 9, 22),
        first_shortfall_date=None,
        event_count=0,
        historical_days=30,
        historical_activity_count=2,
        coverage_status="fresh",
        position_status="observed",
        position_confidence=Decimal("0.9"),
        confidence=Decimal("0.8"),
        data_sufficiency="medium",
        position_reason_codes_json="[]",
        evidence_json="[]",
        assumptions_json="[]",
        points_json=json.dumps(points),
        created_at=datetime(2026, 9, 19, 12, 0),
    )


def _point(target_date, *, expected=100, low=90, high=110, risk="watch"):
    return {
        "date": target_date.isoformat(),
        "expected_balance": expected,
        "low_balance": low,
        "high_balance": high,
        "scheduled_increase": 0,
        "scheduled_decrease": 0,
        "baseline_increase": 0,
        "baseline_decrease": 0,
        "event_count": 0,
        "evidence_ids": [],
        "risk": risk,
        "risk_reasons": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cutoff_date", "message"),
    [
        (date(2026, 9, 21), "Forecast snapshot cutoff cannot be in the future"),
        (date(2025, 9, 19), "Forecast snapshot cutoff cannot be more than 365 days old"),
    ],
)
async def test_create_snapshot_rejects_invalid_cutoff_dates(monkeypatch, cutoff_date, message):
    db = _ServiceDb(scalar_values=[SimpleNamespace(), SimpleNamespace()])

    async def fake_today(_db, user_id):
        assert user_id == "user-1"
        return date(2026, 9, 20)

    monkeypatch.setattr(accountability_module, "user_financial_today", fake_today)

    with pytest.raises(ValueError, match=message):
        await BalanceForecastAccountabilityService(db).create_snapshot(
            "user-1",
            "account-1",
            SimpleNamespace(cutoff_date=cutoff_date, horizon_days=3),
        )


@pytest.mark.asyncio
async def test_create_snapshot_persists_forecast_and_returns_existing_snapshot(monkeypatch):
    today = date(2026, 9, 20)
    point = _point(date(2026, 9, 21))
    forecast = SimpleNamespace(
        currency="INR",
        balance_kind="asset",
        horizon_start=today - date.resolution,
        horizon_end=date(2026, 9, 21),
        horizon_days=1,
        ruleset_version="forecast-1",
        status="ready",
        starting_balance=1000,
        starting_balance_as_of=today - date.resolution,
        starting_balance_basis="observed",
        expected_ending_balance=990,
        expected_change=-10,
        lowest_expected_balance=990,
        lowest_expected_date=date(2026, 9, 21),
        first_shortfall_date=None,
        event_count=1,
        historical_days=30,
        historical_activity_count=2,
        coverage_status="fresh",
        position_status="observed",
        position_confidence=0.9,
        confidence=0.8,
        data_sufficiency="medium",
        position_reason_codes=["verified"],
        evidence=[],
        assumptions=["Stable balance"],
        points=[SimpleNamespace(model_dump=lambda mode: point)],
    )
    db = _ServiceDb(scalar_values=[SimpleNamespace(), SimpleNamespace()])

    async def fake_today(_db, _user_id):
        return today

    async def fake_forecast(self, user_id, account_id, *, horizon_days, as_of):
        assert (user_id, account_id, horizon_days, as_of) == (
            "user-1",
            "account-1",
            1,
            today - date.resolution,
        )
        return forecast

    existing = _snapshot(points=[point], cutoff=today - date.resolution)
    find_calls = []

    async def fake_find(*args, **kwargs):
        find_calls.append((args, kwargs))
        return None if len(find_calls) == 1 else existing

    monkeypatch.setattr(accountability_module, "user_financial_today", fake_today)
    monkeypatch.setattr(accountability_module.BalanceForecastService, "forecast", fake_forecast)
    monkeypatch.setattr(BalanceForecastAccountabilityService, "_find_snapshot", fake_find)

    service = BalanceForecastAccountabilityService(db)
    created = await service.create_snapshot(
        "user-1",
        "account-1",
        SimpleNamespace(cutoff_date=today - date.resolution, horizon_days=1),
    )

    assert created.id == "generated-row"
    assert db.commits == 1
    assert db.added[0].points_json == json.dumps([point], sort_keys=True, separators=(",", ":"))

    reused = await service.create_snapshot(
        "user-1",
        "account-1",
        SimpleNamespace(cutoff_date=today - date.resolution, horizon_days=1),
    )
    assert reused.id == "snapshot-1"
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_evaluate_handles_empty_and_pending_existing_and_observed_points(monkeypatch):
    today = date(2026, 9, 23)
    observed_date = date(2026, 9, 20)
    missing_date = date(2026, 9, 21)
    cutoff = date(2026, 9, 19)
    points = [
        _point(cutoff),
        _point(observed_date, expected=100, low=90, high=110),
        _point(missing_date, expected=None, low=None, high=None, risk="none"),
        _point(date(2026, 9, 22)),
    ]
    snapshot = _snapshot(points=points, cutoff=cutoff)
    existing = SimpleNamespace(snapshot_id=snapshot.id, target_date=date(2026, 9, 22))
    observation = SimpleNamespace(
        id="observation-1", amount=Decimal("105"), source="manual", as_of=observed_date
    )
    db = _ServiceDb(
        scalar_values=[SimpleNamespace()],
        scalar_rows=[[snapshot], [existing], [observation]],
    )

    async def fake_today(_db, _user_id):
        return today

    monkeypatch.setattr(accountability_module, "user_financial_today", fake_today)
    result = await BalanceForecastAccountabilityService(db).evaluate("user-1", "account-1")

    assert result.evaluated_count == 1
    assert result.already_evaluated_count == 1
    assert result.pending_count == 1
    assert result.interval_coverage_pct == 100
    assert result.mean_absolute_error == 5
    assert result.median_absolute_percentage_error == 5
    assert result.calibration_status == "insufficient_sample"
    assert result.outcomes[0].actual_balance == 105
    assert result.outcomes[0].interval_covered is True
    assert db.commits == 1


@pytest.mark.asyncio
async def test_evaluate_returns_empty_report_without_snapshots(monkeypatch):
    db = _ServiceDb(scalar_values=[SimpleNamespace()], scalar_rows=[[]])

    async def fake_today(_db, _user_id):
        return date(2026, 9, 20)

    monkeypatch.setattr(accountability_module, "user_financial_today", fake_today)
    result = await BalanceForecastAccountabilityService(db).evaluate("user-1", "account-1")

    assert result.evaluated_count == 0
    assert result.pending_count == 0
    assert result.outcomes == []
    assert result.interval_coverage_pct is None


@pytest.mark.asyncio
async def test_list_outcomes_serializes_joined_rows():
    snapshot = _snapshot(points=[])
    outcome = SimpleNamespace(
        id="outcome-1",
        financial_account_id="account-1",
        target_date=date(2026, 9, 20),
        actual_observation_id="observation-1",
        actual_source="manual",
        actual_balance=Decimal("105"),
        expected_balance=Decimal("100"),
        low_balance=None,
        high_balance=None,
        signed_error=Decimal("5"),
        absolute_error=Decimal("5"),
        interval_covered=None,
        predicted_risk="none",
        outcome_ruleset_version="outcome-1",
        evaluated_at=datetime(2026, 9, 20, 12, 0),
    )
    db = _ServiceDb(execute_rows=[(outcome, snapshot)])

    results = await BalanceForecastAccountabilityService(db).list_outcomes("user-1", "account-1")

    assert len(results) == 1
    assert results[0].id == "outcome-1"
    assert results[0].low_balance is None
    assert results[0].interval_covered is None
