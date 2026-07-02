"""Reusable parser field extractors.

These wrap the existing proven pattern functions so Phase 9 can introduce
stage boundaries without changing extraction behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.parser import patterns
from app.services.parser.base_parser import TransactionTypeEnum


@dataclass(frozen=True)
class ExtractedFields:
    amount: float | None
    currency: str
    transaction_type: TransactionTypeEnum | None
    merchant_raw: str | None
    date: date | None
    account_last4: str | None
    reference_id: str | None


def extract_amount(text: str) -> float | None:
    return patterns.extract_amount(text)


def extract_currency(text: str) -> str:
    upper_text = text.upper()
    if "USD" in upper_text or "$" in upper_text:
        return "USD"
    if "EUR" in upper_text:
        return "EUR"
    return "INR"


def extract_transaction_type(text: str) -> TransactionTypeEnum | None:
    raw_type = patterns.detect_transaction_type(text)
    return TransactionTypeEnum(raw_type) if raw_type else None


def extract_merchant(text: str, transaction_type: TransactionTypeEnum | None) -> tuple[str | None, str]:
    merchant = patterns.extract_merchant(text)
    if merchant:
        return merchant, "exact"
    inferred = patterns.infer_generic_merchant(text, transaction_type.value if transaction_type else None)
    if inferred:
        return inferred, "generic"
    return None, "missing"


def extract_date(text: str) -> date | None:
    return patterns.extract_date(text)


def extract_account_last4(text: str) -> str | None:
    return patterns.extract_account(text)


def extract_reference_id(text: str) -> str | None:
    return patterns.extract_reference_id(text)


def extract_all(text: str) -> ExtractedFields:
    transaction_type = extract_transaction_type(text)
    merchant, _ = extract_merchant(text, transaction_type)
    return ExtractedFields(
        amount=extract_amount(text),
        currency=extract_currency(text),
        transaction_type=transaction_type,
        merchant_raw=merchant,
        date=extract_date(text),
        account_last4=extract_account_last4(text),
        reference_id=extract_reference_id(text),
    )
