from datetime import date
from decimal import Decimal

from app.services.card_refund_tracker_service import build_card_refund_tracker


def test_keeps_pending_refunds_visible_and_bounds_posted_totals_to_recent_evidence():
    tracker = build_card_refund_tracker(
        as_of=date(2026, 8, 20),
        refunds=[
            (date(2026, 8, 18), Decimal("1250"), "pending", "newly_imported"),
            (date(2026, 1, 15), Decimal("900"), "processing", "matched"),
            (date(2026, 8, 10), Decimal("700"), "completed", "matched"),
            (date(2026, 5, 1), Decimal("300"), "completed", "matched"),
        ],
    )

    assert tracker.status == "pending"
    assert tracker.pending_count == 2
    assert tracker.pending_amount == 2150
    assert tracker.oldest_pending_date == date(2026, 1, 15)
    assert tracker.posted_count_90d == 1
    assert tracker.posted_amount_90d == 700
    assert tracker.reason_codes == [
        "pending_refunds",
        "posted_refunds_last_90_days",
    ]
    assert {item.label for item in tracker.evidence} == {
        "Pending refund evidence",
        "Posted refunds (last 90 days)",
    }


def test_marks_unknown_refund_lifecycle_for_review_without_counting_it_as_pending():
    tracker = build_card_refund_tracker(
        as_of=date(2026, 8, 20),
        refunds=[(date(2026, 8, 19), Decimal("500"), "failed", "newly_imported")],
    )

    assert tracker.status == "needs_review"
    assert tracker.pending_count == 0
    assert tracker.pending_amount == 0
    assert tracker.needs_review_count == 1
    assert tracker.reason_codes == ["no_pending_refunds", "refund_lifecycle_review_required"]


def test_ignores_user_excluded_refunds_and_reports_clear_state():
    tracker = build_card_refund_tracker(
        as_of=date(2026, 8, 20),
        refunds=[(date(2026, 8, 19), Decimal("500"), "completed", "ignored_by_rule")],
    )

    assert tracker.status == "clear"
    assert tracker.pending_count == 0
    assert tracker.posted_count_90d == 0
    assert tracker.reason_codes == ["no_pending_refunds"]
    assert tracker.evidence == []
