"""Typed expected-versus-observed financial event contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TemporalEventKind = Literal[
    "income",
    "bill",
    "subscription",
    "commitment",
    "liability_installment",
    "card_milestone",
    "reserve",
    "recurring_expense",
    "account_identity",
    "transaction_lifecycle",
]
TemporalDirection = Literal["inflow", "outflow", "reserve", "neutral"]
TemporalEventState = Literal[
    "expected",
    "observed",
    "overdue",
    "missed",
    "cancelled",
    "conflict",
]
TemporalSourceType = Literal[
    "cash_plan",
    "bill",
    "commitment",
    "liability_schedule",
    "card_calendar",
    "card_payment_intent",
    "reserve_plan",
    "recurring_pattern",
    "transaction",
    "user_confirmation",
    "financial_account",
    "statement_line",
    "deposit_statement_line",
    "card_dispute",
]
TemporalDecision = Literal["confirmed", "cancelled", "observed", "linked", "conflict"]
TemporalBackfillSourceType = Literal[
    "transaction",
    "financial_account",
    "statement_line",
    "deposit_statement_line",
    "card_payment_intent",
]


def _default_temporal_backfill_sources() -> list[TemporalBackfillSourceType]:
    return [
        "transaction",
        "financial_account",
        "statement_line",
        "deposit_statement_line",
        "card_payment_intent",
    ]


class TemporalAmount(BaseModel):
    low: float | None = None
    expected: float | None = None
    high: float | None = None


class TemporalEvidenceReference(BaseModel):
    source_type: TemporalSourceType
    source_id: str
    role: Literal["definition", "pattern_observation", "explicit_observation", "match"]


class TemporalObservation(BaseModel):
    observed_date: date
    amount: float | None = None
    transaction_id: str | None = None
    confirmation: Literal["ledger_match", "user_status", "issuer_status"]


class TemporalEventDecisionUpsert(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision: TemporalDecision
    transaction_id: str | None = Field(None, max_length=36)
    observed_date: date | None = None
    observed_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    note: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_decision_evidence(self):
        if self.decision == "linked" and self.transaction_id is None:
            raise ValueError("Linked decisions require a transaction")
        if self.decision == "observed" and self.observed_date is None:
            raise ValueError("Observed decisions require an observed date")
        if self.decision == "conflict" and not self.note:
            raise ValueError("Conflict decisions require a note")
        if self.decision != "linked" and self.transaction_id is not None:
            raise ValueError("Only linked decisions can include a transaction")
        return self


class TemporalEventDecisionResponse(BaseModel):
    id: str
    decision: TemporalDecision
    transaction_id: str | None = None
    observed_date: date | None = None
    observed_amount: float | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TemporalFinancialEvent(BaseModel):
    id: str
    kind: TemporalEventKind
    direction: TemporalDirection
    state: TemporalEventState
    label: str
    currency: str = Field(..., min_length=3, max_length=3)
    expected_date: date
    window_start: date
    window_end: date
    amount: TemporalAmount
    observation: TemporalObservation | None = None
    decision: TemporalEventDecisionResponse | None = None
    conflict_reason: str | None = None
    cadence: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    data_sufficiency: Literal["low", "medium", "high"]
    evidence: list[TemporalEvidenceReference] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ruleset_version: str
    data_through: date


class TemporalEventSummary(BaseModel):
    range_start: date
    range_end: date
    as_of: date
    currency: str
    ruleset_version: str
    counts: dict[TemporalEventState, int]
    events: list[TemporalFinancialEvent] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class TemporalRecomputationIssue(BaseModel):
    decision_id: str
    event_id: str
    issue: Literal["orphaned_event", "ruleset_drift", "missing_linked_transaction"]
    detail: str


class TemporalRecomputationAudit(BaseModel):
    range_start: date
    range_end: date
    data_through: date
    ruleset_version: str
    source_event_count: int
    decision_count: int
    applicable_decision_count: int
    orphaned_decision_count: int
    ruleset_drift_count: int
    missing_link_count: int
    events_by_kind: dict[TemporalEventKind, int]
    events_by_state: dict[TemporalEventState, int]
    issues: list[TemporalRecomputationIssue] = Field(default_factory=list)
    would_mutate: bool = False


class TemporalHistoryBackfillRequest(BaseModel):
    """Request a safe baseline capture for legacy rows without source history."""

    dry_run: bool = True
    source_types: list[TemporalBackfillSourceType] = Field(
        default_factory=_default_temporal_backfill_sources,
        min_length=1,
        max_length=4,
    )
    max_rows_per_source: int = Field(default=5000, ge=1, le=50000)

    @model_validator(mode="after")
    def validate_source_types(self):
        if len(set(self.source_types)) != len(self.source_types):
            raise ValueError("Source types must be unique")
        return self


class TemporalHistoryBackfillSource(BaseModel):
    source_type: TemporalBackfillSourceType
    candidate_count: int = Field(..., ge=0)
    existing_snapshot_count: int = Field(..., ge=0)
    missing_snapshot_count: int = Field(..., ge=0)
    captured_count: int = Field(..., ge=0)
    skipped_count: int = Field(..., ge=0)
    truncated: bool = False


class TemporalHistoryBackfillResponse(BaseModel):
    ruleset_version: str
    dry_run: bool
    captured_at: datetime
    baseline_only: bool = True
    sources: list[TemporalHistoryBackfillSource] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
