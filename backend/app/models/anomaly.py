"""User-owned anomaly adjudication evidence."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnomalyAdjudication(Base):
    """Append-only reviewer decision for one server-derived anomaly signal."""

    __tablename__ = "anomaly_adjudications"
    __table_args__ = (
        Index("ix_anomaly_adjudications_user_created", "user_id", "created_at"),
        Index("ix_anomaly_adjudications_user_anomaly", "user_id", "anomaly_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    anomaly_id: Mapped[str] = mapped_column(String(180), nullable=False)
    predicted_alert: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    baseline_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    delta_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
