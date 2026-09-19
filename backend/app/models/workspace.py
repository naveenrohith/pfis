"""User-owned dashboard preferences and recommendation state."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
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
    recommendation_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expected_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    smallest_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    consequence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    conflicts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_links_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    freshness_as_of: Mapped[date | None] = mapped_column(nullable=True)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False, default="monitor")
    reversibility: Mapped[str] = mapped_column(String(24), nullable=False, default="reversible")
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance_ruleset_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_as_of: Mapped[date | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    baseline_metric_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    baseline_metric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    baseline_metric_unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class RecommendationOutcome(Base):
    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        UniqueConstraint("decision_id", name="uq_recommendation_outcome_decision"),
        Index("ix_recommendation_outcomes_user_observed", "user_id", "observed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    decision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recommendation_states.id", ondelete="CASCADE"), nullable=False
    )
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    actual_impact_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    actual_impact_unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    baseline_metric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    observed_metric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    automatic_impact_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    metric_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metric_unit: Mapped[str | None] = mapped_column(String(24), nullable=True)
    outcome_ruleset_version: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
