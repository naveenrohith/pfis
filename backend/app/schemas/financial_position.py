"""API contracts for PFIS verified financial-position workflows."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.intelligence import EvidenceItem

SourceKind = Literal["manual", "email", "statement", "connector"]
ReviewOutcome = Literal["matched", "newly_imported", "ignored_by_rule", "needs_review"]
BalancePositionStatus = Literal[
    "observed", "estimated", "stale", "incomplete", "needs_review", "unsupported"
]
BalancePositionProductType = Literal[
    "bank", "credit_card", "loan", "pay_later", "cash", "investment", "unknown"
]


class CommitmentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(..., min_length=1, max_length=160)
    commitment_type: str = Field(..., min_length=1, max_length=32)
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    due_date: date
    cadence: Literal["weekly", "monthly", "quarterly", "annual"] | None = None
    financial_account_id: str | None = None
    liability_id: str | None = None
    source_kind: SourceKind = "manual"
    source_identifier: str | None = Field(None, max_length=128)
    confirmed: bool = False


class CommitmentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str | None = Field(None, min_length=1, max_length=160)
    amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    due_date: date | None = None
    cadence: Literal["weekly", "monthly", "quarterly", "annual"] | None = None
    confirmed: bool | None = None
    is_active: bool | None = None


class CommitmentResponse(CommitmentCreate):
    id: str
    user_id: str
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CashPlanUpsert(BaseModel):
    primary_financial_account_id: str
    next_income_date: date | None = None
    next_income_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    show_daily_allowance: bool = False


class CashPlanResponse(BaseModel):
    primary_financial_account_id: str
    currency: str
    verified_balance: float | None
    balance_as_of: date | None
    # ``planning_balance`` is the balance PFIS is willing to use for flexible
    # money. It may be an eligible settled roll-forward, but it is never
    # presented as an issuer/provider live balance.
    estimated_balance: float | None = None
    estimated_balance_as_of: date | None = None
    planning_balance: float | None = None
    planning_balance_as_of: date | None = None
    balance_basis: Literal["verified", "estimated"] | None = None
    position_status: Literal[
        "needs_observation",
        "observed",
        "estimated",
        "stale",
        "incomplete",
        "needs_review",
    ] = "needs_observation"
    position_confidence: float = Field(default=0.0, ge=0, le=1)
    position_reason_codes: list[str] = Field(default_factory=list)
    observed_source: str | None = None
    observed_at: datetime | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    latest_sync_at: datetime | None = None
    coverage_complete: bool | None = None
    coverage_status: Literal["fresh", "due", "overdue", "unknown"] = "unknown"
    settled_movement_since_observation: float | None = None
    pending_increase: float = 0.0
    pending_decrease: float = 0.0
    next_income_date: date | None
    confirmed_commitments: list[CommitmentResponse]
    commitment_total: float
    approved_reserve_total: float
    flexible_money: float | None
    daily_allowance: float | None
    readiness: Literal[
        "ready",
        "needs_verified_balance",
        "needs_fresh_balance",
        "needs_next_income",
        "needs_position_review",
    ]
    assumptions: list[str]


class ReservePlanCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    financial_account_id: str
    label: str = Field(..., min_length=1, max_length=160)
    target_amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    due_date: date
    monthly_allocation: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    approved: bool = False


class ReservePlanUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str | None = Field(None, min_length=1, max_length=160)
    target_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    due_date: date | None = None
    monthly_allocation: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    approved: bool | None = None
    is_active: bool | None = None


class ReservePlanResponse(ReservePlanCreate):
    id: str
    user_id: str
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LiabilityCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(..., min_length=1, max_length=160)
    liability_type: Literal["loan", "pay_later", "card_emi", "credit_card"]
    financial_account_id: str | None = None
    source_kind: SourceKind = "manual"
    source_identifier: str | None = Field(None, max_length=160)
    source_confidence: Decimal | None = Field(None, ge=0, le=1, max_digits=4, decimal_places=3)
    outstanding_principal: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    monthly_due: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    next_due_date: date | None = None
    end_date: date | None = None
    interest_rate: Decimal | None = Field(None, ge=0, max_digits=7, decimal_places=4)
    tenure_months: int | None = Field(None, gt=0)
    remaining_installments: int | None = Field(None, ge=0)
    complete_schedule: bool = False


class LiabilityResponse(BaseModel):
    id: str
    user_id: str
    label: str
    liability_type: Literal["loan", "pay_later", "card_emi", "credit_card"]
    financial_account_id: str | None
    source_kind: SourceKind
    source_identifier: str | None
    source_confidence: float | None
    outstanding_principal: float | None
    monthly_due: float | None
    next_due_date: date | None
    end_date: date | None
    interest_rate: float | None
    tenure_months: int | None
    remaining_installments: int | None
    complete_schedule: bool
    issuer_plan_reference: str | None
    observed_original_amount: float | None
    observed_monthly_amount: float | None
    observed_principal_component: float | None
    observed_interest_component: float | None
    observed_tax_component: float | None
    observed_fee_component: float | None
    last_observed_statement_date: date | None
    evidence_line_count: int
    schedule_status: Literal["not_provided", "observed_partial", "confirmed"]
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LiabilityScheduleItemCreate(BaseModel):
    due_date: date
    installment_amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    principal_amount: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    interest_amount: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    tax_amount: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    fee_amount: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)


class LiabilityScheduleConfirm(BaseModel):
    """A complete issuer-provided or explicitly user-confirmed instalment schedule."""

    source_kind: Literal["manual", "statement"] = "manual"
    items: list[LiabilityScheduleItemCreate] = Field(..., min_length=1, max_length=360)


class LiabilityScheduleItemResponse(BaseModel):
    id: str
    liability_id: str
    user_id: str
    due_date: date
    installment_amount: float
    principal_amount: float | None
    interest_amount: float | None
    tax_amount: float | None
    fee_amount: float | None
    source_kind: str
    source_identifier: str | None
    confidence: float | None
    status: Literal["upcoming", "paid", "skipped"]
    model_config = ConfigDict(from_attributes=True)


class LiabilityScheduleItemUpdate(BaseModel):
    status: Literal["upcoming", "paid", "skipped"]


class LiabilityOverviewResponse(BaseModel):
    currency: str
    liabilities: list[LiabilityResponse]
    known_monthly_debt: float
    confirmed_monthly_debt: float
    observed_card_emi_monthly: float
    next_due_date: date | None
    next_due_amount: float | None
    complete_schedule_count: int
    partial_evidence_count: int
    assumptions: list[str]


class BalanceReconciliationResponse(BaseModel):
    """Immutable balance interval with known movement and unexplained residual."""

    id: str
    financial_account_id: str
    opening_snapshot_id: str
    closing_snapshot_id: str
    currency: str
    balance_kind: Literal["asset", "liability"]
    opening_as_of: date
    closing_as_of: date
    opening_balance: float
    known_movement: float
    expected_closing_balance: float
    observed_closing_balance: float
    residual: float
    absolute_residual: float
    transaction_count: int = Field(..., ge=0)
    eligible_transaction_count: int = Field(..., ge=0)
    excluded_transaction_count: int = Field(..., ge=0)
    eligible_transaction_ids: list[str] = Field(default_factory=list)
    excluded_transaction_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    reconciliation_status: Literal["reconciled", "needs_review"]
    ruleset_version: str
    created_at: datetime


class ReconciliationItem(BaseModel):
    id: str
    kind: Literal[
        "transaction_review",
        "duplicate_candidate",
        "unlinked_transfer",
        "unexplained_movement",
    ]
    title: str
    description: str
    amount: float | None = None
    activity_date: date | None = None
    transaction_ids: list[str] = Field(default_factory=list)
    basis: str


class AccountPositionResponse(BaseModel):
    financial_account_id: str
    account_id: str
    product_type: BalancePositionProductType
    currency: str
    balance_kind: Literal["asset", "liability"]
    verified_balance: float | None
    balance_as_of: date | None
    balance_source: str | None
    observed_balance: float | None = None
    observed_as_of: date | None = None
    observed_verified: bool | None = None
    observed_source: str | None = None
    observed_source_record_id: str | None = None
    observed_at: datetime | None = None
    observed_effective_at: datetime | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    latest_sync_at: datetime | None = None
    coverage_complete: bool | None = None
    coverage_status: Literal["fresh", "due", "overdue", "unknown"] = "unknown"
    reconciliation_delta: float | None = None
    last_reconciled_at: datetime | None = None
    estimated_balance: float | None = None
    estimated_as_of: date | None = None
    settled_movement_since_observation: float | None = None
    pending_increase: float = 0.0
    pending_decrease: float = 0.0
    unlinked_count: int = Field(default=0, ge=0)
    unreviewed_count: int = Field(default=0, ge=0)
    duplicate_candidate_count: int = Field(default=0, ge=0)
    position_status: Literal[
        "needs_observation", "observed", "estimated", "stale", "incomplete", "needs_review"
    ] = "needs_observation"
    position_confidence: float = Field(default=0.0, ge=0, le=1)
    position_reason_codes: list[str] = Field(default_factory=list)
    position_ruleset_version: str = "pfis-balance-position-1"
    status: BalancePositionStatus = "incomplete"
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    ruleset_version: str = "pfis-balance-position-1"
    opening_balance: float | None = None
    opening_as_of: date | None = None
    known_movement: float | None = None
    inflows: float
    outflows: float
    rail_breakdown: dict[str, float]
    reconciliation_status: Literal["not_ready", "reconciled", "needs_review"]
    unexplained_amount: float | None
    review_count: int
    reconciliation_items: list[ReconciliationItem] = Field(default_factory=list)


class StatementLineResponse(BaseModel):
    id: str
    transaction_date: date
    description: str
    amount: float
    transaction_type: str
    card_event: str
    component_kind: str = "ordinary"
    issuer_plan_reference: str | None = None
    installment_number: int | None = None
    merchant_normalized: str | None = None
    merchant_confidence: float | None = None
    review_outcome: ReviewOutcome
    created_transaction_id: str | None
    model_config = ConfigDict(from_attributes=True)


class StatementReviewItemResponse(StatementLineResponse):
    financial_account_id: str
    account_label: str
    masked_number: str
    statement_date: date
    decision_count: int
    candidate_transactions: list["StatementReviewCandidate"]


class StatementReviewCandidate(BaseModel):
    id: str
    label: str
    amount: float
    transaction_date: date
    transaction_type: str
    source_kind: str


class StatementCardPaymentCandidateResponse(BaseModel):
    """A bank debit that may fund one card-payment statement line.

    This is evidence for a user review, never an automatic transfer or match.
    """

    transaction_id: str
    paying_account_id: str
    account_label: str
    masked_number: str
    amount: float
    transaction_date: date
    description: str
    reference_id: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    match_method: Literal["reference", "same_day_amount", "near_day_amount"]
    evidence: list[str] = Field(default_factory=list)


class StatementLineReviewRequest(BaseModel):
    decision: Literal["ignore", "match", "import", "record_card_payment"]
    matched_transaction_id: str | None = None
    paying_account_id: str | None = None
    note: str | None = Field(None, max_length=500)


class StatementLineReviewResponse(BaseModel):
    line: StatementLineResponse
    decision: str
    previous_outcome: ReviewOutcome
    new_outcome: ReviewOutcome
    matched_transaction_id: str | None
    paying_account_id: str | None
    decided_at: datetime


class CreditCardStatementResponse(BaseModel):
    id: str
    financial_account_id: str
    statement_date: date
    period_start: date
    period_end: date
    due_date: date | None
    total_due: float | None
    minimum_due: float | None
    credit_limit: float | None
    available_credit_limit: float | None
    available_cash_limit: float | None
    currency: str
    lines: list[StatementLineResponse] = Field(default_factory=list)


class DepositStatementLineResponse(BaseModel):
    id: str
    line_number: int
    transaction_date: date
    value_date: date
    description: str
    reference_id: str | None
    amount: float
    transaction_type: Literal["debit", "credit"]
    payment_rail: Literal["upi", "debit_card", "atm", "transfer", "other"]
    balance_after: float
    review_outcome: str
    created_transaction_id: str | None
    model_config = ConfigDict(from_attributes=True)


class DepositStatementReviewItemResponse(DepositStatementLineResponse):
    """Owned unknown-rail deposit evidence awaiting an explicit user decision."""

    financial_account_id: str
    account_label: str
    masked_number: str
    period_start: date
    period_end: date
    decision_count: int


class DepositStatementLineReviewRequest(BaseModel):
    """Explicitly classify or ignore one unresolved deposit statement row."""

    decision: Literal["ignore", "import"]
    payment_rail: Literal["upi", "debit_card", "atm", "transfer"] | None = None
    note: str | None = Field(None, max_length=500)


class DepositStatementLineReviewResponse(BaseModel):
    line: DepositStatementLineResponse
    decision: Literal["ignore", "import"]
    previous_outcome: ReviewOutcome
    new_outcome: ReviewOutcome
    payment_rail: Literal["upi", "debit_card", "atm", "transfer", "other"]
    created_transaction_id: str | None
    decided_at: datetime


class DepositAccountStatementResponse(BaseModel):
    id: str
    financial_account_id: str
    period_start: date
    period_end: date
    opening_balance: float
    closing_balance: float
    currency: str
    imported_transaction_count: int
    review_count: int
    lines: list[DepositStatementLineResponse] = Field(default_factory=list)


class StatementTextImport(BaseModel):
    """Safe API/testing import surface; PDF uploads are converted to text server-side."""

    financial_account_id: str
    document_fingerprint: str = Field(..., min_length=64, max_length=64)
    statement_text: str = Field(..., min_length=40, max_length=150_000)


class StatementDetectionRequest(BaseModel):
    """Read-only statement recognition input; source text is never persisted."""

    statement_text: str = Field(..., min_length=40, max_length=150_000)


class StatementAnalysisLineResponse(BaseModel):
    """Bounded evidence preview; this is never a persisted statement line."""

    line_number: int
    transaction_date: date | None
    description: str
    amount: float | None
    direction: Literal["debit", "credit", "unknown"]
    payment_rail: Literal[
        "upi",
        "debit_card",
        "atm",
        "transfer",
        "credit_card",
        "other",
        "unknown",
    ]
    balance_after: float | None
    confidence: float = Field(..., ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)


class StatementAnalysisResponse(BaseModel):
    """Read-only totals and a small, redacted transaction preview."""

    status: Literal["available", "partial", "signature_only", "failed"]
    source_kind: Literal["reviewed_extractor", "generic_table", "signature_only"]
    period_start: date | None
    period_end: date | None
    opening_balance: float | None
    closing_balance: float | None
    row_count: int = Field(..., ge=0)
    preview_count: int = Field(..., ge=0)
    omitted_line_count: int = Field(..., ge=0)
    debit_total: float = Field(..., ge=0)
    credit_total: float = Field(..., ge=0)
    rail_totals: dict[str, float] = Field(default_factory=dict)
    reconciled: bool | None
    confidence: float = Field(..., ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    ruleset_version: str
    lines: list[StatementAnalysisLineResponse] = Field(default_factory=list)


class StatementAnalysisReviewCreate(BaseModel):
    """Persist a redacted statement analysis without importing ledger activity."""

    document_fingerprint: str | None = Field(None, min_length=64, max_length=64)
    statement_text: str = Field(..., min_length=40, max_length=150_000)


class StatementAnalysisReviewResponse(BaseModel):
    """One user-owned durable statement analysis awaiting explicit mapping/import."""

    id: str
    document_fingerprint: str
    institution: str | None
    product_type: Literal["credit_card", "deposit_account", "unknown"]
    format_id: str | None
    support_status: Literal[
        "supported",
        "recognized_not_supported",
        "ambiguous",
        "unsupported",
    ]
    confidence: float = Field(..., ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    activity_types: list[str] = Field(default_factory=list)
    detector_version: str
    status: Literal["ready_to_import", "pending_review"]
    analysis: StatementAnalysisResponse
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class StatementDocumentDetectionResponse(BaseModel):
    """Redacted HDFC digital-document classification before account selection."""

    status: Literal["recognized", "ambiguous", "unknown"]
    issuer: Literal["hdfc", "unknown"]
    document_kind: Literal["credit_card_statement", "deposit_account_statement", "unknown"]
    format_id: str | None
    import_supported: bool
    import_endpoint: str | None
    reason_code: Literal[
        "recognized_hdfc_credit_card",
        "recognized_hdfc_deposit_account",
        "ambiguous_hdfc_statement",
        "unrecognized_hdfc_layout",
        "unsupported_issuer",
    ]
    matched_signal_codes: list[str] = Field(default_factory=list)
    detector_version: str


class StatementDetectionResponse(BaseModel):
    institution: str | None
    product_type: Literal["credit_card", "deposit_account", "unknown"]
    format_id: str | None
    support_status: Literal[
        "supported",
        "recognized_not_supported",
        "ambiguous",
        "unsupported",
    ]
    confidence: float = Field(..., ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    activity_types: list[str] = Field(default_factory=list)
    detector_version: str
    analysis: StatementAnalysisResponse | None = None


class StatementImportResultResponse(BaseModel):
    product_type: Literal["credit_card", "deposit_account"]
    detection: StatementDetectionResponse
    credit_card_statement: CreditCardStatementResponse | None = None
    deposit_account_statement: DepositAccountStatementResponse | None = None


class CardPreferenceUpsert(BaseModel):
    preferred_payment_account_id: str | None = None
    utilization_target_pct: Decimal | None = Field(
        None, gt=0, le=100, max_digits=5, decimal_places=2
    )
    reward_rules: list[dict[str, str | int | float | bool]] = Field(
        default_factory=list, max_length=20
    )


class CardPreferenceResponse(CardPreferenceUpsert):
    financial_account_id: str


class CardPaymentIntentCreate(BaseModel):
    paying_account_id: str | None = None
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    planned_for: date
    note: str | None = Field(None, max_length=240)


class CardPaymentIntentResponse(CardPaymentIntentCreate):
    id: str
    financial_account_id: str
    status: Literal["planned", "recorded", "cancelled"]
    transfer_group_id: str | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CardPaymentIntentUpdate(BaseModel):
    status: Literal["recorded", "cancelled"]
    paying_account_id: str | None = None


class CardCalendarEventCreate(BaseModel):
    event_type: Literal["renewal", "annual_fee", "fee_reversal", "milestone", "milestone_spend"]
    label: str = Field(..., min_length=1, max_length=160)
    event_date: date
    source_label: str = Field("User-entered", min_length=1, max_length=160)
    source_identifier: str | None = Field(None, max_length=128)
    annual_fee_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    fee_reversal_condition: str | None = Field(None, max_length=500)
    fee_reversal_status: (
        Literal["unknown", "pending", "waived", "reversed", "not_eligible"] | None
    ) = None
    milestone_spend_target: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    milestone_period_start: date | None = None
    milestone_period_end: date | None = None


class CardCalendarEventUpdate(BaseModel):
    event_type: (
        Literal["renewal", "annual_fee", "fee_reversal", "milestone", "milestone_spend"] | None
    ) = None
    label: str | None = Field(None, min_length=1, max_length=160)
    event_date: date | None = None
    source_label: str | None = Field(None, min_length=1, max_length=160)
    source_identifier: str | None = Field(None, max_length=128)
    annual_fee_amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    fee_reversal_condition: str | None = Field(None, max_length=500)
    fee_reversal_status: (
        Literal["unknown", "pending", "waived", "reversed", "not_eligible"] | None
    ) = None
    milestone_spend_target: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    milestone_period_start: date | None = None
    milestone_period_end: date | None = None


class CardCalendarEventResponse(CardCalendarEventCreate):
    id: str
    financial_account_id: str
    source_kind: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CardActivitySignal(BaseModel):
    id: str
    signal_type: Literal["duplicate_candidate", "high_value", "pending_reversal"]
    title: str
    description: str
    amount: float
    activity_date: date
    basis: str


class CardEmiComponentResponse(BaseModel):
    statement_line_id: str
    statement_date: date
    transaction_date: date
    component_kind: str
    amount: float
    installment_number: int | None
    description: str


class CardEmiPlanResponse(BaseModel):
    issuer_plan_reference: str
    merchant: str
    original_amount: float | None
    conversion_date: date | None
    latest_installment_number: int | None
    latest_statement_date: date | None
    latest_due_date: date | None
    latest_principal: float
    latest_interest: float
    latest_tax: float
    latest_fees: float
    latest_installment_amount: float
    evidence_line_count: int
    observed_principal: float
    observed_interest: float
    observed_tax: float
    observed_fees: float
    status: Literal["observed", "active", "preclosed"]
    schedule_completeness: Literal["partial"]
    limitation: str
    missing_fields: list[str]
    components: list[CardEmiComponentResponse]


class FinancialIntelligenceRepairRequest(BaseModel):
    dry_run: bool = True


class FinancialIntelligenceRepairResponse(BaseModel):
    dry_run: bool
    email_merchants_repaired: int
    statement_merchants_repaired: int
    source_provenance_repaired: int
    transaction_semantics_repaired: int
    emi_components_classified: int
    emi_ledger_events_projected: int
    accounting_adjustments_marked: int
    non_spend_payments_classified: int
    duplicates_merged: int
    fuel_surcharge_duplicates_merged: int
    amounts_reconciled_to_statement: int
    liabilities_synced: int
    false_positive_transactions_removed: int
    conflicts_held_for_review: int


class CardStatementHistoryItem(BaseModel):
    id: str
    statement_date: date
    period_start: date
    period_end: date
    due_date: date | None
    total_due: float | None
    minimum_due: float | None
    line_count: int
    needs_review_count: int


class CardStatementProjectionEvidence(BaseModel):
    label: str
    value: str
    basis: str


class CardRecurringChargeProjection(BaseModel):
    """A merchant cadence expected before statement close, not an issuer fact."""

    merchant: str
    expected_date: date
    expected_date_low: date = Field(
        ...,
        description="Lower bound of the bounded historical timing envelope, not an issuer date.",
    )
    expected_date_high: date = Field(
        ...,
        description="Upper bound of the bounded historical timing envelope, not an issuer date.",
    )
    expected_amount: float = Field(..., ge=0)
    expected_amount_low: float = Field(
        ...,
        ge=0,
        description="Lower bound of the bounded historical amount envelope, not an issuer quote.",
    )
    expected_amount_high: float = Field(
        ...,
        ge=0,
        description="Upper bound of the bounded historical amount envelope, not an issuer quote.",
    )
    cadence: str | None = None
    occurrences: int = Field(..., ge=2)
    confidence: float = Field(..., ge=0, le=1)


class CardRefundTrackerResponse(BaseModel):
    """Bounded, explicit refund lifecycle evidence for one card."""

    status: Literal["clear", "pending", "needs_review"]
    as_of: date
    horizon_days: int = Field(default=90, ge=1)
    pending_count: int = Field(default=0, ge=0)
    pending_amount: float = Field(default=0, ge=0)
    oldest_pending_date: date | None = None
    posted_count_90d: int = Field(default=0, ge=0)
    posted_amount_90d: float = Field(default=0, ge=0)
    needs_review_count: int = Field(default=0, ge=0)
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[CardStatementProjectionEvidence] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-refund-tracker-1"


class CardStatementProjectionPoint(BaseModel):
    """One bounded future day in the explainable card trajectory."""

    date: date
    days_from_today: int = Field(..., ge=1)
    projected_balance: float = Field(..., ge=0)
    range_low: float = Field(..., ge=0)
    range_high: float = Field(..., ge=0)
    projected_utilization_pct: float = Field(..., ge=0)
    target_status: Literal["under_target", "at_risk", "over_target", "unavailable"] = "unavailable"
    credit_limit_status: Literal["under_limit", "at_risk", "over_limit", "unavailable"] = (
        "unavailable"
    )
    event_amount: float = 0
    event_labels: list[str] = Field(default_factory=list)


class CardStatementProjectionResponse(BaseModel):
    status: Literal[
        "available",
        "needs_recent_statement",
        "needs_current_position",
        "needs_credit_limit",
        "needs_activity",
    ]
    as_of: date | None = None
    projected_statement_date: date | None = None
    projected_balance: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    projected_utilization_pct: float | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    next_state: Literal[
        "monitor_cycle", "reduce_spend_or_pay", "prepare_statement_payment", "review_evidence"
    ]
    target_status: Literal["under_target", "at_risk", "over_target", "unavailable"] = "unavailable"
    target_headroom_amount: float | None = Field(default=None, ge=0)
    target_excess_amount: float | None = Field(default=None, ge=0)
    target_breach_date: date | None = None
    target_breach_days: int | None = Field(default=None, ge=0)
    credit_limit_status: Literal["under_limit", "at_risk", "over_limit", "unavailable"] = (
        "unavailable"
    )
    credit_limit_headroom_amount: float | None = Field(default=None, ge=0)
    credit_limit_excess_amount: float | None = Field(default=None, ge=0)
    credit_limit_breach_date: date | None = None
    credit_limit_breach_days: int | None = Field(default=None, ge=0)
    calibration: Literal["current_cycle_only", "historical_blend"] = "current_cycle_only"
    historical_sample_count: int = Field(default=0, ge=0)
    seasonal_sample_count: int = Field(
        default=0,
        ge=0,
        description="Number of prior statement cycles contributing calendar day-of-cycle evidence.",
    )
    seasonal_days_covered: int = Field(
        default=0,
        ge=0,
        description="Future cycle days with at least two prior observations used by the seasonal blend.",
    )
    known_future_payment_total: float = Field(default=0, ge=0)
    known_future_charge_total: float = Field(default=0, ge=0)
    known_future_recurring_charge_total: float = Field(default=0, ge=0)
    potential_pending_refund_total: float = Field(
        default=0,
        ge=0,
        description=(
            "Pending refund credit that may lower the range but is excluded from the central estimate."
        ),
    )
    recurring_charge_candidates: list[CardRecurringChargeProjection] = Field(default_factory=list)
    daily_path: list[CardStatementProjectionPoint] = Field(
        default_factory=list,
        description="Bounded day-by-day estimate from tomorrow through the projected close.",
    )
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[CardStatementProjectionEvidence] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-statement-projection-9"


class CardUpcomingEvent(BaseModel):
    """One dated card event or risk signal in the upcoming-state timeline."""

    id: str
    event_type: Literal[
        "payment_due",
        "statement_close",
        "planned_payment",
        "projected_charge",
        "utilization_target_breach",
        "credit_limit_breach",
        "calendar_event",
        "pending_refund",
    ]
    date: date
    days_from_today: int = Field(..., ge=0)
    label: str
    amount: float | None = Field(default=None, ge=0)
    source_kind: Literal["issuer", "user", "forecast", "ledger"]
    status: Literal["observed", "planned", "estimated", "risk"]
    confidence: float = Field(..., ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)


class CardUpcomingStateResponse(BaseModel):
    """A single next-state decision surface composed from existing card evidence."""

    financial_account_id: str
    as_of: date
    state: Literal[
        "monitor_cycle",
        "payment_due",
        "target_pressure",
        "limit_pressure",
        "review_evidence",
        "no_upcoming_evidence",
    ]
    next_event: CardUpcomingEvent | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[CardStatementProjectionEvidence] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    events: list[CardUpcomingEvent] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-upcoming-state-1"


class CardPortfolioUpcomingCard(BaseModel):
    """One card's evidence inside the multi-card upcoming-state view."""

    financial_account_id: str
    label: str
    state: Literal[
        "monitor_cycle",
        "payment_due",
        "target_pressure",
        "limit_pressure",
        "review_evidence",
        "no_upcoming_evidence",
    ]
    next_event: CardUpcomingEvent | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    total_due: float | None = Field(default=None, ge=0)
    due_date: date | None = None
    estimated_current_outstanding: float | None = Field(default=None, ge=0)
    estimated_current_as_of: date | None = None
    balance_status: Literal[
        "needs_observation", "observed", "estimated", "stale", "incomplete", "needs_review"
    ]
    projection_status: Literal[
        "available",
        "needs_recent_statement",
        "needs_current_position",
        "needs_credit_limit",
        "needs_activity",
    ]
    projected_statement_date: date | None = None
    target_status: Literal["under_target", "at_risk", "over_target", "unavailable"]
    credit_limit_status: Literal["under_limit", "at_risk", "over_limit", "unavailable"]
    reason_codes: list[str] = Field(default_factory=list)


class CardPortfolioUpcomingStateResponse(BaseModel):
    """Read-only next-state and due exposure across all active cards."""

    as_of: date
    state: Literal[
        "no_active_cards",
        "monitor_cycle",
        "payment_due",
        "target_pressure",
        "limit_pressure",
        "review_evidence",
        "no_upcoming_evidence",
    ]
    card_count: int = Field(..., ge=0)
    cards_with_due: int = Field(..., ge=0)
    issuer_total_due: float | None = Field(default=None, ge=0)
    issuer_total_due_cards: int = Field(default=0, ge=0)
    issuer_total_due_complete: bool = False
    earliest_due_date: date | None = None
    estimated_outstanding_total: float | None = Field(default=None, ge=0)
    estimated_outstanding_cards: int = Field(default=0, ge=0)
    estimated_outstanding_complete: bool = False
    next_event: CardUpcomingEvent | None = None
    events: list[CardUpcomingEvent] = Field(default_factory=list)
    cards_needing_review: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[CardStatementProjectionEvidence] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    cards: list[CardPortfolioUpcomingCard] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-portfolio-upcoming-1"


CardSpendRoutingPriority = Literal["utilization_safety", "rewards", "balanced"]


class CardSpendRoutingRequest(BaseModel):
    """Explicit user intent for a hypothetical card-spend routing preview."""

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    category: str | None = Field(None, min_length=1, max_length=120)
    priority: CardSpendRoutingPriority = "balanced"


class CardSpendRoutingOption(BaseModel):
    """One card's bounded eligibility and reward evidence for a hypothetical spend."""

    financial_account_id: str
    label: str
    currency: str
    status: Literal[
        "recommended",
        "eligible",
        "over_target",
        "over_limit",
        "needs_review",
        "unavailable",
    ]
    current_outstanding: float | None = None
    credit_limit: float | None = None
    current_utilization_pct: float | None = None
    projected_statement_balance: float | None = None
    projected_statement_utilization_pct: float | None = None
    utilization_status: Literal[
        "within_target",
        "over_target",
        "within_limit",
        "over_limit",
        "unavailable",
    ] = "unavailable"
    utilization_target_pct: float | None = None
    target_headroom_amount: float | None = None
    hard_headroom_amount: float | None = None
    reward_label: str | None = None
    reward_rate_pct: float | None = None
    estimated_reward: float | None = None
    reward_status: Literal["explicit", "no_rule", "category_mismatch", "invalid_rule"]
    source_kind: Literal["provider", "ledger_estimate", "none"]
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class CardSpendRoutingResponse(BaseModel):
    """Read-only, deterministic routing advice for one hypothetical card spend."""

    as_of: date
    amount: float
    category: str | None = None
    priority: CardSpendRoutingPriority
    currency: str | None = None
    state: Literal["ready", "partial", "needs_review", "no_active_cards"]
    recommended_card_id: str | None = None
    options: list[CardSpendRoutingOption] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-spend-routing-1"


class CardOverviewResponse(BaseModel):
    financial_account_id: str
    currency: str
    latest_statement_id: str | None
    statement_date: date | None
    period_start: date | None
    period_end: date | None
    total_due: float | None
    # Explicit card-position anatomy. ``total_due`` remains the compatibility
    # field; these names make the statement anchor and post-statement roll
    # forward unambiguous to callers.
    billed_total_due: float | None = None
    billed_total_due_as_of: date | None = None
    paid_since_statement: float | None = None
    unbilled_activity: float | None = None
    unbilled_activity_increase: float | None = None
    unbilled_activity_decrease: float | None = None
    minimum_due: float | None
    due_date: date | None
    previous_due: float | None
    payments_credits: float | None
    purchases_debits: float | None
    finance_charges: float | None
    credit_limit: float | None
    available_credit_limit: float | None
    available_cash_limit: float | None
    observed_balance: float | None = None
    observed_balance_as_of: date | None = None
    observed_source: str | None = None
    observed_source_record_id: str | None = None
    observed_at: datetime | None = None
    observed_effective_at: datetime | None = None
    provider_current_outstanding: float | None = None
    provider_current_outstanding_as_of: date | None = None
    provider_billed_due: float | None = None
    provider_pending_amount: float | None = None
    provider_credit_limit: float | None = None
    provider_available_credit: float | None = None
    provider_source: str | None = None
    provider_source_record_id: str | None = None
    provider_observed_at: datetime | None = None
    provider_effective_at: datetime | None = None
    provider_coverage_start: datetime | None = None
    provider_coverage_end: datetime | None = None
    provider_coverage_complete: bool | None = None
    estimated_current_balance: float | None = None
    estimated_current_as_of: date | None = None
    settled_movement_since_observation: float | None = None
    pending_increase: float = 0.0
    pending_decrease: float = 0.0
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    latest_sync_at: datetime | None = None
    coverage_complete: bool | None = None
    coverage_status: Literal["fresh", "due", "overdue", "unknown"] = "unknown"
    reconciliation_delta: float | None = None
    last_reconciled_at: datetime | None = None
    estimated_utilization_pct: float | None = None
    next_statement_projection: CardStatementProjectionResponse
    refund_tracker: CardRefundTrackerResponse
    balance_status: Literal[
        "needs_observation", "observed", "estimated", "stale", "incomplete", "needs_review"
    ] = "needs_observation"
    balance_confidence: float = Field(default=0.0, ge=0, le=1)
    balance_reason_codes: list[str] = Field(default_factory=list)
    balance_ruleset_version: str = "pfis-balance-position-1"
    statement_utilization_pct: float | None
    utilization_target_pct: float | None
    preferred_payment_account_id: str | None
    reward_rules: list[dict[str, str | int | float | bool]]
    coverage: dict[ReviewOutcome, int]
    statement_lines: list[StatementLineResponse]
    statement_history: list[CardStatementHistoryItem]
    planned_payments: list[CardPaymentIntentResponse]
    calendar: list[CardCalendarEventResponse]
    activity_signals: list[CardActivitySignal]
    emi_plans: list[CardEmiPlanResponse] = Field(default_factory=list)


class CardUtilizationHistoryPoint(BaseModel):
    """One issuer-backed or ledger-estimated utilization observation."""

    as_of: date
    basis: Literal["issuer_statement", "ledger_estimate"]
    statement_id: str | None = None
    balance: float | None = Field(default=None, ge=0)
    credit_limit: float | None = Field(default=None, ge=0)
    utilization_pct: float | None = Field(default=None, ge=0)
    status: Literal[
        "within_target",
        "within_limit",
        "over_target",
        "over_limit",
        "unavailable",
    ] = "unavailable"
    source_transaction_count: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)


class CardUtilizationHistoryResponse(BaseModel):
    """Historical utilization trend with a bounded current-cycle roll-forward."""

    financial_account_id: str
    as_of: date
    utilization_target_pct: float | None = Field(default=None, ge=0, le=100)
    statement_points: list[CardUtilizationHistoryPoint] = Field(default_factory=list)
    daily_points: list[CardUtilizationHistoryPoint] = Field(default_factory=list)
    trend: Literal["improving", "worsening", "stable", "insufficient_history", "unavailable"]
    trend_basis: Literal[
        "issuer_statements",
        "issuer_to_current_estimate",
        "unavailable",
    ] = "unavailable"
    trend_delta_pct: float | None = None
    peak_statement_utilization_pct: float | None = Field(default=None, ge=0)
    peak_daily_utilization_pct: float | None = Field(default=None, ge=0)
    target_breach_count: int = Field(default=0, ge=0)
    credit_limit_breach_count: int = Field(default=0, ge=0)
    reason_codes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-utilization-history-1"


class CardPaymentScenario(BaseModel):
    """One deterministic card-payment strategy evaluated against the runway."""

    scenario: Literal["minimum_due", "total_due"]
    payment_date: date
    payment_amount: float = Field(
        ...,
        ge=0,
        description=(
            "Issuer-stated strategy amount. This is a planning target, not a submitted payment."
        ),
    )
    planned_payment_applied: float = Field(
        default=0,
        ge=0,
        description="Existing planned payment intention credited toward this strategy.",
    )
    additional_payment_amount: float = Field(
        default=0,
        ge=0,
        description="Additional amount beyond existing planned intentions needed for this strategy.",
    )
    effective_payment_amount: float = Field(
        ...,
        ge=0,
        description="Total hypothetical cash leaving the funding account, including planned intentions.",
    )
    remaining_total_due: float = Field(
        ...,
        ge=0,
        description="Billed total remaining after the hypothetical payment plan.",
    )
    expected_funding_balance_after: float | None = None
    lower_band_funding_balance_after: float | None = None
    upper_band_funding_balance_after: float | None = None
    expected_cash_gap: float | None = Field(default=None, ge=0)
    lower_band_cash_gap: float | None = Field(default=None, ge=0)
    expected_covered: bool | None = None
    lower_band_covered: bool | None = None
    status: Literal["covered", "at_risk", "unavailable"] = "unavailable"


class CardDueRunwayResponse(BaseModel):
    """Affordability of the issuer-stated total due from one funding account."""

    financial_account_id: str
    currency: str
    status: Literal[
        "covered",
        "at_risk",
        "needs_statement",
        "needs_payment_account",
        "needs_funding_anchor",
        "needs_review",
        "due_passed",
    ]
    statement_date: date | None
    due_date: date | None
    days_until_due: int | None
    total_due: float | None
    minimum_due: float | None
    estimated_current_outstanding: float | None
    credit_limit: float | None
    issuer_available_credit_limit: float | None
    funding_account_id: str | None
    funding_account_label: str | None
    funding_balance_basis: Literal["observed", "estimated"] | None
    funding_balance_as_of: date | None
    funding_position_status: str | None
    funding_balance_before_due_expected: float | None
    funding_balance_before_due_low: float | None
    funding_balance_before_due_high: float | None
    expected_balance_after_total_due: float | None
    expected_cash_gap: float | None
    lower_band_cash_gap: float | None
    planned_payment_total: float = 0.0
    expected_total_due_covered: bool | None
    lower_band_total_due_covered: bool | None
    minimum_due_covered_on_lower_band: bool | None
    payment_scenarios: list[CardPaymentScenario] = Field(
        default_factory=list,
        description=(
            "Minimum- and total-due planning scenarios. They are deterministic estimates, "
            "not payment instructions or issuer confirmations."
        ),
    )
    confidence: float = Field(default=0.0, ge=0, le=1)
    position_reason_codes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-due-runway-2"


class CardPortfolioPaymentPlanFundingPath(BaseModel):
    """One funding-account path after a hypothetical portfolio payment plan."""

    funding_account_id: str
    funding_account_label: str
    card_ids: list[str] = Field(default_factory=list)
    cards_covered_on_lower_band: int = Field(default=0, ge=0)
    cards_at_risk: int = Field(default=0, ge=0)
    forecast_status: Literal["ready", "needs_anchor", "needs_review"]
    status: Literal["covered", "at_risk", "needs_review", "unavailable"]
    starting_balance: float | None = None
    starting_balance_as_of: date | None = None
    starting_balance_basis: Literal["observed", "estimated"] | None = None
    lowest_expected_balance_after: float | None = None
    lowest_lower_band_balance_after: float | None = None
    lowest_upper_band_balance_after: float | None = None
    first_lower_band_shortfall_date: date | None = None
    lower_band_cash_gap: float | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class CardPortfolioPaymentPlanStrategy(BaseModel):
    """A portfolio-wide minimum- or total-due payment target."""

    strategy: Literal["minimum_due", "total_due"]
    status: Literal[
        "covered",
        "at_risk",
        "needs_statement",
        "needs_payment_account",
        "needs_review",
        "unavailable",
    ]
    issuer_payment_target_total: float | None = Field(default=None, ge=0)
    planned_payment_total: float = Field(default=0, ge=0)
    additional_payment_total: float | None = Field(default=None, ge=0)
    effective_payment_total: float | None = Field(default=None, ge=0)
    remaining_total_due: float | None = Field(default=None, ge=0)
    cards_with_target: int = Field(default=0, ge=0)
    cards_with_funding_path: int = Field(default=0, ge=0)
    cards_covered_on_lower_band: int = Field(default=0, ge=0)
    cards_at_risk: int = Field(default=0, ge=0)
    cards_unavailable: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    funding_paths: list[CardPortfolioPaymentPlanFundingPath] = Field(default_factory=list)


class CardPortfolioPaymentPlanCard(BaseModel):
    """Per-card evidence retained inside a portfolio payment-plan comparison."""

    financial_account_id: str
    label: str
    currency: str
    runway_status: Literal[
        "covered",
        "at_risk",
        "needs_statement",
        "needs_payment_account",
        "needs_funding_anchor",
        "needs_review",
        "due_passed",
    ]
    statement_date: date | None = None
    due_date: date | None = None
    total_due: float | None = Field(default=None, ge=0)
    minimum_due: float | None = Field(default=None, ge=0)
    funding_account_id: str | None = None
    funding_account_label: str | None = None
    minimum_due_scenario: CardPaymentScenario | None = None
    total_due_scenario: CardPaymentScenario | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class CardPortfolioPaymentPlanResponse(BaseModel):
    """Read-only comparison of minimum- and total-due plans across active cards."""

    as_of: date
    state: Literal["no_active_cards", "ready", "partial", "needs_review"]
    card_count: int = Field(..., ge=0)
    cards_with_statement: int = Field(default=0, ge=0)
    cards_needing_review: int = Field(default=0, ge=0)
    minimum_due_plan: CardPortfolioPaymentPlanStrategy
    total_due_plan: CardPortfolioPaymentPlanStrategy
    cards: list[CardPortfolioPaymentPlanCard] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ruleset_version: str = "pfis-card-portfolio-payment-plan-1"
