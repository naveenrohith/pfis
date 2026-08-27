"""Bounded, read-only analysis for recognized financial statements.

Statement recognition and statement import intentionally remain separate.  This
module may summarize evidence from an uploaded document, but it never creates
accounts, transactions, statement rows, or fingerprints.  Generic layouts are
parsed only when their column order and row shape are explicit; otherwise the
result stays signature-only.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.generic_deposit_statement_extractor import (
    extract_generic_deposit_statement,
)
from app.services.hdfc_deposit_statement_extractor import (
    classify_payment_rail,
    extract_hdfc_deposit_statement,
    is_reviewed_deposit_layout,
)
from app.services.hdfc_statement_extractor import (
    extract_hdfc_statement,
    is_reviewed_layout,
)
from app.services.statement_detection import StatementDetection

ANALYSIS_RULESET_VERSION = "pfis-statement-analysis-1"
MAX_PREVIEW_LINES = 25
MAX_DESCRIPTION_LENGTH = 120

_DATE_RE = re.compile(
    r"(?<!\w)(?:"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"\d{1,2}\s+[A-Za-z]{3},?\s+\d{4}"
    r")(?!\w)"
)
_MONEY_RE = re.compile(
    r"(?<!\w)(?:₹|INR|RS\.?\s*)?"
    r"\(?-?[\d,]+(?:\.\d{1,2})?\)?(?!\w)",
    re.IGNORECASE,
)
_CARD_EVENT_CREDIT = {"credit", "refund"}


def analyze_statement(statement_text: str, detection: StatementDetection) -> dict[str, Any]:
    """Return a non-persistent, bounded analysis for a detected statement."""

    try:
        if detection.support_status == "ambiguous":
            return _signature_only("ambiguous_product_signature")

        if detection.product_type == "deposit_account":
            if detection.institution == "hdfc" and is_reviewed_deposit_layout(statement_text):
                return _reviewed_deposit_analysis(statement_text)
            if detection.support_status == "supported":
                return _generic_reviewed_deposit_analysis(statement_text)
            return _generic_deposit_analysis(statement_text)

        if detection.product_type == "credit_card":
            if (
                detection.institution == "hdfc"
                and detection.support_status == "supported"
                and is_reviewed_layout(statement_text)
            ):
                return _reviewed_card_analysis(statement_text)
            return _generic_card_analysis(statement_text)

        return _signature_only("analysis_not_available_for_signature")
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError):
        # A failed analysis must not turn a read-only detector into a write
        # path, nor make an otherwise valid detection endpoint unavailable.
        return _signature_only("analysis_failed_closed")


def _reviewed_deposit_analysis(statement_text: str) -> dict[str, Any]:
    extracted = extract_hdfc_deposit_statement(statement_text)
    return _deposit_analysis_from_extracted(
        extracted,
        reason_codes=("reviewed_import_profile", "running_balance_reconciled"),
    )


def _generic_reviewed_deposit_analysis(statement_text: str) -> dict[str, Any]:
    extracted = extract_generic_deposit_statement(statement_text)
    return _deposit_analysis_from_extracted(
        extracted,
        reason_codes=("reviewed_generic_import_profile", "running_balance_reconciled"),
    )


def _deposit_analysis_from_extracted(
    extracted: dict[str, Any], *, reason_codes: tuple[str, ...]
) -> dict[str, Any]:
    lines = [
        _line(
            line_number=index,
            transaction_date=item["transaction_date"],
            description=item["description"],
            amount=item["amount"],
            direction=item["transaction_type"],
            payment_rail=item["payment_rail"],
            balance_after=item["balance_after"],
            confidence=1.0,
            reason_codes=("reviewed_columns_and_balance_reconciled",),
        )
        for index, item in enumerate(extracted["lines"], start=1)
    ]
    return _finalize(
        status="available",
        source_kind="reviewed_extractor",
        lines=lines,
        period_start=extracted["period_start"],
        period_end=extracted["period_end"],
        opening_balance=extracted["opening_balance"],
        closing_balance=extracted["closing_balance"],
        reconciled=True,
        reason_codes=reason_codes,
    )


def _reviewed_card_analysis(statement_text: str) -> dict[str, Any]:
    extracted = extract_hdfc_statement(statement_text)
    lines = [
        _line(
            line_number=index,
            transaction_date=item["transaction_date"],
            description=item["description"],
            amount=item["amount"],
            direction=("credit" if item.get("transaction_type") in _CARD_EVENT_CREDIT else "debit"),
            payment_rail="credit_card",
            balance_after=None,
            confidence=1.0,
            reason_codes=("reviewed_card_event", item.get("card_event", "purchase")),
        )
        for index, item in enumerate(extracted["lines"], start=1)
    ]
    return _finalize(
        status="available",
        source_kind="reviewed_extractor",
        lines=lines,
        period_start=extracted["period_start"],
        period_end=extracted["period_end"],
        opening_balance=None,
        closing_balance=None,
        reconciled=None,
        reason_codes=("reviewed_import_profile", "card_event_direction_classified"),
    )


def _generic_deposit_analysis(statement_text: str) -> dict[str, Any]:
    header = _find_deposit_header(statement_text)
    if header is None:
        return _signature_only("tabular_columns_not_proven")

    rows: list[dict[str, Any]] = []
    for raw_line in statement_text.splitlines():
        row = _parse_deposit_row(raw_line, header)
        if row is not None:
            rows.append(row)
    if not rows:
        return _signature_only("transaction_rows_not_proven")

    lines = [
        _line(
            line_number=index,
            transaction_date=item["transaction_date"],
            description=item["description"],
            amount=item["amount"],
            direction=item["direction"],
            payment_rail=item["payment_rail"],
            balance_after=item["balance_after"],
            confidence=item["confidence"],
            reason_codes=item["reason_codes"],
        )
        for index, item in enumerate(rows, start=1)
    ]
    directions_proven = all(item["direction"] in {"debit", "credit"} for item in rows)
    explicit_opening = _labelled_money(statement_text, r"OPENING\s+BALANCE")
    opening_balance = explicit_opening
    closing_balance = rows[-1]["balance_after"]
    reconciled: bool | None = None
    reason_codes = ["generic_table_columns_proven"]
    if explicit_opening is not None and directions_proven:
        reconciled = _balances_reconcile(rows, explicit_opening)
        reason_codes.append(
            "running_balance_reconciled" if reconciled else "running_balance_not_reconciled"
        )
    elif directions_proven:
        reason_codes.append("opening_balance_not_disclosed")
    else:
        reason_codes.append("direction_not_proven")

    period_start, period_end = _period(statement_text, rows)
    return _finalize(
        status="partial",
        source_kind="generic_table",
        lines=lines,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        reconciled=reconciled,
        reason_codes=tuple(reason_codes),
    )


def _generic_card_analysis(statement_text: str) -> dict[str, Any]:
    if not _has_card_table_header(statement_text):
        return _signature_only("transaction_rows_not_proven")

    rows: list[dict[str, Any]] = []
    for raw_line in statement_text.splitlines():
        row = _parse_card_row(raw_line)
        if row is not None:
            rows.append(row)
    if not rows:
        return _signature_only("transaction_rows_not_proven")

    lines = [
        _line(
            line_number=index,
            transaction_date=item["transaction_date"],
            description=item["description"],
            amount=item["amount"],
            direction=item["direction"],
            payment_rail="credit_card",
            balance_after=None,
            confidence=item["confidence"],
            reason_codes=item["reason_codes"],
        )
        for index, item in enumerate(rows, start=1)
    ]
    period_start, period_end = _period(statement_text, rows)
    return _finalize(
        status="partial",
        source_kind="generic_table",
        lines=lines,
        period_start=period_start,
        period_end=period_end,
        opening_balance=None,
        closing_balance=None,
        reconciled=None,
        reason_codes=("generic_card_rows_previewed", "credit_direction_requires_explicit_marker"),
    )


def _find_deposit_header(statement_text: str) -> dict[str, int] | None:
    for raw_line in statement_text.splitlines():
        upper = " ".join(raw_line.upper().split())
        if "DATE" not in upper or "BALANCE" not in upper:
            continue
        if not any(label in upper for label in ("NARRATION", "DESCRIPTION", "PARTICULARS")):
            continue
        debit_match = re.search(r"\b(?:DEBIT|WITHDRAWAL)(?:\s+AMT(?:OUNT)?\.?)?\b", upper)
        credit_match = re.search(r"\b(?:CREDIT|DEPOSIT)(?:\s+AMT(?:OUNT)?\.?)?\b", upper)
        balance_match = re.search(r"\b(?:CLOSING\s+)?BALANCE\b", upper)
        if not debit_match or not credit_match or not balance_match:
            continue
        if debit_match.start() == credit_match.start():
            continue
        debit_index = 0 if debit_match.start() < credit_match.start() else 1
        credit_index = 1 - debit_index
        return {"debit_index": debit_index, "credit_index": credit_index, "balance_index": 2}
    return None


def _parse_deposit_row(raw_line: str, header: dict[str, int]) -> dict[str, Any] | None:
    date_match = re.match(
        r"^\s*(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b", raw_line
    )
    if not date_match:
        return None
    transaction_date = _parse_date(date_match.group("date"))
    remainder = raw_line[date_match.end() :]
    masked = _mask_dates(remainder)
    money_matches = list(_MONEY_RE.finditer(masked))
    if len(money_matches) < 3:
        return None
    selected = money_matches[-3:]
    values = [_money(match.group(0)) for match in selected]
    description = _clean_description(masked[: selected[0].start()])
    if not description:
        return None
    debit = values[header["debit_index"]]
    credit = values[header["credit_index"]]
    balance = values[header["balance_index"]]
    reason_codes: tuple[str, ...]
    if debit > 0 and credit == 0:
        direction = "debit"
        amount = debit
        reason_codes = ("explicit_debit_column",)
        confidence = 0.93
    elif credit > 0 and debit == 0:
        direction = "credit"
        amount = credit
        reason_codes = ("explicit_credit_column",)
        confidence = 0.93
    else:
        direction = "unknown"
        amount = max(debit, credit)
        reason_codes = (
            "direction_not_proven",
            "debit_and_credit_columns_are_not_exclusive",
        )
        confidence = 0.55
    rail = classify_payment_rail(description) if direction != "unknown" else "unknown"
    return {
        "transaction_date": transaction_date,
        "description": description,
        "amount": amount,
        "direction": direction,
        "payment_rail": rail,
        "balance_after": balance,
        "confidence": confidence,
        "reason_codes": reason_codes,
    }


def _has_card_table_header(statement_text: str) -> bool:
    normalized = " ".join(statement_text.upper().split())
    return (
        ("TRANSACTION DATE" in normalized or "DATE & TIME" in normalized)
        and "AMOUNT" in normalized
        and ("TRANSACTION DESCRIPTION" in normalized or "DESCRIPTION" in normalized)
    )


def _parse_card_row(raw_line: str) -> dict[str, Any] | None:
    date_match = re.match(
        r"^\s*(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}\s+[A-Za-z]{3},?\s+\d{4})\b",
        raw_line,
    )
    if not date_match:
        return None
    transaction_date = _parse_date(date_match.group("date"))
    remainder = raw_line[date_match.end() :]
    masked = _mask_dates(remainder)
    money_matches = list(_MONEY_RE.finditer(masked))
    if not money_matches:
        return None
    amount_match = money_matches[-1]
    amount = _money(amount_match.group(0))
    description = _clean_description(masked[: amount_match.start()])
    if not description:
        return None
    upper = description.upper()
    explicit_credit = bool(
        re.search(r"\b(?:CR|CREDIT|REFUND|CASHBACK|CASH\s+BACK|PAYMENT|REVERSAL)\b", upper)
        or "+" in raw_line[: amount_match.start()]
    )
    explicit_direction = explicit_credit or bool(
        re.search(r"\b(?:DR|DEBIT|PURCHASE|FEE|INTEREST)\b", upper)
    )
    direction = "credit" if explicit_credit else ("debit" if explicit_direction else "unknown")
    return {
        "transaction_date": transaction_date,
        "description": description,
        "amount": amount,
        "direction": direction,
        "confidence": 0.86 if direction != "unknown" else 0.52,
        "reason_codes": (
            ("explicit_credit_marker",)
            if direction == "credit"
            else ("explicit_debit_marker",)
            if direction == "debit"
            else ("direction_not_proven",)
        ),
    }


def _finalize(
    *,
    status: str,
    source_kind: str,
    lines: list[dict[str, Any]],
    period_start: date | None,
    period_end: date | None,
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
    reconciled: bool | None,
    reason_codes: tuple[str, ...],
) -> dict[str, Any]:
    debit_total = sum(
        (
            Decimal(str(line["amount"]))
            for line in lines
            if line["direction"] == "debit" and line["amount"] is not None
        ),
        Decimal("0"),
    )
    credit_total = sum(
        (
            Decimal(str(line["amount"]))
            for line in lines
            if line["direction"] == "credit" and line["amount"] is not None
        ),
        Decimal("0"),
    )
    rail_totals: dict[str, Decimal] = {}
    for line in lines:
        rail = line["payment_rail"]
        if rail == "unknown":
            continue
        if line["amount"] is not None:
            rail_totals[rail] = rail_totals.get(rail, Decimal("0")) + Decimal(str(line["amount"]))
    preview = lines[:MAX_PREVIEW_LINES]
    mean_confidence = (
        float(sum(line["confidence"] for line in lines) / len(lines)) if lines else 0.0
    )
    return {
        "status": status,
        "source_kind": source_kind,
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance": _float(opening_balance),
        "closing_balance": _float(closing_balance),
        "row_count": len(lines),
        "preview_count": len(preview),
        "omitted_line_count": max(0, len(lines) - len(preview)),
        "debit_total": _float(debit_total),
        "credit_total": _float(credit_total),
        "rail_totals": {key: _float(value) for key, value in sorted(rail_totals.items())},
        "reconciled": reconciled,
        "confidence": round(mean_confidence, 2),
        "reason_codes": list(reason_codes),
        "ruleset_version": ANALYSIS_RULESET_VERSION,
        "lines": preview,
    }


def _signature_only(reason: str) -> dict[str, Any]:
    return {
        "status": "signature_only",
        "source_kind": "signature_only",
        "period_start": None,
        "period_end": None,
        "opening_balance": None,
        "closing_balance": None,
        "row_count": 0,
        "preview_count": 0,
        "omitted_line_count": 0,
        "debit_total": 0.0,
        "credit_total": 0.0,
        "rail_totals": {},
        "reconciled": None,
        "confidence": 0.0,
        "reason_codes": [reason],
        "ruleset_version": ANALYSIS_RULESET_VERSION,
        "lines": [],
    }


def _line(
    *,
    line_number: int,
    transaction_date: date,
    description: str,
    amount: Decimal,
    direction: str,
    payment_rail: str,
    balance_after: Decimal | None,
    confidence: float,
    reason_codes: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "line_number": line_number,
        "transaction_date": transaction_date,
        "description": _redact_description(description),
        "amount": _float(amount),
        "direction": direction,
        "payment_rail": payment_rail,
        "balance_after": _float(balance_after),
        "confidence": confidence,
        "reason_codes": list(reason_codes),
    }


def _period(statement_text: str, rows: list[dict[str, Any]]) -> tuple[date | None, date | None]:
    period_match = re.search(
        r"(?:STATEMENT|BILLING)\s+PERIOD\s*:?\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3},?\s+\d{4})\s*"
        r"(?:TO|-)\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3},?\s+\d{4})",
        statement_text,
        re.IGNORECASE,
    )
    if period_match:
        return _parse_date(period_match.group(1)), _parse_date(period_match.group(2))
    dates = [row["transaction_date"] for row in rows if row.get("transaction_date") is not None]
    return (min(dates), max(dates)) if dates else (None, None)


def _balances_reconcile(rows: list[dict[str, Any]], opening_balance: Decimal) -> bool:
    previous = opening_balance
    for row in rows:
        if row["direction"] == "debit":
            expected = previous - row["amount"]
        elif row["direction"] == "credit":
            expected = previous + row["amount"]
        else:
            return False
        if expected != row["balance_after"]:
            return False
        previous = row["balance_after"]
    return True


def _labelled_money(statement_text: str, label: str) -> Decimal | None:
    match = re.search(
        label + r"\s*:?\s*(?:INR|RS\.?|₹)?\s*([\d,]+(?:\.\d{1,2})?)", statement_text, re.IGNORECASE
    )
    return _money(match.group(1)) if match else None


def _mask_dates(value: str) -> str:
    return _DATE_RE.sub(lambda match: " " * len(match.group(0)), value)


def _parse_date(value: str) -> date:
    for fmt in (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%Y/%m/%d",
        "%Y-%m-%d",
        "%d %b, %Y",
        "%d %b %Y",
    ):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError("unsupported statement date")


def _money(value: str) -> Decimal:
    normalized = re.sub(r"(?i)(?:₹|INR|RS\.?)\s*", "", value)
    normalized = re.sub(r"[^\d,().-]", "", normalized)
    normalized = normalized.replace(",", "").replace("(", "-").replace(")", "").strip().rstrip(".")
    amount = Decimal(normalized).quantize(Decimal("0.01"))
    if amount < 0:
        raise ValueError("negative statement amount")
    return amount


def _clean_description(value: str) -> str:
    return " ".join(value.replace("|", " ").split())[:MAX_DESCRIPTION_LENGTH]


def _redact_description(value: str) -> str:
    redacted = re.sub(r"(?i)(?:x|\*){2,}\d{4,}", "[REDACTED]", value)
    redacted = re.sub(r"\b\d{8,}\b", "[REDACTED]", redacted)
    return _clean_description(redacted)


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None
