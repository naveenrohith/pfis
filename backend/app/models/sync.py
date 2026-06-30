"""
Sync, Budget, Feedback, and DLQ Models
Operational models added from architect review:
- SyncRun: tracks each Gmail sync operation
- Budget: monthly spending limits per category
- UserCorrection: feedback loop for improving parsing
- ParseFailure: Dead Letter Queue for failed parses
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SyncStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SyncRun(Base):
    """Tracks each Gmail sync operation for observability and debugging."""

    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    emails_fetched: Mapped[int] = mapped_column(Integer, default=0)
    emails_processed: Mapped[int] = mapped_column(Integer, default=0)
    emails_failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus), default=SyncStatus.RUNNING)

    # Relationships
    user = relationship("User", back_populates="sync_runs")

    def __repr__(self) -> str:
        return f"<SyncRun {self.status.value} fetched={self.emails_fetched}>"


class Budget(Base):
    """Monthly spending limits per category."""

    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=False
    )
    monthly_limit: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships
    user = relationship("User", back_populates="budgets")
    category = relationship("Category", back_populates="budgets")

    def __repr__(self) -> str:
        return f"<Budget ₹{self.monthly_limit}>"


class UserCorrection(Base):
    """Feedback loop — user corrections feed back into parsing rules."""

    __tablename__ = "user_corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=False, index=True
    )
    field_corrected: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=True)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    transaction = relationship("Transaction", back_populates="corrections")

    def __repr__(self) -> str:
        return f"<UserCorrection {self.field_corrected}: {self.old_value} → {self.new_value}>"


class ParseFailure(Base):
    """Dead Letter Queue — stores failed parse attempts for retry."""

    __tablename__ = "parse_failures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("raw_emails.id"), nullable=False, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_version: Mapped[int] = mapped_column(Integer, default=1)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    email = relationship("RawEmail", back_populates="parse_failure")

    def __repr__(self) -> str:
        return f"<ParseFailure retries={self.retry_count} resolved={self.resolved}>"


class BackgroundJob(Base):
    """Persistent background orchestration record for async job execution."""

    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.QUEUED)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="jobs")

    def __repr__(self) -> str:
        return f"<BackgroundJob {self.job_type} status={self.status.value}>"


class OAuthState(Base):
    """Persistent OAuth state storage (replaces in-memory sets/dicts)."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    flow_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "google_login" or "gmail_connect"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<OAuthState {self.flow_type} expires={self.expires_at}>"
