"""Financial account domain model."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FinancialAccount(Base):
    """A user-owned financial account with explicit identity evidence."""

    __tablename__ = "financial_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "institution_name",
            "account_type",
            "masked_number",
            name="uq_financial_accounts_user_identity",
        ),
        Index("ix_financial_accounts_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    institution_name: Mapped[str] = mapped_column(String(160), nullable=False, default="Unknown")
    account_type: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    balance_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="asset")
    masked_number: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    connector_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    identity_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unresolved", server_default="unresolved"
    )
    identity_confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0.350"), server_default="0.350"
    )
    identity_evidence_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    user = relationship("User", back_populates="financial_accounts")
    transactions = relationship("Transaction", back_populates="financial_account")
    balance_snapshots = relationship(
        "AccountBalanceSnapshot",
        back_populates="financial_account",
        cascade="all, delete-orphan",
        order_by="AccountBalanceSnapshot.as_of",
    )
    balance_source_states = relationship(
        "AccountBalanceSource",
        back_populates="financial_account",
        cascade="all, delete-orphan",
    )
    card_position_observations = relationship(
        "CardPositionObservation",
        back_populates="financial_account",
        cascade="all, delete-orphan",
        order_by="CardPositionObservation.as_of",
    )
    balance_provider_mappings = relationship(
        "BalanceProviderAccountMapping",
        back_populates="financial_account",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<FinancialAccount {self.institution_name} {self.masked_number}>"


class AccountLinkRule(Base):
    """A user-approved mapping from explicit source evidence to one owned product."""

    __tablename__ = "account_link_rules"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "evidence_kind",
            "evidence_value",
            "currency",
            name="uq_account_link_rules_user_evidence",
        ),
        Index("ix_account_link_rules_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    evidence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_value: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AccountBalanceSnapshot(Base):
    """Append-only balance observation for a user-owned financial account."""

    __tablename__ = "account_balance_snapshots"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_account_balance_amount_nonnegative"),
        UniqueConstraint(
            "financial_account_id",
            "source",
            "source_record_id",
            name="uq_account_balance_snapshots_source_record",
        ),
        Index(
            "ix_account_balance_snapshots_account_effective",
            "financial_account_id",
            "as_of",
            "effective_at",
        ),
        Index("ix_account_balance_snapshots_user_as_of", "user_id", "as_of"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    financial_account = relationship("FinancialAccount", back_populates="balance_snapshots")

    def __repr__(self) -> str:
        return f"<AccountBalanceSnapshot {self.financial_account_id} {self.as_of}>"


class AccountBalanceSource(Base):
    """Durable freshness and coverage state for one balance source.

    This is operational metadata, not another balance fact.  It records how a
    provider (or statement importer) is expected to refresh an account and
    whether the latest observation covered the activity window that the
    position calculation relies on.
    """

    __tablename__ = "account_balance_sources"
    __table_args__ = (
        CheckConstraint(
            "expected_cadence_minutes IS NULL OR expected_cadence_minutes > 0",
            name="ck_account_balance_sources_cadence_positive",
        ),
        UniqueConstraint(
            "financial_account_id",
            "source",
            "source_account_id",
            name="uq_account_balance_sources_account_source",
        ),
        Index(
            "ix_account_balance_sources_user_updated",
            "user_id",
            "updated_at",
        ),
        Index(
            "ix_account_balance_sources_account_source",
            "financial_account_id",
            "source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    # Provider account identity is intentionally opaque and never stores an
    # access token or other credential.  Empty string is the stable key for a
    # source that has only one account-level stream.
    source_account_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="", server_default=""
    )
    expected_cadence_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coverage_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_source_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Opaque provider pagination cursor used only by the connector runner.
    # It is never returned in the user-facing coverage response.
    cursor_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    financial_account = relationship("FinancialAccount", back_populates="balance_source_states")

    def __repr__(self) -> str:
        return f"<AccountBalanceSource {self.financial_account_id} {self.source}>"
