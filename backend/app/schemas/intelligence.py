"""Schemas for merchant, category, analytics, goals, and explanations."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.forecast_drift import ForecastDriftStatusResponse

Severity = Literal["info", "success", "warning", "danger"]
GoalType = Literal["savings", "category_reduction", "recurring_reduction"]
DataSufficiency = Literal["low", "medium", "high"]
DataConfidenceStatus = Literal["strong", "watch", "limited"]
DataConfidenceKey = Literal["coverage", "freshness", "parsing", "conflicts"]
SourceCoverageStatus = Literal["current", "stale", "partial", "unknown", "disconnected", "error"]
SourceCoverageCompleteness = Literal["known", "partial", "unknown"]
ForecastCalibrationStatus = Literal[
    "same_month_supported",
    "mix_supported",
    "supported",
    "insufficient_history",
    "not_applicable",
]
RecommendationRankStatus = Literal["ranked", "withheld", "excluded"]
RecommendationConstraintStatus = Literal["passed", "failed"]


class EvidenceItem(BaseModel):
    label: str
    value: str


class RecommendationRankReason(BaseModel):
    code: str
    detail: str
    weight: float


class RecommendationConstraintCheck(BaseModel):
    name: str
    status: RecommendationConstraintStatus
    reason: str


class TransactionPreview(BaseModel):
    id: str
    merchant: str
    category: str | None = None
    amount: float
    transaction_type: str
    transaction_date: date
    confidence_score: float
    reviewed_flag: bool


class MerchantSummary(BaseModel):
    merchant_key: str
    name: str
    total_spend: float = 0.0
    transaction_count: int = 0
    avg_spend: float = 0.0
    month_change_pct: float | None = None
    category: str | None = None
    category_id: str | None = None
    recurrence_likelihood: float = 0.0
    recurrence_status: str = "candidate"
    recurrence_cadence: str | None = None
    recurrence_confidence: float = 0.0
    next_expected_date: date | None = None
    data_sufficiency: DataSufficiency = "low"
    latest_transaction_date: date | None = None


class MerchantDetail(MerchantSummary):
    aliases: list[str] = Field(default_factory=list)
    default_category_id: str | None = None
    latest_transactions: list[TransactionPreview] = Field(default_factory=list)


class MerchantUpdate(BaseModel):
    normalized_name: str | None = Field(None, min_length=1, max_length=255)
    default_category_id: str | None = None
    aliases: list[Annotated[str, Field(min_length=1, max_length=255)]] | None = Field(
        None, max_length=100
    )
    apply_existing: bool = True


class LearnedMerchantRule(BaseModel):
    id: str
    raw_descriptor: str
    normalized_name: str
    category_id: str | None = None
    source: str
    confidence: float
    source_transaction_id: str | None = None
    created_at: datetime
    updated_at: datetime


class CategoryTopMerchant(BaseModel):
    name: str
    total: float
    count: int


class CategoryIntelligenceItem(BaseModel):
    category_id: str | None
    name: str
    parent_category_id: str | None = None
    parent_name: str | None = None
    icon: str | None = None
    total_spend: float = 0.0
    transaction_count: int = 0
    month_change_pct: float | None = None
    budget_limit: float | None = None
    budget_usage_pct: float | None = None
    top_merchants: list[CategoryTopMerchant] = Field(default_factory=list)


class CategoryIntelligenceResponse(BaseModel):
    month: int
    year: int
    categories: list[CategoryIntelligenceItem] = Field(default_factory=list)


class SpendingAnomaly(BaseModel):
    """A material category or merchant departure from the user's own history."""

    id: str
    kind: Literal["category", "merchant"]
    predicted_alert: bool = True
    label: str
    current_amount: float = Field(..., ge=0)
    baseline_amount: float = Field(..., ge=0)
    delta_amount: float = Field(..., ge=0)
    delta_pct: float = Field(..., ge=0)
    robust_score: float = Field(..., ge=0)
    history_periods: int = Field(..., ge=0)
    transaction_count: int = Field(..., ge=0)
    confidence: float = Field(..., ge=0, le=1)
    data_sufficiency: DataSufficiency = "medium"
    severity: Literal["info", "warning"] = "warning"
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ruleset_version: str = "pfis-anomaly-2"
    adjudication: Literal["expected", "material", "insufficient_evidence"] | None = None
    adjudication_note: str | None = None


class AnomalyAdjudicationRequest(BaseModel):
    """Explicit user feedback; it never asserts fraud or causality."""

    decision: Literal["expected", "material", "insufficient_evidence"]
    note: str | None = Field(default=None, max_length=500)


class AnomalyAdjudicationResponse(BaseModel):
    schema_version: str = "pfis-anomaly-adjudication-1"
    id: str
    anomaly_id: str
    predicted_alert: bool = True
    kind: Literal["category", "merchant"]
    label: str
    period_start: date
    period_end: date
    decision: Literal["expected", "material", "insufficient_evidence"]
    note: str | None = None
    current_amount: float
    baseline_amount: float
    delta_amount: float
    confidence: float
    transaction_count: int
    ruleset_version: str
    created_at: datetime


class InsightsResponse(BaseModel):
    """Typed monthly insights payload with optional evidence-backed anomalies."""

    insights: list[dict] = Field(default_factory=list)
    daily_trend: list[dict] = Field(default_factory=list)
    recurring_payments: list[dict] = Field(default_factory=list)
    anomalies: list[SpendingAnomaly] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class CashFlowProjection(BaseModel):
    month: int
    year: int
    income: float = 0.0
    spend_to_date: float = 0.0
    net_to_date: float = 0.0
    projected_spend: float = 0.0
    projected_net: float = 0.0
    daily_spend_rate: float = 0.0
    days_elapsed: int = 0
    days_in_month: int = 0
    recurring_commitments: float = 0.0
    confirmed_commitments: float = 0.0
    expected_income: float = 0.0
    flexible_spend_projection: float = 0.0
    budgeted_remaining: float = 0.0
    projected_range_low: float = 0.0
    projected_range_high: float = 0.0
    interval_calibration: Literal["same_cutoff_empirical", "robust_history", "low_evidence"] = (
        "low_evidence"
    )
    interval_calibration_samples: int = Field(default=0, ge=0)
    interval_target_coverage_pct: float = Field(default=80.0, ge=0, le=100)
    category_mix_status: ForecastCalibrationStatus = "insufficient_history"
    category_mix_sample_months: int = Field(default=0, ge=0)
    category_mix_adjustment: float = 0.0
    pay_cycle_status: ForecastCalibrationStatus = "not_applicable"
    pay_cycle_sample_count: int = Field(default=0, ge=0)
    temporal_expected_income: float = 0.0
    temporal_expected_outflows: float = 0.0
    temporal_conflicted_outflows: float = 0.0
    temporal_event_count: int = 0
    temporal_conflict_count: int = 0
    temporal_ruleset_version: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: float = 0.0
    data_sufficiency: DataSufficiency = "low"
    historical_months: int = 0
    data_through: date | None = None
    ruleset_version: str = "pfis-cash-flow-6"


class ForecastBacktestExclusion(BaseModel):
    month: int
    year: int
    reason: Literal["insufficient_prior_history", "no_observed_spend"]


class ForecastHorizonMetrics(BaseModel):
    cutoff_day: int
    eligible_periods: int
    mean_absolute_error: float | None = None
    median_absolute_percentage_error: float | None = None
    weighted_absolute_percentage_error: float | None = None
    interval_coverage_pct: float | None = None
    interval_coverage_gap_pct: float | None = None
    average_interval_width: float | None = None


class CashFlowBacktestReport(BaseModel):
    ruleset_version: str
    evaluation_version: str = "pfis-cash-flow-backtest-2"
    as_of: date
    requested_months: int
    evaluated_months: int
    excluded_months: list[ForecastBacktestExclusion] = Field(default_factory=list)
    horizons: list[ForecastHorizonMetrics] = Field(default_factory=list)
    interval_target_coverage_pct: float = 80.0
    temporal_evidence_evaluated: bool = False
    temporal_evidence_periods: int = 0
    temporal_event_count: int = 0
    transaction_history_evaluated: bool = False
    transaction_history_cutoffs: int = 0
    transaction_history_coverage_pct: float = 0.0
    category_mix_supported_periods: int = Field(default=0, ge=0)
    category_mix_applied_periods: int = Field(default=0, ge=0)
    settled_transaction_count: int = Field(default=0, ge=0)
    unsettled_transaction_count: int = Field(default=0, ge=0)
    limitations: list[str] = Field(default_factory=list)


class CashFlowForecastSnapshotCreate(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2020, le=2030)


class CashFlowForecastSnapshotResponse(BaseModel):
    id: str
    target_month: int
    target_year: int
    cutoff_date: date
    forecast_ruleset_version: str
    temporal_ruleset_version: str | None = None
    projected_spend: float
    projected_net: float
    projected_range_low: float
    projected_range_high: float
    expected_income: float
    temporal_expected_income: float
    temporal_expected_outflows: float
    temporal_conflicted_outflows: float
    confidence: float
    data_sufficiency: DataSufficiency
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    created_at: datetime


class CashFlowForecastOutcomeResponse(BaseModel):
    id: str
    snapshot_id: str
    target_month: int
    target_year: int
    cutoff_date: date
    forecast_ruleset_version: str
    outcome_ruleset_version: str
    projected_spend: float
    projected_range_low: float
    projected_range_high: float
    actual_income: float
    actual_spend: float
    actual_net: float
    spend_absolute_error: float
    spend_absolute_percentage_error: float | None = None
    spend_range_covered: bool
    evaluated_at: datetime


class CashFlowOutcomeEvaluationResponse(BaseModel):
    evaluation_version: str
    evaluated_count: int
    already_evaluated_count: int
    ineligible_count: int
    drift_status: ForecastDriftStatusResponse = Field(default_factory=ForecastDriftStatusResponse)
    outcomes: list[CashFlowForecastOutcomeResponse] = Field(default_factory=list)


class ScenarioRequest(BaseModel):
    month: int = Field(..., ge=1, le=12)
    year: int = Field(..., ge=2020, le=2030)
    flexible_spend_reduction: float = Field(0.0, ge=0, le=10_000_000)
    recurring_reduction: float = Field(0.0, ge=0, le=10_000_000)
    additional_income: float = Field(0.0, ge=0, le=10_000_000)


class ScenarioResponse(BaseModel):
    month: int
    year: int
    baseline_projected_net: float = 0.0
    scenario_projected_net: float = 0.0
    scenario_projected_spend: float = 0.0
    monthly_impact: float = 0.0
    requested_flexible_spend_reduction: float = 0.0
    effective_flexible_spend_reduction: float = 0.0
    requested_recurring_reduction: float = 0.0
    effective_recurring_reduction: float = 0.0
    additional_income: float = 0.0
    assumptions: list[str] = Field(default_factory=list)
    data_through: date | None = None
    ruleset_version: str = "pfis-scenario-1"


class MonthComparison(BaseModel):
    month: int
    year: int
    previous_month: int
    previous_year: int
    income: float = 0.0
    previous_income: float = 0.0
    spend: float = 0.0
    previous_spend: float = 0.0
    savings: float = 0.0
    previous_savings: float = 0.0
    spend_change_pct: float | None = None
    income_change_pct: float | None = None
    category_deltas: list[dict] = Field(default_factory=list)


class DataConfidenceDimension(BaseModel):
    key: DataConfidenceKey
    label: str
    score: int = Field(..., ge=0, le=100)
    status: DataConfidenceStatus
    summary: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    remediation_label: str | None = None
    remediation_target: str | None = None


class FinancialHealthScore(BaseModel):
    score: int
    monthly_stability: int = 0
    data_confidence: int = 0
    data_confidence_breakdown: list[DataConfidenceDimension] = Field(default_factory=list)
    data_confidence_ruleset_version: str = "pfis-data-confidence-2"
    source_coverage_score: int = 0
    source_coverage_ruleset_version: str = "pfis-source-coverage-1"
    source_coverage: list["SourceCoverage"] = Field(default_factory=list)
    data_sufficiency: DataSufficiency = "low"
    savings_rate: float = 0.0
    budget_adherence: float | None = None
    recurring_burden: float = 0.0
    review_cleanliness: float = 100.0
    spending_volatility: float = 0.0
    ruleset_version: str = "pfis-stability-1"
    signals: list[dict] = Field(default_factory=list)


class SourceCoverage(BaseModel):
    """Evidence about how much of a user's declared source is actually visible."""

    key: str
    label: str
    status: SourceCoverageStatus
    completeness: SourceCoverageCompleteness = "unknown"
    score: int = Field(..., ge=0, le=100)
    observed_count: int = Field(default=0, ge=0)
    coverage_start: date | None = None
    coverage_end: date | None = None
    freshness_at: datetime | None = None
    freshness_age_days: int | None = Field(default=None, ge=0)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    remediation_label: str | None = None
    remediation_target: str | None = None


class SourceCoverageResponse(BaseModel):
    """User-scoped source coverage without implying provider completeness."""

    ruleset_version: str = "pfis-source-coverage-1"
    as_of: datetime
    overall_score: int = Field(..., ge=0, le=100)
    sources: list[SourceCoverage] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class GoalCreate(BaseModel):
    goal_type: GoalType
    label: str = Field(..., min_length=1, max_length=160)
    target_amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    target_key: str | None = Field(None, max_length=160)
    target_month: int | None = Field(None, ge=1, le=12)
    target_year: int | None = Field(None, ge=2020, le=2030)


class GoalUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=160)
    target_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    target_key: str | None = Field(None, max_length=160)
    target_month: int | None = Field(None, ge=1, le=12)
    target_year: int | None = Field(None, ge=2020, le=2030)
    is_active: bool | None = None


class GoalResponse(BaseModel):
    id: str
    user_id: str
    goal_type: GoalType
    label: str
    target_amount: float
    target_key: str | None = None
    target_month: int | None = None
    target_year: int | None = None
    is_active: bool = True
    current_amount: float = 0.0
    progress_pct: float = 0.0
    status: str = "tracking"
    created_at: datetime


ExplainSurfaceKind = Literal[
    "category", "budget", "merchant", "financial_health", "cash_flow", "general"
]
ExplainEvidenceStatus = Literal["verified", "partial", "conflict", "unverified"]
ExplainMetricStatus = Literal["verified", "mismatch", "unverified", "invalid", "withheld"]


class ExplainRequest(BaseModel):
    surface: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    metrics: dict = Field(default_factory=dict)
    month: int | None = Field(None, ge=1, le=12)
    year: int | None = Field(None, ge=2020, le=2030)
    subject_id: str | None = Field(None, min_length=1, max_length=160)


class ExplainMetric(BaseModel):
    """One supplied aggregate and how PFIS qualified it."""

    key: str
    label: str
    supplied_value: str | None = None
    verified_value: str | None = None
    status: ExplainMetricStatus
    note: str


class ExplainAction(BaseModel):
    label: str
    reason: str
    target: str | None = None


class ExplainResponse(BaseModel):
    surface: str
    summary: str
    drivers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    safety_note: str
    ruleset_version: str = "pfis-explain-1"
    surface_kind: ExplainSurfaceKind = "general"
    evidence_status: ExplainEvidenceStatus = "unverified"
    source: str = "client_supplied"
    as_of: datetime | None = None
    period_month: int | None = None
    period_year: int | None = None
    metrics: list[ExplainMetric] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    coverage_score: int | None = Field(default=None, ge=0, le=100)
    coverage: list[SourceCoverage] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    actions: list[ExplainAction] = Field(default_factory=list)
