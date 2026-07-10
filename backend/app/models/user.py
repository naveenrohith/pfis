"""
User Model
Stores registered users of the PFIS system.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships (lazy="select" — explicit eager loading where needed)
    transactions = relationship("Transaction", back_populates="user", lazy="select")
    raw_emails = relationship("RawEmail", back_populates="user", lazy="select")
    gmail_accounts = relationship("GmailAccount", back_populates="user", lazy="select")
    budgets = relationship("Budget", back_populates="user", lazy="select")
    sync_runs = relationship("SyncRun", back_populates="user", lazy="select")
    jobs = relationship("BackgroundJob", back_populates="user", lazy="select")
    goals = relationship("Goal", back_populates="user", lazy="select")
    pipeline_events = relationship("PipelineEvent", back_populates="user", lazy="select")
    financial_accounts = relationship("FinancialAccount", back_populates="user", lazy="select")

    def __repr__(self) -> str:
        return f"<User {self.email}>"
