"""Evidence-labelled account balance forecast contracts.

The forecast is deliberately a path from a verified/estimated position, not a
replacement for a provider balance.  Every value is therefore labelled with
its starting basis, coverage state, assumptions, and uncertainty band.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.forecast_drift import ForecastDriftStatusResponse
from app.schemas.intelligence import DataSufficiency, EvidenceItem

ForecastStatus = Literal["ready", "needs_anchor", "needs_review"]
ForecastRisk = Literal["none", "watch", "shortfall", "limit_pressure"]


class AccountBalanceForecastPoint(BaseModel):
    """One daily balance point, including the amount of evidence applied that day."""

    date: date
    expected_balance: float | None
    low_balance: float | None
    high_balance: float | None
    scheduled_increase: float = 0.0
    scheduled_decrease: float = 0.0
    baseline_increase: float = 0.0
    baseline_decrease: float = 0.0
    event_count: int = Field(default=0, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    risk: ForecastRisk = "none"
    risk_reasons: list[str] = Field(default_factory=list)


class AccountBalanceForecastResponse(BaseModel):
    """Account-level daily path from the latest trusted position anchor."""

    financial_account_id: str
    account_type: str
    institution_name: str
    masked_number: str
    currency: str
    balance_kind: Literal["asset", "liability"]
    status: ForecastStatus
    horizon_start: date
    horizon_end: date
    horizon_days: int = Field(..., ge=1, le=180)
    starting_balance: float | None
    starting_balance_as_of: date | None
    starting_balance_basis: Literal["observed", "estimated"] | None
    expected_ending_balance: float | None
    expected_change: float | None
    lowest_expected_balance: float | None
    lowest_expected_date: date | None
    first_shortfall_date: date | None
    scheduled_increase_total: float = 0.0
    scheduled_decrease_total: float = 0.0
    baseline_increase_total: float = 0.0
    baseline_decrease_total: float = 0.0
    event_count: int = Field(default=0, ge=0)
    historical_days: int = Field(default=0, ge=0)
    historical_activity_count: int = Field(default=0, ge=0)
    coverage_status: Literal["fresh", "due", "overdue", "unknown"] = "unknown"
    position_status: str = "needs_observation"
    position_confidence: float = Field(default=0.0, ge=0, le=1)
    confidence: float = Field(default=0.0, ge=0, le=1)
    data_sufficiency: DataSufficiency = "low"
    position_reason_codes: list[str] = Field(default_factory=list)
    drift_status: ForecastDriftStatusResponse | None = None
    assumptions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    points: list[AccountBalanceForecastPoint] = Field(default_factory=list)
    ruleset_version: str = "pfis-account-balance-forecast-1"


class AccountBalanceForecastSnapshotCreate(BaseModel):
    """Request to freeze the current account path for later evaluation."""

    horizon_days: int = Field(default=30, ge=1, le=180)
    cutoff_date: date | None = None


class AccountBalanceForecastSnapshotResponse(BaseModel):
    """Immutable forecast metadata and points captured at one cutoff."""

    id: str
    financial_account_id: str
    currency: str
    balance_kind: Literal["asset", "liability"]
    cutoff_date: date
    horizon_start: date
    horizon_end: date
    horizon_days: int = Field(..., ge=1, le=180)
    forecast_ruleset_version: str
    status: ForecastStatus
    starting_balance: float | None
    starting_balance_as_of: date | None
    starting_balance_basis: Literal["observed", "estimated"] | None
    expected_ending_balance: float | None
    expected_change: float | None
    lowest_expected_balance: float | None
    lowest_expected_date: date | None
    first_shortfall_date: date | None
    event_count: int = Field(default=0, ge=0)
    historical_days: int = Field(default=0, ge=0)
    historical_activity_count: int = Field(default=0, ge=0)
    coverage_status: Literal["fresh", "due", "overdue", "unknown"]
    position_status: str
    position_confidence: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)
    data_sufficiency: DataSufficiency
    position_reason_codes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    points: list[AccountBalanceForecastPoint] = Field(default_factory=list)
    created_at: datetime


class AccountBalanceForecastOutcomeResponse(BaseModel):
    """Observed balance compared with one immutable forecast point."""

    id: str
    snapshot_id: str
    financial_account_id: str
    target_date: date
    cutoff_date: date
    actual_observation_id: str
    actual_source: str
    actual_balance: float
    expected_balance: float
    low_balance: float | None
    high_balance: float | None
    signed_error: float
    absolute_error: float
    interval_covered: bool | None
    predicted_risk: ForecastRisk
    forecast_ruleset_version: str
    outcome_ruleset_version: str
    evaluated_at: datetime


class AccountBalanceForecastEvaluationResponse(BaseModel):
    """Account-scoped daily forecast calibration report."""

    evaluation_version: str
    evaluated_count: int
    already_evaluated_count: int
    pending_count: int
    interval_coverage_pct: float | None = None
    mean_absolute_error: float | None = None
    median_absolute_percentage_error: float | None = None
    calibration_status: Literal["insufficient_sample", "within_threshold", "drift"] = (
        "insufficient_sample"
    )
    drift_status: ForecastDriftStatusResponse = Field(default_factory=ForecastDriftStatusResponse)
    calibration_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "maximum_median_absolute_percentage_error_pct": 20.0,
            "minimum_interval_coverage_pct": 70.0,
            "minimum_outcomes": 3.0,
        }
    )
    outcomes: list[AccountBalanceForecastOutcomeResponse] = Field(default_factory=list)
