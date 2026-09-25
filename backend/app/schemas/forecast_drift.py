"""Forecast drift guard response contracts."""

from typing import Literal

from pydantic import BaseModel, Field

ForecastDriftStatusValue = Literal["insufficient_evidence", "healthy", "degraded"]


class ForecastDriftHorizonStatus(BaseModel):
    horizon: str
    matured_outcomes: int = Field(default=0, ge=0)
    mean_absolute_percentage_error: float | None = None
    interval_coverage_pct: float | None = None
    status: ForecastDriftStatusValue = "insufficient_evidence"


class ForecastDriftStatusResponse(BaseModel):
    ruleset_version: str = "pfis-forecast-drift-guard-1"
    status: ForecastDriftStatusValue = "insufficient_evidence"
    reason_code: str = "forecast_drift_guard"
    minimum_outcomes: int = 3
    maximum_mape_pct: float = 20.0
    minimum_interval_coverage_pct: float = 70.0
    horizons: list[ForecastDriftHorizonStatus] = Field(default_factory=list)
