"""Deterministic matching shared by statement and email ingestion."""

import re
from collections.abc import Iterable
from decimal import Decimal

from app.services.parser.normalizer import extract_descriptor_identity

FUEL_EVIDENCE_TERMS = (
    "fuel",
    "petrol",
    "diesel",
    "filling",
    "petroleum",
    "petro",
)


def merchant_key(value: str) -> str:
    identity = extract_descriptor_identity(value)
    return re.sub(r"[^a-z0-9]", "", identity.candidate.lower())[:80]


def merchants_match(statement_description: str, ledger_merchant: str) -> bool:
    """Match controlled issuer suffix variation without fuzzy guessing."""
    statement_key = merchant_key(statement_description)
    ledger_key = merchant_key(ledger_merchant)
    if not statement_key or not ledger_key:
        return False
    if statement_key == ledger_key:
        return True
    shorter, longer = sorted((statement_key, ledger_key), key=len)
    return len(shorter) >= 5 and shorter in longer


def merchant_evidence_matches(statement_description: str, values: Iterable[str | None]) -> bool:
    """Match a statement merchant against any retained or reparsed identity evidence."""
    return any(value and merchants_match(statement_description, value) for value in values)


def is_fuel_evidence(*values: str | None) -> bool:
    """Return true only when explicit fuel-domain language is present."""
    combined = " ".join(value or "" for value in values).casefold()
    return any(term in combined for term in FUEL_EVIDENCE_TERMS)


def is_fuel_surcharge_amount_match(
    statement_amount: Decimal,
    alert_amount: Decimal,
) -> bool:
    """Recognize a posted fuel charge that includes a bounded issuer surcharge.

    The statement must be greater than the alert amount. The controlled ceiling
    allows common Indian fuel surcharge/tax postings while excluding general
    approximate-amount matching.
    """
    if alert_amount <= 0 or statement_amount <= alert_amount:
        return False
    difference = statement_amount - alert_amount
    return difference <= Decimal("50.00") and (difference / alert_amount) <= Decimal("0.0300")
