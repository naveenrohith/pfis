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
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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
    __table_args__ = (Index("ix_sync_runs_user_started", "user_id", "start_time"),)

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
    status: Mapped[SyncStatus] = mapped_column(
        Enum(
            SyncStatus,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=SyncStatus.RUNNING,
    )

    # Relationships
    user = relationship("User", back_populates="sync_runs")

    def __repr__(self) -> str:
        return f"<SyncRun {self.status.value} fetched={self.emails_fetched}>"


class Budget(Base):
    """Monthly spending limits per category."""

    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("monthly_limit > 0", name="ck_budgets_monthly_limit_positive"),
        UniqueConstraint("user_id", "category_id", name="uq_budgets_user_category"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    category_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("categories.id"), nullable=False
    )
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

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
    failure_stage: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    parser_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[int] = mapped_column(Integer, default=1)
    pattern_version: Mapped[int] = mapped_column(Integer, default=1)
    confidence_version: Mapped[int] = mapped_column(Integer, default=1)
    normalization_version: Mapped[int] = mapped_column(Integer, default=1)
    diagnostic_json: Mapped[str] = mapped_column(Text, default="{}")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    email = relationship("RawEmail", back_populates="parse_failure")

    def __repr__(self) -> str:
        return f"<ParseFailure retries={self.retry_count} resolved={self.resolved}>"


class PipelineEvent(Base):
    """Non-secret event log for parser and transaction pipeline observability."""

    __tablename__ = "pipeline_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    email_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("raw_emails.id"), nullable=True, index=True
    )
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    parser_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    user = relationship("User", back_populates="pipeline_events")

    def __repr__(self) -> str:
        return f"<PipelineEvent {self.event_type}:{self.status}>"


class BackgroundJob(Base):
    """Persistent background orchestration record for async job execution."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_background_jobs_attempt_nonnegative"),
        CheckConstraint("max_attempts > 0", name="ck_background_jobs_max_attempts_positive"),
        UniqueConstraint("idempotency_key", name="uq_background_jobs_idempotency_key"),
        Index("ix_background_jobs_due", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        default=JobStatus.QUEUED,
    )
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="jobs")

    def __repr__(self) -> str:
        return f"<BackgroundJob {self.job_type} status={self.status.value}>"


class Goal(Base):
    """User-defined financial goal tracked against monthly aggregates."""

    __tablename__ = "goals"
    __table_args__ = (CheckConstraint("target_amount > 0", name="ck_goals_target_amount_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    goal_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    target_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    target_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    user = relationship("User", back_populates="goals")

    def __repr__(self) -> str:
        return f"<Goal {self.goal_type}:{self.label}>"


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
    browser_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_verifier_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    nonce_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<OAuthState {self.flow_type} expires={self.expires_at}>"


class ConnectorAuditEvent(Base):
    """Non-secret audit events for connector lifecycle and sync operations."""

    __tablename__ = "connector_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True, index=True
    )
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    connector_account_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    def __repr__(self) -> str:
        return f"<ConnectorAuditEvent {self.connector_type}:{self.event_type}>"
