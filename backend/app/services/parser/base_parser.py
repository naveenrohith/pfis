"""
Base Parser & Parser Result
Defines the contract for all bank-specific parsers and the structured output.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from enum import Enum


class TransactionTypeEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    REFUND = "refund"


@dataclass
class ParseResult:
    """Structured output from a parser. Every field is optional — confidence depends on how many were extracted."""

    amount: Optional[float] = None
    currency: str = "INR"
    transaction_type: Optional[TransactionTypeEnum] = None
    merchant_raw: Optional[str] = None
    date: Optional[date] = None
    account_last4: Optional[str] = None
    reference_id: Optional[str] = None
    bank: str = ""
    parser_version: int = 1
    merchant_source: str = "missing"  # exact | inferred | generic | missing

    # Computed
    confidence_score: float = 0.0

    def compute_confidence(self) -> float:
        """
        Confidence scoring as defined in the plan:
        - amount found    → +40
        - merchant found  → +30
        - date found      → +20
        - type found      → +10
        """
        score = 0
        if self.amount is not None and self.amount > 0:
            score += 40
        if self.merchant_raw:
            merchant_score = {
                "exact": 30,
                "inferred": 20,
                "generic": 10,
            }.get(self.merchant_source, 30)
            score += merchant_score
        if self.date is not None:
            score += 20
        if self.transaction_type is not None:
            score += 10

        self.confidence_score = score / 100.0
        return self.confidence_score

    @property
    def is_valid(self) -> bool:
        """A result is minimally valid if we extracted at least amount and type."""
        return self.amount is not None and self.amount > 0 and self.transaction_type is not None


class BaseParser:
    """
    Base class for all bank-specific parsers.
    Subclasses implement parse() with their own regex patterns.
    """

    BANK_NAME: str = "UNKNOWN"
    VERSION: int = 1

    def parse(self, subject: str, body: str) -> ParseResult:
        """
        Parse an email and return structured transaction data.
        Must be overridden by subclasses.
        """
        raise NotImplementedError

    def _clean_text(self, text: str) -> str:
        """Convert email HTML/plain text into parser-friendly text."""
        import html
        import re

        text = html.unescape(text or "")
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<!--.*?-->", " ", text)
        text = re.sub(r"(?i)<br\s*/?>", " ", text)
        text = re.sub(r"(?i)</(?:p|div|tr|td|table|li|h\d)>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
