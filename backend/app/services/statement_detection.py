"""Fail-closed financial statement recognition before any persistence begins."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.services.generic_credit_card_statement_extractor import (
    is_reviewed_generic_credit_card_layout,
)
from app.services.generic_deposit_statement_extractor import is_reviewed_generic_deposit_layout
from app.services.hdfc_deposit_statement_extractor import is_reviewed_deposit_layout
from app.services.hdfc_statement_extractor import is_reviewed_layout

StatementProduct = Literal["credit_card", "deposit_account", "unknown"]
StatementSupport = Literal[
    "supported",
    "recognized_not_supported",
    "ambiguous",
    "unsupported",
]

DETECTOR_VERSION = "pfis-statement-detector-4"


@dataclass(frozen=True)
class StatementDetection:
    institution: str | None
    product_type: StatementProduct
    format_id: str | None
    support_status: StatementSupport
    confidence: float
    reason_codes: tuple[str, ...]
    activity_types: tuple[str, ...] = ()
    detector_version: str = DETECTOR_VERSION


def _has(text: str, *phrases: str) -> bool:
    return any(phrase in text for phrase in phrases)


def _activity_types(text: str) -> tuple[str, ...]:
    detected: list[str] = []
    for activity_type, patterns in (
        ("upi", (r"\bUPI\b", r"\bUPI[-/]")),
        ("debit_card", (r"\bDEBIT CARD\b", r"\bPOS\b", r"\bE-COM\b")),
        ("atm", (r"\bATM\b", r"\bCASH WDL\b")),
        ("bank_transfer", (r"\bNEFT\b", r"\bIMPS\b", r"\bRTGS\b")),
        (
            "cheque",
            (
                r"\bCHQ[-/]\w+",
                r"\bCHEQUE\s+(?:PAID|DEPOSIT|RETURN|CLEARING)\b",
            ),
        ),
    ):
        if any(re.search(pattern, text) for pattern in patterns):
            detected.append(activity_type)
    return tuple(detected)


def detect_statement(statement_text: str) -> StatementDetection:
    """Recognize reviewed statement families without inferring an import contract."""

    normalized = re.sub(r"\s+", " ", statement_text.upper()).strip()
    if len(normalized) < 40:
        return StatementDetection(
            institution=None,
            product_type="unknown",
            format_id=None,
            support_status="unsupported",
            confidence=0.0,
            reason_codes=("insufficient_text",),
        )

    institution = "hdfc" if _has(normalized, "HDFC BANK", "HDFC BANK LTD") else None

    card_markers = {
        "credit_card_label": _has(normalized, "CREDIT CARD STATEMENT", "CARD STATEMENT"),
        "total_amount_due": "TOTAL AMOUNT DUE" in normalized,
        "minimum_due": _has(normalized, "MINIMUM AMOUNT DUE", "MINIMUM DUE"),
        "credit_limit": _has(normalized, "TOTAL CREDIT LIMIT", "CREDIT LIMIT"),
        "payment_due_date": _has(normalized, "PAYMENT DUE DATE", "DUE DATE"),
        "card_identity": _has(normalized, "CREDIT CARD NO", "CARD ENDING", "CARD NUMBER"),
    }
    deposit_markers = {
        "account_statement": _has(
            normalized,
            "ACCOUNT STATEMENT",
            "STATEMENT OF ACCOUNT",
            "SAVINGS ACCOUNT STATEMENT",
            "CURRENT ACCOUNT STATEMENT",
        ),
        "account_identity": _has(normalized, "ACCOUNT NO", "ACCOUNT NUMBER"),
        "narration": "NARRATION" in normalized,
        "withdrawal": _has(normalized, "WITHDRAWAL AMT", "WITHDRAWAL AMOUNT", "DEBIT AMT"),
        "deposit": _has(normalized, "DEPOSIT AMT", "DEPOSIT AMOUNT", "CREDIT AMT"),
        "closing_balance": "CLOSING BALANCE" in normalized,
        "value_date": _has(normalized, "VALUE DT", "VALUE DATE"),
    }

    card_score = sum(card_markers.values())
    deposit_score = sum(deposit_markers.values())
    card_recognized = (
        card_markers["total_amount_due"]
        and (card_markers["credit_card_label"] or card_markers["credit_limit"])
        and card_score >= 3
    )
    deposit_recognized = (
        deposit_markers["account_statement"]
        and deposit_markers["account_identity"]
        and deposit_markers["narration"]
        and deposit_markers["closing_balance"]
        and (deposit_markers["withdrawal"] or deposit_markers["deposit"])
        and deposit_score >= 5
    )

    if institution is not None and card_recognized and deposit_recognized:
        return StatementDetection(
            institution="hdfc",
            product_type="unknown",
            format_id=None,
            support_status="ambiguous",
            confidence=0.0,
            reason_codes=("multiple_product_signatures",),
            activity_types=_activity_types(normalized),
        )
    if institution is not None and card_recognized:
        confidence = min(0.99, 0.63 + 0.06 * card_score)
        write_enabled = is_reviewed_layout(statement_text)
        return StatementDetection(
            institution="hdfc",
            product_type="credit_card",
            format_id=(
                "hdfc-credit-card-digital" if write_enabled else "hdfc-credit-card-candidate"
            ),
            support_status="supported" if write_enabled else "recognized_not_supported",
            confidence=round(confidence, 2),
            reason_codes=tuple(key for key, present in card_markers.items() if present)
            + (("reviewed_import_profile",) if write_enabled else ()),
            activity_types=("credit_card",),
        )
    if institution is not None and deposit_recognized:
        confidence = min(0.97, 0.58 + 0.055 * deposit_score)
        write_enabled = is_reviewed_deposit_layout(statement_text)
        return StatementDetection(
            institution="hdfc",
            product_type="deposit_account",
            format_id=("hdfc-deposit-pipe-v1" if write_enabled else "hdfc-deposit-account-tabular"),
            support_status="supported" if write_enabled else "recognized_not_supported",
            confidence=round(confidence, 2),
            reason_codes=tuple(key for key, present in deposit_markers.items() if present)
            + (("reviewed_import_profile",) if write_enabled else ()),
            activity_types=_activity_types(normalized),
        )

    # Keep an HDFC-branded but unfamiliar document explicitly in the HDFC
    # review queue.  Generic signatures below are only for unknown issuers.
    if institution is not None:
        return StatementDetection(
            institution="hdfc",
            product_type="unknown",
            format_id=None,
            support_status="unsupported",
            confidence=0.2,
            reason_codes=("hdfc_layout_not_recognized",),
            activity_types=_activity_types(normalized),
        )

    # A product-shaped document from another issuer is useful evidence for
    # account matching, but it is not permission to import.  The HDFC branch
    # above remains deliberately strict and owns every write-enabled profile.
    generic_card_markers = {
        "credit_card_label": _has(
            normalized,
            "CREDIT CARD STATEMENT",
            "CREDIT CARD NO",
            "CREDIT CARD NUMBER",
            "CARD STATEMENT",
            "CARDHOLDER STATEMENT",
        ),
        "total_amount_due": "TOTAL AMOUNT DUE" in normalized,
        "minimum_due": _has(normalized, "MINIMUM AMOUNT DUE", "MINIMUM DUE", "MINIMUM PAYMENT"),
        "payment_due_date": _has(normalized, "PAYMENT DUE DATE", "PAYMENT DUE", "DUE DATE"),
        "credit_limit": _has(normalized, "TOTAL CREDIT LIMIT", "CREDIT LIMIT"),
        "billing_period": _has(normalized, "BILLING PERIOD", "STATEMENT PERIOD"),
        "transaction_table": _has(
            normalized,
            "TRANSACTION DESCRIPTION",
            "TRANSACTION DETAILS",
            "TRANSACTION DATE",
        ),
    }
    generic_deposit_markers = {
        "account_statement": _has(
            normalized,
            "ACCOUNT STATEMENT",
            "STATEMENT OF ACCOUNT",
            "BANK STATEMENT",
            "SAVINGS ACCOUNT STATEMENT",
            "CURRENT ACCOUNT STATEMENT",
        ),
        "account_identity": _has(normalized, "ACCOUNT NO", "ACCOUNT NUMBER"),
        "transaction_description": _has(
            normalized,
            "NARRATION",
            "DESCRIPTION",
            "TRANSACTION DETAILS",
            "PARTICULARS",
        ),
        "debit_column": _has(
            normalized,
            "WITHDRAWAL AMT",
            "WITHDRAWAL AMOUNT",
            "DEBIT AMT",
            "DEBIT AMOUNT",
            "DEBIT",
        ),
        "credit_column": _has(
            normalized,
            "DEPOSIT AMT",
            "DEPOSIT AMOUNT",
            "CREDIT AMT",
            "CREDIT AMOUNT",
            "CREDIT",
        ),
        "balance_column": _has(normalized, "CLOSING BALANCE", "BALANCE", "AVAILABLE BALANCE"),
        "date_column": _has(normalized, "TRANSACTION DATE", "VALUE DATE", "VALUE DT", "DATE"),
    }
    generic_card_score = sum(generic_card_markers.values())
    generic_deposit_score = sum(generic_deposit_markers.values())
    generic_card_recognized = (
        generic_card_markers["credit_card_label"]
        and generic_card_markers["total_amount_due"]
        and (
            generic_card_markers["minimum_due"]
            or generic_card_markers["payment_due_date"]
            or generic_card_markers["credit_limit"]
        )
        and (
            generic_card_markers["billing_period"]
            or generic_card_markers["transaction_table"]
        )
    )
    generic_deposit_recognized = (
        generic_deposit_markers["account_statement"]
        and generic_deposit_markers["account_identity"]
        and generic_deposit_markers["transaction_description"]
        and generic_deposit_markers["balance_column"]
        and (
            generic_deposit_markers["debit_column"]
            or generic_deposit_markers["credit_column"]
        )
        and generic_deposit_score >= 5
    )

    if generic_card_recognized and generic_deposit_recognized:
        return StatementDetection(
            institution=None,
            product_type="unknown",
            format_id=None,
            support_status="ambiguous",
            confidence=0.0,
            reason_codes=("multiple_generic_product_signatures",),
            activity_types=_activity_types(normalized),
        )
    if generic_card_recognized:
        generic_card_write_enabled = is_reviewed_generic_credit_card_layout(statement_text)
        return StatementDetection(
            institution=None,
            product_type="credit_card",
            format_id=(
                "generic-credit-card-tabular-v1"
                if generic_card_write_enabled
                else "generic-credit-card-candidate"
            ),
            support_status=(
                "supported" if generic_card_write_enabled else "recognized_not_supported"
            ),
            confidence=round(
                min(0.88 if generic_card_write_enabled else 0.78, 0.48 + 0.04 * generic_card_score),
                2,
            ),
            reason_codes=("generic_credit_card_signature",)
            + tuple(key for key, present in generic_card_markers.items() if present)
            + (("reviewed_generic_card_balance_reconciled",) if generic_card_write_enabled else ()),
            activity_types=("credit_card",),
        )
    if generic_deposit_recognized:
        generic_write_enabled = is_reviewed_generic_deposit_layout(statement_text)
        return StatementDetection(
            institution=None,
            product_type="deposit_account",
            format_id=(
                "generic-deposit-tabular-v1"
                if generic_write_enabled
                else "generic-deposit-account-candidate"
            ),
            support_status="supported" if generic_write_enabled else "recognized_not_supported",
            confidence=round(
                min(0.88 if generic_write_enabled else 0.78, 0.48 + 0.04 * generic_deposit_score),
                2,
            ),
            reason_codes=("generic_deposit_account_signature",)
            + tuple(key for key, present in generic_deposit_markers.items() if present)
            + (("reviewed_generic_balance_reconciled",) if generic_write_enabled else ()),
            activity_types=_activity_types(normalized),
        )
    return StatementDetection(
        institution=None,
        product_type="unknown",
        format_id=None,
        support_status="unsupported",
        confidence=0.2,
        reason_codes=("institution_not_recognized",),
        activity_types=_activity_types(normalized),
    )
