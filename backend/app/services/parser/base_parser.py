"""
Base Parser & Parser Result
Defines the contract for all bank-specific parsers and the structured output.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

# Confidence weights (0–100 scale). Centralized so scoring stays tunable.
CONFIDENCE_WEIGHT_AMOUNT = 40
CONFIDENCE_WEIGHT_MERCHANT = {"exact": 30, "inferred": 20, "generic": 10}
CONFIDENCE_WEIGHT_DATE = 20
CONFIDENCE_WEIGHT_TYPE = 10


class TransactionTypeEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    REFUND = "refund"


@dataclass
class ParseResult:
    """Structured output from a parser. Every field is optional — confidence depends on how many were extracted."""

    amount: float | None = None
    currency: str = "INR"
    transaction_type: TransactionTypeEnum | None = None
    merchant_raw: str | None = None
    date: date | None = None
    account_last4: str | None = None
    reference_id: str | None = None
    bank: str = ""
    parser_version: int = 1
    parser_name: str | None = None
    pattern_version: int = 1
    confidence_version: int = 1
    normalization_version: int = 1
    merchant_source: str = "missing"  # exact | inferred | generic | missing
    used_fallback: bool = False  # True when the generic fallback parser handled this email
    validation_errors: list[str] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)

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
        field_scores: dict[str, float] = {
            "amount": 0.0,
            "merchant": 0.0,
            "date": 0.0,
            "type": 0.0,
            "reference": 1.0 if self.reference_id else 0.0,
            "account": 1.0 if self.account_last4 else 0.0,
            "currency": 1.0 if self.currency else 0.0,
        }
        score = 0
        if self.amount is not None and self.amount > 0:
            score += CONFIDENCE_WEIGHT_AMOUNT
            field_scores["amount"] = 1.0
        if self.merchant_raw:
            merchant_score = CONFIDENCE_WEIGHT_MERCHANT.get(
                self.merchant_source, CONFIDENCE_WEIGHT_MERCHANT["exact"]
            )
            score += merchant_score
            field_scores["merchant"] = merchant_score / CONFIDENCE_WEIGHT_MERCHANT["exact"]
        if self.date is not None:
            score += CONFIDENCE_WEIGHT_DATE
            field_scores["date"] = 1.0
        if self.transaction_type is not None:
            score += CONFIDENCE_WEIGHT_TYPE
            field_scores["type"] = 1.0

        self.confidence_score = score / 100.0
        self.field_confidence = field_scores
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
        from app.utils.text import clean_html_to_text

        return clean_html_to_text(text)

    @staticmethod
    def _match_amount(amount_patterns: Iterable[re.Pattern[str]], text: str) -> float | None:
        """Return the first amount matched by any of the given patterns."""
        for pattern in amount_patterns:
            match = pattern.search(text)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _match_merchant(merchant_patterns: Iterable[re.Pattern[str]], text: str) -> str | None:
        """Return the first merchant (>=3 chars) matched by any of the given patterns."""
        for pattern in merchant_patterns:
            match = pattern.search(text)
            if match:
                merchant = match.group(1).strip(" .-")
                if merchant and len(merchant) >= 3:
                    return merchant
        return None
