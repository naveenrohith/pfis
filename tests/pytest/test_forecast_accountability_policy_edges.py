"""Pure calibration and serialization coverage for daily forecast accountability."""

import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.schemas.balance_forecast import AccountBalanceForecastPoint
from app.services.balance_forecast_accountability_service import (
    BalanceForecastAccountabilityService,
)


@pytest.mark.parametrize(
    ("actual", "expected", "result"),
    [
        (Decimal("100"), Decimal("0"), None),
        (Decimal("110"), Decimal("100"), 10.0),
        (Decimal("90"), Decimal("100"), 10.0),
    ],
)
def test_forecast_accountability_percentage_error_handles_zero_and_signed_error(
    actual: Decimal, expected: Decimal, result: float | None
):
    assert BalanceForecastAccountabilityService._percentage_error(actual, expected) == result


def test_forecast_accountability_median_and_calibration_states_are_deterministic():
    assert BalanceForecastAccountabilityService._median([]) is None
    assert BalanceForecastAccountabilityService._median([3.0, 1.0, 2.0]) == 2.0
    assert BalanceForecastAccountabilityService._median([4.0, 1.0, 2.0, 3.0]) == 2.5
    assert (
        BalanceForecastAccountabilityService._calibration_status(2, 1.0, 100.0)
        == "insufficient_sample"
    )
    assert BalanceForecastAccountabilityService._calibration_status(3, 21.0, 100.0) == "drift"
    assert BalanceForecastAccountabilityService._calibration_status(3, 10.0, 69.0) == "drift"
    assert (
        BalanceForecastAccountabilityService._calibration_status(3, 10.0, 70.0)
        == "within_threshold"
    )
    thresholds = BalanceForecastAccountabilityService._calibration_thresholds()
    assert thresholds == {
        "maximum_median_absolute_percentage_error_pct": 20.0,
        "minimum_interval_coverage_pct": 70.0,
        "minimum_outcomes": 3.0,
    }


def test_forecast_accountability_response_serializers_keep_optional_fields_typed():
    point = AccountBalanceForecastPoint(
        date=date(2026, 9, 20),
        expected_balance=100.0,
        low_balance=90.0,
        high_balance=110.0,
        risk="watch",
    )
    created_at = datetime(2026, 9, 19, 12, 0)
    snapshot = SimpleNamespace(
        id="snapshot-1",
        financial_account_id="account-1",
        currency="INR",
        balance_kind="asset",
        cutoff_date=date(2026, 9, 19),
        horizon_start=date(2026, 9, 19),
        horizon_end=date(2026, 9, 20),
        horizon_days=1,
        forecast_ruleset_version="forecast-1",
        status="ready",
        starting_balance=Decimal("100"),
        starting_balance_as_of=date(2026, 9, 19),
        starting_balance_basis="observed",
        expected_ending_balance=Decimal("100"),
        expected_change=Decimal("0"),
        lowest_expected_balance=Decimal("100"),
        lowest_expected_date=date(2026, 9, 19),
        first_shortfall_date=None,
        event_count=0,
        historical_days=180,
        historical_activity_count=3,
        coverage_status="fresh",
        position_status="observed",
        position_confidence=Decimal("0.9"),
        confidence=Decimal("0.8"),
        data_sufficiency="medium",
        position_reason_codes_json=json.dumps(["verified"]),
        evidence_json=json.dumps([{"label": "Anchor", "value": "100"}]),
        assumptions_json=json.dumps(["Evidence labelled"]),
        points_json=json.dumps([point.model_dump(mode="json")]),
        created_at=created_at,
    )
    response = BalanceForecastAccountabilityService._snapshot_response(snapshot)
    assert response.id == "snapshot-1"
    assert response.starting_balance == 100
    assert response.evidence[0].label == "Anchor"
    assert response.points[0].risk == "watch"

    outcome = SimpleNamespace(
        id="outcome-1",
        financial_account_id="account-1",
        target_date=date(2026, 9, 20),
        actual_observation_id="observation-1",
        actual_source="manual",
        actual_balance=Decimal("105"),
        expected_balance=Decimal("100"),
        low_balance=Decimal("90"),
        high_balance=Decimal("110"),
        signed_error=Decimal("5"),
        absolute_error=Decimal("5"),
        interval_covered=True,
        predicted_risk="watch",
        outcome_ruleset_version="outcome-1",
        evaluated_at=created_at,
    )
    outcome_response = BalanceForecastAccountabilityService._outcome_response(outcome, snapshot)
    assert outcome_response.snapshot_id == "snapshot-1"
    assert outcome_response.actual_balance == 105
    assert outcome_response.interval_covered is True
    assert outcome_response.forecast_ruleset_version == "forecast-1"


def test_forecast_accountability_decimal_helpers_preserve_none():
    assert BalanceForecastAccountabilityService._decimal("12.50") == Decimal("12.50")
    assert BalanceForecastAccountabilityService._decimal_or_none("12.50") == Decimal("12.50")
    assert BalanceForecastAccountabilityService._decimal_or_none(None) is None
