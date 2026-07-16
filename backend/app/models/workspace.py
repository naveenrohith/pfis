"""User-owned dashboard preferences and recommendation state."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DashboardPreference(Base):
    __tablename__ = "dashboard_preferences"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    layout_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    widgets_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    theme: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    density: Mapped[str] = mapped_column(String(16), nullable=False, default="comfortable")
    briefing_cadence: Mapped[str] = mapped_column(
        String(16), nullable=False, default="daily", server_default="daily"
    )
    favorites_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    onboarding_goal: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class RecommendationState(Base):
    __tablename__ = "recommendation_states"
    __table_args__ = (
        UniqueConstraint("user_id", "recommendation_id", name="uq_recommendation_state_user_rec"),
        Index("ix_recommendation_states_user_state", "user_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    recommendation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
