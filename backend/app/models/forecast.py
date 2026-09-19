"""Immutable forecast predictions and their later observed outcomes."""

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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CashFlowForecastSnapshot(Base):
    """A forecast frozen at the financial-day cutoff when it was requested."""

    __tablename__ = "cash_flow_forecast_snapshots"
    __table_args__ = (
        CheckConstraint("target_month BETWEEN 1 AND 12", name="ck_forecast_snapshot_month"),
        CheckConstraint("target_year BETWEEN 2020 AND 2030", name="ck_forecast_snapshot_year"),
        UniqueConstraint(
            "user_id",
            "target_year",
            "target_month",
            "cutoff_date",
            "forecast_ruleset_version",
            name="uq_cash_flow_forecast_snapshot_cutoff",
        ),
        Index(
            "ix_cash_flow_forecast_snapshots_user_target",
            "user_id",
            "target_year",
            "target_month",
            "cutoff_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    target_year: Mapped[int] = mapped_column(nullable=False)
    target_month: Mapped[int] = mapped_column(nullable=False)
    cutoff_date: Mapped[date] = mapped_column(Date, nullable=False)
    forecast_ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    temporal_ruleset_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    projected_spend: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    projected_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    projected_range_low: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    projected_range_high: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    temporal_expected_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    temporal_expected_outflows: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    temporal_conflicted_outflows: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    data_sufficiency: Mapped[str] = mapped_column(String(12), nullable=False)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CashFlowForecastOutcome(Base):
    """Observed target-month truth evaluated once against one frozen prediction."""

    __tablename__ = "cash_flow_forecast_outcomes"
    __table_args__ = (
        UniqueConstraint("snapshot_id", name="uq_cash_flow_forecast_outcome_snapshot"),
        Index("ix_cash_flow_forecast_outcomes_user_evaluated", "user_id", "evaluated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("cash_flow_forecast_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    outcome_ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    actual_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_spend: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    spend_absolute_error: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    spend_absolute_percentage_error: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3), nullable=True
    )
    spend_range_covered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AccountBalanceForecastSnapshot(Base):
    """Immutable daily account forecast captured at a financial-day cutoff."""

    __tablename__ = "account_balance_forecast_snapshots"
    __table_args__ = (
        CheckConstraint(
            "horizon_days BETWEEN 1 AND 180",
            name="ck_account_balance_forecast_snapshot_horizon",
        ),
        UniqueConstraint(
            "user_id",
            "financial_account_id",
            "cutoff_date",
            "horizon_days",
            "forecast_ruleset_version",
            name="uq_account_balance_forecast_snapshot_cutoff",
        ),
        Index(
            "ix_account_balance_forecast_snapshots_user_account_cutoff",
            "user_id",
            "financial_account_id",
            "cutoff_date",
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
    balance_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    cutoff_date: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_start: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_end: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_days: Mapped[int] = mapped_column(nullable=False)
    forecast_ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    starting_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    starting_balance_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    starting_balance_basis: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expected_ending_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    expected_change: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    lowest_expected_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    lowest_expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_shortfall_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_count: Mapped[int] = mapped_column(nullable=False, default=0)
    historical_days: Mapped[int] = mapped_column(nullable=False, default=0)
    historical_activity_count: Mapped[int] = mapped_column(nullable=False, default=0)
    coverage_status: Mapped[str] = mapped_column(String(12), nullable=False)
    position_status: Mapped[str] = mapped_column(String(24), nullable=False)
    position_confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    data_sufficiency: Mapped[str] = mapped_column(String(12), nullable=False)
    position_reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    assumptions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    points_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class AccountBalanceForecastOutcome(Base):
    """One observed balance matched to one frozen forecast point."""

    __tablename__ = "account_balance_forecast_outcomes"
    __table_args__ = (
        CheckConstraint(
            "actual_balance >= 0",
            name="ck_account_balance_forecast_outcome_actual_nonnegative",
        ),
        UniqueConstraint(
            "snapshot_id",
            "target_date",
            name="uq_account_balance_forecast_outcome_snapshot_date",
        ),
        Index(
            "ix_account_balance_forecast_outcomes_user_account_date",
            "user_id",
            "financial_account_id",
            "target_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_balance_forecast_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_observation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("account_balance_snapshots.id"),
        nullable=False,
    )
    actual_source: Mapped[str] = mapped_column(String(24), nullable=False)
    actual_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    low_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    high_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    signed_error: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    absolute_error: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    interval_covered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    predicted_risk: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome_ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
