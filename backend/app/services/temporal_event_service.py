"""Recomputable expected-versus-observed financial timeline."""

from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import (
    CardCalendarEvent,
    CardPaymentIntent,
    CashPlan,
    Commitment,
    Liability,
    LiabilityScheduleItem,
    ReservePlan,
)
from app.models.knowledge import TemporalEventDecision
from app.models.roadmap import RoadmapBill
from app.models.transaction import Transaction, TransactionType
from app.models.user import User
from app.schemas.temporal import (
    TemporalAmount,
    TemporalDirection,
    TemporalEventDecisionResponse,
    TemporalEventDecisionUpsert,
    TemporalEventKind,
    TemporalEventState,
    TemporalEventSummary,
    TemporalEvidenceReference,
    TemporalFinancialEvent,
    TemporalObservation,
    TemporalRecomputationAudit,
    TemporalRecomputationIssue,
    TemporalSourceType,
)
from app.services.knowledge.recurring_knowledge import RecurringPattern, RecurringPatternService
from app.services.knowledge.ruleset_registry import TEMPORAL_EVENTS
from app.services.temporal_source_history import historical_source_snapshots
from app.services.transaction_aggregates import income_event_predicate
from app.utils.financial_time import financial_today

_MAX_HORIZON_DAYS = 366
_STATE_ORDER: tuple[TemporalEventState, ...] = (
    "conflict",
    "overdue",
    "missed",
    "expected",
    "observed",
    "cancelled",
)


class TemporalEventService:
    """Unify dated PFIS evidence without guessing cross-source matches."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def timeline(
        self,
        user_id: str,
        *,
        range_start: date | None = None,
        range_end: date | None = None,
        as_of: date | None = None,
        historical_safe: bool = False,
    ) -> TemporalEventSummary:
        user = await self.db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise LookupError("User not found")
        today = financial_today(user.timezone)
        as_of = as_of or today
        if as_of > today:
            raise ValueError(
                "Temporal evidence cannot be evaluated after the current financial day"
            )
        range_start = range_start or as_of - timedelta(days=31)
        range_end = range_end or as_of + timedelta(days=90)
        if range_end < range_start:
            raise ValueError("Timeline end date must be on or after the start date")
        if (range_end - range_start).days > _MAX_HORIZON_DAYS:
            raise ValueError("Timeline range cannot exceed 366 days")

        events: list[TemporalFinancialEvent] = []
        if historical_safe:
            events.extend(
                await self._historical_source_events(
                    user_id,
                    user.currency,
                    user.timezone,
                    as_of,
                    range_start,
                    range_end,
                )
            )
        else:
            events.extend(
                await self._cash_plan_events(user_id, user.currency, as_of, range_start, range_end)
            )
            events.extend(
                await self._bill_events(
                    user_id,
                    user.currency,
                    user.timezone,
                    as_of,
                    range_start,
                    range_end,
                )
            )
            events.extend(
                await self._commitment_events(user_id, user.currency, as_of, range_start, range_end)
            )
            events.extend(
                await self._liability_events(user_id, user.currency, as_of, range_start, range_end)
            )
            events.extend(
                await self._card_calendar_events(
                    user_id, user.currency, as_of, range_start, range_end
                )
            )
            events.extend(
                await self._card_payment_intent_events(
                    user_id, user.currency, as_of, range_start, range_end
                )
            )
            events.extend(
                await self._reserve_events(user_id, user.currency, as_of, range_start, range_end)
            )
            events.extend(
                await self._account_identity_events(
                    user_id, user.currency, user.timezone, as_of, range_start, range_end
                )
            )
            events.extend(
                await self._transaction_lifecycle_events(
                    user_id, user.currency, as_of, range_start, range_end
                )
            )
        events.extend(await self._recurring_expense_events(user_id, as_of, range_start, range_end))
        events.extend(await self._income_pattern_events(user_id, as_of, range_start, range_end))
        events = await self._apply_decisions(user_id, events, as_of=as_of)
        events.sort(
            key=lambda item: (item.expected_date, _STATE_ORDER.index(item.state), item.label)
        )

        counts: dict[TemporalEventState, int] = dict.fromkeys(_STATE_ORDER, 0)
        for event in events:
            counts[event.state] += 1
        return TemporalEventSummary(
            range_start=range_start,
            range_end=range_end,
            as_of=as_of,
            currency=user.currency,
            ruleset_version=TEMPORAL_EVENTS.version,
            counts=counts,
            events=events,
            assumptions=[
                "Only dated evidence already owned by this user is included.",
                "A similar merchant or amount is not treated as a payment match.",
                "Pattern dates are estimates; user and issuer dates remain explicit evidence.",
                *(
                    [
                        "Historical-safe mode uses append-only planning snapshots and transaction-derived patterns; source types without history remain excluded."
                    ]
                    if historical_safe
                    else []
                ),
            ],
        )

    async def upsert_decision(
        self,
        user_id: str,
        event_id: str,
        data: TemporalEventDecisionUpsert,
        *,
        range_start: date | None = None,
        range_end: date | None = None,
    ) -> TemporalFinancialEvent:
        timeline = await self.timeline(user_id, range_start=range_start, range_end=range_end)
        event = next((item for item in timeline.events if item.id == event_id), None)
        if event is None:
            raise LookupError("Temporal event not found in the requested range")
        if event.kind in {"account_identity", "transaction_lifecycle"}:
            raise ValueError(
                "Account identity and transaction lifecycle evidence are resolved from source records, not temporal decisions"
            )

        transaction: Transaction | None = None
        if data.decision == "linked":
            transaction = await self.db.scalar(
                select(Transaction).where(
                    Transaction.id == data.transaction_id,
                    Transaction.user_id == user_id,
                )
            )
            if transaction is None:
                raise LookupError("Transaction not found")
            self._validate_transaction_link(event, transaction)

        definition = next(
            (
                item
                for item in event.evidence
                if item.role == "definition" and item.source_type != "user_confirmation"
            ),
            None,
        )
        if definition is None:
            raise ValueError("Temporal event has no stable source definition")

        row = await self.db.scalar(
            select(TemporalEventDecision).where(
                TemporalEventDecision.user_id == user_id,
                TemporalEventDecision.event_id == event_id,
            )
        )
        if row is None:
            row = TemporalEventDecision(user_id=user_id, event_id=event_id)
            self.db.add(row)
        row.event_kind = event.kind
        row.source_type = definition.source_type
        row.source_id = definition.source_id
        row.occurrence_date = event.expected_date
        row.event_ruleset_version = event.ruleset_version
        row.decision = data.decision
        row.note = data.note
        row.transaction_id = transaction.id if transaction is not None else None
        row.observed_date = (
            transaction.transaction_date if transaction is not None else data.observed_date
        )
        row.observed_amount = (
            transaction.amount if transaction is not None else data.observed_amount
        )
        await self.db.commit()

        refreshed = await self.timeline(user_id, range_start=range_start, range_end=range_end)
        result = next((item for item in refreshed.events if item.id == event_id), None)
        if result is None:
            raise RuntimeError("Temporal decision target disappeared during recomputation")
        return result

    async def delete_decision(self, user_id: str, event_id: str) -> bool:
        row = await self.db.scalar(
            select(TemporalEventDecision).where(
                TemporalEventDecision.user_id == user_id,
                TemporalEventDecision.event_id == event_id,
            )
        )
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True

    async def recomputation_audit(
        self,
        user_id: str,
        *,
        range_start: date | None = None,
        range_end: date | None = None,
        as_of: date | None = None,
        historical_safe: bool = False,
    ) -> TemporalRecomputationAudit:
        """Compare persisted overlays with a fresh read-model build without writing."""

        timeline = await self.timeline(
            user_id,
            range_start=range_start,
            range_end=range_end,
            as_of=as_of,
            historical_safe=historical_safe,
        )
        decisions = list(
            (
                await self.db.scalars(
                    select(TemporalEventDecision).where(
                        TemporalEventDecision.user_id == user_id,
                        TemporalEventDecision.occurrence_date >= timeline.range_start,
                        TemporalEventDecision.occurrence_date <= timeline.range_end,
                        *(
                            [
                                func.date(TemporalEventDecision.created_at) <= timeline.as_of,
                                func.date(TemporalEventDecision.updated_at) <= timeline.as_of,
                            ]
                            if as_of is not None
                            else []
                        ),
                    )
                )
            ).all()
        )
        event_ids = {event.id for event in timeline.events}
        issues: list[TemporalRecomputationIssue] = []
        applicable = 0
        orphaned = 0
        ruleset_drift = 0
        missing_links = 0
        for row in decisions:
            if row.event_id not in event_ids:
                orphaned += 1
                issues.append(
                    TemporalRecomputationIssue(
                        decision_id=row.id,
                        event_id=row.event_id,
                        issue="orphaned_event",
                        detail="The source-derived event no longer exists in this range.",
                    )
                )
            else:
                applicable += 1
            if row.event_ruleset_version != timeline.ruleset_version:
                ruleset_drift += 1
                issues.append(
                    TemporalRecomputationIssue(
                        decision_id=row.id,
                        event_id=row.event_id,
                        issue="ruleset_drift",
                        detail=(
                            f"Decision uses {row.event_ruleset_version}; current events use "
                            f"{timeline.ruleset_version}."
                        ),
                    )
                )
            if row.decision == "linked" and row.transaction_id is None:
                missing_links += 1
                issues.append(
                    TemporalRecomputationIssue(
                        decision_id=row.id,
                        event_id=row.event_id,
                        issue="missing_linked_transaction",
                        detail="The exact linked transaction is no longer retained.",
                    )
                )

        events_by_kind: dict[TemporalEventKind, int] = defaultdict(int)
        events_by_state: dict[TemporalEventState, int] = defaultdict(int)
        for event in timeline.events:
            events_by_kind[event.kind] += 1
            events_by_state[event.state] += 1
        return TemporalRecomputationAudit(
            range_start=timeline.range_start,
            range_end=timeline.range_end,
            data_through=timeline.as_of,
            ruleset_version=timeline.ruleset_version,
            source_event_count=len(timeline.events),
            decision_count=len(decisions),
            applicable_decision_count=applicable,
            orphaned_decision_count=orphaned,
            ruleset_drift_count=ruleset_drift,
            missing_link_count=missing_links,
            events_by_kind=dict(events_by_kind),
            events_by_state=dict(events_by_state),
            issues=issues,
        )

    async def _apply_decisions(
        self,
        user_id: str,
        events: list[TemporalFinancialEvent],
        *,
        as_of: date | None = None,
    ) -> list[TemporalFinancialEvent]:
        if not events:
            return events
        decisions = list(
            (
                await self.db.scalars(
                    select(TemporalEventDecision).where(
                        TemporalEventDecision.user_id == user_id,
                        TemporalEventDecision.event_id.in_([event.id for event in events]),
                    )
                )
            ).all()
        )
        if as_of is not None:
            decisions = [
                row
                for row in decisions
                if row.created_at.date() <= as_of and row.updated_at.date() <= as_of
            ]
        transaction_ids = [row.transaction_id for row in decisions if row.transaction_id]
        transactions = (
            {
                row.id: row
                for row in (
                    await self.db.scalars(
                        select(Transaction).where(
                            Transaction.user_id == user_id,
                            Transaction.id.in_(transaction_ids),
                            *(
                                [
                                    Transaction.transaction_date <= as_of,
                                    func.date(Transaction.created_at) <= as_of,
                                ]
                                if as_of is not None
                                else []
                            ),
                        )
                    )
                ).all()
            }
            if transaction_ids
            else {}
        )
        by_event = {row.event_id: row for row in decisions}
        resolved: list[TemporalFinancialEvent] = []
        for event in events:
            row = by_event.get(event.id)
            if row is None:
                resolved.append(event)
                continue
            evidence = [
                *event.evidence,
                self._evidence("user_confirmation", row.id, "explicit_observation"),
            ]
            updates: dict = {
                "decision": TemporalEventDecisionResponse.model_validate(row),
                "evidence": evidence,
            }
            if row.decision == "confirmed":
                updates["confidence"] = 1.0
            elif row.decision == "cancelled":
                updates["state"] = "cancelled"
                updates["observation"] = None
            elif row.decision == "observed":
                updates["state"] = "observed"
                updates["observation"] = TemporalObservation(
                    observed_date=row.observed_date or event.expected_date,
                    amount=float(row.observed_amount) if row.observed_amount is not None else None,
                    confirmation="user_status",
                )
            elif row.decision == "conflict":
                updates["state"] = "conflict"
                updates["conflict_reason"] = row.note
            elif row.decision == "linked":
                transaction = transactions.get(row.transaction_id or "")
                if transaction is None:
                    updates["state"] = "conflict"
                    updates["conflict_reason"] = "Linked transaction is no longer available"
                else:
                    observed_amount = float(row.observed_amount or transaction.amount)
                    updates["observation"] = TemporalObservation(
                        observed_date=row.observed_date or transaction.transaction_date,
                        amount=observed_amount,
                        transaction_id=transaction.id,
                        confirmation="ledger_match",
                    )
                    updates["evidence"] = [
                        *evidence,
                        self._evidence("transaction", transaction.id, "match"),
                    ]
                    expected_amount = event.amount.expected
                    mismatch = expected_amount is not None and abs(
                        observed_amount - expected_amount
                    ) > max(expected_amount * 0.1, 1.0)
                    updates["state"] = "conflict" if mismatch else "observed"
                    updates["conflict_reason"] = (
                        "Linked transaction amount differs from the expected amount"
                        if mismatch
                        else None
                    )
            resolved.append(event.model_copy(update=updates))
        return resolved

    @staticmethod
    def _validate_transaction_link(event: TemporalFinancialEvent, transaction: Transaction) -> None:
        expected_type = {
            "inflow": TransactionType.CREDIT,
            "outflow": TransactionType.DEBIT,
        }.get(event.direction)
        if expected_type is None:
            raise ValueError("This event type cannot be linked to a ledger transaction")
        if transaction.transaction_type != expected_type:
            raise ValueError("Transaction direction does not match the temporal event")
        if transaction.currency != event.currency:
            raise ValueError("Transaction currency does not match the temporal event")
        if transaction.review_outcome == "ignored_by_rule":
            raise ValueError("Ignored activity cannot be temporal evidence")
        earliest = event.window_start - timedelta(days=14)
        latest = event.window_end + timedelta(days=14)
        if not earliest <= transaction.transaction_date <= latest:
            raise ValueError("Transaction date is outside the event matching window")

    async def _historical_source_events(
        self,
        user_id: str,
        currency: str,
        timezone: str,
        as_of: date,
        start: date,
        end: date,
    ) -> list[TemporalFinancialEvent]:
        snapshots = await historical_source_snapshots(
            self.db,
            user_id=user_id,
            timezone=timezone,
            as_of=as_of,
        )
        events: list[TemporalFinancialEvent] = []
        for (source_type, source_id), payload in snapshots.items():
            if source_type == "cash_plan":
                occurrence_date = self._snapshot_date(payload.get("next_income_date"))
                if occurrence_date is None or not start <= occurrence_date <= end:
                    continue
                events.append(
                    self._event(
                        user_id=user_id,
                        source_type="cash_plan",
                        source_id=source_id,
                        occurrence_date=occurrence_date,
                        kind="income",
                        direction="inflow",
                        state=self._dated_state(occurrence_date, as_of),
                        label="Planned income",
                        currency=currency,
                        amount=self._snapshot_amount(payload.get("next_income_amount")),
                        confidence=0.85,
                        sufficiency="medium",
                        evidence=[self._evidence("cash_plan", source_id, "definition")],
                        assumptions=[
                            "The date and amount are user planning inputs, not observed income."
                        ],
                        as_of=as_of,
                    )
                )
            elif source_type == "bill":
                events.extend(
                    self._historical_bill_events(
                        user_id,
                        currency,
                        source_id,
                        payload,
                        as_of,
                        start,
                        end,
                    )
                )
            elif source_type == "commitment":
                events.extend(
                    self._historical_commitment_events(
                        user_id,
                        currency,
                        source_id,
                        payload,
                        as_of,
                        start,
                        end,
                    )
                )
            elif source_type == "liability_schedule":
                event = self._historical_liability_schedule_event(
                    user_id,
                    currency,
                    source_id,
                    payload,
                    as_of,
                    start,
                    end,
                )
                if event is not None:
                    events.append(event)
            elif source_type == "reserve_plan":
                occurrence_date = self._snapshot_date(payload.get("due_date"))
                if (
                    not payload.get("approved")
                    or not payload.get("is_active", True)
                    or occurrence_date is None
                    or not start <= occurrence_date <= end
                ):
                    continue
                events.append(
                    self._event(
                        user_id=user_id,
                        source_type="reserve_plan",
                        source_id=source_id,
                        occurrence_date=occurrence_date,
                        kind="reserve",
                        direction="reserve",
                        state=self._dated_state(occurrence_date, as_of),
                        label=str(payload.get("label") or "Reserve"),
                        currency=currency,
                        amount=self._snapshot_amount(payload.get("target_amount")),
                        confidence=0.98,
                        sufficiency="high",
                        evidence=[self._evidence("reserve_plan", source_id, "definition")],
                        assumptions=["A reserve protects cash but is not itself a ledger outflow."],
                        as_of=as_of,
                    )
                )
            elif source_type == "card_calendar":
                occurrence_date = self._snapshot_date(payload.get("event_date"))
                if occurrence_date is None or not start <= occurrence_date <= end:
                    continue
                events.append(
                    self._event(
                        user_id=user_id,
                        source_type="card_calendar",
                        source_id=source_id,
                        occurrence_date=occurrence_date,
                        kind="card_milestone",
                        direction="neutral",
                        state=self._dated_state(occurrence_date, as_of),
                        label=str(payload.get("label") or "Card calendar event"),
                        currency=currency,
                        amount=TemporalAmount(),
                        confidence=0.8,
                        sufficiency="medium",
                        evidence=[self._evidence("card_calendar", source_id, "definition")],
                        assumptions=[
                            "Calendar milestones do not imply an amount or payment instruction."
                        ],
                        as_of=as_of,
                    )
                )
            elif source_type == "financial_account":
                event = self._historical_account_identity_event(
                    user_id,
                    currency,
                    source_id,
                    payload,
                    as_of,
                    start,
                    end,
                )
                if event is not None:
                    events.append(event)
            elif source_type == "transaction":
                event = self._historical_transaction_lifecycle_event(
                    user_id,
                    currency,
                    source_id,
                    payload,
                    as_of,
                    start,
                    end,
                )
                if event is not None:
                    events.append(event)
            elif source_type == "card_payment_intent":
                event = self._historical_card_payment_intent_event(
                    user_id,
                    currency,
                    source_id,
                    payload,
                    as_of,
                    start,
                    end,
                )
                if event is not None:
                    events.append(event)
        return events

    def _historical_account_identity_event(
        self,
        user_id: str,
        currency: str,
        source_id: str,
        payload: dict[str, Any],
        as_of: date,
        start: date,
        end: date,
    ) -> TemporalFinancialEvent | None:
        occurrence_date = self._snapshot_date(payload.get("effective_date"))
        if occurrence_date is None or not start <= occurrence_date <= end:
            return None
        return self._account_identity_event(
            user_id=user_id,
            currency=str(payload.get("currency") or currency),
            source_id=source_id,
            occurrence_date=occurrence_date,
            institution_name=str(payload.get("institution_name") or "Unknown"),
            account_type=str(payload.get("account_type") or "unknown"),
            masked_number=str(payload.get("masked_number") or ""),
            balance_kind=str(payload.get("balance_kind") or "asset"),
            is_active=bool(payload.get("is_active", True)),
            identity_status=str(payload.get("identity_status") or "unresolved"),
            identity_confidence=float(payload.get("identity_confidence") or 0.0),
            as_of=as_of,
        )

    async def _account_identity_events(
        self,
        user_id: str,
        currency: str,
        timezone_name: str,
        as_of: date,
        start: date,
        end: date,
    ) -> list[TemporalFinancialEvent]:
        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(FinancialAccount.user_id == user_id)
                )
            ).all()
        )
        events: list[TemporalFinancialEvent] = []
        for account in accounts:
            changed_at = account.updated_at or account.created_at
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=UTC)
            occurrence_date = changed_at.astimezone(ZoneInfo(timezone_name)).date()
            if not start <= occurrence_date <= end:
                continue
            events.append(
                self._account_identity_event(
                    user_id=user_id,
                    currency=account.currency or currency,
                    source_id=account.id,
                    occurrence_date=occurrence_date,
                    institution_name=account.institution_name,
                    account_type=account.account_type,
                    masked_number=account.masked_number,
                    balance_kind=account.balance_kind,
                    is_active=account.is_active,
                    identity_status=account.identity_status,
                    identity_confidence=float(account.identity_confidence),
                    as_of=as_of,
                )
            )
        return events

    def _account_identity_event(
        self,
        *,
        user_id: str,
        currency: str,
        source_id: str,
        occurrence_date: date,
        institution_name: str,
        account_type: str,
        masked_number: str,
        balance_kind: str,
        is_active: bool,
        identity_status: str,
        identity_confidence: float,
        as_of: date,
    ) -> TemporalFinancialEvent:
        type_label = account_type.replace("_", " ")
        label = institution_name
        if type_label != "unknown":
            label = f"{institution_name} · {type_label}"
        if masked_number:
            label = f"{label} · {masked_number}"
        state: TemporalEventState = "observed" if is_active else "cancelled"
        sufficiency = cast(
            Literal["low", "medium", "high"],
            {"confirmed": "high", "inferred": "medium"}.get(identity_status, "low"),
        )
        assumptions = [
            "This is account identity evidence, not a live balance or transaction.",
        ]
        if identity_status != "confirmed":
            assumptions.append(
                "The product type remains unresolved; PFIS will not promote it into typed position or debt calculations."
            )
        if not is_active:
            assumptions.append("The account is inactive; historical evidence remains retained.")
        return self._event(
            user_id=user_id,
            source_type="financial_account",
            source_id=source_id,
            occurrence_date=occurrence_date,
            kind="account_identity",
            direction="neutral",
            state=state,
            label=label,
            currency=currency,
            amount=TemporalAmount(),
            confidence=identity_confidence,
            sufficiency=sufficiency,
            evidence=[self._evidence("financial_account", source_id, "explicit_observation")],
            assumptions=assumptions,
            as_of=as_of,
        )

    async def _transaction_lifecycle_events(
        self,
        user_id: str,
        currency: str,
        as_of: date,
        start: date,
        end: date,
    ) -> list[TemporalFinancialEvent]:
        rows = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.transaction_date >= start,
                        Transaction.transaction_date <= end,
                    )
                )
            ).all()
        )
        events: list[TemporalFinancialEvent] = []
        for row in rows:
            transaction_type = self._enum_value(row.transaction_type)
            card_event = self._enum_value(row.card_event)
            if not self._is_transaction_lifecycle_state(
                str(row.transaction_status), transaction_type, card_event
            ):
                continue
            events.append(
                self._transaction_lifecycle_event(
                    user_id=user_id,
                    currency=row.currency or currency,
                    source_id=row.id,
                    occurrence_date=row.transaction_date,
                    amount=row.amount,
                    transaction_type=transaction_type,
                    transaction_status=str(row.transaction_status),
                    card_event=card_event,
                    label=row.merchant_normalized or row.merchant_raw or "Financial activity",
                    confidence=float(row.confidence_score or 0.0),
                    reviewed=bool(row.reviewed_flag),
                    source_kind=row.source_kind,
                    as_of=as_of,
                )
            )
        return events

    def _historical_transaction_lifecycle_event(
        self,
        user_id: str,
        currency: str,
        source_id: str,
        payload: dict[str, Any],
        as_of: date,
        start: date,
        end: date,
    ) -> TemporalFinancialEvent | None:
        occurrence_date = self._snapshot_date(payload.get("transaction_date"))
        if occurrence_date is None or not start <= occurrence_date <= end:
            return None
        transaction_type = self._enum_value(payload.get("transaction_type"))
        card_event = self._enum_value(payload.get("card_event"))
        transaction_status = str(payload.get("transaction_status") or "completed")
        if not self._is_transaction_lifecycle_state(
            transaction_status, transaction_type, card_event
        ):
            return None
        return self._transaction_lifecycle_event(
            user_id=user_id,
            currency=str(payload.get("currency") or currency),
            source_id=source_id,
            occurrence_date=occurrence_date,
            amount=payload.get("amount"),
            transaction_type=transaction_type,
            transaction_status=transaction_status,
            card_event=card_event,
            label=str(
                payload.get("merchant_normalized")
                or payload.get("merchant_raw")
                or "Financial activity"
            ),
            confidence=float(payload.get("confidence_score") or 0.0),
            reviewed=bool(payload.get("reviewed_flag", False)),
            source_kind=str(payload.get("source_kind") or "manual"),
            as_of=as_of,
        )

    def _historical_card_payment_intent_event(
        self,
        user_id: str,
        currency: str,
        source_id: str,
        payload: dict[str, Any],
        as_of: date,
        start: date,
        end: date,
    ) -> TemporalFinancialEvent | None:
        planned_for = self._snapshot_date(payload.get("planned_for"))
        if planned_for is None or not start <= planned_for <= end:
            return None
        return self._card_payment_intent_event(
            user_id=user_id,
            currency=currency,
            source_id=source_id,
            planned_for=planned_for,
            amount=payload.get("amount"),
            status=str(payload.get("status") or "planned"),
            note=str(payload.get("note") or ""),
            transfer_group_id=str(payload.get("transfer_group_id") or "") or None,
            as_of=as_of,
        )

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "").lower()

    @staticmethod
    def _is_transaction_lifecycle_state(
        transaction_status: str,
        transaction_type: str,
        card_event: str,
    ) -> bool:
        status = transaction_status.lower()
        return (
            status != "completed"
            or transaction_type == "refund"
            or card_event in {"refund", "reversal"}
        )

    def _transaction_lifecycle_event(
        self,
        *,
        user_id: str,
        currency: str,
        source_id: str,
        occurrence_date: date,
        amount: Any,
        transaction_type: str,
        transaction_status: str,
        card_event: str,
        label: str,
        confidence: float,
        reviewed: bool,
        source_kind: str,
        as_of: date,
    ) -> TemporalFinancialEvent:
        status = transaction_status.lower()
        is_pending = any(
            token in status for token in ("pending", "initiated", "processing", "authorized")
        )
        is_failed = status in {"failed", "declined", "cancelled", "expired", "reversed"}
        state: TemporalEventState = (
            "expected" if is_pending else "cancelled" if is_failed else "observed"
        )
        is_inflow = transaction_type in {"credit", "refund"} or card_event in {
            "refund",
            "reversal",
        }
        direction: TemporalDirection = "inflow" if is_inflow else "outflow"
        if card_event == "reversal" or "reversal" in status:
            title = "Reversal"
        elif card_event == "refund" or transaction_type == "refund" or "refund" in status:
            title = "Refund"
        else:
            title = f"{transaction_status.replace('_', ' ').title()} transaction"
        label = f"{title} · {label}"
        confirmation = cast(
            Literal["ledger_match", "user_status", "issuer_status"],
            (
                "issuer_status"
                if source_kind in {"email", "statement", "connector"}
                else "user_status"
            ),
        )
        observation = (
            TemporalObservation(
                observed_date=occurrence_date,
                amount=self._snapshot_float(amount),
                transaction_id=source_id,
                confirmation=confirmation,
            )
            if state == "observed"
            else None
        )
        assumptions = [
            "Transaction lifecycle status is retained source evidence; it does not create a second ledger row.",
        ]
        if state == "expected":
            assumptions.append("Pending or initiated activity may settle, fail, or reverse later.")
        elif state == "cancelled":
            assumptions.append(
                "Failed or cancelled activity is retained for audit and excluded from settled movement."
            )
        else:
            assumptions.append(
                "Observed lifecycle evidence is not a guarantee that a provider will not correct it later."
            )
        sufficiency = cast(
            Literal["low", "medium", "high"],
            "high" if reviewed and confidence >= 0.8 else "medium" if confidence >= 0.5 else "low",
        )
        return self._event(
            user_id=user_id,
            source_type="transaction",
            source_id=source_id,
            occurrence_date=occurrence_date,
            kind="transaction_lifecycle",
            direction=direction,
            state=state,
            label=label,
            currency=currency,
            amount=self._snapshot_amount(amount),
            confidence=confidence,
            sufficiency=sufficiency,
            evidence=[self._evidence("transaction", source_id, "explicit_observation")],
            observation=observation,
            assumptions=assumptions,
            as_of=as_of,
        )

    def _historical_bill_events(
        self,
        user_id: str,
        currency: str,
        source_id: str,
        payload: dict[str, Any],
        as_of: date,
        start: date,
        end: date,
    ) -> list[TemporalFinancialEvent]:
        due_date = self._snapshot_date(payload.get("due_date"))
        if due_date is None:
            return []
        status = str(payload.get("status") or "due")
        occurrence_dates = (
            [due_date]
            if status in {"paid", "skipped"}
            else self._occurrences(due_date, payload.get("cadence"), start, end)
        )
        events: list[TemporalFinancialEvent] = []
        for occurrence_date in occurrence_dates:
            if not start <= occurrence_date <= end:
                continue
            observed = status == "paid" and occurrence_date == due_date
            cancelled = status == "skipped" and occurrence_date == due_date
            state: TemporalEventState = (
                "observed"
                if observed
                else "cancelled" if cancelled else self._dated_state(occurrence_date, as_of)
            )
            events.append(
                self._event(
                    user_id=user_id,
                    source_type="bill",
                    source_id=source_id,
                    occurrence_date=occurrence_date,
                    kind="subscription" if payload.get("bill_type") == "subscription" else "bill",
                    direction="outflow",
                    state=state,
                    label=str(payload.get("label") or "Bill"),
                    currency=currency,
                    amount=self._snapshot_amount(payload.get("amount")),
                    confidence=0.98 if payload.get("confirmed") else 0.8,
                    sufficiency="high" if payload.get("confirmed") else "medium",
                    cadence=payload.get("cadence"),
                    evidence=[
                        self._evidence(
                            "bill",
                            source_id,
                            "explicit_observation" if observed else "definition",
                        )
                    ],
                    observation=(
                        TemporalObservation(
                            observed_date=occurrence_date,
                            amount=self._snapshot_float(payload.get("amount")),
                            confirmation="user_status",
                        )
                        if observed
                        else None
                    ),
                    assumptions=(
                        ["Paid status is explicit, but no ledger transaction is linked."]
                        if observed
                        else []
                    ),
                    as_of=as_of,
                )
            )
        return events

    def _historical_commitment_events(
        self,
        user_id: str,
        currency: str,
        source_id: str,
        payload: dict[str, Any],
        as_of: date,
        start: date,
        end: date,
    ) -> list[TemporalFinancialEvent]:
        if not payload.get("is_active", True):
            return []
        due_date = self._snapshot_date(payload.get("due_date"))
        if due_date is None:
            return []
        events: list[TemporalFinancialEvent] = []
        for occurrence_date in self._occurrences(due_date, payload.get("cadence"), start, end):
            events.append(
                self._event(
                    user_id=user_id,
                    source_type="commitment",
                    source_id=source_id,
                    occurrence_date=occurrence_date,
                    kind="commitment",
                    direction="outflow",
                    state=self._dated_state(occurrence_date, as_of),
                    label=str(payload.get("label") or "Commitment"),
                    currency=currency,
                    amount=self._snapshot_amount(payload.get("amount")),
                    confidence=0.98 if payload.get("confirmed") else 0.78,
                    sufficiency="high" if payload.get("confirmed") else "medium",
                    cadence=payload.get("cadence"),
                    evidence=[self._evidence("commitment", source_id, "definition")],
                    as_of=as_of,
                )
            )
        return events

    def _historical_liability_schedule_event(
        self,
        user_id: str,
        currency: str,
        source_id: str,
        payload: dict[str, Any],
        as_of: date,
        start: date,
        end: date,
    ) -> TemporalFinancialEvent | None:
        due_date = self._snapshot_date(payload.get("due_date"))
        if due_date is None or not start <= due_date <= end:
            return None
        status = str(payload.get("status") or "upcoming")
        observed = status == "paid"
        cancelled = status == "skipped"
        state: TemporalEventState = (
            "observed"
            if observed
            else "cancelled" if cancelled else self._dated_state(due_date, as_of)
        )
        source_kind = str(payload.get("source_kind") or "manual")
        amount = self._snapshot_amount(payload.get("installment_amount"))
        confidence = self._snapshot_float(payload.get("confidence")) or 0.8
        return self._event(
            user_id=user_id,
            source_type="liability_schedule",
            source_id=source_id,
            occurrence_date=due_date,
            kind="liability_installment",
            direction="outflow",
            state=state,
            label=str(payload.get("label") or "Liability instalment"),
            currency=currency,
            amount=amount,
            confidence=confidence,
            sufficiency="high" if payload.get("complete_schedule") else "medium",
            evidence=[
                self._evidence(
                    "liability_schedule",
                    source_id,
                    "explicit_observation" if observed else "definition",
                )
            ],
            observation=(
                TemporalObservation(
                    observed_date=due_date,
                    amount=self._snapshot_float(payload.get("installment_amount")),
                    confirmation="issuer_status" if source_kind == "statement" else "user_status",
                )
                if observed
                else None
            ),
            assumptions=(
                ["Paid schedule status has no linked ledger transaction."] if observed else []
            ),
            as_of=as_of,
        )

    @staticmethod
    def _snapshot_date(value: Any) -> date | None:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _snapshot_amount(value: Any) -> TemporalAmount:
        if value is None:
            return TemporalAmount()
        try:
            amount = float(Decimal(str(value)))
        except (ArithmeticError, ValueError):
            return TemporalAmount()
        return TemporalAmount(low=amount, expected=amount, high=amount)

    @staticmethod
    def _snapshot_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(Decimal(str(value)))
        except (ArithmeticError, ValueError):
            return None

    async def _cash_plan_events(
        self, user_id: str, currency: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        plan = await self.db.scalar(select(CashPlan).where(CashPlan.user_id == user_id))
        if (
            plan is None
            or plan.next_income_date is None
            or not start <= plan.next_income_date <= end
        ):
            return []
        return [
            self._event(
                user_id=user_id,
                source_type="cash_plan",
                source_id=plan.id,
                occurrence_date=plan.next_income_date,
                kind="income",
                direction="inflow",
                state=self._dated_state(plan.next_income_date, as_of),
                label="Planned income",
                currency=currency,
                amount=self._exact_amount(plan.next_income_amount),
                confidence=0.85,
                sufficiency="medium",
                evidence=[self._evidence("cash_plan", plan.id, "definition")],
                assumptions=["The date and amount are user planning inputs, not observed income."],
                as_of=as_of,
            )
        ]

    async def _bill_events(
        self,
        user_id: str,
        currency: str,
        timezone_name: str,
        as_of: date,
        start: date,
        end: date,
    ) -> list[TemporalFinancialEvent]:
        rows = list(
            (await self.db.scalars(select(RoadmapBill).where(RoadmapBill.user_id == user_id))).all()
        )
        events: list[TemporalFinancialEvent] = []
        for row in rows:
            occurrence_dates = [row.due_date]
            if row.status not in {"paid", "skipped"}:
                occurrence_dates = self._occurrences(row.due_date, row.cadence, start, end)
            for occurrence_date in occurrence_dates:
                if not start <= occurrence_date <= end:
                    continue
                observed = row.status == "paid" and occurrence_date == row.due_date
                cancelled = row.status == "skipped" and occurrence_date == row.due_date
                state: TemporalEventState = (
                    "observed"
                    if observed
                    else "cancelled" if cancelled else self._dated_state(occurrence_date, as_of)
                )
                events.append(
                    self._event(
                        user_id=user_id,
                        source_type="bill",
                        source_id=row.id,
                        occurrence_date=occurrence_date,
                        kind="subscription" if row.bill_type == "subscription" else "bill",
                        direction="outflow",
                        state=state,
                        label=row.label,
                        currency=currency,
                        amount=self._exact_amount(row.amount),
                        confidence=0.98 if row.confirmed else 0.8,
                        sufficiency="high" if row.confirmed else "medium",
                        cadence=row.cadence,
                        evidence=[
                            self._evidence(
                                "bill",
                                row.id,
                                "explicit_observation" if observed else "definition",
                            )
                        ],
                        observation=(
                            TemporalObservation(
                                observed_date=(
                                    self._financial_date(row.paid_at, timezone_name)
                                    if row.paid_at
                                    else row.due_date
                                ),
                                amount=float(row.amount),
                                confirmation="user_status",
                            )
                            if observed
                            else None
                        ),
                        assumptions=(
                            ["Paid status is explicit, but no ledger transaction is linked."]
                            if observed
                            else []
                        ),
                        as_of=as_of,
                    )
                )
        return events

    @staticmethod
    def _financial_date(value: datetime, timezone_name: str) -> date:
        """Convert stored UTC/naive timestamps to the user's financial day."""

        aware_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware_value.astimezone(ZoneInfo(timezone_name)).date()

    async def _commitment_events(
        self, user_id: str, currency: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        rows = list(
            (
                await self.db.scalars(
                    select(Commitment).where(
                        Commitment.user_id == user_id, Commitment.is_active.is_(True)
                    )
                )
            ).all()
        )
        events: list[TemporalFinancialEvent] = []
        for row in rows:
            for occurrence_date in self._occurrences(row.due_date, row.cadence, start, end):
                events.append(
                    self._event(
                        user_id=user_id,
                        source_type="commitment",
                        source_id=row.id,
                        occurrence_date=occurrence_date,
                        kind="commitment",
                        direction="outflow",
                        state=self._dated_state(occurrence_date, as_of),
                        label=row.label,
                        currency=currency,
                        amount=self._exact_amount(row.amount),
                        confidence=0.98 if row.confirmed else 0.78,
                        sufficiency="high" if row.confirmed else "medium",
                        cadence=row.cadence,
                        evidence=[self._evidence("commitment", row.id, "definition")],
                        as_of=as_of,
                    )
                )
        return events

    async def _liability_events(
        self, user_id: str, currency: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        rows = (
            await self.db.execute(
                select(LiabilityScheduleItem, Liability)
                .join(Liability, Liability.id == LiabilityScheduleItem.liability_id)
                .where(
                    LiabilityScheduleItem.user_id == user_id,
                    LiabilityScheduleItem.due_date >= start,
                    LiabilityScheduleItem.due_date <= end,
                )
            )
        ).all()
        events: list[TemporalFinancialEvent] = []
        for item, liability in rows:
            observed = item.status == "paid"
            state: TemporalEventState = (
                "observed"
                if observed
                else (
                    "cancelled"
                    if item.status == "skipped"
                    else self._dated_state(item.due_date, as_of)
                )
            )
            confidence = float(item.confidence or liability.source_confidence or Decimal("0.8"))
            events.append(
                self._event(
                    user_id=user_id,
                    source_type="liability_schedule",
                    source_id=item.id,
                    occurrence_date=item.due_date,
                    kind="liability_installment",
                    direction="outflow",
                    state=state,
                    label=liability.label,
                    currency=currency,
                    amount=self._exact_amount(item.installment_amount),
                    confidence=confidence,
                    sufficiency="high" if liability.complete_schedule else "medium",
                    evidence=[
                        self._evidence(
                            "liability_schedule",
                            item.id,
                            "explicit_observation" if observed else "definition",
                        )
                    ],
                    observation=(
                        TemporalObservation(
                            observed_date=item.due_date,
                            amount=float(item.installment_amount),
                            confirmation=(
                                "issuer_status"
                                if item.source_kind == "statement"
                                else "user_status"
                            ),
                        )
                        if observed
                        else None
                    ),
                    assumptions=(
                        ["Paid schedule status has no linked ledger transaction."]
                        if observed
                        else []
                    ),
                    as_of=as_of,
                )
            )
        return events

    async def _card_calendar_events(
        self, user_id: str, currency: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        rows = list(
            (
                await self.db.scalars(
                    select(CardCalendarEvent).where(
                        CardCalendarEvent.user_id == user_id,
                        CardCalendarEvent.event_date >= start,
                        CardCalendarEvent.event_date <= end,
                    )
                )
            ).all()
        )
        return [
            self._event(
                user_id=user_id,
                source_type="card_calendar",
                source_id=row.id,
                occurrence_date=row.event_date,
                kind="card_milestone",
                direction="neutral",
                state=self._dated_state(row.event_date, as_of),
                label=row.label,
                currency=currency,
                amount=TemporalAmount(),
                confidence=0.8,
                sufficiency="medium",
                evidence=[self._evidence("card_calendar", row.id, "definition")],
                assumptions=["Calendar milestones do not imply an amount or payment instruction."],
                as_of=as_of,
            )
            for row in rows
        ]

    async def _card_payment_intent_events(
        self, user_id: str, currency: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        rows = list(
            (
                await self.db.scalars(
                    select(CardPaymentIntent)
                    .where(
                        CardPaymentIntent.user_id == user_id,
                        CardPaymentIntent.planned_for >= start,
                        CardPaymentIntent.planned_for <= end,
                    )
                    .order_by(
                        CardPaymentIntent.planned_for.asc(), CardPaymentIntent.created_at.asc()
                    )
                )
            ).all()
        )
        return [
            self._card_payment_intent_event(
                user_id=user_id,
                currency=currency,
                source_id=row.id,
                planned_for=row.planned_for,
                amount=row.amount,
                status=row.status,
                note=row.note or "",
                transfer_group_id=row.transfer_group_id,
                as_of=as_of,
            )
            for row in rows
        ]

    def _card_payment_intent_event(
        self,
        *,
        user_id: str,
        currency: str,
        source_id: str,
        planned_for: date,
        amount: Any,
        status: str,
        note: str,
        transfer_group_id: str | None,
        as_of: date,
    ) -> TemporalFinancialEvent:
        normalized_status = status.lower()
        if normalized_status == "recorded":
            state: TemporalEventState = "observed"
            evidence_role: Literal[
                "definition", "pattern_observation", "explicit_observation", "match"
            ] = "explicit_observation"
            observation = TemporalObservation(
                observed_date=planned_for,
                amount=self._snapshot_float(amount),
                confirmation="user_status",
            )
            assumptions = [
                "Recorded status confirms a user-entered/manual transfer in PFIS; it is not issuer settlement proof.",
            ]
            if transfer_group_id:
                assumptions.append(
                    "The related transfer group is retained separately from this planning-source event."
                )
        elif normalized_status == "cancelled":
            state = "cancelled"
            evidence_role = "explicit_observation"
            observation = None
            assumptions = [
                "Cancellation is a user status and does not prove whether an external payment attempt occurred."
            ]
        else:
            state = self._dated_state(planned_for, as_of)
            evidence_role = "definition"
            observation = None
            assumptions = [
                "A payment intention is user planning evidence; it never contacts the bank or card issuer."
            ]
        label = "Card payment"
        if normalized_status == "recorded":
            label = "Recorded card payment"
        elif normalized_status == "cancelled":
            label = "Cancelled card payment"
        if note:
            label = f"{label} · {note}"
        return self._event(
            user_id=user_id,
            source_type="card_payment_intent",
            source_id=source_id,
            occurrence_date=planned_for,
            kind="commitment",
            direction="outflow",
            state=state,
            label=label,
            currency=currency,
            amount=self._snapshot_amount(amount),
            confidence=0.9 if normalized_status in {"recorded", "cancelled"} else 0.86,
            sufficiency="medium",
            evidence=[self._evidence("card_payment_intent", source_id, evidence_role)],
            observation=observation,
            assumptions=assumptions,
            as_of=as_of,
        )

    async def _reserve_events(
        self, user_id: str, currency: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        rows = list(
            (
                await self.db.scalars(
                    select(ReservePlan).where(
                        ReservePlan.user_id == user_id,
                        ReservePlan.approved.is_(True),
                        ReservePlan.is_active.is_(True),
                        ReservePlan.due_date >= start,
                        ReservePlan.due_date <= end,
                    )
                )
            ).all()
        )
        return [
            self._event(
                user_id=user_id,
                source_type="reserve_plan",
                source_id=row.id,
                occurrence_date=row.due_date,
                kind="reserve",
                direction="reserve",
                state=self._dated_state(row.due_date, as_of),
                label=row.label,
                currency=currency,
                amount=self._exact_amount(row.target_amount),
                confidence=0.98,
                sufficiency="high",
                evidence=[self._evidence("reserve_plan", row.id, "definition")],
                assumptions=["A reserve protects cash but is not itself a ledger outflow."],
                as_of=as_of,
            )
            for row in rows
        ]

    async def _recurring_expense_events(
        self, user_id: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        patterns = await RecurringPatternService(self.db).analyze(user_id, as_of=as_of)
        return self._pattern_events(
            user_id, patterns, "recurring_expense", "outflow", as_of, start, end
        )

    async def _income_pattern_events(
        self, user_id: str, as_of: date, start: date, end: date
    ) -> list[TemporalFinancialEvent]:
        rows = (
            await self.db.execute(
                select(
                    Transaction.id,
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    Transaction.amount,
                    Transaction.transaction_date,
                    Transaction.financial_account_id,
                    Transaction.currency,
                )
                .where(
                    Transaction.user_id == user_id,
                    income_event_predicate(),
                    Transaction.transaction_date <= as_of,
                )
                .order_by(Transaction.transaction_date.asc())
            )
        ).all()
        grouped: dict[tuple[str, str, str], list[tuple[date, float]]] = defaultdict(list)
        source_ids: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        labels: dict[tuple[str, str, str], str] = {}
        for row in rows:
            label = (row.merchant_normalized or row.merchant_raw or "Income").strip()
            key = (row.financial_account_id or "unassigned", label.casefold(), row.currency)
            labels[key] = label
            grouped[key].append((row.transaction_date, float(row.amount)))
            source_ids[key].append(row.id)
        patterns = [
            pattern
            for key, entries in grouped.items()
            if (
                pattern := RecurringPatternService._analyze_group(
                    labels[key],
                    entries,
                    as_of,
                    financial_account_id=None if key[0] == "unassigned" else key[0],
                    currency=key[2],
                    source_transaction_ids=tuple(source_ids[key]),
                )
            )
            is not None
        ]
        return self._pattern_events(user_id, patterns, "income", "inflow", as_of, start, end)

    def _pattern_events(
        self,
        user_id: str,
        patterns: list[RecurringPattern],
        kind: TemporalEventKind,
        direction: TemporalDirection,
        as_of: date,
        start: date,
        end: date,
    ) -> list[TemporalFinancialEvent]:
        events: list[TemporalFinancialEvent] = []
        for pattern in patterns:
            expected_date = pattern.next_expected_date
            if (
                expected_date is None
                or pattern.status not in {"early", "mature", "missed"}
                or not start <= expected_date <= end
            ):
                continue
            tolerance = self._pattern_tolerance(pattern.cadence)
            state: TemporalEventState = (
                "missed" if pattern.status == "missed" else self._dated_state(expected_date, as_of)
            )
            variance = max(0.03, (1 - pattern.amount_confidence) * 0.35)
            evidence = [
                self._evidence("transaction", transaction_id, "pattern_observation")
                for transaction_id in pattern.source_transaction_ids
            ]
            events.append(
                self._event(
                    user_id=user_id,
                    source_type="recurring_pattern",
                    source_id=pattern.stream_key,
                    occurrence_date=expected_date,
                    kind=kind,
                    direction=direction,
                    state=state,
                    label=pattern.merchant,
                    currency=pattern.currency,
                    amount=TemporalAmount(
                        low=round(pattern.avg_amount * (1 - variance), 2),
                        expected=pattern.avg_amount,
                        high=round(pattern.avg_amount * (1 + variance), 2),
                    ),
                    confidence=pattern.confidence,
                    sufficiency=cast(Literal["low", "medium", "high"], pattern.data_sufficiency),
                    cadence=pattern.cadence,
                    evidence=[
                        self._evidence("recurring_pattern", pattern.stream_key, "definition"),
                        *evidence,
                    ],
                    assumptions=[
                        "The event window comes from observed cadence, not a provider due date.",
                        "The amount range reflects observed amount consistency.",
                    ],
                    as_of=as_of,
                    window_start=expected_date - timedelta(days=tolerance),
                    window_end=expected_date + timedelta(days=tolerance),
                )
            )
        return events

    @staticmethod
    def _dated_state(expected_date: date, as_of: date) -> TemporalEventState:
        return "overdue" if expected_date < as_of else "expected"

    @staticmethod
    def _pattern_tolerance(cadence: str | None) -> int:
        return {
            "weekly": 2,
            "fortnightly": 3,
            "monthly": 5,
            "quarterly": 10,
            "annual": 20,
        }.get(cadence or "", 5)

    @staticmethod
    def _evidence(
        source_type: TemporalSourceType,
        source_id: str,
        role: Literal["definition", "pattern_observation", "explicit_observation", "match"],
    ) -> TemporalEvidenceReference:
        return TemporalEvidenceReference(source_type=source_type, source_id=source_id, role=role)

    @staticmethod
    def _exact_amount(value: Decimal | None) -> TemporalAmount:
        if value is None:
            return TemporalAmount()
        amount = float(value)
        return TemporalAmount(low=amount, expected=amount, high=amount)

    @staticmethod
    def _occurrences(seed: date, cadence: str | None, start: date, end: date) -> list[date]:
        if cadence is None:
            return [seed] if start <= seed <= end else []
        steps = 0
        if seed < start:
            if cadence == "weekly":
                steps = max(0, (start - seed).days // 7)
            else:
                interval_months = {"monthly": 1, "quarterly": 3, "annual": 12}[cadence]
                month_delta = (start.year - seed.year) * 12 + start.month - seed.month
                steps = max(0, month_delta // interval_months)
            current = TemporalEventService._advance_by(seed, cadence, steps)
            while current < start:
                steps += 1
                current = TemporalEventService._advance_by(seed, cadence, steps)
        else:
            current = seed
        occurrences: list[date] = []
        for _ in range(60):
            if current > end:
                break
            occurrences.append(current)
            steps += 1
            current = TemporalEventService._advance_by(seed, cadence, steps)
        return occurrences

    @staticmethod
    def _advance_by(value: date, cadence: str, steps: int) -> date:
        if cadence == "weekly":
            return value + timedelta(days=7 * steps)
        months = {"monthly": 1, "quarterly": 3, "annual": 12}[cadence] * steps
        absolute = value.year * 12 + value.month - 1 + months
        year, month_index = divmod(absolute, 12)
        month = month_index + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    @staticmethod
    def _event(
        *,
        user_id: str,
        source_type: TemporalSourceType,
        source_id: str,
        occurrence_date: date,
        kind: TemporalEventKind,
        direction: TemporalDirection,
        state: TemporalEventState,
        label: str,
        currency: str,
        amount: TemporalAmount,
        confidence: float,
        sufficiency: Literal["low", "medium", "high"],
        evidence: list[TemporalEvidenceReference],
        as_of: date,
        cadence: str | None = None,
        observation: TemporalObservation | None = None,
        assumptions: list[str] | None = None,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> TemporalFinancialEvent:
        event_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"pfis:{user_id}:{source_type}:{source_id}:{occurrence_date.isoformat()}:{kind}",
            )
        )
        return TemporalFinancialEvent(
            id=event_id,
            kind=kind,
            direction=direction,
            state=state,
            label=label,
            currency=currency,
            expected_date=occurrence_date,
            window_start=window_start or occurrence_date,
            window_end=window_end or occurrence_date,
            amount=amount,
            observation=observation,
            cadence=cadence,
            confidence=max(0.0, min(confidence, 1.0)),
            data_sufficiency=sufficiency,
            evidence=evidence,
            assumptions=assumptions or [],
            ruleset_version=TEMPORAL_EVENTS.version,
            data_through=as_of,
        )
