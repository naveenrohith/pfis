"""Compose a dated, read-only next-state timeline for one credit card."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.financial_position import (
    CardOverviewResponse,
    CardStatementProjectionEvidence,
    CardUpcomingEvent,
    CardUpcomingStateResponse,
)
from app.services.financial_clock import user_financial_today
from app.services.financial_position_service import FinancialPositionService

RULESET_VERSION = "pfis-card-upcoming-state-1"

_EVENT_PRIORITY = {
    "credit_limit_breach": 50,
    "utilization_target_breach": 45,
    "payment_due": 40,
    "planned_payment": 35,
    "projected_charge": 25,
    "pending_refund": 20,
    "statement_close": 15,
    "calendar_event": 10,
}

UpcomingState = Literal[
    "monitor_cycle",
    "payment_due",
    "target_pressure",
    "limit_pressure",
    "review_evidence",
    "no_upcoming_evidence",
]
UpcomingEventType = Literal[
    "payment_due",
    "statement_close",
    "planned_payment",
    "projected_charge",
    "utilization_target_breach",
    "credit_limit_breach",
    "calendar_event",
    "pending_refund",
]
UpcomingSource = Literal["issuer", "user", "forecast", "ledger"]
UpcomingStatus = Literal["observed", "planned", "estimated", "risk"]


class CardUpcomingStateService:
    """Build one next-state view from the card overview's existing evidence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upcoming(self, user_id: str, card_account_id: str) -> CardUpcomingStateResponse:
        overview = await FinancialPositionService(self.db).card_overview(user_id, card_account_id)
        as_of = await user_financial_today(self.db, user_id)
        return build_card_upcoming_state(overview, as_of=as_of)


def build_card_upcoming_state(
    overview: CardOverviewResponse, *, as_of: date
) -> CardUpcomingStateResponse:
    """Compose upcoming events without creating or inferring ledger activity."""

    projection = overview.next_statement_projection
    events: list[CardUpcomingEvent] = []

    if (
        overview.due_date is not None
        and overview.total_due is not None
        and overview.due_date >= as_of
    ):
        events.append(
            _event(
                    event_id=f"issuer-due:{overview.financial_account_id}:{overview.due_date}",
                    event_type="payment_due",
                    event_date=overview.due_date,
                    as_of=as_of,
                    label="Issuer-stated card payment due",
                    amount=overview.total_due,
                    source_kind="issuer",
                    status="observed",
                    confidence=1.0,
                    reason_codes=["issuer_statement_due"],
            )
        )

    if projection.status == "available":
        if projection.projected_statement_date is not None:
            events.append(
                _event(
                    event_id=f"projected-close:{overview.financial_account_id}:{projection.projected_statement_date}",
                    event_type="statement_close",
                    event_date=projection.projected_statement_date,
                    as_of=as_of,
                    label="Estimated next statement close",
                    amount=projection.projected_balance,
                    source_kind="forecast",
                    status="estimated",
                    confidence=projection.confidence,
                    reason_codes=["projected_statement_close"],
                )
            )
        if projection.target_breach_date is not None and projection.target_breach_date >= as_of:
            events.append(
                _event(
                    event_id=f"target-breach:{overview.financial_account_id}:{projection.target_breach_date}",
                    event_type="utilization_target_breach",
                    event_date=projection.target_breach_date,
                    as_of=as_of,
                    label="Estimated utilization-target pressure",
                    amount=_positive_or_none(projection.target_excess_amount),
                    source_kind="forecast",
                    status="risk",
                    confidence=projection.confidence,
                    reason_codes=["utilization_target_breach_estimated"],
                )
            )
        if (
            projection.credit_limit_breach_date is not None
            and projection.credit_limit_breach_date >= as_of
        ):
            events.append(
                _event(
                    event_id=f"limit-breach:{overview.financial_account_id}:{projection.credit_limit_breach_date}",
                    event_type="credit_limit_breach",
                    event_date=projection.credit_limit_breach_date,
                    as_of=as_of,
                    label="Estimated credit-limit pressure",
                    amount=_positive_or_none(projection.credit_limit_excess_amount),
                    source_kind="forecast",
                    status="risk",
                    confidence=projection.confidence,
                    reason_codes=["credit_limit_breach_estimated"],
                )
            )
        for point in projection.daily_path:
            if point.date < as_of or point.event_amount <= 0:
                continue
            for label in point.event_labels:
                if label == "Planned payment":
                    continue
                events.append(
                    _event(
                        event_id=(
                            f"projection-charge:{overview.financial_account_id}:"
                            f"{point.date}:{_slug(label)}"
                        ),
                        event_type="projected_charge",
                        event_date=point.date,
                        as_of=as_of,
                        label=label,
                        amount=abs(point.event_amount),
                        source_kind="forecast",
                        status="estimated",
                        confidence=projection.confidence,
                        reason_codes=["dated_projection_event"],
                    )
                )

    for payment in overview.planned_payments:
        if payment.status == "planned" and payment.planned_for >= as_of:
            events.append(
                _event(
                    event_id=f"planned-payment:{payment.id}",
                    event_type="planned_payment",
                    event_date=payment.planned_for,
                    as_of=as_of,
                    label=payment.note or "Planned card payment",
                    amount=float(payment.amount),
                    source_kind="user",
                    status="planned",
                    confidence=0.86,
                    reason_codes=["user_payment_intention"],
                )
            )

    for calendar_event in overview.calendar:
        if calendar_event.event_date >= as_of:
            events.append(
                _event(
                    event_id=f"calendar:{calendar_event.id}",
                    event_type="calendar_event",
                    event_date=calendar_event.event_date,
                    as_of=as_of,
                    label=calendar_event.label,
                    amount=None,
                    source_kind="user",
                    status="planned",
                    confidence=0.75,
                    reason_codes=["user_calendar_event"],
                )
            )

    if overview.refund_tracker.pending_amount > 0:
        events.append(
            _event(
                event_id=f"pending-refund:{overview.financial_account_id}:{overview.refund_tracker.as_of}",
                event_type="pending_refund",
                event_date=as_of,
                as_of=as_of,
                label="Pending refund may lower future card balance",
                amount=overview.refund_tracker.pending_amount,
                source_kind="ledger",
                status="estimated",
                confidence=0.65,
                reason_codes=["pending_refund_not_settled"],
            )
        )

    events = _dedupe_and_sort(events)[:30]
    state, state_reasons = _state_for(overview, events, as_of=as_of)
    confidence = _state_confidence(overview, state)
    next_event = events[0] if events else None
    evidence = [
        CardStatementProjectionEvidence(
            label="Upcoming state",
            value=state.replace("_", " "),
            basis=(
                "Composed from issuer statement facts, user intentions, card calendar events, "
                "and PFIS forecast evidence; it is not an external action or guarantee."
            ),
        ),
        CardStatementProjectionEvidence(
            label="Upcoming evidence",
            value=f"{len(events)} dated event(s)"
            if events
            else "No dated upcoming event",
            basis="Only events with explicit dates or bounded projection dates are included.",
        ),
    ]
    assumptions = [
        "Issuer due dates are statement facts; planned and forecast events are not confirmed settlement.",
        "PFIS does not send payments, reserve credit, or claim live available credit from this timeline.",
    ]
    reason_codes = ["upcoming_state_composed", *state_reasons]
    if projection.status != "available":
        reason_codes.append("statement_projection_unavailable")
        assumptions.append(
            "The next-statement projection is unavailable, so the timeline stays limited to explicit due, plan, calendar, and refund evidence."
        )
    if overview.due_date is not None and overview.due_date < as_of:
        reason_codes.append("issuer_due_date_passed")
        assumptions.append(
            "The issuer due date has passed; PFIS does not assume that payment settled."
        )
    if not events:
        reason_codes.append("no_upcoming_card_events")

    return CardUpcomingStateResponse(
        financial_account_id=overview.financial_account_id,
        as_of=as_of,
        state=state,
        next_event=next_event,
        confidence=confidence,
        reason_codes=list(dict.fromkeys(reason_codes)),
        evidence=evidence,
        assumptions=assumptions,
        events=events,
        ruleset_version=RULESET_VERSION,
    )


def _event(
    *,
    event_id: str,
    event_type: UpcomingEventType,
    event_date: date,
    as_of: date,
    label: str,
    amount: float | None,
    source_kind: UpcomingSource,
    status: UpcomingStatus,
    confidence: float,
    reason_codes: list[str],
) -> CardUpcomingEvent:
    return CardUpcomingEvent(
        id=event_id,
        event_type=event_type,
        date=event_date,
        days_from_today=max((event_date - as_of).days, 0),
        label=label[:160],
        amount=amount,
        source_kind=source_kind,
        status=status,
        confidence=max(0.0, min(confidence, 1.0)),
        reason_codes=reason_codes,
    )


def _dedupe_and_sort(events: list[CardUpcomingEvent]) -> list[CardUpcomingEvent]:
    unique: dict[str, CardUpcomingEvent] = {}
    for event in events:
        unique.setdefault(event.id, event)
    return sorted(
        unique.values(),
        key=lambda event: (
            event.date,
            -_EVENT_PRIORITY.get(event.event_type, 0),
            event.id,
        ),
    )


def _state_for(
    overview: CardOverviewResponse,
    events: list[CardUpcomingEvent],
    *,
    as_of: date,
) -> tuple[
    UpcomingState,
    list[str],
]:
    projection = overview.next_statement_projection
    if projection.credit_limit_status in {"over_limit", "at_risk"}:
        return "limit_pressure", ["credit_limit_pressure"]
    if projection.target_status in {"over_target", "at_risk"}:
        return "target_pressure", ["utilization_target_pressure"]
    due = next((event for event in events if event.event_type == "payment_due"), None)
    if due is not None and due.days_from_today <= 7:
        return "payment_due", ["issuer_payment_due_within_seven_days"]
    if projection.status == "available":
        return "monitor_cycle", ["projection_available"]
    if due is not None:
        return "payment_due", ["issuer_payment_due_known"]
    if events:
        return "monitor_cycle", ["explicit_upcoming_evidence"]
    if overview.balance_status in {"needs_observation", "needs_review", "incomplete", "stale"}:
        return "review_evidence", ["card_position_needs_review"]
    return "no_upcoming_evidence", ["no_upcoming_state_signal"]


def _state_confidence(overview: CardOverviewResponse, state: UpcomingState) -> float:
    projection_confidence = overview.next_statement_projection.confidence
    if state in {"limit_pressure", "target_pressure", "monitor_cycle"}:
        return projection_confidence
    if state == "payment_due":
        return max(projection_confidence, 0.75) if overview.due_date else projection_confidence
    if state == "review_evidence":
        return min(overview.balance_confidence, 0.45)
    return 0.0


def _positive_or_none(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48] or "event"
