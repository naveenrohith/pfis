"""Schemas for deterministic subscription and recurring-payment review."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

SubscriptionLifecycle = Literal["candidate", "mature", "missed", "inactive"]
SubscriptionReviewAction = Literal["confirm", "mark_not_recurring", "cancelled"]


class SubscriptionReviewItem(BaseModel):
    schema_version: str = "pfis-subscription-review-item-1"
    id: str
    stream_key: str
    merchant: str
    lifecycle_status: SubscriptionLifecycle
    cadence: str | None = None
    typical_amount: float
    monthly_equivalent: float
    currency: str = "INR"
    amount_change_detected: bool = False
    amount_low: float
    amount_high: float
    occurrences: int
    cadence_confidence: float
    amount_confidence: float
    confidence: float
    last_seen: date
    next_expected: date | None = None
    next_expected_null_reason: str | None = None
    days_since_last_expected: int | None = None
    evidence_transaction_ids: list[str] = Field(default_factory=list)
    financial_account_id: str | None = None
    user_action: SubscriptionReviewAction | None = None
    action_id: str | None = None
    action_note: str | None = None
    action_updated_at: datetime | None = None
    ruleset_version: str


class SubscriptionReviewListResponse(BaseModel):
    schema_version: str = "pfis-subscription-review-list-1"
    as_of: date
    ruleset_version: str
    thresholds: dict[str, float | int | str]
    items: list[SubscriptionReviewItem] = Field(default_factory=list)
    excluded_count: int = 0


class SubscriptionReviewActionRequest(BaseModel):
    action: SubscriptionReviewAction
    note: str | None = Field(default=None, max_length=500)


class SubscriptionReviewActionResponse(BaseModel):
    schema_version: str = "pfis-subscription-review-action-1"
    id: str
    stream_key: str
    merchant: str
    action: SubscriptionReviewAction
    note: str | None = None
    created_at: datetime
    updated_at: datetime
