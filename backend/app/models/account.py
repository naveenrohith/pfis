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
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FinancialAccount(Base):
    """A user-owned financial account inferred from connector metadata."""

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    user = relationship("User", back_populates="financial_accounts")
    transactions = relationship("Transaction", back_populates="financial_account")
    balance_snapshots = relationship(
        "AccountBalanceSnapshot",
        back_populates="financial_account",
        cascade="all, delete-orphan",
        order_by="AccountBalanceSnapshot.as_of",
    )

    def __repr__(self) -> str:
        return f"<FinancialAccount {self.institution_name} {self.masked_number}>"


class AccountBalanceSnapshot(Base):
    """Append-only balance observation for a user-owned financial account."""

    __tablename__ = "account_balance_snapshots"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_account_balance_amount_nonnegative"),
        UniqueConstraint(
            "financial_account_id", "as_of", name="uq_account_balance_snapshots_account_as_of"
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    financial_account = relationship("FinancialAccount", back_populates="balance_snapshots")

    def __repr__(self) -> str:
        return f"<AccountBalanceSnapshot {self.financial_account_id} {self.as_of}>"
