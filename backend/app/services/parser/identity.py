"""Transaction identity helpers for duplicate detection and observability."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class IdentityResult:
    level: str
    fingerprint: str
    reference_key: str | None = None
    fuzzy_key: str | None = None


def build_identity(
    *,
    user_id: str,
    amount: float,
    transaction_date: date,
    merchant: str | None,
    reference_id: str | None,
    account_last4: str | None,
) -> IdentityResult:
    """Build duplicate identity metadata while preserving current fingerprint logic."""
    stable_merchant = (merchant or "unknown").lower().strip()
    raw = "|".join(
        [
            user_id,
            str(amount),
            str(transaction_date),
            stable_merchant,
            reference_id or "",
            account_last4 or "",
        ]
    )
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()
    if reference_id:
        return IdentityResult(
            level="reference",
            fingerprint=fingerprint,
            reference_key=f"{user_id}|{reference_id}|{account_last4 or ''}",
        )
    fuzzy_key = f"{user_id}|{transaction_date}|{round(amount, 2)}|{stable_merchant[:18]}"
    return IdentityResult(level="fingerprint", fingerprint=fingerprint, fuzzy_key=fuzzy_key)
