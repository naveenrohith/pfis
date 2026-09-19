"""Focused evidence-gate tests for the product readiness contract."""

import pytest
from app.schemas.operational import ForecastReadiness
from app.services.intelligence_readiness_service import IntelligenceReadinessService

from tests.pytest.helpers import create_user


def _forecast(**overrides: object) -> ForecastReadiness:
    values: dict[str, object] = {
        "evaluated_months": 6,
        "eligible_horizons": 3,
        "interval_coverage_floor_pct": 80.0,
        "maximum_mape_pct": 10.0,
        "temporal_evidence_evaluated": True,
        "transaction_history_coverage_pct": 100.0,
        "daily_snapshot_count": 4,
        "daily_outcome_count": 0,
    }
    values.update(overrides)
    return ForecastReadiness.model_validate(values)


def test_forecast_gate_waits_for_prospective_daily_outcomes() -> None:
    gate = IntelligenceReadinessService._forecast_gate(_forecast())

    assert gate.status == "collecting"
    assert "three exact-date verified daily outcomes" in gate.next_step
    assert "0 exact-date outcome(s)" in gate.summary


def test_forecast_gate_reports_daily_interval_coverage() -> None:
    gate = IntelligenceReadinessService._forecast_gate(
        _forecast(
            daily_outcome_count=3,
            daily_interval_coverage_pct=66.67,
            daily_mean_absolute_error=125.0,
        )
    )

    assert gate.status == "blocked"
    assert "Daily interval coverage: 66.67" in gate.evidence
    assert "Daily mean absolute error: 125.0" in gate.evidence


@pytest.mark.asyncio
async def test_readiness_endpoint_exposes_daily_accountability(client) -> None:
    user = await create_user(client, "readiness-daily-accountability")

    response = await client.get(f"/api/analytics/intelligence-readiness?user_id={user['id']}")

    assert response.status_code == 200
    forecast = response.json()["forecast"]
    assert forecast["daily_snapshot_count"] == 0
    assert forecast["daily_outcome_count"] == 0
    assert forecast["daily_interval_coverage_pct"] is None
    assert forecast["daily_mean_absolute_error"] is None
