"""Verified financial-position, statement, and planning domain records.

These tables deliberately store structured financial evidence, never uploaded PDF
bytes or passwords.  Every record is user scoped and can therefore be queried
without relying on a provider-specific source after import.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
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


class StatementImport(Base):
    __tablename__ = "statement_imports"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "document_fingerprint", name="uq_statement_import_user_fingerprint"
        ),
        Index("ix_statement_imports_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    issuer: Mapped[str] = mapped_column(String(40), nullable=False)
    document_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="imported")
    rejection_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StatementAnalysisReview(Base):
    """Durable, redacted analysis for a statement not yet safe to import.

    This record deliberately has no financial-account foreign key and never
    stores source text or uploaded bytes.  It lets an ambiguous or unfamiliar
    statement remain reviewable before account mapping or ledger mutation.
    """

    __tablename__ = "statement_analysis_reviews"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_fingerprint",
            name="uq_statement_analysis_review_user_fingerprint",
        ),
        Index(
            "ix_statement_analysis_reviews_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    document_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(40), nullable=True)
    product_type: Mapped[str] = mapped_column(String(24), nullable=False)
    format_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    support_status: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    activity_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    analysis_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_review")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CardPositionObservation(Base):
    """Append-only issuer facts for a credit-card position.

    Statement fields and provider position fields are deliberately separate:
    a refresh may report current outstanding without changing the last billed
    statement, and missing issuer fields remain NULL instead of being derived.
    """

    __tablename__ = "card_position_observations"
    __table_args__ = (
        CheckConstraint(
            "current_outstanding >= 0",
            name="ck_card_position_current_outstanding_nonnegative",
        ),
        CheckConstraint(
            "billed_due IS NULL OR billed_due >= 0",
            name="ck_card_position_billed_due_nonnegative",
        ),
        CheckConstraint(
            "pending_amount IS NULL OR pending_amount >= 0",
            name="ck_card_position_pending_nonnegative",
        ),
        CheckConstraint(
            "credit_limit IS NULL OR credit_limit >= 0",
            name="ck_card_position_credit_limit_nonnegative",
        ),
        CheckConstraint(
            "available_credit IS NULL OR available_credit >= 0",
            name="ck_card_position_available_credit_nonnegative",
        ),
        CheckConstraint(
            "expected_cadence_minutes IS NULL OR expected_cadence_minutes > 0",
            name="ck_card_position_cadence_positive",
        ),
        UniqueConstraint(
            "financial_account_id",
            "source",
            "source_record_id",
            name="uq_card_position_observations_source_record",
        ),
        Index(
            "ix_card_position_observations_user_account_as_of",
            "user_id",
            "financial_account_id",
            "as_of",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    current_outstanding: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    billed_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    pending_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    available_credit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="connector")
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_cadence_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coverage_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coverage_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    financial_account = relationship(
        "FinancialAccount", back_populates="card_position_observations"
    )


class CreditCardStatement(Base):
    __tablename__ = "credit_card_statements"
    __table_args__ = (
        UniqueConstraint(
            "financial_account_id", "statement_date", name="uq_card_statement_account_date"
        ),
        Index("ix_card_statements_user_date", "user_id", "statement_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    statement_import_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("statement_imports.id"), nullable=False, unique=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    minimum_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    available_credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    available_cash_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    previous_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    payments_credits: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    purchases_debits: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    finance_charges: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DepositAccountStatement(Base):
    """One arithmetically reconciled statement for a user-owned bank account."""

    __tablename__ = "deposit_account_statements"
    __table_args__ = (
        UniqueConstraint("statement_import_id", name="uq_deposit_statement_import"),
        UniqueConstraint(
            "financial_account_id",
            "period_start",
            "period_end",
            name="uq_deposit_statement_account_period",
        ),
        CheckConstraint("opening_balance >= 0", name="ck_deposit_statement_opening_nonnegative"),
        CheckConstraint("closing_balance >= 0", name="ck_deposit_statement_closing_nonnegative"),
        Index("ix_deposit_statements_user_period", "user_id", "period_end"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    statement_import_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("statement_imports.id"), nullable=False
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DepositStatementLine(Base):
    """Durable source evidence for one bank-statement activity row."""

    __tablename__ = "deposit_statement_lines"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_deposit_statement_line_amount_positive"),
        CheckConstraint("balance_after >= 0", name="ck_deposit_statement_line_balance_nonnegative"),
        CheckConstraint(
            "transaction_type IN ('debit', 'credit')",
            name="ck_deposit_statement_line_type",
        ),
        UniqueConstraint(
            "deposit_account_statement_id",
            "line_number",
            name="uq_deposit_statement_line_number",
        ),
        Index("ix_deposit_statement_lines_user_review", "user_id", "review_outcome"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    deposit_account_statement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("deposit_account_statements.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(12), nullable=False)
    payment_rail: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    balance_after: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    review_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    created_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DepositStatementLineReviewDecision(Base):
    """Append-only evidence of an explicit deposit-line classification decision."""

    __tablename__ = "deposit_statement_line_review_decisions"
    __table_args__ = (
        Index(
            "ix_deposit_statement_review_decisions_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_deposit_line_review_decisions_line_id",
            "deposit_statement_line_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    deposit_statement_line_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("deposit_statement_lines.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    new_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    payment_rail: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StatementLine(Base):
    __tablename__ = "statement_lines"
    __table_args__ = (
        Index("ix_statement_lines_user_review", "user_id", "review_outcome"),
        UniqueConstraint(
            "credit_card_statement_id", "line_number", name="uq_statement_line_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    credit_card_statement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("credit_card_statements.id"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transaction_type: Mapped[str] = mapped_column(String(12), nullable=False)
    card_event: Mapped[str] = mapped_column(String(20), nullable=False, default="purchase")
    component_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ordinary", index=True
    )
    issuer_plan_reference: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    installment_number: Mapped[int | None] = mapped_column(nullable=True)
    merchant_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    merchant_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="needs_review")
    created_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StatementLineMatch(Base):
    __tablename__ = "statement_line_matches"
    __table_args__ = (
        UniqueConstraint("statement_line_id", name="uq_statement_line_match_line"),
        UniqueConstraint("transaction_id", name="uq_statement_line_match_transaction"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    statement_line_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("statement_lines.id"), nullable=False
    )
    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=False
    )
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class StatementLineReviewDecision(Base):
    """Append-only evidence of an explicit statement-line review decision."""

    __tablename__ = "statement_line_review_decisions"
    __table_args__ = (
        Index(
            "ix_statement_review_decisions_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    statement_line_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("statement_lines.id"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    new_outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    matched_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    paying_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AccountBalanceReconciliation(Base):
    """Immutable comparison between two verified balance observations."""

    __tablename__ = "account_balance_reconciliations"
    __table_args__ = (
        UniqueConstraint(
            "opening_snapshot_id",
            "closing_snapshot_id",
            name="uq_account_balance_reconciliation_interval",
        ),
        Index(
            "ix_account_balance_reconciliations_user_account_closing",
            "user_id",
            "financial_account_id",
            "closing_as_of",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    opening_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_balance_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    closing_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_balance_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    opening_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    closing_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    known_movement: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    observed_closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    residual: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    absolute_residual: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    transaction_count: Mapped[int] = mapped_column(nullable=False, default=0)
    eligible_transaction_count: Mapped[int] = mapped_column(nullable=False, default=0)
    excluded_transaction_count: Mapped[int] = mapped_column(nullable=False, default=0)
    eligible_transaction_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    excluded_transaction_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reconciliation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Commitment(Base):
    __tablename__ = "commitments"
    __table_args__ = (Index("ix_commitments_user_due", "user_id", "due_date", "is_active"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=True
    )
    liability_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("liabilities.id"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    commitment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    cadence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    source_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CashPlan(Base):
    __tablename__ = "cash_plans"
    __table_args__ = (UniqueConstraint("user_id", name="uq_cash_plan_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    primary_financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False
    )
    next_income_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_income_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    show_daily_allowance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ReservePlan(Base):
    __tablename__ = "reserve_plans"
    __table_args__ = (Index("ix_reserve_plans_user_due", "user_id", "due_date", "approved"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    monthly_allocation: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Liability(Base):
    __tablename__ = "liabilities"
    __table_args__ = (
        Index("ix_liabilities_user_active", "user_id", "is_active"),
        Index("ix_liabilities_user_schedule_status", "user_id", "schedule_status"),
        UniqueConstraint(
            "user_id",
            "financial_account_id",
            "issuer_plan_reference",
            name="uq_liability_user_account_plan",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    liability_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    source_identifier: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    issuer_plan_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outstanding_principal: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    monthly_due: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    tenure_months: Mapped[int | None] = mapped_column(nullable=True)
    remaining_installments: Mapped[int | None] = mapped_column(nullable=True)
    observed_original_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    observed_monthly_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    observed_principal_component: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    observed_interest_component: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    observed_tax_component: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    observed_fee_component: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    last_observed_statement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    evidence_line_count: Mapped[int] = mapped_column(nullable=False, default=0)
    schedule_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_provided")
    complete_schedule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class LiabilityScheduleItem(Base):
    __tablename__ = "liability_schedule_items"
    __table_args__ = (
        UniqueConstraint("liability_id", "due_date", name="uq_liability_schedule_due"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    liability_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("liabilities.id"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    installment_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    principal_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    interest_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    source_identifier: Mapped[str | None] = mapped_column(String(160), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="upcoming")


class CardPreference(Base):
    """User-chosen, non-issuer card settings and explicit reward assumptions."""

    __tablename__ = "card_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "financial_account_id", name="uq_card_preferences_user_account"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False
    )
    preferred_payment_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=True
    )
    utilization_target_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    reward_rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CardPaymentIntent(Base):
    """A user planning note; it never initiates a payment with an issuer or bank."""

    __tablename__ = "card_payment_intents"
    __table_args__ = (
        Index("ix_card_payment_intents_user_date", "user_id", "planned_for", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False
    )
    paying_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    planned_for: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    note: Mapped[str | None] = mapped_column(String(240), nullable=True)
    transfer_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CardCalendarEvent(Base):
    __tablename__ = "card_calendar_events"
    __table_args__ = (Index("ix_card_calendar_events_user_date", "user_id", "event_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
