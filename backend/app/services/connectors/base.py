"""Base connector contracts for source ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from app.services.connectors.source_record import SourceRecord


class ConnectorErrorType(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConnectorCursor:
    history_id: str | None = None
    fallback_used: bool = False
    # Provider-neutral opaque pagination cursor.  It is deliberately separate
    # from Gmail's history ID so a balance connector can resume a provider
    # response without leaking provider-specific fields into the contract.
    opaque_token: str | None = None

    def __post_init__(self) -> None:
        if self.opaque_token is not None and len(self.opaque_token) > 512:
            raise ValueError("opaque provider cursor cannot exceed 512 characters")


@dataclass(frozen=True)
class ConnectorError:
    error_type: ConnectorErrorType
    message: str
    retryable: bool


@dataclass(frozen=True)
class ConnectorBatch:
    records: list[SourceRecord]
    cursor: ConnectorCursor
    metrics: dict[str, int | float | bool] = field(default_factory=dict)
    errors: list[ConnectorError] = field(default_factory=list)


@dataclass(frozen=True)
class BalanceObservation:
    """Connector-neutral balance fact supplied by a trusted provider.

    The local financial-account ID is resolved before ingestion; the opaque
    source account and record IDs preserve provider lineage without storing
    credentials.  Coverage is explicit because a successful provider call can
    still be truncated or history-limited.
    """

    financial_account_id: str
    amount: Decimal
    currency: str
    as_of: date
    source_record_id: str
    observed_at: datetime
    source: str = "connector"
    source_account_id: str | None = None
    effective_at: datetime | None = None
    expected_cadence_minutes: int | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_complete: bool = True

    def __post_init__(self) -> None:
        if not self.financial_account_id.strip():
            raise ValueError("financial_account_id is required")
        if not self.source_record_id.strip():
            raise ValueError("source_record_id is required")
        if self.amount < 0:
            raise ValueError("amount must be non-negative")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        if self.effective_at is not None:
            if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
                raise ValueError("effective_at must include a timezone")
            if self.effective_at > self.observed_at:
                raise ValueError("effective_at cannot be after observed_at")
        if self.coverage_start is not None and (
            self.coverage_start.tzinfo is None or self.coverage_start.utcoffset() is None
        ):
            raise ValueError("coverage_start must include a timezone")
        if self.coverage_end is not None and (
            self.coverage_end.tzinfo is None or self.coverage_end.utcoffset() is None
        ):
            raise ValueError("coverage_end must include a timezone")
        if (
            self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_end < self.coverage_start
        ):
            raise ValueError("coverage_end must be on or after coverage_start")
        if self.coverage_complete and (self.coverage_start is None or self.coverage_end is None):
            raise ValueError("complete coverage requires coverage_start and coverage_end")
        if self.expected_cadence_minutes is not None and self.expected_cadence_minutes <= 0:
            raise ValueError("expected_cadence_minutes must be positive")


@dataclass(frozen=True)
class CardPositionObservation:
    """Issuer-provided card facts attached to one balance refresh.

    ``current_outstanding`` is required because it is the liability fact that
    can update the account position.  The other fields remain independent
    issuer facts: PFIS must not derive available credit or billed due from an
    estimated balance when the provider did not supply them.
    """

    financial_account_id: str
    currency: str
    current_outstanding: Decimal
    as_of: date
    source_record_id: str
    observed_at: datetime
    billed_due: Decimal | None = None
    pending_amount: Decimal | None = None
    credit_limit: Decimal | None = None
    available_credit: Decimal | None = None
    source: str = "connector"
    source_account_id: str | None = None
    effective_at: datetime | None = None
    expected_cadence_minutes: int | None = None
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    coverage_complete: bool = True

    def __post_init__(self) -> None:
        if not self.financial_account_id.strip():
            raise ValueError("financial_account_id is required")
        if not self.source_record_id.strip():
            raise ValueError("source_record_id is required")
        if self.source != "connector":
            raise ValueError("Card provider observations must use source=connector")
        for name, value in (
            ("current_outstanding", self.current_outstanding),
            ("billed_due", self.billed_due),
            ("pending_amount", self.pending_amount),
            ("credit_limit", self.credit_limit),
            ("available_credit", self.available_credit),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        if self.effective_at is not None:
            if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
                raise ValueError("effective_at must include a timezone")
            if self.effective_at > self.observed_at:
                raise ValueError("effective_at cannot be after observed_at")
        if self.coverage_start is not None and (
            self.coverage_start.tzinfo is None or self.coverage_start.utcoffset() is None
        ):
            raise ValueError("coverage_start must include a timezone")
        if self.coverage_end is not None and (
            self.coverage_end.tzinfo is None or self.coverage_end.utcoffset() is None
        ):
            raise ValueError("coverage_end must include a timezone")
        if (
            self.coverage_start is not None
            and self.coverage_end is not None
            and self.coverage_end < self.coverage_start
        ):
            raise ValueError("coverage_end must be on or after coverage_start")
        if self.coverage_complete and (self.coverage_start is None or self.coverage_end is None):
            raise ValueError("complete coverage requires coverage_start and coverage_end")
        if self.expected_cadence_minutes is not None and self.expected_cadence_minutes <= 0:
            raise ValueError("expected_cadence_minutes must be positive")


@dataclass(frozen=True)
class BalanceAccountCandidate:
    """A provider-discovered account identity awaiting user mapping."""

    provider_account_id: str
    display_name: str | None = None
    masked_number: str | None = None
    account_type: str | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_account_id.strip():
            raise ValueError("provider_account_id is required")
        if len(self.provider_account_id.strip()) > 128:
            raise ValueError("provider_account_id is too long")
        for value, field_name, limit in (
            (self.display_name, "display_name", 160),
            (self.masked_number, "masked_number", 32),
            (self.account_type, "account_type", 40),
            (self.currency, "currency", 3),
        ):
            if value is not None and len(value.strip()) > limit:
                raise ValueError(f"{field_name} is too long")


class BalanceAccountDiscovery(Protocol):
    """Optional provider capability for account discovery before mapping."""

    async def discover_accounts(self, user_id: str) -> list[BalanceAccountCandidate]: ...


@dataclass(frozen=True)
class BalanceObservationBatch:
    """A provider response containing append-only observations."""

    source: str
    observations: list[BalanceObservation] = field(default_factory=list)
    card_observations: list[CardPositionObservation] = field(default_factory=list)
    cursor: ConnectorCursor = field(default_factory=ConnectorCursor)
    coverage_complete: bool = True
    errors: list[ConnectorError] = field(default_factory=list)
    # A connector can fail before it returns an observation.  These opaque
    # local account IDs let ingestion persist that failure against the right
    # source-health rows without storing credentials or provider payloads.
    affected_account_ids: list[str] = field(default_factory=list)

    def validate_for_accounts(self, account_ids: set[str]) -> None:
        """Validate a connector response before any financial row is written.

        Provider responses are untrusted input even after transport
        authentication.  Reject duplicate source identities and account IDs
        outside the requested scope so a retry cannot silently overwrite a
        different position or attach one provider response to another user's
        account.
        """

        if self.source != "connector":
            raise ValueError("Balance connector batches must use source=connector")
        if not account_ids:
            raise ValueError("At least one requested account is required")
        if len(self.affected_account_ids) != len(set(self.affected_account_ids)):
            raise ValueError("Balance connector affected accounts must be unique")
        if not set(self.affected_account_ids).issubset(account_ids):
            raise ValueError("Balance connector affected an unrequested account")

        seen_balance_ids: set[tuple[str, str]] = set()
        for observation in self.observations:
            key = (observation.financial_account_id, observation.source_record_id)
            if key in seen_balance_ids:
                raise ValueError("Balance connector returned a duplicate source record")
            seen_balance_ids.add(key)
            if observation.financial_account_id not in account_ids:
                raise ValueError("Balance connector returned an unrequested account")

        seen_card_ids: set[tuple[str, str]] = set()
        for card_observation in self.card_observations:
            key = (card_observation.financial_account_id, card_observation.source_record_id)
            if key in seen_card_ids:
                raise ValueError("Card connector returned a duplicate source record")
            seen_card_ids.add(key)
            if card_observation.financial_account_id not in account_ids:
                raise ValueError("Card connector returned an unrequested account")


class BalanceConnector(Protocol):
    """Read-only provider contract for observed bank/card positions."""

    source_type: str

    async def fetch_balance_observations(
        self,
        user_id: str,
        account_ids: list[str],
        cursor: ConnectorCursor,
    ) -> BalanceObservationBatch: ...


@dataclass(frozen=True)
class BackfillOptions:
    max_results: int | None = 500


class BaseConnector(Protocol):
    source_type: str

    async def fetch_incremental(self, user_id: str, cursor: ConnectorCursor) -> ConnectorBatch: ...

    async def fetch_backfill(self, user_id: str, options: BackfillOptions) -> ConnectorBatch: ...

    async def refresh_credentials(self) -> dict[str, Any]: ...
