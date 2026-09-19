"""Append-only snapshots for reconstructing user-owned planning evidence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TemporalSourceSnapshot(Base):
    """One immutable state observation of a mutable temporal source."""

    __tablename__ = "temporal_source_snapshots"
    __table_args__ = (
        Index(
            "ix_temporal_source_snapshots_user_source_time",
            "user_id",
            "source_type",
            "source_id",
            "captured_at",
        ),
        Index("ix_temporal_source_snapshots_user_time", "user_id", "captured_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="pfis-temporal-source-history-1"
    )
