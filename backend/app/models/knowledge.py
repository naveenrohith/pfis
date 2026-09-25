"""Persisted user decisions over recomputable financial knowledge."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TemporalEventDecision(Base):
    """A user-owned decision attached to one stable derived event identity."""

    __tablename__ = "temporal_event_decisions"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_temporal_decision_user_event"),
        Index("ix_temporal_decisions_user_date", "user_id", "occurrence_date"),
        Index("ix_temporal_decisions_user_state", "user_id", "decision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    observed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    observed_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class SubscriptionReviewAction(Base):
    """Latest user-owned review action for one recurring merchant stream."""

    __tablename__ = "subscription_review_actions"
    __table_args__ = (
        UniqueConstraint("user_id", "stream_key", name="uq_subscription_review_user_stream"),
        Index("ix_subscription_review_actions_user_action", "user_id", "action"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stream_key: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant: Mapped[str] = mapped_column(String(255), nullable=False)
    financial_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
