"""Branch coverage for the card upcoming-state composition rules."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from app.services.card_upcoming_state_service import (
    _dedupe_and_sort,
    _event,
    _positive_or_none,
    _slug,
    build_card_upcoming_state,
)


def _projection(**overrides):
    values = {
        "status": "unavailable",
        "projected_statement_date": None,
        "projected_balance": None,
        "target_breach_date": None,
        "target_excess_amount": None,
        "credit_limit_breach_date": None,
        "credit_limit_excess_amount": None,
        "daily_path": [],
        "confidence": 0.4,
        "credit_limit_status": "within_limit",
        "target_status": "within_target",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _overview(**overrides):
    values = {
        "financial_account_id": "card-1",
        "due_date": None,
        "total_due": None,
        "next_statement_projection": _projection(),
        "planned_payments": [],
        "calendar": [],
        "refund_tracker": SimpleNamespace(pending_amount=0, as_of=date(2026, 9, 20)),
        "balance_status": "observed",
        "balance_confidence": 0.8,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_upcoming_state_composes_issuer_forecast_user_and_ledger_events():
    today = date(2026, 9, 20)
    projection = _projection(
        status="available",
        projected_statement_date=today + timedelta(days=8),
        projected_balance=1200,
        target_breach_date=today + timedelta(days=4),
        target_excess_amount=50,
        credit_limit_breach_date=today + timedelta(days=6),
        credit_limit_excess_amount=-10,
        credit_limit_status="at_risk",
        confidence=0.7,
        daily_path=[
            SimpleNamespace(
                date=today - timedelta(days=1), event_amount=100, event_labels=["Past"]
            ),
            SimpleNamespace(
                date=today + timedelta(days=2),
                event_amount=100,
                event_labels=["Planned payment", "Large purchase"],
            ),
            SimpleNamespace(
                date=today + timedelta(days=3), event_amount=-100, event_labels=["Refund"]
            ),
        ],
    )
    overview = _overview(
        due_date=today + timedelta(days=2),
        total_due=500,
        next_statement_projection=projection,
        planned_payments=[
            SimpleNamespace(
                id="payment-1",
                status="planned",
                planned_for=today + timedelta(days=1),
                note="Pay before due date",
                amount=250,
            ),
            SimpleNamespace(
                id="payment-2",
                status="cancelled",
                planned_for=today + timedelta(days=1),
                note=None,
                amount=100,
            ),
        ],
        calendar=[
            SimpleNamespace(
                id="calendar-1", event_date=today + timedelta(days=5), label="Call bank"
            ),
            SimpleNamespace(
                id="calendar-2", event_date=today - timedelta(days=1), label="Old event"
            ),
        ],
        refund_tracker=SimpleNamespace(pending_amount=75, as_of=today),
    )

    result = build_card_upcoming_state(overview, as_of=today)

    assert result.state == "limit_pressure"
    assert result.confidence == 0.7
    assert result.next_event is not None
    assert {event.event_type for event in result.events} == {
        "payment_due",
        "statement_close",
        "planned_payment",
        "projected_charge",
        "utilization_target_breach",
        "credit_limit_breach",
        "calendar_event",
        "pending_refund",
    }
    assert all(event.label != "Planned payment" for event in result.events)
    assert "upcoming_state_composed" in result.reason_codes


def test_upcoming_state_handles_passed_due_dates_and_missing_projection():
    today = date(2026, 9, 20)
    result = build_card_upcoming_state(
        _overview(
            due_date=today - timedelta(days=1),
            total_due=400,
            balance_status="needs_review",
        ),
        as_of=today,
    )
    assert result.state == "review_evidence"
    assert result.next_event is None
    assert "issuer_due_date_passed" in result.reason_codes
    assert "statement_projection_unavailable" in result.reason_codes
    assert "no_upcoming_card_events" in result.reason_codes
    assert result.confidence == 0.45


def test_upcoming_state_uses_projection_and_evidence_fallback_states():
    today = date(2026, 9, 20)
    available = build_card_upcoming_state(
        _overview(next_statement_projection=_projection(status="available", confidence=0.6)),
        as_of=today,
    )
    assert available.state == "monitor_cycle"
    assert available.confidence == 0.6

    explicit = build_card_upcoming_state(
        _overview(
            planned_payments=[
                SimpleNamespace(
                    id="payment-1",
                    status="planned",
                    planned_for=today + timedelta(days=1),
                    note=None,
                    amount=10,
                )
            ]
        ),
        as_of=today,
    )
    assert explicit.state == "monitor_cycle"
    assert explicit.confidence == 0.4

    clear = build_card_upcoming_state(_overview(), as_of=today)
    assert clear.state == "no_upcoming_evidence"
    assert clear.confidence == 0.0


def test_upcoming_state_helpers_bound_values_and_dedupe_events():
    today = date(2026, 9, 20)
    first = _event(
        event_id="same",
        event_type="calendar_event",
        event_date=today + timedelta(days=3),
        as_of=today,
        label="x" * 200,
        amount=None,
        source_kind="user",
        status="planned",
        confidence=2,
        reason_codes=[],
    )
    duplicate = _event(
        event_id="same",
        event_type="calendar_event",
        event_date=today + timedelta(days=4),
        as_of=today,
        label="duplicate",
        amount=None,
        source_kind="user",
        status="planned",
        confidence=-1,
        reason_codes=[],
    )
    assert _dedupe_and_sort([first, duplicate]) == [first]
    assert first.confidence == 1.0
    assert len(first.label) == 160
    assert _positive_or_none(5) == 5
    assert _positive_or_none(0) is None
    assert _positive_or_none(None) is None
    assert _slug("Large Purchase / Test") == "large-purchase-test"
    assert _slug("!!!") == "event"
