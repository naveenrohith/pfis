"""Read-only refund lifecycle evidence for credit-card workspaces."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.schemas.financial_position import (
    CardRefundTrackerResponse,
    CardStatementProjectionEvidence,
)
from app.services.transaction_aggregates import (
    is_pending_transaction_status,
    is_settled_transaction_status,
)

RULESET_VERSION = "pfis-card-refund-tracker-1"
REFUND_LOOKBACK_DAYS = 90
_MONEY = Decimal("0.01")
RefundTrackerStatus = Literal["clear", "pending", "needs_review"]


def build_card_refund_tracker(
    *,
    as_of: date,
    refunds: list[tuple[date, Decimal, str, str]],
) -> CardRefundTrackerResponse:
    """Summarize explicit card refund rows without inferring missing refunds.

    Each row is ``(transaction_date, amount, transaction_status,
    review_outcome)``. Pending rows remain visible even when older than the
    posted-refund lookback; posted totals are intentionally limited to the
    latest 90 days so a lifetime total cannot masquerade as current relief.
    Rows ignored by a user/rule are excluded from the tracker.
    """

    posted_cutoff = as_of - timedelta(days=REFUND_LOOKBACK_DAYS - 1)
    pending_rows: list[tuple[date, Decimal]] = []
    posted_rows: list[tuple[date, Decimal]] = []
    review_rows: list[tuple[date, Decimal]] = []
    for refund_date, amount, transaction_status, review_outcome in refunds:
        if amount <= 0 or review_outcome == "ignored_by_rule":
            continue
        if is_pending_transaction_status(transaction_status):
            pending_rows.append((refund_date, amount))
        elif is_settled_transaction_status(transaction_status):
            if refund_date >= posted_cutoff:
                posted_rows.append((refund_date, amount))
        else:
            review_rows.append((refund_date, amount))

    pending_amount = sum((amount for _, amount in pending_rows), Decimal("0"))
    posted_amount = sum((amount for _, amount in posted_rows), Decimal("0"))
    status: RefundTrackerStatus
    if review_rows:
        status = "needs_review"
    elif pending_rows:
        status = "pending"
    else:
        status = "clear"

    reason_codes: list[str] = []
    evidence: list[CardStatementProjectionEvidence] = []
    if pending_rows:
        reason_codes.append("pending_refunds")
        evidence.append(
            CardStatementProjectionEvidence(
                label="Pending refund evidence",
                value=(
                    f"{len(pending_rows)} row(s) · "
                    f"{pending_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)}"
                ),
                basis="Explicit card refund rows with a pending transaction lifecycle; credit restoration is not issuer-confirmed.",
            )
        )
    else:
        reason_codes.append("no_pending_refunds")
    if posted_rows:
        reason_codes.append("posted_refunds_last_90_days")
        evidence.append(
            CardStatementProjectionEvidence(
                label="Posted refunds (last 90 days)",
                value=(
                    f"{len(posted_rows)} row(s) · "
                    f"{posted_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)}"
                ),
                basis="Settled card refund rows dated inside the bounded lookback window.",
            )
        )
    if review_rows:
        reason_codes.append("refund_lifecycle_review_required")
        review_amount = sum((amount for _, amount in review_rows), Decimal("0"))
        evidence.append(
            CardStatementProjectionEvidence(
                label="Refund rows needing review",
                value=(
                    f"{len(review_rows)} row(s) · "
                    f"{review_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)}"
                ),
                basis="Refund evidence has neither a settled nor a recognized pending lifecycle.",
            )
        )

    return CardRefundTrackerResponse(
        status=status,
        as_of=as_of,
        horizon_days=REFUND_LOOKBACK_DAYS,
        pending_count=len(pending_rows),
        pending_amount=float(pending_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)),
        oldest_pending_date=min((item[0] for item in pending_rows), default=None),
        posted_count_90d=len(posted_rows),
        posted_amount_90d=float(posted_amount.quantize(_MONEY, rounding=ROUND_HALF_UP)),
        needs_review_count=len(review_rows),
        reason_codes=reason_codes,
        evidence=evidence,
        ruleset_version=RULESET_VERSION,
    )
