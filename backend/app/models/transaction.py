"""
Transaction Model
Core entity — stores parsed financial transactions.
Includes confidence scoring, parser versioning, and dedup fingerprint.
"""

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TransactionType(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    REFUND = "refund"


class PaymentMethod(str, enum.Enum):
    UPI = "upi"
    DEBIT_CARD = "debit_card"
    CREDIT_CARD = "credit_card"
    EMI = "emi"
    PAY_LATER = "pay_later"
    WALLET = "wallet"
    BANK_TRANSFER = "bank_transfer"
    OTHER = "other"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_txn_user_date", "user_id", "transaction_date"),
        Index("ix_txn_user_month_category", "user_id", "transaction_type", "category_id"),
        Index("ix_txn_user_review", "user_id", "reviewed_flag"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(
            PaymentMethod,
            values_callable=lambda enum_type: [member.value for member in enum_type],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=PaymentMethod.OTHER,
    )
    transaction_status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")
    transaction_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merchant_raw: Mapped[str] = mapped_column(String(255), nullable=True)
    merchant_normalized: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    category_id: Mapped[str] = mapped_column(String(36), ForeignKey("categories.id"), nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_last4: Mapped[str] = mapped_column(String(4), nullable=True)
    reference_id: Mapped[str] = mapped_column(String(100), nullable=True)

    # Quality & traceability
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    reviewed_flag: Mapped[bool] = mapped_column(default=False, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parser_version: Mapped[int] = mapped_column(Integer, default=1)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=True, index=True)
    source_email_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_emails.id"), nullable=True
    )
    financial_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("financial_accounts.id"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    user = relationship("User", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    source_email = relationship("RawEmail", back_populates="transaction")
    financial_account = relationship("FinancialAccount", back_populates="transactions")
    corrections = relationship("UserCorrection", back_populates="transaction", lazy="selectin")

    @property
    def source_received_at(self) -> datetime | None:
        """Timestamp of the source notification, when PFIS ingested from email."""
        source_email = self.__dict__.get("source_email")
        return source_email.received_at if source_email else None

    def __repr__(self) -> str:
        return f"<Transaction {self.merchant_normalized} ₹{self.amount}>"
