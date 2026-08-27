"""Strict issuer-neutral credit-card statement extraction.

Recognition can identify many generic card layouts, but this profile is
write-enabled only when a de-identified tabular export proves card identity,
the billing facts, explicit debit/credit direction, and an exact liability
running-balance chain.  It intentionally accepts one pipe-delimited contract;
unfamiliar PDFs remain review-only until a sanitized layout is reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.hdfc_statement_extractor import classify_emi_component

EXTRACTOR_VERSION = "generic-credit-card-tabular-v1"
LAYOUT_NAME = "generic-credit-card-tabular-v1"
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")


def is_reviewed_generic_credit_card_layout(text: str) -> bool:
    """Return whether text satisfies the complete generic card contract."""

    try:
        extract_generic_credit_card_statement(text)
    except ValueError:
        return False
    return True


def extract_generic_credit_card_statement(text: str) -> dict[str, Any]:
    """Extract one strict issuer-neutral card statement before persistence."""

    normalized = _normalized_upper(text)
    if "CREDIT CARD" not in normalized and "CARD STATEMENT" not in normalized:
        raise ValueError("This is not a generic credit-card statement")
    account_last4 = _card_last4(text)
    period = _statement_period(text)
    statement_date = _labelled_date(text, r"STATEMENT\s+DATE")
    due_date = _labelled_date(text, r"(?:PAYMENT\s+)?DUE\s+DATE")
    total_due = _amount_after(text, r"TOTAL\s+(?:AMOUNT\s+)?DUE")
    minimum_due = _amount_after(
        text,
        r"MINIMUM\s+(?:AMOUNT\s+|PAYMENT\s+)?DUE",
    )
    credit_limit = _amount_after(
        text,
        r"(?:TOTAL\s+)?CREDIT\s+LIMIT",
        exclude_label=r"AVAILABLE\s+CREDIT",
    )
    available_credit_limit = _amount_after(
        text,
        r"AVAILABLE\s+CREDIT(?:\s+LIMIT)?",
    )
    available_cash_limit = _amount_after(text, r"AVAILABLE\s+CASH\s+LIMIT")
    opening_balance = _amount_after(text, r"OPENING\s+BALANCE")
    header_line, header = _find_header(text)
    missing = [
        name
        for name, value in (
            ("card identity", account_last4),
            ("statement period", period),
            ("statement date", statement_date),
            ("total due", total_due),
            ("minimum due", minimum_due),
            ("due date", due_date),
            ("credit limit", credit_limit),
            ("opening balance", opening_balance),
            ("transaction header", header),
        )
        if value is None
    ]
    if missing:
        raise ValueError("Generic credit-card statement is missing " + ", ".join(missing))
    assert period is not None
    assert statement_date is not None
    assert total_due is not None
    assert minimum_due is not None
    assert credit_limit is not None
    assert opening_balance is not None
    assert header_line is not None
    assert header is not None
    if period[0] > period[1]:
        raise ValueError("Generic credit-card statement period is invalid")
    if credit_limit <= 0 or total_due < 0 or minimum_due < 0 or opening_balance < 0:
        raise ValueError("Generic credit-card statement amounts are invalid")
    if minimum_due > total_due:
        raise ValueError("Generic credit-card minimum due exceeds total due")

    previous_balance = opening_balance
    rows: list[dict[str, Any]] = []
    header_seen = False
    for raw_line in text.splitlines():
        if raw_line == header_line:
            header_seen = True
            continue
        if not header_seen or "|" not in raw_line:
            continue
        cells = [cell.strip() for cell in raw_line.split("|")]
        if len(cells) != header.column_count:
            raise ValueError("Generic credit-card row has ambiguous columns")
        assert header.date_index is not None
        assert header.description_index is not None
        assert header.debit_index is not None
        assert header.credit_index is not None
        assert header.balance_index is not None
        transaction_date = _parse_date(cells[header.date_index])
        if not period[0] <= transaction_date <= period[1]:
            raise ValueError("Generic credit-card row falls outside the statement period")
        description = " ".join(cells[header.description_index].split())
        if not description:
            raise ValueError("Generic credit-card row is missing description")
        debit = _optional_money(cells[header.debit_index])
        credit = _optional_money(cells[header.credit_index])
        if (debit is None) == (credit is None):
            raise ValueError("Generic credit-card row must contain one debit or credit")
        amount = debit if debit is not None else credit
        assert amount is not None
        balance_after = _money(cells[header.balance_index])
        expected_balance = previous_balance + (debit or Decimal("0")) - (credit or Decimal("0"))
        if balance_after != expected_balance:
            raise ValueError("Generic credit-card running balance does not reconcile")
        transaction_type, card_event = _classify_card_event(
            description, is_credit=credit is not None
        )
        if card_event == "ambiguous_credit":
            raise ValueError("Generic credit-card credit event is not explicitly classified")
        component = classify_emi_component(
            description,
            is_credit=credit is not None,
        )
        rows.append(
            {
                "transaction_date": transaction_date,
                "description": description,
                "amount": amount,
                "reference_id": (
                    cells[header.reference_index].strip() or None
                    if header.reference_index is not None
                    else None
                ),
                "transaction_type": transaction_type,
                "card_event": card_event,
                **component,
            }
        )
        previous_balance = balance_after

    if not rows:
        raise ValueError("Generic credit-card statement contains no transaction rows")
    if previous_balance != total_due:
        raise ValueError("Generic credit-card closing balance does not equal total amount due")
    return {
        "statement_date": statement_date,
        "period_start": period[0],
        "period_end": period[1],
        "due_date": due_date,
        "total_due": total_due,
        "minimum_due": minimum_due,
        "credit_limit": credit_limit,
        "available_credit_limit": available_credit_limit,
        "available_cash_limit": available_cash_limit,
        "previous_due": None,
        "payments_credits": sum(
            (row["amount"] for row in rows if row["transaction_type"] == "credit"),
            Decimal("0"),
        ),
        "purchases_debits": sum(
            (row["amount"] for row in rows if row["transaction_type"] == "debit"),
            Decimal("0"),
        ),
        "finance_charges": None,
        "card_last4": account_last4,
        "layout_name": LAYOUT_NAME,
        "currency": _source_currency(text) or "unknown",
        "lines": rows,
    }


@dataclass(frozen=True, slots=True)
class _Header:
    column_count: int
    date_index: int
    description_index: int
    debit_index: int
    credit_index: int
    balance_index: int
    reference_index: int | None


def _find_header(text: str) -> tuple[str | None, _Header | None]:
    for raw_line in text.splitlines():
        if "|" not in raw_line:
            continue
        cells = [" ".join(cell.upper().split()) for cell in raw_line.split("|")]
        if len(cells) < 5:
            continue

        def find(*patterns: str, _cells: list[str] = cells) -> int | None:
            for index, cell in enumerate(_cells):
                if any(re.search(pattern, cell) for pattern in patterns):
                    return index
            return None

        date_index = find(r"\bDATE\b", r"TRANSACTION\s+DATE")
        description_index = find(
            r"DESCRIPTION",
            r"NARRATION",
            r"PARTICULARS",
            r"TRANSACTION\s+DETAILS",
        )
        debit_index = find(r"\bDEBIT\b", r"CHARGE", r"PURCHASE")
        credit_index = find(r"\bCREDIT\b", r"PAYMENT", r"REFUND")
        balance_index = find(r"\bBALANCE\b", r"CLOSING\s+BALANCE", r"RUNNING\s+BALANCE")
        reference_index = find(r"REFERENCE", r"REF\.?\b", r"AUTH")
        required = (date_index, description_index, debit_index, credit_index, balance_index)
        if any(index is None for index in required):
            continue
        assert date_index is not None
        assert description_index is not None
        assert debit_index is not None
        assert credit_index is not None
        assert balance_index is not None
        if len({date_index, description_index, debit_index, credit_index, balance_index}) != 5:
            continue
        return raw_line, _Header(
            column_count=len(cells),
            date_index=date_index,
            description_index=description_index,
            debit_index=debit_index,
            credit_index=credit_index,
            balance_index=balance_index,
            reference_index=reference_index,
        )
    return None, None


def _classify_card_event(description: str, *, is_credit: bool) -> tuple[str, str]:
    upper = " ".join(description.upper().split())
    if is_credit:
        if re.search(r"\b(?:REFUND|RETURNED|REVERSAL|REVERSED)\b", upper):
            return "refund", "reversal" if "REVERS" in upper else "refund"
        if re.search(r"\b(?:CASHBACK|CASH\s+BACK)\b", upper):
            return "refund", "cashback"
        if re.search(r"\b(?:PAYMENT|PAID|RECEIVED|THANK)\b", upper):
            return "credit", "payment"
        return "refund", "ambiguous_credit"
    if re.search(r"\b(?:GST|IGST|CGST|SGST|TAX)\b", upper):
        return "debit", "tax"
    if re.search(r"\b(?:INTEREST|FINANCE\s+CHARGE)\b", upper):
        return "debit", "interest"
    if re.search(r"\b(?:FEE|CHARGE|SURCHARGE)\b", upper):
        return "debit", "fee"
    return "debit", "purchase"


def _card_last4(text: str) -> str | None:
    match = re.search(
        r"(?:CREDIT\s+CARD|CARD)\s+(?:NO\.?|NUMBER)\s*[:\-]?\s*" r"(?:(?:X|\*)[\s-]*){2,}(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _statement_period(text: str) -> tuple[date, date] | None:
    match = re.search(
        r"(?:STATEMENT|BILLING)\s+PERIOD\s*[:\-]?\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\s*"
        r"(?:TO|THROUGH|-)\s*"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    start = _parse_date(match.group(1))
    end = _parse_date(match.group(2))
    return start, end


def _labelled_date(text: str, label: str) -> date | None:
    match = re.search(
        rf"{label}\s*[:\-]?\s*(\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|\d{{4}}[/-]\d{{1,2}}[/-]\d{{1,2}})",
        text,
        re.IGNORECASE,
    )
    return _parse_date(match.group(1)) if match else None


def _amount_after(
    text: str,
    label: str,
    *,
    exclude_label: str | None = None,
) -> Decimal | None:
    amount_pattern = (
        rf"{label}\s*[:\-]?\s*((?:(?:INR|USD|EUR|GBP|RS\.?)\s*)?" r"\(?-?[\d,]+(?:\.\d{1,2})?\)?)"
    )
    for raw_line in text.splitlines():
        if exclude_label and re.search(exclude_label, raw_line, re.IGNORECASE):
            continue
        match = re.search(amount_pattern, raw_line, re.IGNORECASE)
        if match is not None:
            return _money(match.group(1))
    return None


def _parse_date(value: str) -> date:
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date: {value}")


def _money(value: str) -> Decimal:
    normalized = re.sub(r"(?:INR|USD|EUR|GBP|RS\.?)", "", value, flags=re.IGNORECASE)
    normalized = normalized.replace(",", "").strip()
    negative = normalized.startswith("(") and normalized.endswith(")")
    normalized = normalized.strip("()")
    try:
        amount = Decimal(normalized).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Generic credit-card statement contains an invalid amount") from exc
    if negative or amount < 0:
        raise ValueError("Generic credit-card statement amounts cannot be negative")
    return amount


def _optional_money(value: str) -> Decimal | None:
    normalized = value.strip()
    if normalized in {"", "-", "—", "–"}:
        return None
    amount = _money(normalized)
    return amount if amount else None


def _source_currency(text: str) -> str | None:
    match = re.search(r"\b(INR|USD|EUR|GBP)\b", text.upper())
    return match.group(1) if match else None


def _normalized_upper(text: str) -> str:
    return "\n".join(" ".join(line.upper().split()) for line in text.splitlines())
