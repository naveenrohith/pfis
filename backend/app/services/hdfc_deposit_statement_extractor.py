"""Fail-closed extraction for PFIS's reviewed HDFC deposit text profile.

The profile is deliberately narrower than statement recognition.  It models
the public HDFC deposit-statement column contract using a de-identified,
pipe-delimited fixture.  Unfamiliar PDF text must be reviewed before this
extractor is expanded; recognition alone is never permission to write rows.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

EXTRACTOR_VERSION = "hdfc-deposit-reviewed-v1"
LAYOUT_NAME = "hdfc-deposit-pipe-v1"

_HEADER = (
    "DATE | NARRATION | CHQ./REF.NO. | VALUE DT | "
    "WITHDRAWAL AMT. | DEPOSIT AMT. | CLOSING BALANCE"
)
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y")


def is_reviewed_deposit_layout(text: str) -> bool:
    """Return whether text matches the one write-enabled deposit profile."""

    normalized = _normalized_upper(text)
    return (
        "HDFC BANK" in normalized
        and "ACCOUNT STATEMENT" in normalized
        and _HEADER in normalized
        and bool(re.search(r"ACCOUNT\s+(?:NO\.?|NUMBER)\s*:\s*[X*]+\d{4}\b", normalized))
        and bool(
            re.search(
                r"STATEMENT\s+PERIOD\s*:\s*\d{2}[/-]\d{2}[/-]\d{4}"
                r"\s+TO\s+\d{2}[/-]\d{2}[/-]\d{4}",
                normalized,
            )
        )
    )


def extract_hdfc_deposit_statement(text: str) -> dict[str, Any]:
    """Extract and arithmetically reconcile a reviewed deposit statement.

    Raises ``ValueError`` before persistence when identity, dates, columns, or
    running balances cannot be proved from the source text.
    """

    if not is_reviewed_deposit_layout(text):
        raise ValueError("This is not the reviewed HDFC deposit statement layout")

    period_match = re.search(
        r"STATEMENT\s+PERIOD\s*:\s*(\d{2}[/-]\d{2}[/-]\d{4})" r"\s+TO\s+(\d{2}[/-]\d{2}[/-]\d{4})",
        text,
        re.IGNORECASE,
    )
    account_match = re.search(
        r"ACCOUNT\s+(?:NO\.?|NUMBER)\s*:\s*([X*]+)(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    opening_match = re.search(
        r"OPENING\s+BALANCE\s*:\s*(?:INR\s*)?([\d,]+\.\d{2})\b",
        text,
        re.IGNORECASE,
    )
    if period_match is None or account_match is None or opening_match is None:
        raise ValueError("Deposit statement identity or opening balance could not be verified")

    period_start = _parse_date(period_match.group(1))
    period_end = _parse_date(period_match.group(2))
    if period_start > period_end:
        raise ValueError("Deposit statement period is invalid")

    opening_balance = _money(opening_match.group(1))
    previous_balance = opening_balance
    rows: list[dict[str, Any]] = []
    header_seen = False
    for raw_line in text.splitlines():
        normalized_line = " ".join(raw_line.upper().split())
        if normalized_line == _HEADER:
            header_seen = True
            continue
        if not header_seen or "|" not in raw_line:
            continue
        cells = [cell.strip() for cell in raw_line.split("|")]
        if len(cells) != 7:
            raise ValueError("Deposit statement row has ambiguous columns")
        try:
            transaction_date = _parse_date(cells[0])
            value_date = _parse_date(cells[3])
        except ValueError as exc:
            raise ValueError("Deposit statement row contains an invalid date") from exc
        if not period_start <= transaction_date <= period_end:
            raise ValueError("Deposit statement row falls outside the statement period")
        description = " ".join(cells[1].split())
        if not description:
            raise ValueError("Deposit statement row is missing narration")
        withdrawal = _optional_money(cells[4])
        deposit = _optional_money(cells[5])
        if (withdrawal is None) == (deposit is None):
            raise ValueError("Deposit statement row must contain one withdrawal or deposit")
        amount = withdrawal if withdrawal is not None else deposit
        assert amount is not None
        if amount <= 0:
            raise ValueError("Deposit statement row amount must be positive")
        closing_balance = _money(cells[6])
        expected_balance = previous_balance - (withdrawal or Decimal()) + (deposit or Decimal())
        if closing_balance != expected_balance:
            raise ValueError("Deposit statement running balance does not reconcile")
        rail = classify_payment_rail(description)
        rows.append(
            {
                "transaction_date": transaction_date,
                "value_date": value_date,
                "description": description,
                "reference_id": cells[2] or None,
                "amount": amount,
                "transaction_type": "debit" if withdrawal is not None else "credit",
                "payment_rail": rail,
                "balance_after": closing_balance,
                "review_outcome": "ready_to_import" if rail != "other" else "needs_review",
            }
        )
        previous_balance = closing_balance

    if not rows:
        raise ValueError("Deposit statement contains no reviewed transaction rows")

    return {
        "account_last4": account_match.group(2),
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance": opening_balance,
        "closing_balance": previous_balance,
        "currency": "INR",
        "layout_name": LAYOUT_NAME,
        "lines": rows,
    }


def classify_payment_rail(description: str) -> str:
    """Classify only explicit rail evidence contained in the narration."""

    upper = " ".join(description.upper().split())
    if re.search(r"(?:^|[/\s-])UPI(?:[/\s-]|$)", upper):
        return "upi"
    if re.search(r"\b(?:POS|E-COM|ECOM|DEBIT\s+CARD)\b", upper):
        return "debit_card"
    if re.search(r"\b(?:ATM|NWD|EAW)\b", upper):
        return "atm"
    if re.search(r"\b(?:NEFT|IMPS|RTGS)\b", upper):
        return "transfer"
    return "other"


def _parse_date(value: str) -> date:
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date: {value}")


def _money(value: str) -> Decimal:
    try:
        amount = Decimal(value.replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("Deposit statement row contains an invalid amount") from exc
    if amount < 0:
        raise ValueError("Deposit statement balances cannot be negative")
    return amount


def _optional_money(value: str) -> Decimal | None:
    normalized = value.strip()
    return _money(normalized) if normalized not in {"", "-"} else None


def _normalized_upper(text: str) -> str:
    return "\n".join(" ".join(line.upper().split()) for line in text.splitlines())
