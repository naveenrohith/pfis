"""Deterministic review workflow over the shared recurring-pattern read model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import SubscriptionReviewAction
from app.services.financial_clock import user_financial_today
from app.services.knowledge.recurring_knowledge import RecurringPattern, RecurringPatternService
from app.services.knowledge.ruleset_registry import RECURRING_PATTERN

MATURE_MIN_OCCURRENCES = 3
MATURE_MIN_CADENCE_CONFIDENCE = 0.70
MISSED_GRACE_FRACTION = 0.50
MISSED_MIN_GRACE_DAYS = 7
INACTIVE_GRACE_MULTIPLIER = 2.00
INACTIVE_MIN_GRACE_DAYS = 30
AMOUNT_CHANGE_RELATIVE_THRESHOLD = 0.10
AMOUNT_CHANGE_ABSOLUTE_THRESHOLD = 100.0
EXCLUDING_ACTIONS = {"mark_not_recurring", "cancelled"}
ALLOWED_ACTIONS = {"confirm", "mark_not_recurring", "cancelled"}


@dataclass(frozen=True, slots=True)
class DerivedLifecycle:
    status: str
    next_expected: date | None
    next_expected_null_reason: str | None
    days_since_last_expected: int | None


class SubscriptionReviewService:
    """Review recurring merchant streams without inventing a new detector."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_items(self, user_id: str, *, as_of: date | None = None) -> dict:
        as_of = as_of or await user_financial_today(self.db, user_id)
        patterns = await RecurringPatternService(self.db).analyze(user_id, as_of=as_of)
        actions = await self._actions_by_stream(user_id)

        items = []
        excluded_count = 0
        for pattern in patterns:
            action = actions.get(pattern.stream_key)
            if action is not None and action.action in EXCLUDING_ACTIONS:
                excluded_count += 1
                continue
            items.append(self._item_payload(pattern, as_of, action))

        items.sort(
            key=lambda item: (
                {"mature": 0, "missed": 1, "candidate": 2, "inactive": 3}[item["lifecycle_status"]],
                -item["monthly_equivalent"],
                item["merchant"].casefold(),
            )
        )
        return {
            "schema_version": "pfis-subscription-review-list-1",
            "as_of": as_of,
            "ruleset_version": RECURRING_PATTERN.version,
            "thresholds": self.thresholds(),
            "items": items,
            "excluded_count": excluded_count,
        }

    async def record_action(
        self,
        user_id: str,
        stream_key: str,
        *,
        action: str,
        note: str | None = None,
        as_of: date | None = None,
    ) -> dict:
        if action not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=422, detail="Unsupported subscription review action")

        existing = await self._action(user_id, stream_key)
        pattern = await self._pattern(user_id, stream_key, as_of=as_of)
        if pattern is None and existing is None:
            raise HTTPException(status_code=404, detail="Recurring stream not found")
        if pattern is None and existing is not None and existing.action != action:
            raise HTTPException(status_code=404, detail="Recurring stream not found")

        now = datetime.now(UTC)
        if existing is None:
            assert pattern is not None
            existing = SubscriptionReviewAction(
                user_id=user_id,
                stream_key=stream_key,
                merchant=pattern.merchant,
                financial_account_id=pattern.financial_account_id,
                currency=pattern.currency,
                action=action,
                note=note,
                created_at=now,
                updated_at=now,
            )
            self.db.add(existing)
        else:
            if pattern is not None:
                existing.merchant = pattern.merchant
                existing.financial_account_id = pattern.financial_account_id
                existing.currency = pattern.currency
            existing.action = action
            existing.note = note
            existing.updated_at = now

        await self.db.commit()
        await self.db.refresh(existing)
        return self._action_payload(existing)

    async def _pattern(
        self, user_id: str, stream_key: str, *, as_of: date | None = None
    ) -> RecurringPattern | None:
        patterns = await RecurringPatternService(self.db).analyze(user_id, as_of=as_of)
        return next((pattern for pattern in patterns if pattern.stream_key == stream_key), None)

    async def _actions_by_stream(self, user_id: str) -> dict[str, SubscriptionReviewAction]:
        result = await self.db.execute(
            select(SubscriptionReviewAction).where(SubscriptionReviewAction.user_id == user_id)
        )
        return {action.stream_key: action for action in result.scalars().all()}

    async def _action(self, user_id: str, stream_key: str) -> SubscriptionReviewAction | None:
        result = await self.db.execute(
            select(SubscriptionReviewAction).where(
                SubscriptionReviewAction.user_id == user_id,
                SubscriptionReviewAction.stream_key == stream_key,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def thresholds() -> dict[str, float | int | str]:
        return {
            "mature_min_occurrences": MATURE_MIN_OCCURRENCES,
            "mature_min_cadence_confidence": MATURE_MIN_CADENCE_CONFIDENCE,
            "missed_grace_days": (
                f"max({MISSED_MIN_GRACE_DAYS}, "
                f"round({MISSED_GRACE_FRACTION} * median_interval_days))"
            ),
            "inactive_grace_days": (
                f"max({INACTIVE_MIN_GRACE_DAYS}, "
                f"round({INACTIVE_GRACE_MULTIPLIER} * median_interval_days))"
            ),
            "amount_change_relative_threshold": AMOUNT_CHANGE_RELATIVE_THRESHOLD,
            "amount_change_absolute_threshold": AMOUNT_CHANGE_ABSOLUTE_THRESHOLD,
        }

    @staticmethod
    def _item_payload(
        pattern: RecurringPattern,
        as_of: date,
        action: SubscriptionReviewAction | None,
    ) -> dict:
        lifecycle = SubscriptionReviewService._derive_lifecycle(pattern, as_of)
        amount_band = pattern.amount_high - pattern.amount_low
        relative_band = amount_band / pattern.avg_amount if pattern.avg_amount > 0 else 0.0
        amount_change_detected = (
            pattern.occurrences >= 3
            and amount_band > 0
            and (
                relative_band >= AMOUNT_CHANGE_RELATIVE_THRESHOLD
                or amount_band >= AMOUNT_CHANGE_ABSOLUTE_THRESHOLD
            )
        )
        return {
            "schema_version": "pfis-subscription-review-item-1",
            "id": pattern.stream_key,
            "stream_key": pattern.stream_key,
            "merchant": pattern.merchant,
            "lifecycle_status": lifecycle.status,
            "cadence": pattern.cadence,
            "typical_amount": pattern.avg_amount,
            "monthly_equivalent": pattern.monthly_equivalent,
            "currency": pattern.currency,
            "amount_change_detected": amount_change_detected,
            "amount_low": pattern.amount_low,
            "amount_high": pattern.amount_high,
            "occurrences": pattern.occurrences,
            "cadence_confidence": pattern.cadence_confidence,
            "amount_confidence": pattern.amount_confidence,
            "confidence": pattern.confidence,
            "last_seen": pattern.last_seen,
            "next_expected": lifecycle.next_expected,
            "next_expected_null_reason": lifecycle.next_expected_null_reason,
            "days_since_last_expected": lifecycle.days_since_last_expected,
            "evidence_transaction_ids": list(pattern.source_transaction_ids),
            "financial_account_id": pattern.financial_account_id,
            "user_action": action.action if action else None,
            "action_id": action.id if action else None,
            "action_note": action.note if action else None,
            "action_updated_at": action.updated_at if action else None,
            "ruleset_version": pattern.ruleset_version,
        }

    @staticmethod
    def _derive_lifecycle(pattern: RecurringPattern, as_of: date) -> DerivedLifecycle:
        if pattern.cadence is None or pattern.median_interval_days is None:
            return DerivedLifecycle("candidate", None, "cadence_not_regular", None)

        expected = RecurringPatternService._advance_expected_date(
            pattern.last_seen,
            pattern.cadence,
            pattern.median_interval_days,
        )
        days_since_expected = max(0, (as_of - expected).days)
        is_mature_cadence = (
            pattern.occurrences >= MATURE_MIN_OCCURRENCES
            and pattern.cadence_confidence >= MATURE_MIN_CADENCE_CONFIDENCE
        )
        if not is_mature_cadence:
            reason = (
                "insufficient_occurrences"
                if pattern.occurrences < MATURE_MIN_OCCURRENCES
                else "cadence_confidence_below_mature_threshold"
            )
            return DerivedLifecycle("candidate", None, reason, days_since_expected)

        missed_grace_days = max(
            MISSED_MIN_GRACE_DAYS,
            round(MISSED_GRACE_FRACTION * pattern.median_interval_days),
        )
        inactive_grace_days = max(
            INACTIVE_MIN_GRACE_DAYS,
            round(INACTIVE_GRACE_MULTIPLIER * pattern.median_interval_days),
        )
        if days_since_expected > inactive_grace_days:
            return DerivedLifecycle(
                "inactive",
                None,
                "stream_inactive_after_multiple_missed_cycles",
                days_since_expected,
            )
        if days_since_expected > missed_grace_days:
            return DerivedLifecycle(
                "missed",
                None,
                "payment_past_expected_grace",
                days_since_expected,
            )
        return DerivedLifecycle("mature", expected, None, days_since_expected)

    @staticmethod
    def _action_payload(action: SubscriptionReviewAction) -> dict:
        return {
            "schema_version": "pfis-subscription-review-action-1",
            "id": action.id,
            "stream_key": action.stream_key,
            "merchant": action.merchant,
            "action": action.action,
            "note": action.note,
            "created_at": action.created_at,
            "updated_at": action.updated_at,
        }
