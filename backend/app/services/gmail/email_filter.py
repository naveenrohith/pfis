"""Compatibility facade for the connector-neutral classification engine."""

from app.services.classification.engine import (
    KNOWN_BANK_SENDERS,
    ClassificationType as EmailType,
    classify_source_record,
    is_known_sender,
)


def classify_email(sender: str, subject: str, body: str) -> tuple[EmailType, str, float]:
    """Return the legacy tuple shape used by existing parser and Gmail code."""
    result = classify_source_record(sender, subject, body)
    return result.classification, result.institution, result.confidence
