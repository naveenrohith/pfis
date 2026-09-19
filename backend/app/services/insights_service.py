"""
Insights Service — Phase 5
Generates auto-computed financial intelligence from transaction data.

Insight Types:
1. Category spending percentages + top category
2. Top merchant identification
3. Month-over-month spending trend comparison
4. Recurring payment detection (same merchant + similar amount + regular interval)
5. Spending anomaly detection (daily spikes plus category/merchant baselines)
6. Daily spending trend data (for line chart)
7. Savings rate computation
"""

import logging
import statistics
from calendar import monthrange
from datetime import date
from typing import Literal, cast

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.transaction import Transaction
from app.schemas.intelligence import DataSufficiency, EvidenceItem, SpendingAnomaly
from app.services.anomaly_adjudication_service import AnomalyAdjudicationService
from app.services.financial_clock import user_financial_today
from app.services.knowledge.recurring_knowledge import RecurringPattern, RecurringPatternService
from app.services.transaction_aggregates import (
    financial_activity_predicate,
    income_effect_expression,
    spend_effect_expression,
    spend_event_predicate,
)

logger = logging.getLogger(__name__)

ANOMALY_RULESET_VERSION = "pfis-anomaly-2"
ANOMALY_HISTORY_MONTHS = 24
ANOMALY_MIN_HISTORY_PERIODS = 3
ANOMALY_MIN_CURRENT_AMOUNT = 50.0
ANOMALY_MIN_DELTA = 100.0
ANOMALY_MIN_RELATIVE_DELTA = 0.25
ANOMALY_ROBUST_SCORE = 3.5


def _shift_month(month: int, year: int, offset: int) -> tuple[int, int]:
    """Shift a calendar month without relying on server-local dates."""
    absolute = year * 12 + month - 1 + offset
    shifted_year, shifted_month = divmod(absolute, 12)
    return shifted_month + 1, shifted_year


class InsightsService:
    """Generates auto-computed financial intelligence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def anomalies_for_period(
        self, user_id: str, month: int, year: int
    ) -> list[SpendingAnomaly]:
        """Return the server-derived anomaly set used for adjudication."""

        return await self._anomaly_candidates(user_id, month, year)

    async def anomaly_samples_for_period(
        self, user_id: str, month: int, year: int, *, limit: int = 4
    ) -> list[SpendingAnomaly]:
        """Return bounded non-alert samples for balanced anomaly evaluation."""

        candidates = await self._anomaly_candidates(user_id, month, year, include_non_alert=True)
        samples = [candidate for candidate in candidates if not candidate.predicted_alert]
        adjudications = await AnomalyAdjudicationService(self.db).latest_for(
            user_id, [sample.id for sample in samples]
        )
        for sample in samples:
            adjudication = adjudications.get(sample.id)
            if adjudication:
                sample.adjudication = adjudication.decision
                sample.adjudication_note = adjudication.note
        return samples[:limit]

    async def generate_insights(
        self,
        user_id: str,
        month: int,
        year: int,
        *,
        recurring_patterns: list[RecurringPattern] | None = None,
    ) -> dict:
        """
        Generate all insights for a user's given month.
        Returns a dict with insight cards, trend data, and recurring items.
        """
        insights = []

        # --- Gather data sequentially (AsyncSession is not safe for concurrent use) ---
        prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)

        current = await self._monthly_aggregates(user_id, month, year)
        current_spend = current["spend"]
        current_income = current["income"]
        avg_confidence = current["avg_confidence"]
        categories = await self._category_breakdown(user_id, month, year)
        top_merchants = await self._top_merchants(user_id, month, year)
        daily_trend = await self._daily_spending_trend(user_id, month, year)
        period_end = date(year, month, monthrange(year, month)[1])
        today = await user_financial_today(self.db, user_id)
        recurring = (
            self._recurring_payload(recurring_patterns)
            if recurring_patterns is not None
            else await self._detect_recurring(user_id, min(period_end, today))
        )
        anomalies = await self._spending_anomalies(user_id, month, year)
        adjudications = await AnomalyAdjudicationService(self.db).latest_for(
            user_id, [anomaly.id for anomaly in anomalies]
        )
        for anomaly in anomalies:
            adjudication = adjudications.get(anomaly.id)
            if adjudication:
                anomaly.adjudication = adjudication.decision
                anomaly.adjudication_note = adjudication.note
        prev = await self._monthly_aggregates(user_id, prev_month, prev_year)
        prev_spend = prev["spend"]
        prev_income = prev["income"]

        # --- Generate insight cards ---

        # 1. Top category
        if categories:
            top_cat = categories[0]
            pct = round((top_cat["total"] / current_spend * 100), 0) if current_spend > 0 else 0
            insights.append(
                {
                    "type": "top_category",
                    "icon": "🏷️",
                    "title": f"{top_cat['name']} is your biggest expense",
                    "description": f"You spent ₹{top_cat['total']:,.0f} on {top_cat['name']} — {pct:.0f}% of total spending.",
                    "severity": "info",
                }
            )

        # 2. Top merchant
        if top_merchants:
            top_m = top_merchants[0]
            insights.append(
                {
                    "type": "top_merchant",
                    "icon": "🏪",
                    "title": f"Most spent at {top_m['name']}",
                    "description": f"₹{top_m['total']:,.0f} across {top_m['count']} transaction{'s' if top_m['count'] > 1 else ''}.",
                    "severity": "info",
                }
            )

        # 3. Month-over-month comparison
        if prev_spend > 0 and current_spend > 0:
            change_pct = ((current_spend - prev_spend) / prev_spend) * 100
            if change_pct > 15:
                insights.append(
                    {
                        "type": "spending_trend",
                        "icon": "📈",
                        "title": f"Spending up {change_pct:.0f}% vs last month",
                        "description": f"₹{current_spend:,.0f} this month vs ₹{prev_spend:,.0f} last month. Consider reviewing your expenses.",
                        "severity": "warning",
                    }
                )
            elif change_pct < -10:
                insights.append(
                    {
                        "type": "spending_trend",
                        "icon": "📉",
                        "title": f"Spending down {abs(change_pct):.0f}% — great job!",
                        "description": f"₹{current_spend:,.0f} this month vs ₹{prev_spend:,.0f} last month.",
                        "severity": "success",
                    }
                )
            else:
                insights.append(
                    {
                        "type": "spending_trend",
                        "icon": "➡️",
                        "title": "Spending steady vs last month",
                        "description": f"₹{current_spend:,.0f} this month vs ₹{prev_spend:,.0f} last month ({change_pct:+.0f}%).",
                        "severity": "info",
                    }
                )
        elif current_spend > 0 and prev_spend == 0:
            insights.append(
                {
                    "type": "spending_trend",
                    "icon": "🆕",
                    "title": "First month of data!",
                    "description": f"Total spend: ₹{current_spend:,.0f}. Next month we'll compare trends.",
                    "severity": "info",
                }
            )

        # 4. Savings rate
        if current_income > 0:
            savings_rate = ((current_income - current_spend) / current_income) * 100
            if savings_rate >= 30:
                insights.append(
                    {
                        "type": "savings_rate",
                        "icon": "💰",
                        "title": f"Excellent savings rate: {savings_rate:.0f}%",
                        "description": f"You saved ₹{current_income - current_spend:,.0f} out of ₹{current_income:,.0f} income.",
                        "severity": "success",
                    }
                )
            elif savings_rate >= 10:
                insights.append(
                    {
                        "type": "savings_rate",
                        "icon": "💵",
                        "title": f"Savings rate: {savings_rate:.0f}%",
                        "description": f"You saved ₹{current_income - current_spend:,.0f}. Target 30%+ for financial health.",
                        "severity": "info",
                    }
                )
            elif savings_rate >= 0:
                insights.append(
                    {
                        "type": "savings_rate",
                        "icon": "⚠️",
                        "title": f"Low savings rate: {savings_rate:.0f}%",
                        "description": f"Only ₹{current_income - current_spend:,.0f} saved. Review non-essential spending.",
                        "severity": "warning",
                    }
                )
            else:
                insights.append(
                    {
                        "type": "savings_rate",
                        "icon": "🚨",
                        "title": "Spending exceeds income!",
                        "description": f"You spent ₹{current_spend - current_income:,.0f} more than you earned.",
                        "severity": "danger",
                    }
                )

        # 5. Recurring payments
        if recurring:
            total_recurring = sum(r["avg_amount"] for r in recurring)
            insights.append(
                {
                    "type": "recurring",
                    "icon": "🔁",
                    "title": f"{len(recurring)} recurring payment{'s' if len(recurring) > 1 else ''} detected",
                    "description": f"Estimated ₹{total_recurring:,.0f}/month in subscriptions and recurring charges.",
                    "severity": "info",
                }
            )

        # 6. High-spend day detection
        if daily_trend:
            amounts = [d["total"] for d in daily_trend if d["total"] > 0]
            if len(amounts) >= 3:
                median_daily = statistics.median(amounts)
                mad = statistics.median(abs(amount - median_daily) for amount in amounts)
                max_day = max(daily_trend, key=lambda d: d["total"])
                robust_score = (
                    0.6745 * (max_day["total"] - median_daily) / mad
                    if mad > 0
                    else max_day["total"] / max(median_daily, 1)
                )
                if robust_score > 3.5 and max_day["total"] > 500:
                    insights.append(
                        {
                            "type": "anomaly",
                            "icon": "🔍",
                            "title": f"Spending spike on {max_day['date']}",
                            "description": f"₹{max_day['total']:,.0f} spent — materially above your typical active day of ₹{median_daily:,.0f}. Review it if unexpected.",
                            "severity": "warning",
                        }
                    )

        # 7. Category and merchant baseline departures
        for anomaly in anomalies[:4]:
            insights.append(
                {
                    "type": "baseline_anomaly",
                    "icon": "📈",
                    "title": f"{anomaly.label} is above its usual range",
                    "description": (
                        f"{anomaly.current_amount:,.0f} this month vs "
                        f"{anomaly.baseline_amount:,.0f} typical ({anomaly.delta_pct:.0f}% higher)."
                    ),
                    "severity": anomaly.severity,
                }
            )

        # 8. Average parse confidence
        if avg_confidence is not None and avg_confidence < 0.8:
            insights.append(
                {
                    "type": "quality",
                    "icon": "🎯",
                    "title": f"Parse accuracy: {avg_confidence * 100:.0f}%",
                    "description": "Some transactions may need review. Check items with ⚠️ badges.",
                    "severity": "warning",
                }
            )

        # 9. Category diversity
        if len(categories) >= 4:
            # Check if top category is > 50% — low diversification
            top_pct = categories[0]["total"] / current_spend * 100 if current_spend > 0 else 0
            if top_pct > 50:
                insights.append(
                    {
                        "type": "diversification",
                        "icon": "📊",
                        "title": f"{categories[0]['name']} dominates at {top_pct:.0f}%",
                        "description": "Over half your spending is in one category. Consider diversifying.",
                        "severity": "info",
                    }
                )

        return {
            "insights": insights,
            "daily_trend": daily_trend,
            "recurring_payments": recurring,
            "meta": {
                "month": f"{year}-{month:02d}",
                "total_spend": current_spend,
                "total_income": current_income,
                "prev_spend": prev_spend,
                "prev_income": prev_income,
                "anomaly_count": len(anomalies),
                "insight_count": len(insights),
            },
            "anomalies": [anomaly.model_dump() for anomaly in anomalies],
        }

    # ──────────────────────────────────────────
    # Data queries
    # ──────────────────────────────────────────

    async def _monthly_aggregates(self, user_id: str, month: int, year: int) -> dict:
        """Spend, income, and average confidence for a month in a single query.

        Combines what were previously three separate round-trips (debit total,
        credit total, average confidence) using conditional aggregation. The
        per-field results are identical to the original separate queries.
        """
        result = await self.db.execute(
            select(
                func.coalesce(
                    func.sum(spend_effect_expression()),
                    0,
                ).label("spend"),
                func.coalesce(
                    func.sum(income_effect_expression()),
                    0,
                ).label("income"),
                func.avg(Transaction.confidence_score).label("avg_confidence"),
            ).where(
                Transaction.user_id == user_id,
                financial_activity_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        row = result.one()
        return {
            "spend": float(row.spend),
            "income": float(row.income),
            "avg_confidence": (
                float(row.avg_confidence) if row.avg_confidence is not None else None
            ),
        }

    async def _category_breakdown(self, user_id: str, month: int, year: int) -> list[dict]:
        result = await self.db.execute(
            select(
                Category.name,
                Category.icon,
                func.sum(spend_effect_expression()).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Category.name, Category.icon)
            .having(func.sum(spend_effect_expression()) > 0)
            .order_by(func.sum(spend_effect_expression()).desc())
        )
        return [
            {
                "name": row.name or "Uncategorized",
                "icon": row.icon or "📦",
                "total": float(row.total),
                "count": row.count,
            }
            for row in result.all()
        ]

    async def _top_merchants(self, user_id: str, month: int, year: int) -> list[dict]:
        result = await self.db.execute(
            select(
                Transaction.merchant_normalized,
                func.sum(spend_effect_expression()).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.merchant_normalized)
            .having(func.sum(spend_effect_expression()) > 0)
            .order_by(func.sum(spend_effect_expression()).desc())
            .limit(5)
        )
        return [
            {
                "name": row.merchant_normalized or "Unknown",
                "total": float(row.total),
                "count": row.count,
            }
            for row in result.all()
        ]

    async def _daily_spending_trend(self, user_id: str, month: int, year: int) -> list[dict]:
        """Returns daily spend totals for the given month — data for line chart."""
        result = await self.db.execute(
            select(
                Transaction.transaction_date,
                func.sum(spend_effect_expression()).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.transaction_date)
            .order_by(Transaction.transaction_date.asc())
        )

        # Build a full-month array with zeros for days without transactions
        import calendar

        days_in_month = calendar.monthrange(year, month)[1]
        daily_map = {}
        for row in result.all():
            d = row.transaction_date
            daily_map[d.day] = {"total": float(row.total), "count": row.count}

        trend = []
        today = await user_financial_today(self.db, user_id)
        for day in range(1, days_in_month + 1):
            d = date(year, month, day)
            if d > today:
                break  # Don't include future dates
            entry = daily_map.get(day, {"total": 0, "count": 0})
            trend.append(
                {
                    "date": d.strftime("%d %b"),
                    "day": day,
                    "total": entry["total"],
                    "count": entry["count"],
                }
            )

        return trend

    async def _anomaly_candidates(
        self,
        user_id: str,
        month: int,
        year: int,
        *,
        include_non_alert: bool = False,
    ) -> list[SpendingAnomaly]:
        """Build alert and reviewable non-alert candidates from the same baseline."""

        history_months = [
            _shift_month(month, year, offset) for offset in range(-ANOMALY_HISTORY_MONTHS, 0)
        ]
        history_start = date(history_months[0][1], history_months[0][0], 1)
        current_end = date(year, month, monthrange(year, month)[1])
        result = await self.db.execute(
            select(
                Transaction.transaction_date,
                spend_effect_expression().label("spend_amount"),
                Transaction.merchant_normalized,
                Transaction.merchant_raw,
                Category.name.label("category_name"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                Transaction.transaction_date >= history_start,
                Transaction.transaction_date <= current_end,
            )
        )

        # (kind, label) -> month -> (amount, count)
        monthly: dict[tuple[str, str], dict[tuple[int, int], list[float]]] = {}
        for row in result.all():
            label_category = (row.category_name or "Uncategorized").strip() or "Uncategorized"
            label_merchant = (
                row.merchant_normalized or row.merchant_raw or "Unknown"
            ).strip() or "Unknown"
            key_month = (row.transaction_date.year, row.transaction_date.month)
            amount = float(row.spend_amount or 0)
            for key in (("category", label_category), ("merchant", label_merchant)):
                bucket = monthly.setdefault(key, {}).setdefault(key_month, [0.0, 0.0])
                bucket[0] += amount
                bucket[1] += 1

        current_key = (year, month)
        candidates: list[SpendingAnomaly] = []
        for (kind, label), values in monthly.items():
            current_amount, current_count = values.get(current_key, [0.0, 0.0])
            if current_amount < ANOMALY_MIN_CURRENT_AMOUNT:
                continue
            history_values = [values.get(period, [0.0, 0.0])[0] for period in history_months]
            observed_history = [value for value in history_values if value > 0]
            if len(observed_history) < ANOMALY_MIN_HISTORY_PERIODS:
                continue
            same_calendar_month_history = [
                values.get(period, [0.0, 0.0])[0]
                for period in history_months
                if period[0] == month and values.get(period, [0.0, 0.0])[0] > 0
            ]
            baseline_values = (
                same_calendar_month_history
                if len(same_calendar_month_history) >= 2
                else observed_history
            )
            baseline_method = (
                "same_calendar_month"
                if len(same_calendar_month_history) >= 2
                else "rolling_non_zero"
            )
            baseline = statistics.median(baseline_values)
            delta = current_amount - baseline
            mad = statistics.median(abs(value - baseline) for value in baseline_values)
            robust_score = (
                0.6745 * delta / mad
                if mad > 0
                else delta / max(baseline, ANOMALY_MIN_CURRENT_AMOUNT)
            )
            delta_pct = delta / baseline * 100 if baseline else 0.0
            is_alert = (
                delta > 0
                and delta >= max(ANOMALY_MIN_DELTA, baseline * ANOMALY_MIN_RELATIVE_DELTA)
                and (robust_score >= ANOMALY_ROBUST_SCORE or delta_pct >= 50)
            )
            if not is_alert and not include_non_alert:
                continue
            confidence = min(
                0.95 if is_alert else 0.9,
                0.45
                + min(len(baseline_values), ANOMALY_HISTORY_MONTHS) * 0.06
                + min(max(robust_score, 0.0), 5.0) * 0.04,
            )
            data_sufficiency = cast(
                DataSufficiency, "high" if len(baseline_values) >= 5 else "medium"
            )
            anomaly_kind = cast(Literal["category", "merchant"], kind)
            anomaly_id = (
                f"{kind}:{label.casefold()}:{year:04d}-{month:02d}"
                if is_alert
                else f"sample:{kind}:{label.casefold()}:{year:04d}-{month:02d}"
            )
            positive_delta = max(delta, 0.0)
            positive_delta_pct = max(delta_pct, 0.0)
            candidates.append(
                SpendingAnomaly(
                    id=anomaly_id,
                    kind=anomaly_kind,
                    predicted_alert=is_alert,
                    label=label,
                    current_amount=round(current_amount, 2),
                    baseline_amount=round(baseline, 2),
                    delta_amount=round(positive_delta, 2),
                    delta_pct=round(positive_delta_pct, 1),
                    robust_score=round(max(robust_score, 0.0), 2),
                    history_periods=len(observed_history),
                    transaction_count=int(current_count),
                    confidence=round(confidence, 3),
                    data_sufficiency=data_sufficiency,
                    evidence=[
                        EvidenceItem(label="Current month", value=f"{current_amount:,.2f}"),
                        EvidenceItem(
                            label="Baseline",
                            value=f"{baseline:,.2f} ({baseline_method.replace('_', ' ')})",
                        ),
                        EvidenceItem(
                            label="Observed history", value=f"{len(observed_history)} months"
                        ),
                        EvidenceItem(
                            label="Baseline sample", value=f"{len(baseline_values)} months"
                        ),
                    ],
                    assumptions=[
                        (
                            "Baseline uses the median of repeated same-calendar-month observations."
                            if baseline_method == "same_calendar_month"
                            else "Baseline uses the median of non-zero observed months because repeated same-calendar-month history is insufficient."
                        ),
                        "Refunds reduce spend and transfers/bookkeeping are excluded.",
                        (
                            "A departure is a review signal, not proof of fraud or an error."
                            if is_alert
                            else "PFIS did not raise an alert under the current materiality thresholds."
                        ),
                    ],
                    severity="warning" if is_alert else "info",
                    ruleset_version=ANOMALY_RULESET_VERSION,
                )
            )

        candidates.sort(
            key=lambda item: (
                -int(item.predicted_alert),
                -item.delta_amount if item.predicted_alert else -item.current_amount,
                item.kind,
                item.label.casefold(),
            )
        )
        if not include_non_alert:
            return candidates[:8]
        alerts = [candidate for candidate in candidates if candidate.predicted_alert]
        non_alerts = [candidate for candidate in candidates if not candidate.predicted_alert]
        return [*alerts[:8], *non_alerts[:8]]

    async def _spending_anomalies(
        self, user_id: str, month: int, year: int
    ) -> list[SpendingAnomaly]:
        """Find material category/merchant departures from six months of history."""

        return await self._anomaly_candidates(user_id, month, year)

    async def _detect_recurring(self, user_id: str, as_of: date | None = None) -> list[dict]:
        """Return the shared recurring-stream read model for all PFIS surfaces."""
        patterns = await RecurringPatternService(self.db).analyze(user_id, as_of=as_of)
        return self._recurring_payload(patterns)

    @staticmethod
    def _recurring_payload(patterns: list[RecurringPattern]) -> list[dict]:
        return [
            pattern.as_dict()
            for pattern in patterns
            if pattern.status in {"early", "mature", "missed"}
        ]
