"""Public, non-secret product capability and recovery contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CapabilityStatus = Literal["beta", "best_effort", "deferred"]
IntelligenceReadinessStatus = Literal["ready", "collecting", "blocked", "deferred"]


class ProductCapabilitySource(BaseModel):
    key: str
    label: str
    status: CapabilityStatus
    scope: str
    freshness: str
    limitations: list[str] = Field(default_factory=list)


class ProductRecoveryPath(BaseModel):
    code: str
    label: str
    target: str
    description: str


class ProductCapabilitiesResponse(BaseModel):
    schema_version: str = "pfis-capabilities-1"
    product_stage: Literal["beta", "product_candidate", "production"] = "beta"
    incident_status: Literal["not_configured", "operational"] = "not_configured"
    incident_message: str
    sources: list[ProductCapabilitySource] = Field(default_factory=list)
    recovery_paths: list[ProductRecoveryPath] = Field(default_factory=list)


class IntelligenceReadinessGate(BaseModel):
    """One evidence gate in the path from beta intelligence to product release."""

    key: str
    label: str
    status: IntelligenceReadinessStatus
    summary: str
    next_step: str
    target: str | None = None
    evidence: list[str] = Field(default_factory=list)


class TemporalHistoryReadiness(BaseModel):
    """Coverage of immutable source history used by leakage-safe evaluation."""

    transaction_rows: int = Field(..., ge=0)
    transaction_snapshots: int = Field(..., ge=0)
    transaction_coverage_pct: float = Field(..., ge=0, le=100)
    account_rows: int = Field(..., ge=0)
    account_snapshots: int = Field(..., ge=0)
    account_coverage_pct: float = Field(..., ge=0, le=100)
    statement_line_rows: int = Field(default=0, ge=0)
    statement_line_snapshots: int = Field(default=0, ge=0)
    statement_line_coverage_pct: float = Field(default=100.0, ge=0, le=100)
    card_payment_intent_rows: int = Field(default=0, ge=0)
    card_payment_intent_snapshots: int = Field(default=0, ge=0)
    card_payment_intent_coverage_pct: float = Field(default=100.0, ge=0, le=100)
    forward_only: bool = True


class ForecastReadiness(BaseModel):
    """Per-user forecast evidence without pretending a small cohort is general proof."""

    evaluated_months: int = Field(..., ge=0)
    eligible_horizons: int = Field(..., ge=0)
    interval_coverage_floor_pct: float = Field(..., ge=0, le=100)
    maximum_mape_pct: float = Field(..., ge=0)
    temporal_evidence_evaluated: bool = False
    transaction_history_coverage_pct: float = Field(..., ge=0, le=100)
    category_mix_supported_periods: int = Field(default=0, ge=0)
    daily_snapshot_count: int = Field(default=0, ge=0)
    daily_outcome_count: int = Field(default=0, ge=0)
    daily_interval_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    daily_mean_absolute_error: float | None = Field(default=None, ge=0)


class ReconciliationReadiness(BaseModel):
    """Cross-source ledger truth evidence for this workspace."""

    status: IntelligenceReadinessStatus
    evidence_score: int = Field(..., ge=0, le=100)
    transaction_review_coverage_pct: float = Field(..., ge=0, le=100)
    statement_resolution_coverage_pct: float = Field(..., ge=0, le=100)
    account_reconciliation_coverage_pct: float = Field(..., ge=0, le=100)
    unresolved_items: int = Field(..., ge=0)
    duplicate_candidate_groups: int = Field(..., ge=0)
    unexplained_movements: int = Field(..., ge=0)


class ReconciliationQualityResponse(BaseModel):
    """Explainable cross-source reconciliation quality, never a completeness claim."""

    schema_version: str = "pfis-reconciliation-quality-1"
    as_of: datetime
    status: IntelligenceReadinessStatus
    evidence_score: int = Field(..., ge=0, le=100)
    transaction_total: int = Field(..., ge=0)
    transaction_reviewed: int = Field(..., ge=0)
    transaction_needs_review: int = Field(..., ge=0)
    transaction_ignored: int = Field(..., ge=0)
    transaction_review_coverage_pct: float = Field(..., ge=0, le=100)
    account_total: int = Field(..., ge=0)
    accounts_with_history: int = Field(..., ge=0)
    accounts_reconciled: int = Field(..., ge=0)
    accounts_needs_review: int = Field(..., ge=0)
    accounts_not_ready: int = Field(..., ge=0)
    account_reconciliation_coverage_pct: float = Field(..., ge=0, le=100)
    statement_line_total: int = Field(..., ge=0)
    statement_lines_matched: int = Field(..., ge=0)
    statement_lines_newly_imported: int = Field(..., ge=0)
    statement_lines_ignored: int = Field(..., ge=0)
    statement_lines_needs_review: int = Field(..., ge=0)
    statement_resolution_coverage_pct: float = Field(..., ge=0, le=100)
    duplicate_candidate_groups: int = Field(..., ge=0)
    unexplained_movements: int = Field(..., ge=0)
    unresolved_items: int = Field(..., ge=0)
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class IntelligenceReadinessResponse(BaseModel):
    """Machine-readable readiness view for the product's intelligence proof gates."""

    schema_version: str = "pfis-intelligence-readiness-1"
    as_of: datetime
    product_stage: Literal["beta", "product_candidate", "production"] = "beta"
    overall_status: IntelligenceReadinessStatus
    evidence_readiness_score: int = Field(..., ge=0, le=100)
    source_coverage_score: int = Field(..., ge=0, le=100)
    temporal_history: TemporalHistoryReadiness
    forecast: ForecastReadiness
    reconciliation: ReconciliationReadiness
    recommendation_evidence_status: IntelligenceReadinessStatus
    gates: list[IntelligenceReadinessGate] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
