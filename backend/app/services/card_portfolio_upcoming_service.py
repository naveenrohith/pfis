"""Compose a conservative upcoming-state view across a user's active cards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.schemas.financial_position import (
    CardOverviewResponse,
    CardPortfolioUpcomingCard,
    CardPortfolioUpcomingStateResponse,
    CardStatementProjectionEvidence,
    CardUpcomingEvent,
    CardUpcomingStateResponse,
)
from app.services.card_upcoming_state_service import build_card_upcoming_state
from app.services.financial_clock import user_financial_today
from app.services.financial_position_service import FinancialPositionService

RULESET_VERSION = "pfis-card-portfolio-upcoming-1"

_STATE_PRIORITY = {
    "limit_pressure": 60,
    "target_pressure": 50,
    "payment_due": 40,
    "review_evidence": 30,
    "monitor_cycle": 20,
    "no_upcoming_evidence": 10,
}


@dataclass(frozen=True)
class _CardEvidence:
    account_id: str
    label: str
    overview: CardOverviewResponse
    upcoming: CardUpcomingStateResponse


class CardPortfolioUpcomingStateService:
    """Read all active cards without merging issuer facts into one fake card."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upcoming(self, user_id: str) -> CardPortfolioUpcomingStateResponse:
        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount)
                    .where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.account_type == "credit_card",
                    )
                    .order_by(FinancialAccount.institution_name, FinancialAccount.id)
                )
            ).all()
        )
        as_of = await user_financial_today(self.db, user_id)
        evidence: list[_CardEvidence] = []
        position_service = FinancialPositionService(self.db)
        for account in accounts:
            overview = await position_service.card_overview(user_id, account.id)
            evidence.append(
                _CardEvidence(
                    account_id=account.id,
                    label=account.institution_name,
                    overview=overview,
                    upcoming=build_card_upcoming_state(overview, as_of=as_of),
                )
            )
        return build_card_portfolio_upcoming(evidence, as_of=as_of)


def build_card_portfolio_upcoming(
    cards: list[_CardEvidence], *, as_of: date
) -> CardPortfolioUpcomingStateResponse:
    """Aggregate only known values while retaining each card's evidence state."""

    if not cards:
        return CardPortfolioUpcomingStateResponse(
            as_of=as_of,
            state="no_active_cards",
            card_count=0,
            cards_with_due=0,
            confidence=0.0,
            reason_codes=["no_active_cards"],
            evidence=[
                CardStatementProjectionEvidence(
                    label="Card portfolio",
                    value="No active credit cards",
                    basis="Only active user-owned credit-card accounts are included.",
                )
            ],
            assumptions=[
                "No card-level issuer or forecast evidence exists because no active credit card is confirmed."
            ],
            ruleset_version=RULESET_VERSION,
        )

    card_rows: list[CardPortfolioUpcomingCard] = []
    due_values: list[float] = []
    due_dates: list[date] = []
    outstanding_values: list[float] = []
    events: list[CardUpcomingEvent] = []
    states: list[str] = []
    for item in cards:
        overview = item.overview
        upcoming = item.upcoming
        if overview.total_due is not None:
            due_values.append(overview.total_due)
        if overview.due_date is not None:
            due_dates.append(overview.due_date)
        if _eligible_estimated_outstanding(overview):
            outstanding_values.append(cast(float, overview.estimated_current_balance))
        if upcoming.next_event is not None:
            events.append(
                upcoming.next_event.model_copy(
                    update={
                        "id": f"portfolio:{item.account_id}:{upcoming.next_event.id}",
                        "label": f"{item.label}: {upcoming.next_event.label}"[:160],
                    }
                )
            )
        states.append(upcoming.state)
        projection = overview.next_statement_projection
        card_rows.append(
            CardPortfolioUpcomingCard(
                financial_account_id=item.account_id,
                label=item.label,
                state=upcoming.state,
                next_event=upcoming.next_event,
                confidence=upcoming.confidence,
                total_due=overview.total_due,
                due_date=overview.due_date,
                estimated_current_outstanding=overview.estimated_current_balance,
                estimated_current_as_of=overview.estimated_current_as_of,
                balance_status=overview.balance_status,
                projection_status=projection.status,
                projected_statement_date=projection.projected_statement_date,
                target_status=projection.target_status,
                credit_limit_status=projection.credit_limit_status,
                reason_codes=list(
                    dict.fromkeys(
                        [
                            *upcoming.reason_codes,
                            *overview.balance_reason_codes,
                            *projection.reason_codes,
                        ]
                    )
                ),
            )
        )

    ordered_events = sorted(
        events,
        key=lambda event: (
            event.date,
            -_event_priority(event),
            event.id,
        ),
    )
    state = cast(
        Literal[
            "monitor_cycle",
            "payment_due",
            "target_pressure",
            "limit_pressure",
            "review_evidence",
            "no_upcoming_evidence",
        ],
        max(states, key=lambda value: _STATE_PRIORITY[value]),
    )
    issuer_total_due = sum(due_values) if due_values else None
    outstanding_total = sum(outstanding_values) if outstanding_values else None
    due_complete = len(due_values) == len(cards)
    outstanding_complete = len(outstanding_values) == len(cards)
    reason_codes = ["portfolio_state_composed"]
    if not due_complete:
        reason_codes.append("partial_issuer_due_coverage")
    if not outstanding_complete:
        reason_codes.append("partial_current_outstanding_coverage")
    if any(item.upcoming.state == "limit_pressure" for item in cards):
        reason_codes.append("card_limit_pressure_present")
    if any(item.upcoming.state == "target_pressure" for item in cards):
        reason_codes.append("card_utilization_target_pressure_present")
    if any(item.upcoming.state == "review_evidence" for item in cards):
        reason_codes.append("card_evidence_needs_review")
    if not ordered_events:
        reason_codes.append("no_upcoming_card_events")
    assumptions = [
        "Issuer dues are summed only when present on the individual card statement; missing dues remain excluded and counted as incomplete coverage.",
        "Current outstanding is aggregated only when every active card has an eligible non-review estimated position; it is not a live provider total.",
        "Per-card issuer facts, forecasts, planned payments, and review states remain separate in the cards list.",
        "PFIS does not submit payments, reserve cash, or synthesize total available credit across issuers.",
    ]
    confidence = min(item.upcoming.confidence for item in cards)
    return CardPortfolioUpcomingStateResponse(
        as_of=as_of,
        state=state,
        card_count=len(cards),
        cards_with_due=sum(item.overview.due_date is not None for item in cards),
        issuer_total_due=issuer_total_due,
        issuer_total_due_cards=len(due_values),
        issuer_total_due_complete=due_complete,
        earliest_due_date=min(due_dates) if due_dates else None,
        estimated_outstanding_total=outstanding_total if outstanding_complete else None,
        estimated_outstanding_cards=len(outstanding_values),
        estimated_outstanding_complete=outstanding_complete,
        next_event=ordered_events[0] if ordered_events else None,
        events=ordered_events[:30],
        cards_needing_review=sum(
            item.overview.balance_status
            in {"needs_review", "stale", "incomplete", "needs_observation"}
            for item in cards
        ),
        confidence=confidence,
        reason_codes=list(dict.fromkeys(reason_codes)),
        evidence=[
            CardStatementProjectionEvidence(
                label="Issuer due coverage",
                value=f"{len(due_values)} of {len(cards)} card(s)",
                basis="Only statement-backed total due values are counted.",
            ),
            CardStatementProjectionEvidence(
                label="Next-state coverage",
                value=f"{len(ordered_events)} dated event(s)",
                basis="Each event retains its card context, source kind, status, and confidence.",
            ),
        ],
        assumptions=assumptions,
        cards=card_rows,
        ruleset_version=RULESET_VERSION,
    )


def _eligible_estimated_outstanding(overview: CardOverviewResponse) -> bool:
    return (
        overview.estimated_current_balance is not None
        and overview.balance_status in {"observed", "estimated"}
        and not overview.balance_reason_codes
    )


def _event_priority(event: CardUpcomingEvent) -> int:
    return {
        "credit_limit_breach": 50,
        "utilization_target_breach": 45,
        "payment_due": 40,
        "planned_payment": 35,
        "projected_charge": 25,
        "pending_refund": 20,
        "statement_close": 15,
        "calendar_event": 10,
    }.get(event.event_type, 0)
