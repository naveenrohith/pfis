"""Persisted monthly aggregate cache for dashboard and report reads."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MonthlySummary(Base):
    """A user/month snapshot of computed transaction aggregates."""

    __tablename__ = "monthly_summaries"
    __table_args__ = (
        UniqueConstraint("user_id", "month", "year", name="uq_monthly_summaries_user_period"),
        Index("ix_monthly_summaries_user_period", "user_id", "year", "month"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
