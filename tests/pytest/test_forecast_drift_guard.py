"""Deterministic forecast drift guard threshold tests."""

from app.services.forecast_drift_guard import (
    FORECAST_DRIFT_REASON_CODE,
    ForecastDriftGuard,
)


def test_drift_guard_requires_minimum_evidence_before_healthy():
    status = ForecastDriftGuard._status_from_groups({"30d": [(5.0, True), (7.0, True)]})

    assert status.status == "insufficient_evidence"
    assert status.reason_code == FORECAST_DRIFT_REASON_CODE
    assert status.horizons[0].status == "insufficient_evidence"


def test_drift_guard_marks_degraded_on_mape_or_interval_undercoverage():
    status = ForecastDriftGuard._status_from_groups(
        {
            "7d": [(25.0, True), (22.0, True), (18.0, True)],
            "30d": [(5.0, False), (7.0, False), (6.0, True)],
        }
    )

    assert status.status == "degraded"
    by_horizon = {item.horizon: item for item in status.horizons}
    assert by_horizon["7d"].status == "degraded"
    assert by_horizon["30d"].status == "degraded"
    assert by_horizon["30d"].interval_coverage_pct == 33.33


def test_drift_guard_marks_healthy_only_when_all_mature_horizons_pass():
    status = ForecastDriftGuard._status_from_groups(
        {"14d": [(5.0, True), (8.0, True), (10.0, True)]}
    )

    assert status.status == "healthy"
    assert status.horizons[0].mean_absolute_percentage_error == 7.67
