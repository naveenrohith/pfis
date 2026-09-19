"""Fail-closed extraction for an issuer-neutral, reconciled bank table profile.

Recognition may identify many bank/debit/UPI layouts, but only this explicit
profile is write-enabled: it requires a masked account suffix, statement
period, opening balance, unambiguous debit/credit/balance columns, and a
cent-exact running-balance reconciliation for every row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.hdfc_deposit_statement_extractor import classify_payment_rail

EXTRACTOR_VERSION = "generic-deposit-tabular-v1"
LAYOUT_NAME = "generic-deposit-tabular-v1"
_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")
_MONEY_RE = re.compile(
    r"(?<!\w)(?:INR|USD|EUR|GBP|RS\.?\s*)?" r"\(?-?[\d,]+(?:\.\d{1,2})?\)?(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Header:
    delimiter: str
    column_count: int
    date_index: int | None
    description_index: int | None
    debit_index: int | None
    credit_index: int | None
    balance_index: int | None
    value_date_index: int | None
    reference_index: int | None


def is_reviewed_generic_deposit_layout(text: str) -> bool:
    """Return whether the complete generic profile can be extracted safely."""

    try:
        extract_generic_deposit_statement(text)
    except ValueError:
        return False
    return True


def extract_generic_deposit_statement(text: str) -> dict[str, Any]:
    """Extract and reconcile one strict generic deposit statement."""

    period = _statement_period(text)
    account_last4 = _account_last4(text)
    opening_balance = _opening_balance(text)
    header_line, header = _find_header(text)
    if period is None or account_last4 is None or opening_balance is None:
        raise ValueError("Generic bank statement identity, period, or opening balance is missing")
    if header is None or header_line is None:
        raise ValueError("Generic bank statement columns are not unambiguous")

    period_start, period_end = period
    previous_balance = opening_balance
    rows: list[dict[str, Any]] = []
    header_seen = False
    for raw_line in text.splitlines():
        if raw_line == header_line:
            header_seen = True
            continue
        if not header_seen:
            continue
        row = _parse_row(raw_line, header)
        if row is None:
            continue
        transaction_date = row["transaction_date"]
        if not period_start <= transaction_date <= period_end:
            raise ValueError("Generic bank statement row falls outside the statement period")
        withdrawal = row["withdrawal"]
        deposit = row["deposit"]
        if (withdrawal is None) == (deposit is None):
            raise ValueError("Generic bank statement row must contain one debit or credit")
        amount = withdrawal if withdrawal is not None else deposit
        assert amount is not None
        if amount <= 0:
            raise ValueError("Generic bank statement row amount must be positive")
        expected_balance = (
            previous_balance - (withdrawal or Decimal("0")) + (deposit or Decimal("0"))
        )
        if row["balance_after"] != expected_balance:
            raise ValueError("Generic bank statement running balance does not reconcile")
        rail = classify_payment_rail(row["description"])
        rows.append(
            {
                "transaction_date": transaction_date,
                "value_date": row["value_date"] or transaction_date,
                "description": row["description"],
                "reference_id": row["reference_id"],
                "amount": amount,
                "transaction_type": "debit" if withdrawal is not None else "credit",
                "payment_rail": rail,
                "balance_after": row["balance_after"],
                "review_outcome": "ready_to_import" if rail != "other" else "needs_review",
            }
        )
        previous_balance = row["balance_after"]

    if not rows:
        raise ValueError("Generic bank statement contains no transaction rows")

    source_currency = _source_currency(text)
    return {
        "account_last4": account_last4,
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance": opening_balance,
        "closing_balance": previous_balance,
        "currency": source_currency or "unknown",
        "layout_name": LAYOUT_NAME,
        "lines": rows,
    }


def _find_header(text: str) -> tuple[str | None, _Header | None]:
    for raw_line in text.splitlines():
        normalized = " ".join(raw_line.upper().split())
        if "DATE" not in normalized or "BALANCE" not in normalized:
            continue
        if not re.search(
            r"\b(?:NARRATION|DESCRIPTION|PARTICULARS|TRANSACTION\s+DETAILS)\b", normalized
        ):
            continue
        if not re.search(r"\b(?:DEBIT|WITHDRAWAL)\b", normalized):
            continue
        if not re.search(r"\b(?:CREDIT|DEPOSIT)\b", normalized):
            continue
        if "|" in raw_line:
            cells = [" ".join(cell.upper().split()) for cell in raw_line.split("|")]
            header = _pipe_header(cells)
            if header is not None:
                return raw_line, header
            continue
        debit_position = _column_position(normalized, ("WITHDRAWAL", "DEBIT"))
        credit_position = _column_position(normalized, ("DEPOSIT", "CREDIT"))
        balance_position = _column_position(normalized, ("CLOSING BALANCE", "BALANCE"))
        if debit_position is None or credit_position is None or balance_position is None:
            continue
        return raw_line, _Header(
            delimiter="space",
            column_count=0,
            date_index=None,
            description_index=None,
            debit_index=0 if debit_position < credit_position else 1,
            credit_index=1 if debit_position < credit_position else 0,
            balance_index=2,
            value_date_index=None,
            reference_index=None,
        )
    return None, None


def _pipe_header(cells: list[str]) -> _Header | None:
    def find(*patterns: str) -> int | None:
        for index, cell in enumerate(cells):
            if any(re.search(pattern, cell) for pattern in patterns):
                return index
        return None

    date_index = find(r"\bDATE\b", r"TRANSACTION\s+DATE")
    description_index = find(
        r"NARRATION",
        r"DESCRIPTION",
        r"PARTICULARS",
        r"TRANSACTION\s+DETAILS",
    )
    debit_index = find(r"WITHDRAWAL", r"\bDEBIT\b")
    credit_index = find(r"DEPOSIT", r"\bCREDIT\b")
    balance_index = find(r"CLOSING\s+BALANCE", r"\bBALANCE\b")
    value_date_index = find(r"VALUE\s+(?:DATE|DT)")
    reference_index = find(r"REFERENCE", r"REF", r"CHQ")
    required = (date_index, description_index, debit_index, credit_index, balance_index)
    if any(index is None for index in required) or len(set(required)) != len(required):
        return None
    return _Header(
        delimiter="pipe",
        column_count=len(cells),
        date_index=date_index,
        description_index=description_index,
        debit_index=debit_index,
        credit_index=credit_index,
        balance_index=balance_index,
        value_date_index=value_date_index,
        reference_index=reference_index,
    )


def _parse_row(raw_line: str, header: _Header) -> dict[str, Any] | None:
    if header.delimiter == "pipe":
        if "|" not in raw_line:
            return None
        cells = [cell.strip() for cell in raw_line.split("|")]
        if len(cells) != header.column_count:
            raise ValueError("Generic bank statement row has ambiguous columns")
        assert header.date_index is not None
        assert header.description_index is not None
        assert header.debit_index is not None
        assert header.credit_index is not None
        assert header.balance_index is not None
        transaction_date = _parse_date(cells[header.date_index])
        value_date = (
            _parse_date(cells[header.value_date_index])
            if header.value_date_index is not None and cells[header.value_date_index]
            else None
        )
        description = " ".join(cells[header.description_index].split())
        if not description:
            raise ValueError("Generic bank statement row is missing description")
        return {
            "transaction_date": transaction_date,
            "value_date": value_date,
            "description": description,
            "reference_id": (
                cells[header.reference_index].strip() or None
                if header.reference_index is not None
                else None
            ),
            "withdrawal": _optional_money(cells[header.debit_index]),
            "deposit": _optional_money(cells[header.credit_index]),
            "balance_after": _money(cells[header.balance_index]),
        }

    date_match = re.match(
        r"^\s*(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b",
        raw_line,
    )
    if date_match is None:
        return None
    transaction_date = _parse_date(date_match.group("date"))
    remainder = raw_line[date_match.end() :]
    money_matches = list(_MONEY_RE.finditer(remainder))
    if len(money_matches) < 3:
        return None
    selected = money_matches[-3:]
    values = [_money(match.group(0)) for match in selected]
    description = " ".join(remainder[: selected[0].start()].split())
    if not description:
        raise ValueError("Generic bank statement row is missing description")
    assert header.debit_index is not None
    assert header.credit_index is not None
    assert header.balance_index is not None
    withdrawal_value = values[header.debit_index]
    deposit_value = values[header.credit_index]
    return {
        "transaction_date": transaction_date,
        "value_date": None,
        "description": description,
        "reference_id": None,
        # Fixed-width exports commonly use 0.00 for the unused direction.
        # Normalize that placeholder to None so the same exactly-one-direction
        # proof applies as it does to an empty pipe-delimited cell.
        "withdrawal": withdrawal_value if withdrawal_value else None,
        "deposit": deposit_value if deposit_value else None,
        "balance_after": values[header.balance_index],
    }


def _account_last4(text: str) -> str | None:
    match = re.search(
        r"(?:ACCOUNT|A/C)\s*(?:NO\.?|NUMBER)?\s*[:\-]?\s*([X*]+)(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    return match.group(2) if match else None


def _statement_period(text: str) -> tuple[date, date] | None:
    match = re.search(
        r"(?:STATEMENT\s+PERIOD|PERIOD|DATE\s+RANGE)\s*[:\-]?\s*"
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
    if start > end:
        raise ValueError("Generic bank statement period is invalid")
    return start, end


def _opening_balance(text: str) -> Decimal | None:
    match = re.search(
        r"OPENING\s+BALANCE\s*[:\-]?\s*((?:INR|USD|EUR|GBP|RS\.?)?\s*[\d,]+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    return _money(match.group(1)) if match else None


def _source_currency(text: str) -> str | None:
    match = re.search(r"\b(INR|USD|EUR|GBP)\b", text.upper())
    return match.group(1) if match else None


def _column_position(text: str, labels: tuple[str, ...]) -> int | None:
    positions = [text.find(label) for label in labels if text.find(label) >= 0]
    return min(positions) if positions else None


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
        raise ValueError("Generic bank statement contains an invalid amount") from exc
    if negative:
        amount = -amount
    if amount < 0:
        raise ValueError("Generic bank statement balances and amounts cannot be negative")
    return amount


def _optional_money(value: str) -> Decimal | None:
    normalized = value.strip()
    return _money(normalized) if normalized not in {"", "-", "—"} else None
