"""Deterministic financial-guidance API contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.dashboard import (
    RecommendationConflict,
    RecommendationConsequence,
    RecommendationGoalLink,
    RecommendationResolution,
)

GuidancePeriod = Literal["daily", "weekly", "monthly"]
RecommendationUserState = Literal["active", "dismissed", "snoozed", "accepted", "not_relevant"]
RecommendationOutcomeKind = Literal["helped", "no_change", "worse", "not_completed"]
RecommendationFeedbackReason = Literal[
    "not_relevant",
    "not_feasible",
    "already_done",
    "too_risky",
    "wrong_timing",
]


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
    smallest_action: str | None = None
    consequence: RecommendationConsequence | None = None
    conflicts: list[RecommendationConflict] = Field(default_factory=list)
    goal_links: list[RecommendationGoalLink] = Field(default_factory=list)
    resolution: RecommendationResolution = Field(
        default_factory=lambda: RecommendationResolution(
            rationale="No blocking conflict or competing goal was detected."
        )
    )
    confidence: float = 0.0
    freshness_as_of: date | None = None
    urgency: Literal["now", "this_period", "monitor"] = "monitor"
    reversibility: Literal["reversible", "review_required"] = "reversible"


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


class GuidanceEvidence(BaseModel):
    """A typed citation attached to one grounded query answer."""

    source_type: str
    source_id: str | None = None
    label: str
    value: str
    cutoff: date | None = None


class GuidanceQueryResult(BaseModel):
    supported: bool
    intent: str | None = None
    answer: str
    metrics: list[GuidanceMetric] = Field(default_factory=list)
    filters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    plan: list[str] = Field(default_factory=list)
    evidence: list[GuidanceEvidence] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    temporal_scope: str = "selected_calendar_month"
    suggested_actions: list[str] = Field(default_factory=list)
    supported_examples: list[str] = Field(default_factory=list)
    ruleset_version: str


class RecommendationStateUpdate(BaseModel):
    state: RecommendationUserState
    snoozed_until: datetime | None = None
    as_of: date | None = None
    note: str | None = Field(None, max_length=500)
    reason: RecommendationFeedbackReason | None = None

    @model_validator(mode="after")
    def validate_snooze(self):
        if self.state == "snoozed" and self.snoozed_until is None:
            raise ValueError("Snoozed recommendations require a resume time")
        if self.state != "snoozed" and self.snoozed_until is not None:
            raise ValueError("Only snoozed recommendations can include a resume time")
        if self.reason is not None and self.state != "not_relevant":
            raise ValueError(
                "Feedback reasons are only valid when a recommendation is not relevant"
            )
        return self


class RecommendationStateResponse(BaseModel):
    id: str
    recommendation_id: str
    state: RecommendationUserState
    snoozed_until: datetime | None = None
    recommendation_type: str | None = None
    title: str | None = None
    target: str | None = None
    expected_impact: str | None = None
    smallest_action: str | None = None
    consequence: RecommendationConsequence | None = None
    conflicts: list[RecommendationConflict] = Field(default_factory=list)
    goal_links: list[RecommendationGoalLink] = Field(default_factory=list)
    resolution: RecommendationResolution = Field(
        default_factory=lambda: RecommendationResolution(
            rationale="No blocking conflict or competing goal was detected."
        )
    )
    confidence: float = Field(0.0, ge=0, le=1)
    freshness_as_of: date | None = None
    urgency: Literal["now", "this_period", "monitor"] = "monitor"
    reversibility: Literal["reversible", "review_required"] = "reversible"
    evidence: list[RecommendationEvidence] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    guidance_ruleset_version: str | None = None
    decision_as_of: date | None = None
    decision_note: str | None = None
    decision_reason: RecommendationFeedbackReason | None = None
    baseline_metric_key: str | None = None
    baseline_metric_value: float | None = None
    baseline_metric_unit: str | None = None
    decided_at: datetime | None = None
    updated_at: datetime


class RecommendationOutcomeCreate(BaseModel):
    outcome: RecommendationOutcomeKind
    note: str | None = Field(None, max_length=500)
    actual_impact_value: Decimal | None = Field(None, max_digits=18, decimal_places=2)
    actual_impact_unit: Literal["currency", "records", "percentage_points"] | None = None

    @model_validator(mode="after")
    def validate_impact(self):
        if (self.actual_impact_value is None) != (self.actual_impact_unit is None):
            raise ValueError("Impact value and unit must be supplied together")
        return self


class RecommendationOutcomeResponse(BaseModel):
    id: str
    decision_id: str
    outcome: RecommendationOutcomeKind
    note: str | None = None
    actual_impact_value: float | None = None
    actual_impact_unit: str | None = None
    baseline_metric_value: float | None = None
    observed_metric_value: float | None = None
    automatic_impact_value: float | None = None
    metric_key: str | None = None
    metric_unit: str | None = None
    outcome_ruleset_version: str
    observed_at: datetime


class RecommendationEffectivenessCohort(BaseModel):
    recommendation_type: str
    guidance_ruleset_version: str
    outcome_ruleset_version: str
    metric_key: str | None = None
    metric_unit: str | None = None
    sample_size: int = Field(..., ge=0)
    unique_users: int = Field(..., ge=0)
    completed_rate: float | None = Field(None, ge=0, le=1)
    helped_rate: float | None = Field(None, ge=0, le=1)
    measured_evidence_status: Literal["available", "insufficient_sample"]
    measured_sample_size: int = Field(..., ge=0)
    measured_unique_users: int = Field(default=0, ge=0)
    measured_improvement_rate: float | None = Field(None, ge=0, le=1)
    mean_automatic_impact: float | None = None
    user_measurement_agreement_rate: float | None = Field(None, ge=0, le=1)


class RecommendationEffectivenessReport(BaseModel):
    generated_at: datetime
    window_started_at: datetime
    window_days: int = Field(..., ge=1)
    minimum_sample_size: int = Field(..., ge=1)
    minimum_unique_users: int = Field(..., ge=1)
    evidence_status: Literal["available", "insufficient_sample"]
    eligible_outcome_count: int = Field(..., ge=0)
    suppressed_cohort_count: int = Field(..., ge=0)
    cohorts: list[RecommendationEffectivenessCohort] = Field(default_factory=list)
    effectiveness_ruleset_version: str
