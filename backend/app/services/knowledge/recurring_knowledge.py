"""Central recurring-stream detection with cadence, lifecycle, and evidence."""

from __future__ import annotations

import calendar
import hashlib
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction
from app.services.financial_clock import user_financial_today
from app.services.knowledge.contracts import (
    DataSufficiency,
    EvidenceReference,
    SignalEnvelope,
    SignalStatus,
)
from app.services.knowledge.ruleset_registry import RECURRING_PATTERN
from app.services.transaction_aggregates import debit_event_predicate

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
    amount_low: float
    amount_high: float
    monthly_equivalent: float
    cadence: str | None
    median_interval_days: float | None
    cadence_confidence: float
    amount_confidence: float
    confidence: float
    status: str
    last_seen: date
    next_expected_date: date | None
    next_expected_date_low: date | None
    next_expected_date_high: date | None
    data_sufficiency: str
    financial_account_id: str | None = None
    currency: str = "INR"
    stream_key: str = ""
    source_transaction_ids: tuple[str, ...] = field(default_factory=tuple)
    ruleset_version: str = RECURRING_PATTERN.version

    @property
    def is_consistent(self) -> bool:
        return self.amount_confidence >= 0.65

    def as_dict(self) -> dict:
        evidence = (
            EvidenceReference("Occurrences", str(self.occurrences)),
            EvidenceReference("Cadence", self.cadence or "Irregular"),
            EvidenceReference("Last observed", self.last_seen.isoformat()),
            EvidenceReference(
                "Observed amount band",
                f"{self.amount_low:.2f}–{self.amount_high:.2f}",
            ),
            EvidenceReference(
                "Expected date window",
                (
                    f"{self.next_expected_date_low.isoformat()}–"
                    f"{self.next_expected_date_high.isoformat()}"
                    if self.next_expected_date_low and self.next_expected_date_high
                    else "Not available"
                ),
            ),
        )
        signal = SignalEnvelope(
            kind="recurring_pattern",
            status=SignalStatus.CALCULATED,
            value={
                "lifecycle": self.status,
                "cadence": self.cadence,
                "monthly_equivalent": self.monthly_equivalent,
                "amount_low": self.amount_low,
                "amount_high": self.amount_high,
                "next_expected_date_low": (
                    self.next_expected_date_low.isoformat()
                    if self.next_expected_date_low
                    else None
                ),
                "next_expected_date_high": (
                    self.next_expected_date_high.isoformat()
                    if self.next_expected_date_high
                    else None
                ),
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
            "amount_low": self.amount_low,
            "amount_high": self.amount_high,
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
            "next_expected_date_low": (
                self.next_expected_date_low.isoformat()
                if self.next_expected_date_low
                else None
            ),
            "next_expected_date_high": (
                self.next_expected_date_high.isoformat()
                if self.next_expected_date_high
                else None
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

    async def analyze(
        self,
        user_id: str,
        *,
        as_of: date | None = None,
        financial_account_id: str | None = None,
    ) -> list[RecurringPattern]:
        as_of = as_of or await user_financial_today(self.db, user_id)
        query = select(
            Transaction.merchant_normalized,
            Transaction.merchant_raw,
            Transaction.id,
            Transaction.amount,
            Transaction.transaction_date,
            Transaction.financial_account_id,
            Transaction.currency,
        ).where(
            Transaction.user_id == user_id,
            debit_event_predicate(),
            Transaction.transaction_date <= as_of,
        )
        if financial_account_id is not None:
            query = query.where(Transaction.financial_account_id == financial_account_id)
        result = await self.db.execute(query.order_by(Transaction.transaction_date.asc()))

        groups: dict[tuple[str, str, str], list[tuple[date, float]]] = defaultdict(list)
        source_ids: dict[tuple[str, str, str], list[str]] = defaultdict(list)
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
            source_ids[key].append(row.id)

        patterns = [
            pattern
            for key, entries in groups.items()
            if (
                pattern := self._analyze_group(
                    display_names[key],
                    entries,
                    as_of,
                    financial_account_id=None if key[0] == "unassigned" else key[0],
                    currency=key[2],
                    source_transaction_ids=tuple(source_ids[key]),
                )
            )
            is not None
        ]
        patterns.sort(key=lambda item: (item.status != "mature", -item.monthly_equivalent))
        return patterns

    @staticmethod
    def _analyze_group(
        merchant: str,
        entries: list[tuple[date, float]],
        as_of: date,
        *,
        financial_account_id: str | None = None,
        currency: str = "INR",
        source_transaction_ids: tuple[str, ...] = (),
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
        average_amount = statistics.mean(amounts)
        # Two observations can identify a cadence, but are not enough to
        # publish amount drift. Once three settled observations exist, retain
        # the observed min/max while bounding the envelope to 50–150% of the
        # central average. This keeps an outlier from dominating a forecast
        # while still surfacing real bill movement.
        if len(amounts) >= 3 and average_amount > 0:
            amount_low = max(min(amounts), average_amount * 0.50)
            amount_high = min(max(amounts), average_amount * 1.50)
        else:
            amount_low = average_amount
            amount_high = average_amount
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
            next_expected = RecurringPatternService._advance_expected_date(
                dates[-1],
                cadence,
                median_interval,
            )
            cycles_late = (as_of - dates[-1]).days / max(median_interval, 1)
            if cycles_late > 3:
                status = "inactive"
                next_expected = None
            elif cycles_late > 1.6:
                status = "missed"

        next_expected_low = next_expected
        next_expected_high = next_expected
        if next_expected is not None and len(entries) >= 3:
            interval_mad = float(
                statistics.median(abs(value - median_interval) for value in positive_intervals)
            )
            window_days = max(0, round(interval_mad))
            next_expected_low = next_expected - timedelta(days=window_days)
            next_expected_high = next_expected + timedelta(days=window_days)

        monthly_equivalent = statistics.mean(amounts) * 30.4375 / median_interval
        sufficiency = (
            DataSufficiency.HIGH.value
            if len(entries) >= 4 and confidence >= 0.8
            else DataSufficiency.MEDIUM.value if len(entries) >= 3 else DataSufficiency.LOW.value
        )
        return RecurringPattern(
            merchant=merchant,
            occurrences=len(entries),
            avg_amount=round(average_amount, 2),
            amount_low=round(amount_low, 2),
            amount_high=round(amount_high, 2),
            monthly_equivalent=round(monthly_equivalent, 2),
            cadence=cadence,
            median_interval_days=round(median_interval, 1),
            cadence_confidence=round(cadence_confidence, 2),
            amount_confidence=round(amount_confidence, 2),
            confidence=confidence,
            status=status,
            last_seen=dates[-1],
            next_expected_date=next_expected,
            next_expected_date_low=next_expected_low,
            next_expected_date_high=next_expected_high,
            data_sufficiency=sufficiency,
            financial_account_id=financial_account_id,
            currency=currency,
            stream_key=hashlib.sha256(
                f"{financial_account_id or 'unassigned'}|{merchant.casefold()}|{currency}".encode()
            ).hexdigest()[:24],
            source_transaction_ids=source_transaction_ids,
        )

    @staticmethod
    def _advance_expected_date(anchor: date, cadence: str, median_interval: float) -> date:
        """Advance a recurring stream without drifting across month ends."""

        if cadence in {"weekly", "fortnightly"}:
            return anchor + timedelta(days=round(median_interval))
        months = {"monthly": 1, "quarterly": 3, "annual": 12}.get(cadence)
        if months is None:
            return anchor + timedelta(days=round(median_interval))
        absolute_month = anchor.year * 12 + anchor.month - 1 + months
        year, month_index = divmod(absolute_month, 12)
        month = month_index + 1
        day = min(anchor.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

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
