"""Golden cases for deterministic PFIS knowledge rules."""

from datetime import date

from app.services.knowledge.recurring_knowledge import RecurringPatternService


def _pattern(dates: list[date], amounts: list[float] | None = None):
    values = amounts or [499.0] * len(dates)
    return RecurringPatternService._analyze_group(
        "Example Merchant", list(zip(dates, values, strict=True)), dates[-1]
    )


def test_weekly_stream_starts_as_early_signal():
    pattern = _pattern([date(2026, 7, 1), date(2026, 7, 8)])
    assert pattern is not None
    assert pattern.cadence == "weekly"
    assert pattern.status == "early"
    assert pattern.next_expected_date == date(2026, 7, 15)


def test_monthly_stream_becomes_mature_with_evidence():
    pattern = _pattern([date(2026, 4, 15), date(2026, 5, 15), date(2026, 6, 15), date(2026, 7, 15)])
    assert pattern is not None
    assert pattern.cadence == "monthly"
    assert pattern.status == "mature"
    assert pattern.confidence >= 0.8
    assert pattern.data_sufficiency == "high"
    signal = pattern.as_dict()["signal"]
    assert signal["kind"] == "recurring_pattern"
    assert signal["ruleset"]["version"] == "pfis-recurring-4"
    assert signal["sample_size"] == 4


def test_annual_stream_is_supported_without_monthly_misclassification():
    pattern = _pattern([date(2024, 3, 1), date(2025, 3, 1), date(2026, 3, 1)])
    assert pattern is not None
    assert pattern.cadence == "annual"
    assert pattern.status == "mature"


def test_irregular_timing_is_not_promoted_to_recurring():
    pattern = _pattern([date(2026, 4, 1), date(2026, 4, 4), date(2026, 5, 24)])
    assert pattern is not None
    assert pattern.cadence is None
    assert pattern.status == "candidate"


def test_same_day_purchases_are_not_a_recurring_stream():
    pattern = _pattern([date(2026, 7, 1), date(2026, 7, 1)])
    assert pattern is None


def test_variable_monthly_bill_keeps_cadence_and_lower_amount_confidence():
    pattern = _pattern(
        [date(2026, 4, 2), date(2026, 5, 2), date(2026, 6, 2), date(2026, 7, 2)],
        [900.0, 1400.0, 1050.0, 1600.0],
    )
    assert pattern is not None
    assert pattern.cadence == "monthly"
    assert pattern.cadence_confidence > pattern.amount_confidence
    assert pattern.amount_low == 900.0
    assert pattern.amount_high == 1600.0
    assert pattern.as_dict()["signal"]["value"]["amount_low"] == 900.0


def test_variable_monthly_intervals_expose_a_bounded_next_date_window():
    pattern = _pattern(
        [date(2026, 4, 1), date(2026, 4, 29), date(2026, 5, 31), date(2026, 6, 30)]
    )

    assert pattern is not None
    assert pattern.cadence == "monthly"
    assert pattern.next_expected_date == date(2026, 7, 30)
    assert pattern.next_expected_date_low == date(2026, 7, 28)
    assert pattern.next_expected_date_high == date(2026, 8, 1)
    assert pattern.as_dict()["next_expected_date_low"] == "2026-07-28"


def test_monthly_recurrence_preserves_calendar_day_at_month_end():
    pattern = _pattern([date(2026, 1, 30), date(2026, 2, 28), date(2026, 3, 30)])

    assert pattern is not None
    assert pattern.cadence == "monthly"
    assert pattern.next_expected_date == date(2026, 4, 30)
