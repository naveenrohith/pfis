"""Ephemeral Gmail statement intake contracts; passwords never enter responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

from app.schemas.financial_position import StatementDetectionResponse


class GmailStatementCandidate(BaseModel):
    source_ref: str
    sender: str
    subject: str
    filename: str
    size_bytes: int
    received_at: datetime | None = None


class GmailStatementCandidates(BaseModel):
    candidates: list[GmailStatementCandidate]
    next_cursor: str | None = None
    coverage_complete: bool
    message_failures: int = 0
    truncated: bool = False


class GmailStatementRequest(BaseModel):
    source_ref: str = Field(min_length=1, max_length=4096)
    password: SecretStr | None = None


class GmailStatementImportRequest(GmailStatementRequest):
    financial_account_id: str = Field(min_length=1, max_length=36)
    document_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class GmailStatementDetection(BaseModel):
    status: Literal["detected", "password_required", "incorrect_password"]
    detection: StatementDetectionResponse | None = None
    document_fingerprint: str | None = None
