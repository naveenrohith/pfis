"""Validation layer for parser outputs before persistence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.services.parser.base_parser import ParseResult

SUPPORTED_CURRENCIES = {"INR", "USD", "EUR"}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


def validate_parse_result(parse_result: ParseResult) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if parse_result.amount is None:
        issues.append(ValidationIssue("missing_amount", "Transaction amount is required"))
    elif parse_result.amount <= 0:
        issues.append(ValidationIssue("invalid_amount", "Transaction amount must be positive"))

    if parse_result.transaction_type is None:
        issues.append(ValidationIssue("missing_type", "Transaction type is required"))

    if parse_result.date is None:
        issues.append(ValidationIssue("missing_date", "Transaction date is required"))
    else:
        today = datetime.now(UTC).date()
        if parse_result.date.year < 2000 or parse_result.date > today.replace(year=today.year + 1):
            issues.append(ValidationIssue("impossible_date", "Transaction date is outside supported range"))

    if parse_result.currency and parse_result.currency.upper() not in SUPPORTED_CURRENCIES:
        issues.append(ValidationIssue("unsupported_currency", "Currency is not supported"))

    if parse_result.account_last4 and not re.fullmatch(r"\d{4}", parse_result.account_last4):
        issues.append(ValidationIssue("malformed_account", "Account suffix must contain four digits"))

    if parse_result.reference_id and not re.fullmatch(r"[A-Za-z0-9._/-]{4,100}", parse_result.reference_id):
        issues.append(ValidationIssue("malformed_reference", "Reference id contains unsupported characters"))

    parse_result.validation_errors = [issue.code for issue in issues]
    return issues


def validation_summary(issues: list[ValidationIssue]) -> str:
    return "; ".join(issue.message for issue in issues) if issues else ""
