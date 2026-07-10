"""Compatibility facade for the connector-neutral classification engine."""

from app.services.classification.engine import (
    ClassificationType as EmailType,
)
from app.services.classification.engine import (
    classify_source_record,
    is_known_sender,
)

__all__ = ["EmailType", "classify_email", "is_known_sender"]


def classify_email(sender: str, subject: str, body: str) -> tuple[EmailType, str, float]:
    """Return the legacy tuple shape used by existing parser and Gmail code."""
    result = classify_source_record(sender, subject, body)
    return result.classification, result.institution, result.confidence
