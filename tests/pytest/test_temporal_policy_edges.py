"""Pure policy coverage for temporal event normalization and state mapping."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.transaction import Transaction, TransactionType
from app.schemas.temporal import TemporalAmount
from app.services.knowledge.recurring_knowledge import RecurringPattern
from app.services.temporal_event_service import TemporalEventService


def test_temporal_snapshot_helpers_fail_closed_and_preserve_exact_amounts():
    assert TemporalEventService._snapshot_date(date(2026, 9, 19)) == date(2026, 9, 19)
    assert TemporalEventService._snapshot_date("2026-09-19") == date(2026, 9, 19)
    assert TemporalEventService._snapshot_date("not-a-date") is None
    assert TemporalEventService._snapshot_date(42) is None

    assert TemporalEventService._snapshot_amount(None) == TemporalAmount()
    assert TemporalEventService._snapshot_amount("125.50") == TemporalAmount(
        low=125.5, expected=125.5, high=125.5
    )
    assert TemporalEventService._snapshot_amount("invalid") == TemporalAmount()
    assert TemporalEventService._snapshot_float(None) is None
    assert TemporalEventService._snapshot_float("12.50") == 12.5
    assert TemporalEventService._snapshot_float("invalid") is None
    assert TemporalEventService._exact_amount(Decimal("80.25")) == TemporalAmount(
        low=80.25, expected=80.25, high=80.25
    )
    assert TemporalEventService._exact_amount(None) == TemporalAmount()


def test_temporal_date_and_evidence_helpers_are_timezone_and_state_aware():
    as_of = date(2026, 9, 19)
    assert TemporalEventService._dated_state(as_of - timedelta(days=1), as_of) == "overdue"
    assert TemporalEventService._dated_state(as_of, as_of) == "expected"
    assert TemporalEventService._pattern_tolerance("weekly") == 2
    assert TemporalEventService._pattern_tolerance("fortnightly") == 3
    assert TemporalEventService._pattern_tolerance("monthly") == 5
    assert TemporalEventService._pattern_tolerance("quarterly") == 10
    assert TemporalEventService._pattern_tolerance("annual") == 20
    assert TemporalEventService._pattern_tolerance(None) == 5
    evidence = TemporalEventService._evidence("bill", "bill-1", "definition")
    assert evidence.source_id == "bill-1"
    assert evidence.role == "definition"

    utc_value = datetime(2026, 9, 19, 23, 30, tzinfo=UTC)
    assert TemporalEventService._financial_date(utc_value, "Asia/Kolkata") == date(2026, 9, 20)
    assert TemporalEventService._financial_date(datetime(2026, 9, 19, 23, 30), "UTC") == date(
        2026, 9, 19
    )


@pytest.mark.parametrize(
    ("seed", "cadence", "start", "end", "expected"),
    [
        (date(2026, 9, 10), None, date(2026, 9, 1), date(2026, 9, 20), [date(2026, 9, 10)]),
        (date(2026, 9, 10), None, date(2026, 9, 11), date(2026, 9, 20), []),
        (
            date(2026, 9, 1),
            "weekly",
            date(2026, 9, 10),
            date(2026, 9, 25),
            [date(2026, 9, 15), date(2026, 9, 22)],
        ),
        (
            date(2026, 1, 31),
            "monthly",
            date(2026, 2, 1),
            date(2026, 4, 30),
            [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)],
        ),
        (
            date(2026, 1, 31),
            "quarterly",
            date(2026, 2, 1),
            date(2026, 10, 31),
            [date(2026, 4, 30), date(2026, 7, 31), date(2026, 10, 31)],
        ),
        (
            date(2024, 2, 29),
            "annual",
            date(2025, 1, 1),
            date(2027, 3, 1),
            [date(2025, 2, 28), date(2026, 2, 28), date(2027, 2, 28)],
        ),
    ],
)
def test_temporal_occurrences_cover_supported_cadences(
    seed: date, cadence: str | None, start: date, end: date, expected: list[date]
):
    assert TemporalEventService._occurrences(seed, cadence, start, end) == expected


def test_temporal_advance_and_event_helpers_keep_month_end_and_bounds():
    assert TemporalEventService._advance_by(date(2026, 9, 19), "weekly", 2) == date(2026, 10, 3)
    assert TemporalEventService._advance_by(date(2026, 1, 31), "monthly", 1) == date(2026, 2, 28)
    assert TemporalEventService._advance_by(date(2026, 1, 31), "quarterly", 1) == date(2026, 4, 30)
    assert TemporalEventService._advance_by(date(2026, 2, 28), "annual", 1) == date(2027, 2, 28)

    event = TemporalEventService._event(
        user_id="user-1",
        source_type="bill",
        source_id="bill-1",
        occurrence_date=date(2026, 9, 20),
        kind="bill",
        direction="outflow",
        state="expected",
        label="Electricity",
        currency="INR",
        amount=TemporalAmount(low=10, expected=12, high=14),
        confidence=1.4,
        sufficiency="high",
        evidence=[],
        as_of=date(2026, 9, 19),
    )
    assert event.confidence == 1.0
    assert event.window_start == event.expected_date
    assert event.window_end == event.expected_date


@pytest.mark.parametrize(
    ("status", "expected_state", "expected_label", "has_observation"),
    [
        ("recorded", "observed", "Recorded card payment · confirmed", True),
        ("cancelled", "cancelled", "Cancelled card payment", False),
        ("planned", "expected", "Card payment", False),
    ],
)
def test_card_payment_intent_events_preserve_lifecycle_status(
    status: str, expected_state: str, expected_label: str, has_observation: bool
):
    event = TemporalEventService(None)._card_payment_intent_event(
        user_id="user-1",
        currency="INR",
        source_id=f"intent-{status}",
        planned_for=date(2026, 9, 20),
        amount=Decimal("1250"),
        status=status,
        note="confirmed" if status == "recorded" else "",
        transfer_group_id="transfer-1" if status == "recorded" else None,
        as_of=date(2026, 9, 19),
    )
    assert event.state == expected_state
    assert event.label == expected_label
    assert event.observation is not None if has_observation else event.observation is None
    assert event.evidence[0].role == (
        "explicit_observation" if status in {"recorded", "cancelled"} else "definition"
    )


def _pattern(*, status: str, expected_date: date | None, stream_key: str) -> RecurringPattern:
    return RecurringPattern(
        merchant=f"Pattern {stream_key}",
        occurrences=4,
        avg_amount=100.0,
        amount_low=95.0,
        amount_high=105.0,
        monthly_equivalent=100.0,
        cadence="monthly",
        median_interval_days=30.0,
        cadence_confidence=0.9,
        amount_confidence=0.8,
        confidence=0.85,
        status=status,
        last_seen=date(2026, 8, 20),
        next_expected_date=expected_date,
        next_expected_date_low=expected_date,
        next_expected_date_high=expected_date,
        data_sufficiency="high",
        currency="INR",
        stream_key=stream_key,
        source_transaction_ids=(f"txn-{stream_key}",),
    )


def test_temporal_pattern_events_map_supported_lifecycles_and_skip_unsafe_patterns():
    service = TemporalEventService(None)
    as_of = date(2026, 9, 19)
    events = service._pattern_events(
        "user-1",
        [
            _pattern(status="early", expected_date=date(2026, 9, 20), stream_key="early"),
            _pattern(status="mature", expected_date=date(2026, 9, 21), stream_key="mature"),
            _pattern(status="missed", expected_date=date(2026, 9, 22), stream_key="missed"),
            _pattern(status="unstable", expected_date=date(2026, 9, 23), stream_key="skip"),
            _pattern(status="early", expected_date=None, stream_key="none"),
        ],
        "recurring_expense",
        "outflow",
        as_of,
        date(2026, 9, 19),
        date(2026, 9, 22),
    )
    assert [event.state for event in events] == ["expected", "expected", "missed"]
    assert events[0].window_start == date(2026, 9, 15)
    assert events[0].window_end == date(2026, 9, 25)
    assert events[0].amount == TemporalAmount(low=93.0, expected=100.0, high=107.0)
    assert events[0].evidence[-1].role == "pattern_observation"


def _temporal_event(direction: str = "outflow"):
    return TemporalEventService._event(
        user_id="user-1",
        source_type="bill",
        source_id="bill-1",
        occurrence_date=date(2026, 9, 19),
        kind="bill",
        direction=direction,
        state="expected",
        label="Electricity",
        currency="INR",
        amount=TemporalAmount(low=100, expected=100, high=100),
        confidence=1.0,
        sufficiency="high",
        evidence=[],
        as_of=date(2026, 9, 19),
        window_start=date(2026, 9, 12),
        window_end=date(2026, 9, 26),
    )


def test_temporal_transaction_link_validation_accepts_only_exact_owned_evidence():
    event = _temporal_event()
    valid = Transaction(
        transaction_type=TransactionType.DEBIT,
        currency="INR",
        transaction_date=date(2026, 9, 20),
        review_outcome="newly_imported",
    )
    TemporalEventService._validate_transaction_link(event, valid)

    with pytest.raises(ValueError, match="cannot be linked"):
        TemporalEventService._validate_transaction_link(_temporal_event("neutral"), valid)
    with pytest.raises(ValueError, match="direction"):
        TemporalEventService._validate_transaction_link(
            event,
            Transaction(
                transaction_type=TransactionType.CREDIT,
                currency="INR",
                transaction_date=date(2026, 9, 20),
            ),
        )
    with pytest.raises(ValueError, match="currency"):
        TemporalEventService._validate_transaction_link(
            event,
            Transaction(
                transaction_type=TransactionType.DEBIT,
                currency="USD",
                transaction_date=date(2026, 9, 20),
            ),
        )
    with pytest.raises(ValueError, match="Ignored"):
        TemporalEventService._validate_transaction_link(
            event,
            Transaction(
                transaction_type=TransactionType.DEBIT,
                currency="INR",
                transaction_date=date(2026, 9, 20),
                review_outcome="ignored_by_rule",
            ),
        )
    with pytest.raises(ValueError, match="outside"):
        TemporalEventService._validate_transaction_link(
            event,
            Transaction(
                transaction_type=TransactionType.DEBIT,
                currency="INR",
                transaction_date=date(2026, 11, 1),
            ),
        )
