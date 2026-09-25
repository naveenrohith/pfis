"""
Pydantic Schemas for the Financial Decision Workspace.

The workspace endpoint (`GET /api/dashboard/workspace`) returns a single
aggregate DTO composed of a monthly snapshot, a financial timeline, insight
cards, deterministic recommendations, a review summary, and a sync summary.

These schemas are additive: existing transaction, insight, budget, and gmail
schemas remain unchanged.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.intelligence import (
    CashFlowProjection,
    FinancialHealthScore,
    MonthComparison,
    RecommendationConstraintCheck,
    RecommendationRankReason,
    RecommendationRankStatus,
)


class WorkspaceSnapshot(BaseModel):
    """Command-center headline metrics for the selected month."""

    income: float = 0.0
    spend: float = 0.0
    savings: float = 0.0
    net_cash_flow: float = 0.0
    transaction_count: int = 0
    review_count: int = 0
    budget_risk_count: int = 0
    sync_status: str = "idle"


class MonthlySnapshotCoverage(BaseModel):
    incomplete_month: bool = False
    latest_transaction_date: date | None = None
    data_freshness_days: int | None = None
    latest_sync_status: str | None = None
    last_synced_at: str | None = None


class MonthlySnapshotCategory(BaseModel):
    category_id: str | None = None
    name: str
    icon: str | None = None
    total: float = 0.0
    count: int = 0


class MonthlySnapshotMerchant(BaseModel):
    name: str
    total: float = 0.0
    count: int = 0


class MonthlySnapshotBudgetStatus(BaseModel):
    category: str | None = None
    limit: float = 0.0
    actual: float = 0.0
    usage_pct: float = 0.0
    status: str


class MonthlySnapshotResponse(BaseModel):
    month: int
    year: int
    month_label: str
    income: float = 0.0
    spend: float = 0.0
    net: float = 0.0
    transaction_count: int = 0
    top_categories: list[MonthlySnapshotCategory] = Field(default_factory=list)
    top_merchants: list[MonthlySnapshotMerchant] = Field(default_factory=list)
    budget_status: list[MonthlySnapshotBudgetStatus] = Field(default_factory=list)
    recurring_changes: list[dict[str, object]] = Field(default_factory=list)
    notable_anomalies: list[dict[str, object]] = Field(default_factory=list)
    coverage: MonthlySnapshotCoverage = Field(default_factory=MonthlySnapshotCoverage)


class TimelineEvent(BaseModel):
    """A single financial movement rendered on the timeline."""

    type: str  # income | subscription | bill | shopping | refund | spending | transfer
    label: str
    merchant: str | None = None
    category: str | None = None
    amount: float = 0.0
    direction: str = "out"  # in | out
    date: str
    payment_method: str = "other"
    transaction_status: str = "completed"
    confidence: float = 0.0


class WorkspaceInsight(BaseModel):
    """Action-oriented insight card (mirrors insights service card shape)."""

    type: str | None = None
    icon: str | None = None
    title: str
    description: str
    severity: str = "info"


class RecommendationConsequence(BaseModel):
    """A bounded consequence range with an explicit calculation basis."""

    metric: str
    unit: Literal["currency", "records", "percentage_points"]
    low: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    currency: str | None = None
    basis: str


class RecommendationConflict(BaseModel):
    """A trade-off, data gap, or overlapping impact that changes actionability."""

    code: str
    kind: Literal["data_gap", "tradeoff", "overlap"]
    severity: Literal["info", "warning", "blocking"]
    title: str
    description: str
    related_type: str | None = None
    related_goal_id: str | None = None


class RecommendationGoalLink(BaseModel):
    goal_id: str
    label: str
    relationship: Literal["supports", "conflicts"]
    remaining_amount: float | None = None
    currency: str | None = None


class RecommendationResolution(BaseModel):
    """The deterministic next step when an action has trade-offs or data gaps."""

    status: Literal["ready", "needs_review", "blocked", "choose"] = "ready"
    label: str = "Ready to review"
    next_step: str = "Review the evidence before acting."
    rationale: str
    related_recommendation_ids: list[str] = Field(default_factory=list)
    primary_goal_id: str | None = None
    competing_goal_ids: list[str] = Field(default_factory=list)


class WorkspaceRecommendation(BaseModel):
    """A deterministic, actionable recommendation derived from analytics."""

    type: str  # savings | recurring | budget | anomaly | review
    severity: str = "info"
    title: str
    description: str
    action_label: str
    target: str  # frontend section id to route to
    id: str = ""
    priority: int = 50
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[dict[str, str]] = Field(default_factory=list)
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
    ruleset_version: str | None = None
    ranker_ruleset_version: str | None = None
    rank_score: float | None = None
    rank_reasons: list[RecommendationRankReason] = Field(default_factory=list)
    constraint_checks: list[RecommendationConstraintCheck] = Field(default_factory=list)
    evidence_cutoff: date | None = None
    recommendation_status: RecommendationRankStatus = "ranked"
    missing_evidence: list[str] = Field(default_factory=list)


class ReviewSummary(BaseModel):
    """Low-confidence / unreviewed transaction rollup."""

    pending_count: int = 0
    low_confidence_count: int = 0
    avg_confidence: float | None = None


class SyncSummary(BaseModel):
    """Latest sync status surfaced on the command center."""

    latest_status: str | None = None
    last_synced_at: str | None = None
    processed_total: int = 0
    unprocessed_total: int = 0


class WorkspaceResponse(BaseModel):
    """Aggregate response for the Financial Decision Workspace."""

    month: int
    year: int
    snapshot: WorkspaceSnapshot
    timeline: list[TimelineEvent] = Field(default_factory=list)
    insights: list[WorkspaceInsight] = Field(default_factory=list)
    recommendations: list[WorkspaceRecommendation] = Field(default_factory=list)
    review_summary: ReviewSummary
    sync_summary: SyncSummary
    projection: CashFlowProjection
    month_comparison: MonthComparison
    financial_health: FinancialHealthScore
    recurring_commitments: list[dict] = Field(default_factory=list)
