"""Deterministic financial-guidance API contracts."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

GuidancePeriod = Literal["daily", "weekly", "monthly"]
RecommendationUserState = Literal["active", "dismissed", "snoozed"]


class RecommendationEvidence(BaseModel):
    label: str
    value: str


class GuidanceAction(BaseModel):
    id: str
    type: str
    priority: int = Field(..., ge=1, le=100)
    title: str
    description: str
    action_label: str
    target: str
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[RecommendationEvidence] = Field(default_factory=list)
    expected_impact: str | None = None


class GuidanceBrief(BaseModel):
    period: GuidancePeriod
    as_of: date
    headline: str
    summary: str
    health_score: int
    status: str
    changes: list[str] = Field(default_factory=list)
    actions: list[GuidanceAction] = Field(default_factory=list)
    data_through: date
    ruleset_version: str


class GuidanceQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=240)
    month: int | None = Field(None, ge=1, le=12)
    year: int | None = Field(None, ge=2020, le=2035)


class GuidanceMetric(BaseModel):
    label: str
    value: str


class GuidanceQueryResult(BaseModel):
    supported: bool
    intent: str | None = None
    answer: str
    metrics: list[GuidanceMetric] = Field(default_factory=list)
    filters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    suggested_actions: list[str] = Field(default_factory=list)
    supported_examples: list[str] = Field(default_factory=list)
    ruleset_version: str


class RecommendationStateUpdate(BaseModel):
    state: RecommendationUserState
    snoozed_until: datetime | None = None


class RecommendationStateResponse(BaseModel):
    recommendation_id: str
    state: RecommendationUserState
    snoozed_until: datetime | None = None
    updated_at: datetime
