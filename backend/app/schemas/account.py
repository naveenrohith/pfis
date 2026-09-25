"""Account, balance, net-worth, and transfer API contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BalanceKind = Literal["asset", "liability"]
AccountProductType = Literal[
    "bank", "credit_card", "loan", "pay_later", "cash", "investment", "unknown"
]
AccountIdentityStatus = Literal["unresolved", "inferred", "confirmed"]
CurrentPositionStatus = Literal[
    "needs_observation", "observed", "estimated", "stale", "incomplete", "needs_review"
]


def _normalize_account_type(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    return {
        "credit": "credit_card",
        "credit card": "credit_card",
        "pay later": "pay_later",
        "pay-later": "pay_later",
    }.get(normalized, normalized)


class FinancialAccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    institution_name: str = Field(..., min_length=1, max_length=160)
    account_type: AccountProductType = "bank"
    balance_kind: BalanceKind = "asset"
    masked_number: str = Field(..., min_length=2, max_length=32)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    @field_validator("account_type", mode="before")
    @classmethod
    def normalize_account_type(cls, value: object) -> object:
        return _normalize_account_type(value)

    @field_validator("balance_kind", mode="before")
    @classmethod
    def normalize_balance_kind(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FinancialAccountUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    institution_name: str | None = Field(None, min_length=1, max_length=160)
    account_type: AccountProductType | None = None
    balance_kind: BalanceKind | None = None
    masked_number: str | None = Field(None, min_length=2, max_length=32)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    is_active: bool | None = None

    @field_validator("account_type", mode="before")
    @classmethod
    def normalize_account_type(cls, value: object) -> object:
        return _normalize_account_type(value)

    @field_validator("balance_kind", mode="before")
    @classmethod
    def normalize_balance_kind(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FinancialAccountResponse(BaseModel):
    id: str
    user_id: str
    institution_name: str
    account_type: AccountProductType
    balance_kind: BalanceKind
    masked_number: str
    currency: str
    is_active: bool
    identity_status: AccountIdentityStatus = "unresolved"
    identity_confidence: float = Field(default=0.35, ge=0, le=1)
    identity_evidence: list["AccountIdentityEvidence"] = Field(default_factory=list)
    latest_balance: float | None = None
    balance_as_of: date | None = None
    # The latest verified snapshot remains separate from the server-owned
    # current position.  These fields roll eligible settled activity forward
    # without ever calling a transaction-derived estimate provider-live.
    current_balance: float | None = None
    current_balance_as_of: date | None = None
    current_balance_status: CurrentPositionStatus = "needs_observation"
    current_balance_confidence: float = Field(default=0.0, ge=0, le=1)
    current_balance_reason_codes: list[str] = Field(default_factory=list)
    latest_observed_balance: float | None = None
    latest_observed_as_of: date | None = None
    latest_observed_verified: bool | None = None
    created_at: datetime
    updated_at: datetime | None = None


class AccountIdentityEvidence(BaseModel):
    """One durable reason PFIS currently trusts an account identity."""

    source_type: str = Field(..., min_length=1, max_length=40)
    source_id: str = Field(..., min_length=1, max_length=160)
    role: str = Field(..., min_length=1, max_length=40)
    note: str | None = Field(None, max_length=240)
    observed_at: datetime | None = None


class AccountIdentitySnapshotResponse(BaseModel):
    """An immutable account identity/lifecycle observation."""

    financial_account_id: str
    captured_at: datetime
    effective_date: date
    institution_name: str
    account_type: AccountProductType
    balance_kind: BalanceKind
    masked_number: str
    currency: str
    is_active: bool
    identity_status: AccountIdentityStatus
    identity_confidence: float = Field(..., ge=0, le=1)
    identity_evidence: list[AccountIdentityEvidence] = Field(default_factory=list)


class AccountLinkRuleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    financial_account_id: str
    evidence_kind: Literal["masked_suffix"] = "masked_suffix"
    evidence_value: str = Field(..., pattern=r"^\d{4}$")
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_rule_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class AccountLinkRuleResponse(AccountLinkRuleCreate):
    id: str
    user_id: str
    is_active: bool
    repaired_transaction_count: int = 0
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BalanceSnapshotCreate(BaseModel):
    amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    as_of: date
    source: Literal["manual", "statement", "connector"] = "manual"
    source_record_id: str | None = Field(None, max_length=128)
    verified: bool = True
    observed_at: datetime | None = None
    effective_at: datetime | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class BalanceSnapshotResponse(BaseModel):
    id: str
    financial_account_id: str
    amount: float
    currency: str
    as_of: date
    source: str
    source_record_id: str | None = None
    verified: bool = True
    observed_at: datetime
    effective_at: datetime | None = None
    created_at: datetime


class BalanceObservationCreate(BaseModel):
    """Provider-neutral account balance observation envelope.

    A connector must provide a stable source record identity and the provider
    coverage window.  This lets PFIS retry safely and fail closed when a
    provider response is truncated or only partially covers transaction
    history.
    """

    amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    as_of: date
    source_record_id: str = Field(..., min_length=1, max_length=128)
    source_account_id: str | None = Field(None, max_length=128)
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    expected_cadence_minutes: int | None = Field(None, gt=0, le=60 * 24 * 31)
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_complete: bool = True

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_coverage_window(self):
        if (
            self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_end < self.coverage_start
        ):
            raise ValueError("coverage_end must be on or after coverage_start")
        if self.coverage_complete and (self.coverage_start is None or self.coverage_end is None):
            raise ValueError("complete coverage requires coverage_start and coverage_end")
        if (
            self.effective_at is not None
            and self.observed_at is not None
            and self.effective_at > self.observed_at
        ):
            raise ValueError("effective_at cannot be after observed_at")
        return self

    def to_balance_snapshot_create(self) -> BalanceSnapshotCreate:
        """Return the append-only snapshot payload used by AccountService."""

        return BalanceSnapshotCreate(
            amount=self.amount,
            currency=self.currency,
            as_of=self.as_of,
            source="connector",
            source_record_id=self.source_record_id,
            verified=True,
            observed_at=self.observed_at,
            effective_at=self.effective_at,
        )


class BalanceCoverageResponse(BaseModel):
    financial_account_id: str
    source: str
    source_account_id: str | None = None
    expected_cadence_minutes: int | None = None
    expected_next_at: datetime | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_complete: bool
    last_observed_at: datetime | None = None
    last_effective_at: datetime | None = None
    last_success_at: datetime | None = None
    last_source_record_id: str | None = None
    last_error_code: str | None = None
    freshness_status: Literal["fresh", "due", "overdue", "unknown"]
    reason_codes: list[str] = Field(default_factory=list)


BalanceProviderAccountStatus = Literal[
    "unmapped",
    "not_configured",
    "ready",
    "due",
    "overdue",
    "incomplete",
]
BalanceProviderReadinessStatus = Literal[
    "not_configured",
    "blocked",
    "ready",
    "due",
    "overdue",
    "incomplete",
]
BalanceProviderConnectionStatus = Literal[
    "pending",
    "active",
    "expired",
    "revoked",
    "error",
]


class BalanceProviderConnectionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-z0-9][a-z0-9_.:-]{0,49}$",
    )


class BalanceProviderRefreshRequest(BalanceProviderConnectionRequest):
    account_ids: list[str] = Field(default_factory=list, max_length=100)


class BalanceProviderConnectionResponse(BaseModel):
    id: str
    provider_type: str
    status: BalanceProviderConnectionStatus
    consent_requested_at: datetime | None = None
    consent_granted_at: datetime | None = None
    consent_expires_at: datetime | None = None
    last_refresh_requested_at: datetime | None = None
    last_refresh_started_at: datetime | None = None
    last_refresh_completed_at: datetime | None = None
    last_error_code: str | None = None


class BalanceProviderAccountMappingRequest(BaseModel):
    """Map an owned account to an opaque identity returned by a provider."""

    model_config = ConfigDict(str_strip_whitespace=True)

    provider_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-z0-9][a-z0-9_.:-]{0,49}$",
    )
    provider_account_id: str = Field(..., min_length=1, max_length=128)


class BalanceProviderAccountMappingResponse(BaseModel):
    id: str
    financial_account_id: str
    provider_type: str
    provider_account_id: str
    source: str
    created_at: datetime
    updated_at: datetime


class BalanceProviderAccountCandidateResponse(BaseModel):
    """Non-secret account identity returned by provider discovery."""

    provider_account_id: str
    display_name: str | None = None
    masked_number: str | None = None
    account_type: AccountProductType | None = None
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    mapped_financial_account_id: str | None = None


class BalanceProviderAccountResponse(BaseModel):
    """Provider-refresh readiness for one owned account.

    This is operational state, not a balance fact.  It intentionally keeps
    the provider account key opaque and reports whether a consented connector
    could refresh the account without claiming that one exists.
    """

    financial_account_id: str
    account_type: AccountProductType
    masked_number: str
    status: BalanceProviderAccountStatus
    source_account_id: str | None = None
    expected_next_at: datetime | None = None
    last_observed_at: datetime | None = None
    last_success_at: datetime | None = None
    coverage_complete: bool | None = None
    freshness_status: Literal["fresh", "due", "overdue", "unknown"] = "unknown"
    reason_codes: list[str] = Field(default_factory=list)


class BalanceProviderStatusResponse(BaseModel):
    """Explain whether bank/card amounts can be refreshed from a provider."""

    schema_version: str = "pfis-balance-provider-status-1"
    status: BalanceProviderReadinessStatus
    refresh_supported: bool = False
    consent_required: bool = True
    provider_name: str | None = None
    supported_provider_types: list[str] = Field(default_factory=list)
    connections: list[BalanceProviderConnectionResponse] = Field(default_factory=list)
    account_count: int = Field(..., ge=0)
    mapped_account_count: int = Field(..., ge=0)
    last_success_at: datetime | None = None
    reason_codes: list[str] = Field(default_factory=list)
    next_step: str
    accounts: list[BalanceProviderAccountResponse] = Field(default_factory=list)


class BalanceObservationResponse(BaseModel):
    snapshot: BalanceSnapshotResponse
    coverage: BalanceCoverageResponse


class CardPositionObservationCreate(BaseModel):
    """Issuer card-position facts received from a consented connector."""

    current_outstanding: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    billed_due: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    pending_amount: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    credit_limit: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    available_credit: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=2)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    as_of: date
    source_record_id: str = Field(..., min_length=1, max_length=128)
    source_account_id: str | None = Field(None, max_length=128)
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    expected_cadence_minutes: int | None = Field(None, gt=0, le=60 * 24 * 31)
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_complete: bool = True

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_coverage_window(self):
        if (
            self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_end < self.coverage_start
        ):
            raise ValueError("coverage_end must be on or after coverage_start")
        if self.coverage_complete and (self.coverage_start is None or self.coverage_end is None):
            raise ValueError("complete coverage requires coverage_start and coverage_end")
        if (
            self.effective_at is not None
            and self.observed_at is not None
            and self.effective_at > self.observed_at
        ):
            raise ValueError("effective_at cannot be after observed_at")
        return self


class CardPositionObservationResponse(BaseModel):
    id: str
    financial_account_id: str
    currency: str
    current_outstanding: float
    billed_due: float | None = None
    pending_amount: float | None = None
    credit_limit: float | None = None
    available_credit: float | None = None
    as_of: date
    source: str
    source_record_id: str
    source_account_id: str | None = None
    observed_at: datetime
    effective_at: datetime | None = None
    expected_cadence_minutes: int | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_complete: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NetWorthPoint(BaseModel):
    date: date
    assets: float
    liabilities: float
    net_worth: float


class NetWorthSeries(BaseModel):
    currency: str
    as_of: date | None = None
    assets: float = 0.0
    liabilities: float = 0.0
    net_worth: float = 0.0
    points: list[NetWorthPoint] = Field(default_factory=list)
    current_position_status: Literal[
        "observed",
        "estimated",
        "partial",
        "needs_review",
        "stale",
        "not_available",
        "historical",
    ] = "not_available"
    current_position_confidence: float = Field(default=0.0, ge=0, le=1)
    current_position_reason_codes: list[str] = Field(default_factory=list)
    current_position_as_of: date | None = None


class TransferCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    from_account_id: str
    to_account_id: str
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    transaction_date: date
    description: str | None = Field(None, max_length=160)
    payment_rail: Literal["transfer", "atm"] = "transfer"

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def different_accounts(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("Transfer accounts must be different")
        return self


class TransferResponse(BaseModel):
    transfer_group_id: str
    debit_transaction_id: str
    credit_transaction_id: str
    amount: float
    currency: str
    transaction_date: date
    payment_rail: Literal["transfer", "atm"] = "transfer"


class CashPocketBalanceResponse(BaseModel):
    account_id: str
    user_id: str
    currency: str
    transfers_in: float = 0.0
    cash_spend: float = 0.0
    balance: float = 0.0
    as_of: date | None = None
