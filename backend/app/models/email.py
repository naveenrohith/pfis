"""
Email Model
Stores raw emails fetched from Gmail for traceability and re-processing.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RawEmail(Base):
    __tablename__ = "raw_emails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    gmail_message_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=True)
    sender: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    user = relationship("User", back_populates="raw_emails")
    transaction = relationship("Transaction", back_populates="source_email", uselist=False)
    parse_failure = relationship("ParseFailure", back_populates="email", uselist=False)

    def __repr__(self) -> str:
        return f"<RawEmail {self.subject}>"


class GmailAccount(Base):
    """Stores OAuth tokens for connected Gmail accounts."""

    __tablename__ = "gmail_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    google_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    access_token_ref: Mapped[str] = mapped_column(String(500), nullable=True)
    refresh_token_ref: Mapped[str] = mapped_column(String(500), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_history_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_sync_interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    auto_sync_status: Mapped[str] = mapped_column(String(20), default="idle")
    auto_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="gmail_accounts")

    def __repr__(self) -> str:
        return f"<GmailAccount {self.google_account_id}>"
