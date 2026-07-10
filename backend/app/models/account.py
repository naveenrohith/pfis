"""Financial account domain model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FinancialAccount(Base):
    """A user-owned financial account inferred from connector metadata."""

    __tablename__ = "financial_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "masked_number", name="uq_financial_accounts_user_masked"),
        Index("ix_financial_accounts_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    institution_name: Mapped[str] = mapped_column(String(160), nullable=False, default="Unknown")
    account_type: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    masked_number: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    connector_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    user = relationship("User", back_populates="financial_accounts")
    transactions = relationship("Transaction", back_populates="financial_account")

    def __repr__(self) -> str:
        return f"<FinancialAccount {self.institution_name} {self.masked_number}>"
