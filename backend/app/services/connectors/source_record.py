"""Source record contract for connector-driven ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.models.email import RawEmail


class SourceType(str, Enum):
    GMAIL = "gmail"
    DEMO = "demo"
    SMS = "sms"
    PDF = "pdf"
    BANK_API = "bank_api"


@dataclass(frozen=True)
class SourceRecord:
    """Connector-neutral source payload that can feed the parser pipeline."""

    user_id: str
    source_type: SourceType
    source_message_id: str | None
    sender: str
    subject: str
    body: str
    received_at: datetime | None = None

    @classmethod
    def from_raw_email(
        cls,
        email: RawEmail,
        source_type: SourceType = SourceType.GMAIL,
    ) -> SourceRecord:
        """Build a connector-neutral record from the current Gmail raw email model."""
        return cls(
            user_id=email.user_id,
            source_type=source_type,
            source_message_id=email.gmail_message_id,
            sender=email.sender or "",
            subject=email.subject or "",
            body=email.body or "",
            received_at=email.received_at,
        )

    def to_parser_inputs(self) -> tuple[str, str, str]:
        """Return sender, subject, and body values expected by the parser registry."""
        return self.sender, self.subject, self.body
