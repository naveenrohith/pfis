from datetime import date
from decimal import Decimal

from app.services.card_statement_projection_service import (
    CardRecurringChargeCandidate,
    build_card_statement_projection,
)


def test_projects_current_cycle_with_range_confidence_and_action():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("24000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[
            Decimal("4000"),
            Decimal("3000"),
            Decimal("2000"),
            Decimal("-1000"),
        ],
        utilization_target_pct=Decimal("25"),
    )

    assert projection.status == "available"
    assert projection.projected_statement_date == date(2026, 9, 5)
    assert projection.projected_balance == 32533.33
    assert projection.range_low == 27200.0
    assert projection.range_high == 37866.67
    assert projection.projected_utilization_pct == 32.5
    assert projection.confidence == 0.79
    assert projection.next_state == "reduce_spend_or_pay"
    assert projection.target_status == "over_target"
    assert projection.target_headroom_amount == 0
    assert projection.target_excess_amount == 7533.33
    assert projection.target_breach_date == date(2026, 8, 22)
    assert projection.target_breach_days == 2
    assert projection.credit_limit_status == "under_limit"
    assert projection.credit_limit_headroom_amount == 67466.67
    assert projection.credit_limit_excess_amount == 0
    assert projection.credit_limit_breach_date is None
    assert projection.credit_limit_breach_days is None
    assert "utilization_target_exceeded" in projection.reason_codes
    assert "credit_limit_headroom" in projection.reason_codes
    assert len(projection.evidence) == 8
    assert "uncertainty_band_not_guarantee" in projection.reason_codes


def test_fails_closed_when_latest_statement_cycle_has_expired():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 6, 5),
        period_start=date(2026, 5, 6),
        period_end=date(2026, 6, 5),
        current_balance=Decimal("24000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 4,
        utilization_target_pct=Decimal("25"),
    )

    assert projection.status == "needs_recent_statement"
    assert projection.projected_balance is None
    assert projection.next_state == "review_evidence"
    assert projection.reason_codes == ["statement_cycle_is_not_current"]


def test_fails_closed_without_enough_cycle_activity():
    projection = build_card_statement_projection(
        today=date(2026, 8, 10),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("24000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000"), Decimal("500")],
        utilization_target_pct=None,
    )

    assert projection.status == "needs_activity"
    assert projection.confidence == 0
    assert projection.projected_statement_date == date(2026, 9, 5)


def test_blends_prior_cycles_and_subtracts_a_planned_payment_as_explicit_evidence():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("24000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[
            Decimal("4000"),
            Decimal("3000"),
            Decimal("2000"),
            Decimal("-1000"),
        ],
        utilization_target_pct=Decimal("25"),
        historical_daily_paces=[Decimal("300"), Decimal("400")],
        future_planned_payments=[(date(2026, 8, 30), Decimal("2000"))],
        future_scheduled_charges=[(date(2026, 8, 28), Decimal("1200"), "emi-1")],
    )

    assert projection.status == "available"
    assert projection.calibration == "historical_blend"
    assert projection.historical_sample_count == 2
    assert projection.known_future_payment_total == 2000
    assert projection.known_future_charge_total == 1200
    assert projection.projected_balance == 30853.33
    assert projection.projected_utilization_pct == 30.9
    assert projection.confidence == 0.84
    assert "historical_pace_blended" in projection.reason_codes
    assert {item.label for item in projection.evidence} >= {
        "Historical pace calibration",
        "Planned payment before close",
        "Scheduled card charges",
        "Utilization target runway",
    }


def test_marks_target_at_risk_when_only_the_uncertainty_band_crosses_it():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("23000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("500")] * 3,
        utilization_target_pct=Decimal("25"),
    )

    assert projection.projected_balance == 24600
    assert projection.range_high == 25400
    assert projection.target_status == "at_risk"
    assert projection.target_headroom_amount == 400
    assert projection.target_excess_amount == 0
    assert projection.target_breach_date is None
    assert projection.target_breach_days is None
    assert "utilization_target_at_risk" in projection.reason_codes


def test_reports_headroom_when_projected_close_stays_below_target():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("10000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=Decimal("25"),
    )

    assert projection.target_status == "under_target"
    assert projection.target_headroom_amount == 11800
    assert projection.target_excess_amount == 0
    assert projection.target_breach_date is None
    assert projection.target_breach_days is None
    assert "utilization_target_headroom" in projection.reason_codes


def test_adds_bounded_recurring_card_charge_candidates_with_uncertainty_evidence():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("10000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=None,
        future_recurring_charges=[
            CardRecurringChargeCandidate(
                expected_date=date(2026, 8, 28),
                amount=Decimal("899"),
                merchant="STREAMCO",
                cadence="monthly",
                occurrences=4,
                confidence=Decimal("0.86"),
            ),
            CardRecurringChargeCandidate(
                expected_date=date(2026, 9, 20),
                amount=Decimal("500"),
                merchant="OUTSIDE WINDOW",
                cadence="monthly",
                occurrences=4,
                confidence=Decimal("0.95"),
            ),
        ],
    )

    assert projection.status == "available"
    assert projection.projected_balance == 14099
    assert projection.known_future_recurring_charge_total == 899
    assert [item.merchant for item in projection.recurring_charge_candidates] == ["STREAMCO"]
    assert "recurring_charge_candidates_included" in projection.reason_codes
    assert {item.label for item in projection.evidence} >= {"Recurring charge candidates"}
    assert projection.ruleset_version == "pfis-card-statement-projection-9"


def test_bounded_recurring_amount_drift_only_widens_range_not_central_estimate():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("10000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=None,
        future_recurring_charges=[
            CardRecurringChargeCandidate(
                expected_date=date(2026, 8, 28),
                amount=Decimal("1000"),
                amount_low=Decimal("700"),
                amount_high=Decimal("1300"),
                merchant="VARIABLE BILL",
                cadence="monthly",
                occurrences=4,
                confidence=Decimal("0.80"),
            )
        ],
    )

    assert projection.projected_balance == 14200
    assert projection.range_low == 12100
    assert projection.range_high == 16300
    candidate = projection.recurring_charge_candidates[0]
    assert candidate.expected_amount == 1000
    assert candidate.expected_amount_low == 700
    assert candidate.expected_amount_high == 1300
    assert "recurring_amount_variability_uncertainty" in projection.reason_codes
    assert {item.label for item in projection.evidence} >= {"Recurring amount variability"}


def test_bounded_recurring_timing_window_preserves_central_path():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("10000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=None,
        future_recurring_charges=[
            CardRecurringChargeCandidate(
                expected_date=date(2026, 8, 28),
                expected_date_low=date(2026, 8, 26),
                expected_date_high=date(2026, 8, 30),
                amount=Decimal("1000"),
                merchant="VARIABLE TIMING",
                cadence="monthly",
                occurrences=4,
                confidence=Decimal("0.80"),
            )
        ],
    )

    assert projection.projected_balance == 14200
    candidate = projection.recurring_charge_candidates[0]
    assert candidate.expected_date == date(2026, 8, 28)
    assert candidate.expected_date_low == date(2026, 8, 26)
    assert candidate.expected_date_high == date(2026, 8, 30)
    assert "recurring_date_variability_observed" in projection.reason_codes
    assert {item.label for item in projection.evidence} >= {"Recurring timing envelope"}


def test_pending_refund_only_expands_lower_bound_and_never_changes_central_estimate():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("10000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=None,
        pending_refund_amount=Decimal("750"),
    )

    assert projection.projected_balance == 13200
    assert projection.range_low == 10850
    assert projection.range_high == 14800
    assert projection.potential_pending_refund_total == 750
    assert "pending_refund_credit_uncertainty" in projection.reason_codes
    assert {item.label for item in projection.evidence} >= {"Pending refund potential credit"}


def test_calendar_spending_profile_refines_future_day_without_overriding_current_pace():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("10000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=None,
        historical_cycle_movements=[
            (
                date(2026, 5, 6),
                date(2026, 6, 5),
                [
                    (date(2026, 5, 10), Decimal("500")),
                    (date(2026, 5, 16), Decimal("500")),
                    (date(2026, 5, 30), Decimal("2000")),
                ],
            ),
            (
                date(2026, 6, 6),
                date(2026, 7, 5),
                [
                    (date(2026, 6, 10), Decimal("500")),
                    (date(2026, 6, 16), Decimal("500")),
                    (date(2026, 6, 30), Decimal("3000")),
                ],
            ),
        ],
    )

    assert projection.status == "available"
    assert projection.projected_balance == 14005
    assert projection.seasonal_sample_count == 2
    assert projection.seasonal_days_covered == 1
    assert "calendar_spending_seasonality_blended" in projection.reason_codes
    assert "calendar_spending_seasonality_uncertainty" in projection.reason_codes
    assert {item.label for item in projection.evidence} >= {"Calendar spending pattern"}


def test_daily_path_labels_known_events_and_runs_through_projected_close():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 5),
        period_start=date(2026, 7, 6),
        period_end=date(2026, 8, 5),
        current_balance=Decimal("10000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=None,
        future_planned_payments=[(date(2026, 8, 22), Decimal("500"))],
        future_scheduled_charges=[(date(2026, 8, 24), Decimal("1200"), "Card EMI")],
        future_recurring_charges=[
            CardRecurringChargeCandidate(
                expected_date=date(2026, 8, 28),
                amount=Decimal("899"),
                merchant="STREAMCO",
                cadence="monthly",
                occurrences=4,
                confidence=Decimal("0.86"),
            )
        ],
    )

    assert len(projection.daily_path) == 16
    assert projection.daily_path[0].date == date(2026, 8, 21)
    assert projection.daily_path[-1].date == projection.projected_statement_date
    assert projection.daily_path[0].projected_balance == 10200
    assert (
        next(
            point for point in projection.daily_path if point.date == date(2026, 8, 22)
        ).event_amount
        == -500
    )
    assert next(
        point for point in projection.daily_path if point.date == date(2026, 8, 24)
    ).event_labels == ["Scheduled: Card EMI"]
    assert next(
        point for point in projection.daily_path if point.date == date(2026, 8, 28)
    ).event_labels == ["Recurring: STREAMCO"]
    assert "daily_projection_path" in projection.reason_codes


def test_credit_limit_runway_reports_central_breach_and_daily_pressure():
    projection = build_card_statement_projection(
        today=date(2026, 8, 20),
        statement_date=date(2026, 8, 15),
        period_start=date(2026, 7, 16),
        period_end=date(2026, 8, 15),
        current_balance=Decimal("95000"),
        credit_limit=Decimal("100000"),
        balance_confidence=0.9,
        eligible_movements=[Decimal("1000")] * 3,
        utilization_target_pct=None,
    )

    assert projection.credit_limit_status == "over_limit"
    assert projection.credit_limit_headroom_amount == 0
    assert projection.credit_limit_excess_amount == 10600
    assert projection.credit_limit_breach_date == date(2026, 8, 29)
    assert projection.credit_limit_breach_days == 9
    assert projection.next_state == "reduce_spend_or_pay"
    assert "credit_limit_exceeded" in projection.reason_codes
    assert next(
        point for point in projection.daily_path if point.date == date(2026, 8, 29)
    ).credit_limit_status == "over_limit"
    assert {
        item.label for item in projection.evidence
    } >= {"Credit-limit runway", "Central credit-limit breach timing"}
