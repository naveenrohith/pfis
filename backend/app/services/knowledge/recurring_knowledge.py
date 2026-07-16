"""Central recurring-stream detection with cadence, lifecycle, and evidence."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionType
from app.services.knowledge.contracts import (
    DataSufficiency,
    EvidenceReference,
    SignalEnvelope,
    SignalStatus,
)
from app.services.knowledge.ruleset_registry import RECURRING_PATTERN

_CADENCES: tuple[tuple[str, float, float], ...] = (
    ("weekly", 7.0, 3.0),
    ("fortnightly", 14.0, 5.0),
    ("monthly", 30.4375, 9.0),
    ("quarterly", 91.3125, 18.0),
    ("annual", 365.25, 45.0),
)


@dataclass(frozen=True, slots=True)
class RecurringPattern:
    merchant: str
    occurrences: int
    avg_amount: float
    monthly_equivalent: float
    cadence: str | None
    median_interval_days: float | None
    cadence_confidence: float
    amount_confidence: float
    confidence: float
    status: str
    last_seen: date
    next_expected_date: date | None
    data_sufficiency: str
    ruleset_version: str = RECURRING_PATTERN.version

    @property
    def is_consistent(self) -> bool:
        return self.amount_confidence >= 0.65

    def as_dict(self) -> dict:
        evidence = (
            EvidenceReference("Occurrences", str(self.occurrences)),
            EvidenceReference("Cadence", self.cadence or "Irregular"),
            EvidenceReference("Last observed", self.last_seen.isoformat()),
        )
        signal = SignalEnvelope(
            kind="recurring_pattern",
            status=SignalStatus.CALCULATED,
            value={
                "lifecycle": self.status,
                "cadence": self.cadence,
                "monthly_equivalent": self.monthly_equivalent,
            },
            confidence=self.confidence,
            data_sufficiency=DataSufficiency(self.data_sufficiency),
            sample_size=self.occurrences,
            ruleset=RECURRING_PATTERN,
            evidence=evidence,
            assumptions=(
                "A recurring stream requires a recognizable time interval.",
                "Expected dates are estimates, not confirmed payment instructions.",
            ),
            data_through=self.last_seen,
        )
        return {
            "merchant": self.merchant,
            "occurrences": self.occurrences,
            "avg_amount": self.avg_amount,
            "monthly_equivalent": self.monthly_equivalent,
            "is_consistent": self.is_consistent,
            "cadence": self.cadence,
            "median_interval_days": self.median_interval_days,
            "cadence_confidence": self.cadence_confidence,
            "amount_confidence": self.amount_confidence,
            "confidence": self.confidence,
            "status": self.status,
            "last_seen": self.last_seen.isoformat(),
            "next_expected_date": (
                self.next_expected_date.isoformat() if self.next_expected_date else None
            ),
            "data_sufficiency": self.data_sufficiency,
            "ruleset_version": self.ruleset_version,
            "evidence": [{"label": item.label, "value": item.value} for item in evidence],
            "signal": signal.as_dict(),
        }


class RecurringPatternService:
    """Derive user-owned recurring streams from normalized ledger entries."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze(self, user_id: str, *, as_of: date | None = None) -> list[RecurringPattern]:
        as_of = as_of or date.today()
        result = await self.db.execute(
            select(
                Transaction.merchant_normalized,
                Transaction.merchant_raw,
                Transaction.amount,
                Transaction.transaction_date,
                Transaction.financial_account_id,
                Transaction.currency,
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
                Transaction.transaction_date <= as_of,
            )
            .order_by(Transaction.transaction_date.asc())
        )

        groups: dict[tuple[str, str, str], list[tuple[date, float]]] = defaultdict(list)
        display_names: dict[tuple[str, str, str], str] = {}
        for row in result.all():
            merchant = (row.merchant_normalized or row.merchant_raw or "").strip()
            if not merchant:
                continue
            key = (
                (row.financial_account_id or "unassigned"),
                merchant.casefold(),
                row.currency or "INR",
            )
            display_names[key] = merchant
            groups[key].append((row.transaction_date, float(row.amount)))

        patterns = [
            pattern
            for key, entries in groups.items()
            if (pattern := self._analyze_group(display_names[key], entries, as_of)) is not None
        ]
        patterns.sort(key=lambda item: (item.status != "mature", -item.monthly_equivalent))
        return patterns

    @staticmethod
    def _analyze_group(
        merchant: str, entries: list[tuple[date, float]], as_of: date
    ) -> RecurringPattern | None:
        if len(entries) < 2:
            return None

        dates = [entry[0] for entry in entries]
        amounts = [entry[1] for entry in entries]
        intervals = [
            (later - earlier).days for earlier, later in zip(dates, dates[1:], strict=False)
        ]
        positive_intervals = [value for value in intervals if value > 0]
        if not positive_intervals:
            return None

        median_interval = float(statistics.median(positive_intervals))
        cadence, cadence_confidence = RecurringPatternService._cadence(median_interval, intervals)
        amount_median = float(statistics.median(amounts))
        amount_mad = float(statistics.median(abs(value - amount_median) for value in amounts))
        relative_amount_mad = amount_mad / amount_median if amount_median > 0 else 1.0
        amount_confidence = max(0.0, min(1.0, 1.0 - relative_amount_mad / 0.35))
        sample_confidence = min(1.0, (len(entries) - 1) / 3)
        confidence = round(
            cadence_confidence * 0.6 + amount_confidence * 0.25 + sample_confidence * 0.15,
            2,
        )

        status = "candidate"
        if cadence and len(entries) >= 3 and confidence >= 0.7:
            status = "mature"
        elif cadence and confidence >= 0.55:
            status = "early"

        next_expected = None
        if cadence and status in {"early", "mature"}:
            next_expected = dates[-1] + timedelta(days=round(median_interval))
            cycles_late = (as_of - dates[-1]).days / max(median_interval, 1)
            if cycles_late > 3:
                status = "inactive"
                next_expected = None
            elif cycles_late > 1.6:
                status = "missed"

        monthly_equivalent = statistics.mean(amounts) * 30.4375 / median_interval
        sufficiency = (
            DataSufficiency.HIGH.value
            if len(entries) >= 4 and confidence >= 0.8
            else DataSufficiency.MEDIUM.value if len(entries) >= 3 else DataSufficiency.LOW.value
        )
        return RecurringPattern(
            merchant=merchant,
            occurrences=len(entries),
            avg_amount=round(statistics.mean(amounts), 2),
            monthly_equivalent=round(monthly_equivalent, 2),
            cadence=cadence,
            median_interval_days=round(median_interval, 1),
            cadence_confidence=round(cadence_confidence, 2),
            amount_confidence=round(amount_confidence, 2),
            confidence=confidence,
            status=status,
            last_seen=dates[-1],
            next_expected_date=next_expected,
            data_sufficiency=sufficiency,
        )

    @staticmethod
    def _cadence(median_interval: float, intervals: list[int]) -> tuple[str | None, float]:
        name, target, tolerance = min(
            _CADENCES, key=lambda cadence: abs(median_interval - cadence[1])
        )
        distance = abs(median_interval - target)
        if distance > tolerance:
            return None, 0.0
        interval_mad = float(statistics.median(abs(value - median_interval) for value in intervals))
        distance_score = max(0.0, 1.0 - distance / tolerance)
        regularity_score = max(0.0, 1.0 - interval_mad / tolerance)
        if len(intervals) >= 2 and regularity_score < 0.35:
            return None, 0.0
        return name, distance_score * 0.45 + regularity_score * 0.55
