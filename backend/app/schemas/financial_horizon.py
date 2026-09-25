"""Server-owned Financial Horizon response contracts."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

FinancialHorizonStatus = Literal["healthy", "attention", "deficit", "low_data", "stale"]
FinancialHorizonEventStatus = Literal["verified", "planned", "estimated", "risk", "provisional"]
FinancialHorizonEventSource = Literal[
    "balance_position",
    "cash_plan",
    "commitment",
    "liability",
    "card_upcoming",
    "card_due_runway",
    "balance_forecast",
]
FinancialHorizonRiskSeverity = Literal["info", "warning", "danger"]


class FinancialHorizonAmountSummary(BaseModel):
    assets: float = 0.0
    liabilities: float = 0.0
    net: float = 0.0


class FinancialHorizonCurrentPosition(BaseModel):
    currency: str
    account_count: int = Field(default=0, ge=0)
    verified: FinancialHorizonAmountSummary
    provisional: FinancialHorizonAmountSummary
    cash_plan_readiness: str | None = None
    safe_to_spend: float | None = None
    safe_to_spend_basis: str | None = None
    reason_codes: list[str] = Field(default_factory=list)


class FinancialHorizonEvent(BaseModel):
    id: str
    date: dt.date
    label: str
    amount: float | None = None
    direction: Literal["in", "out", "neutral"] = "neutral"
    source: FinancialHorizonEventSource
    source_id: str | None = None
    status: FinancialHorizonEventStatus
    confidence: float = Field(..., ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)


class FinancialHorizonLowestPoint(BaseModel):
    date: dt.date
    expected_balance: float
    low_balance: float | None = None
    high_balance: float | None = None
    confidence: float = Field(..., ge=0, le=1)
    source_account_id: str


class FinancialHorizonRiskSignal(BaseModel):
    code: str
    severity: FinancialHorizonRiskSeverity
    label: str
    detail: str
    date: dt.date | None = None
    amount: float | None = None
    source: str


class FinancialHorizonSourceHealth(BaseModel):
    source_id: str
    source: str
    status: Literal["fresh", "due", "overdue", "unknown", "incomplete", "review"]
    latest_sync_at: dt.datetime | None = None
    coverage_start: dt.datetime | None = None
    coverage_end: dt.datetime | None = None
    coverage_complete: bool | None = None
    reason_codes: list[str] = Field(default_factory=list)


class FinancialHorizonResponse(BaseModel):
    as_of: dt.date
    horizon_days: int = Field(..., ge=7, le=90)
    current_position: FinancialHorizonCurrentPosition
    events: list[FinancialHorizonEvent] = Field(default_factory=list)
    lowest_projected_point: FinancialHorizonLowestPoint | None = None
    lowest_projected_point_unavailable_reason: str | None = None
    risk_signals: list[FinancialHorizonRiskSignal] = Field(default_factory=list)
    source_health: list[FinancialHorizonSourceHealth] = Field(default_factory=list)
    status: FinancialHorizonStatus
    missing_evidence: list[str] = Field(default_factory=list)
    ruleset_version: str = "pfis-horizon-1"
