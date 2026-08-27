"""Deterministic extraction for the reviewed HDFC digital statement layout.

The production PDF route supplies ``pdfplumber`` layout text so columns remain
stable.  A compact legacy text form remains supported for de-identified API
fixtures, but unfamiliar production layouts are rejected by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from app.services.hdfc_deposit_statement_extractor import is_reviewed_deposit_layout

EXTRACTOR_VERSION = "hdfc-digital-v2"
DOCUMENT_DETECTOR_VERSION = "pfis-hdfc-document-detector-1"
REVIEWED_LAYOUT_MARKERS = (
    "DUPLICATE",
    "BILLING PERIOD",
    "DOMESTIC TRANSACTIONS",
    "DATE & TIME",
    "TRANSACTION DESCRIPTION",
)

_DATE_PATTERN = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{4}|" r"\d{1,2}\s+[A-Za-z]{3},?\s+\d{4})"
_MONEY_PATTERN = re.compile(r"(?:[₹C]\s*)?([\d,]+(?:\.\d{2})?)")
_LAYOUT_MONEY_PATTERN = re.compile(r"C\s*([\d,]+(?:\.\d{2})?)")

DocumentDetectionStatus = Literal["recognized", "ambiguous", "unknown"]
DocumentKind = Literal["credit_card_statement", "deposit_account_statement", "unknown"]
DocumentIssuer = Literal["hdfc", "unknown"]
DocumentReasonCode = Literal[
    "recognized_hdfc_credit_card",
    "recognized_hdfc_deposit_account",
    "ambiguous_hdfc_statement",
    "unrecognized_hdfc_layout",
    "unsupported_issuer",
]


@dataclass(frozen=True)
class HdfcStatementDocumentDetection:
    """A redacted, read-only document classification result."""

    status: DocumentDetectionStatus
    issuer: DocumentIssuer
    document_kind: DocumentKind
    format_id: str | None
    import_supported: bool
    import_endpoint: str | None
    reason_code: DocumentReasonCode
    matched_signal_codes: tuple[str, ...]
    detector_version: str = DOCUMENT_DETECTOR_VERSION


def is_reviewed_layout(text: str) -> bool:
    upper = text.upper()
    return all(marker in upper for marker in REVIEWED_LAYOUT_MARKERS)


def detect_hdfc_statement_document(text: str) -> HdfcStatementDocumentDetection:
    """Classify a complete HDFC card/deposit document without extracting values.

    This detector is intentionally stricter than the legacy text importer.  It
    is a preflight contract for digital documents, not permission to persist a
    statement.  Unknown HDFC layouts and non-HDFC documents fail closed.
    """

    normalized = _document_normalize(text)
    issuer_header = _document_normalize("\n".join(text.splitlines()[:3]))
    hdfc_issuer = _document_has(issuer_header, "HDFC BANK", "HDFC BANK LTD")
    if not hdfc_issuer:
        return HdfcStatementDocumentDetection(
            status="unknown",
            issuer="unknown",
            document_kind="unknown",
            format_id=None,
            import_supported=False,
            import_endpoint=None,
            reason_code="unsupported_issuer",
            matched_signal_codes=(),
        )

    card_signals = {
        "hdfc_issuer": hdfc_issuer,
        "credit_card_statement": "CREDIT CARD STATEMENT" in normalized,
        "credit_card_identity": _document_has(
            normalized, "CREDIT CARD NO", "CREDIT CARD NUMBER", "CARD NUMBER"
        ),
        "total_amount_due": "TOTAL AMOUNT DUE" in normalized,
        "billing_period": "BILLING PERIOD" in normalized,
        "duplicate": "DUPLICATE" in normalized,
        "domestic_transactions": "DOMESTIC TRANSACTIONS" in normalized,
        "date_time": "DATE TIME" in normalized,
        "transaction_description": "TRANSACTION DESCRIPTION" in normalized,
    }
    deposit_signals = {
        "hdfc_issuer": hdfc_issuer,
        "account_statement": _document_has(normalized, "ACCOUNT STATEMENT", "STATEMENT OF ACCOUNT"),
        "account_identity": _document_has(normalized, "ACCOUNT NO", "ACCOUNT NUMBER"),
        "narration": _document_has(normalized, "NARRATION", "TRANSACTION DESCRIPTION"),
        "reference": _document_has(normalized, "CHQ REF NO", "REFERENCE", "REF NO"),
        "withdrawal_column": _document_has(normalized, "WITHDRAWAL AMT", "WITHDRAWAL AMOUNT"),
        "deposit_column": _document_has(normalized, "DEPOSIT AMT", "DEPOSIT AMOUNT"),
        "closing_balance": "CLOSING BALANCE" in normalized,
    }
    card_complete = all(card_signals.values())
    deposit_complete = all(deposit_signals.values())
    card_codes = _document_signal_codes(card_signals)
    deposit_codes = _document_signal_codes(deposit_signals)

    if card_complete and deposit_complete:
        return HdfcStatementDocumentDetection(
            status="ambiguous",
            issuer="hdfc",
            document_kind="unknown",
            format_id=None,
            import_supported=False,
            import_endpoint=None,
            reason_code="ambiguous_hdfc_statement",
            matched_signal_codes=_unique_signal_codes((*card_codes, *deposit_codes)),
        )
    if card_complete:
        reviewed = is_reviewed_layout(text)
        return HdfcStatementDocumentDetection(
            status="recognized",
            issuer="hdfc",
            document_kind="credit_card_statement",
            format_id=("hdfc-credit-card-digital" if reviewed else "hdfc-credit-card-candidate"),
            import_supported=reviewed,
            import_endpoint="/api/statements/hdfc/upload" if reviewed else None,
            reason_code="recognized_hdfc_credit_card",
            matched_signal_codes=card_codes,
        )
    if deposit_complete:
        reviewed = is_reviewed_deposit_layout(text)
        return HdfcStatementDocumentDetection(
            status="recognized",
            issuer="hdfc",
            document_kind="deposit_account_statement",
            format_id=("hdfc-deposit-pipe-v1" if reviewed else "hdfc-deposit-account-tabular"),
            import_supported=reviewed,
            import_endpoint="/api/statements/import/upload" if reviewed else None,
            reason_code="recognized_hdfc_deposit_account",
            matched_signal_codes=deposit_codes,
        )

    return HdfcStatementDocumentDetection(
        status="unknown",
        issuer="hdfc",
        document_kind="unknown",
        format_id=None,
        import_supported=False,
        import_endpoint=None,
        reason_code="unrecognized_hdfc_layout",
        matched_signal_codes=_unique_signal_codes((*card_codes, *deposit_codes)),
    )


def _document_normalize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _document_has(text: str, *phrases: str) -> bool:
    return any(phrase in text for phrase in phrases)


def _document_signal_codes(signals: dict[str, bool]) -> tuple[str, ...]:
    return tuple(key for key, present in signals.items() if present)


def _unique_signal_codes(codes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(codes))


def extract_hdfc_statement(text: str) -> dict[str, Any]:
    """Extract a reviewed layout or the de-identified legacy fixture format."""
    statement_date = _labelled_date(text, r"STATEMENT\s+DATE")
    period = re.search(
        rf"(?:STATEMENT|BILLING)\s+PERIOD\s*:?\s*"
        rf"({_DATE_PATTERN})\s*(?:TO|-)\s*({_DATE_PATTERN})",
        text,
        re.IGNORECASE,
    )
    period_start = _parse_date(period.group(1)) if period else None
    period_end = _parse_date(period.group(2)) if period else None

    if is_reviewed_layout(text):
        summary = _reviewed_summary(text)
        limits = _reviewed_limits(text)
        lines = _reviewed_lines(text)
        due_date = limits.pop("due_date")
    else:
        summary = {
            "previous_due": _amount_after(text, r"PREVIOUS\s+(?:STATEMENT\s+)?DUES"),
            "payments_credits": _amount_after(text, r"PAYMENTS?/?CREDITS?(?:\s+RECEIVED)?"),
            "purchases_debits": _amount_after(
                text, r"PURCHASES?/?DEBITS?(?:\s*\(CURRENT\s+BILLING\s+CYCLE\))?"
            ),
            "finance_charges": _amount_after(text, r"FINANCE\s+CHARGES?"),
            "total_due": _amount_after(text, r"TOTAL\s+AMOUNT\s+DUE"),
        }
        limits = {
            "minimum_due": _amount_after(text, r"MINIMUM(?:\s+AMOUNT)?\s+DUE"),
            "credit_limit": _amount_after(text, r"TOTAL\s+CREDIT\s+LIMIT"),
            "available_credit_limit": _amount_after(text, r"AVAILABLE\s+CREDIT\s+LIMIT"),
            "available_cash_limit": _amount_after(text, r"AVAILABLE\s+CASH\s+LIMIT"),
        }
        due_date = _labelled_date(text, r"(?:PAYMENT\s+)?DUE\s+DATE")
        lines = _legacy_lines(text)

    return {
        "statement_date": statement_date,
        "period_start": period_start,
        "period_end": period_end,
        "due_date": due_date,
        **summary,
        **limits,
        "card_last4": _card_last4(text),
        "layout_name": (
            "hdfc-millennia-duplicate-v1" if is_reviewed_layout(text) else "fixture-legacy"
        ),
        "lines": lines,
    }


def _reviewed_summary(text: str) -> dict[str, Decimal | None]:
    """Read the five summary columns from the reviewed fixed-width layout."""
    values: dict[str, Decimal | None] = {
        "previous_due": None,
        "payments_credits": None,
        "purchases_debits": None,
        "finance_charges": None,
        "total_due": None,
    }
    lines = text.splitlines()
    anchor = next(
        (
            index
            for index, line in enumerate(lines)
            if "PREVIOUS STATEMENT DUES" in line.upper() and "TOTAL AMOUNT DUE" in line.upper()
        ),
        None,
    )
    if anchor is None:
        return values
    columns = (
        ("previous_due", 0, 20),
        ("payments_credits", 20, 35),
        ("purchases_debits", 35, 48),
        ("finance_charges", 48, 60),
        ("total_due", 60, 10_000),
    )
    for line in lines[anchor + 1 : anchor + 5]:
        for match in _LAYOUT_MONEY_PATTERN.finditer(line):
            for field, start, end in columns:
                if start <= match.start() < end:
                    values[field] = _decimal(match.group(1))
                    break
    return values


def _reviewed_limits(text: str) -> dict[str, Decimal | date | None]:
    """Read limit, minimum-due, and due-date columns from the reviewed layout."""
    values: dict[str, Decimal | date | None] = {
        "credit_limit": None,
        "available_credit_limit": None,
        "available_cash_limit": None,
        "minimum_due": None,
        "due_date": None,
    }
    lines = text.splitlines()
    anchor = next(
        (
            index
            for index, line in enumerate(lines)
            if "AVAILABLE CREDIT LIMIT" in line.upper()
            and "AVAILABLE CASH LIMIT" in line.upper()
            and "DUE DATE" in line.upper()
        ),
        None,
    )
    if anchor is None:
        return values
    columns = (
        ("credit_limit", 0, 24),
        ("available_credit_limit", 24, 42),
        ("available_cash_limit", 42, 59),
        ("minimum_due", 59, 71),
    )
    for line in lines[anchor + 1 : anchor + 4]:
        for match in _LAYOUT_MONEY_PATTERN.finditer(line):
            for field, start, end in columns:
                if start <= match.start() < end:
                    values[field] = _decimal(match.group(1))
                    break
        date_match = re.search(_DATE_PATTERN, line, re.IGNORECASE)
        if date_match and date_match.start() >= 68:
            values["due_date"] = _parse_date(date_match.group(0))
    return values


def _reviewed_lines(text: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    row_pattern = re.compile(
        r"^\s*(\d{2}/\d{2}/\d{4})\s*\|\s*\d{2}:\d{2}\s+"
        r"(.+?)\s+(\+)?\s*C\s*([\d,]+\.\d{2})\s+l\s*$",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        match = row_pattern.match(raw_line)
        if not match:
            continue
        transaction_date = _parse_date(match.group(1))
        if transaction_date is None:
            continue
        description = " ".join(match.group(2).split())
        is_credit = bool(match.group(3))
        transaction_type, card_event = _classify(description, is_credit)
        component = classify_emi_component(description, is_credit=is_credit)
        lines.append(
            {
                "transaction_date": transaction_date,
                "description": description,
                "amount": _decimal(match.group(4)),
                "reference_id": _reference_id(description),
                "transaction_type": transaction_type,
                "card_event": card_event,
                **component,
            }
        )
    return lines


def _legacy_lines(text: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?m)^[ \t]*(\d{1,2}[/-]\d{1,2}[/-]\d{4})[ \t]+"
        r"(.+?)[ \t]+([\d,]+\.\d{2})([ \t]+(?:CR|CREDIT))?[ \t]*$"
    )
    for match in pattern.finditer(text):
        transaction_date = _parse_date(match.group(1))
        if transaction_date is None:
            continue
        description = " ".join(match.group(2).split())
        transaction_type, card_event = _classify(description, bool(match.group(4)))
        component = classify_emi_component(description, is_credit=bool(match.group(4)))
        lines.append(
            {
                "transaction_date": transaction_date,
                "description": description,
                "amount": _decimal(match.group(3)),
                "reference_id": _reference_id(description),
                "transaction_type": transaction_type,
                "card_event": card_event,
                **component,
            }
        )
    return lines


def _classify(description: str, is_credit: bool) -> tuple[str, str]:
    upper = description.upper()
    if "PAYMENT" in upper and ("RECEIVED" in upper or "THANK" in upper or is_credit):
        return "credit", "payment"
    if "CASHBACK" in upper or "CASH BACK" in upper:
        return "refund", "cashback"
    if "REVERSAL" in upper or "REVERSED" in upper:
        return "refund", "reversal"
    if "REFUND" in upper or is_credit:
        return "refund", "refund"
    if re.search(r"\b(?:GST|IGST|CGST|SGST|TAX)\b", upper):
        return "debit", "tax"
    if "INTEREST" in upper or "FINANCE CHARGE" in upper:
        return "debit", "interest"
    if re.search(r"\b(?:FEE|CHARGE)\b", upper):
        return "debit", "fee"
    return "debit", "purchase"


def classify_emi_component(
    description: str, *, is_credit: bool = False
) -> dict[str, str | int | None]:
    """Classify issuer-labelled EMI anatomy without guessing tenure or rate."""
    upper = " ".join(description.upper().split())
    kind = "ordinary"
    if "EMI" not in upper and not re.search(r"\b(?:PRIN|INT)\s+NB", upper):
        return {
            "component_kind": kind,
            "issuer_plan_reference": None,
            "installment_number": None,
        }

    if "AGGREGATOR" in upper and "CREDIT" in upper:
        kind = "emi_conversion_credit"
    elif "REV" in upper and ("PROCNG FEE" in upper or "PROCESSING FEE" in upper):
        kind = "emi_fee_reversal"
    elif "PROCNG FEE" in upper or "PROCESSING FEE" in upper:
        kind = "emi_processing_fee"
    elif "PRECLO INT" in upper or "PRECLOSE INT" in upper:
        kind = "emi_preclosure_interest"
    elif "LOAN PRECL" in upper or "LOAN PRECLOSE" in upper:
        kind = "emi_preclosure_principal"
    elif re.search(r"\bPRIN(?:CIPAL)?\s+NB", upper):
        kind = "emi_principal"
    elif re.search(r"\bINT(?:EREST)?\s+NB", upper):
        kind = "emi_interest"
    elif upper.startswith("EMI ") and not is_credit:
        kind = "emi_conversion_purchase"

    installment_match = re.search(r"\b(?:PRIN|INT)(?:EREST)?\s+NB(?:R)?\s*:\s*(\d+)", upper)
    # The trailing posting ``(Ref# ...)`` is transaction evidence, not the EMI
    # loan identifier. Read the issuer loan token from the description before
    # that suffix so separate loans are never collapsed under the same Ref#.
    issuer_description = re.split(
        r"\(\s*REF(?:ERENCE)?\s*#",
        upper,
        maxsplit=1,
    )[0]
    numeric_tokens = re.findall(r"\d{4,}", issuer_description)
    issuer_reference = None
    if numeric_tokens and kind not in {
        "ordinary",
        "emi_conversion_purchase",
        "emi_conversion_credit",
    }:
        normalized = numeric_tokens[-1].lstrip("0")
        issuer_reference = normalized[:4] if len(normalized) >= 4 else normalized or None

    return {
        "component_kind": kind,
        "issuer_plan_reference": issuer_reference,
        "installment_number": (int(installment_match.group(1)) if installment_match else None),
    }


def _reference_id(description: str) -> str | None:
    match = re.search(
        r"(?:REF(?:ERENCE)?\s*#?\s*|RRN\s*[:#]?\s*)([A-Z0-9-]{6,40})",
        description,
        re.IGNORECASE,
    )
    return match.group(1).upper() if match else None


def _card_last4(text: str) -> str | None:
    match = re.search(
        r"CREDIT\s+CARD\s+NO\.?\s*[:\-]?\s*(?:\d{0,8})X{4,12}(\d{4})",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _labelled_date(text: str, label: str) -> date | None:
    match = re.search(rf"{label}\s*:?\s*({_DATE_PATTERN})", text, re.IGNORECASE)
    return _parse_date(match.group(1)) if match else None


def _parse_date(value: str) -> date | None:
    normalized = " ".join(value.strip().split())
    for fmt in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %b, %Y",
    ):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _amount_after(text: str, label: str) -> Decimal | None:
    match = re.search(
        rf"{label}[^\d]{{0,40}}([\d,]+(?:\.\d{{2}})?)",
        text,
        re.IGNORECASE,
    )
    return _decimal(match.group(1)) if match else None


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))
