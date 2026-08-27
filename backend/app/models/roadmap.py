"""Later-roadmap domains with explicit ownership and privacy boundaries."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


class RoadmapBill(Base):
    __tablename__ = "roadmap_bills"
    __table_args__ = (Index("ix_roadmap_bills_user_due", "user_id", "due_date", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    bill_type: Mapped[str] = mapped_column(String(32), nullable=False, default="bill")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    cadence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="due")
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    source_identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class HealthChecklistItem(Base):
    __tablename__ = "health_checklist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "item_type", name="uq_health_checklist_user_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_started")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CardDispute(Base):
    __tablename__ = "card_disputes"
    __table_args__ = (Index("ix_card_disputes_user_status", "user_id", "status", "complaint_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    financial_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=False, index=True
    )
    statement_line_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("statement_lines.id"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    complaint_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (
        UniqueConstraint("household_id", "user_id", name="uq_household_member"),
        Index("ix_household_members_active", "household_id", "left_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="annotations_only")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HouseholdExpense(Base):
    """A shared annotation, deliberately disconnected from private transaction evidence."""

    __tablename__ = "household_expenses"
    __table_args__ = (
        Index("ix_household_expenses_household_date", "household_id", "expense_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    payer_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    splits_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class HouseholdSettlement(Base):
    __tablename__ = "household_settlements"
    __table_args__ = (Index("ix_household_settlements_household_status", "household_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    household_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    from_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    note: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
