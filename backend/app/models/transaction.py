"""
Transaction Model
Core entity — stores parsed financial transactions.
Includes confidence scoring, parser versioning, and dedup fingerprint.
"""

import uuid
import enum
from datetime import datetime, date, timezone
from sqlalchemy import String, Float, Date, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TransactionType(str, enum.Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    REFUND = "refund"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False
    )
    merchant_raw: Mapped[str] = mapped_column(String(255), nullable=True)
    merchant_normalized: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=True
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_last4: Mapped[str] = mapped_column(String(4), nullable=True)
    reference_id: Mapped[str] = mapped_column(String(100), nullable=True)

    # Quality & traceability
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    parser_version: Mapped[int] = mapped_column(Integer, default=1)
    fingerprint: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    source_email_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_emails.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    source_email = relationship("RawEmail", back_populates="transaction")
    corrections = relationship("UserCorrection", back_populates="transaction", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Transaction {self.merchant_normalized} ₹{self.amount}>"
