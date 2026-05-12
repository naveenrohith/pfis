"""
Insights Service — Phase 5
Generates auto-computed financial intelligence from transaction data.

Insight Types:
1. Category spending percentages + top category
2. Top merchant identification
3. Month-over-month spending trend comparison
4. Recurring payment detection (same merchant + similar amount + regular interval)
5. Spending anomaly detection (unusual spikes vs average)
6. Daily spending trend data (for line chart)
7. Savings rate computation
"""

import logging
from datetime import date, timedelta
from typing import Optional
from sqlalchemy import select, func, extract, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionType
from app.models.category import Category

logger = logging.getLogger(__name__)


class InsightsService:
    """Generates auto-computed financial intelligence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_insights(
        self, user_id: str, month: int, year: int
    ) -> dict:
        """
        Generate all insights for a user's given month.
        Returns a dict with insight cards, trend data, and recurring items.
        """
        insights = []

        # --- Gather data ---
        current_spend = await self._total_spend(user_id, month, year)
        current_income = await self._total_income(user_id, month, year)
        categories = await self._category_breakdown(user_id, month, year)
        top_merchants = await self._top_merchants(user_id, month, year)
        daily_trend = await self._daily_spending_trend(user_id, month, year)
        recurring = await self._detect_recurring(user_id)
        avg_confidence = await self._avg_confidence(user_id, month, year)

        # Previous month comparison
        prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
        prev_spend = await self._total_spend(user_id, prev_month, prev_year)
        prev_income = await self._total_income(user_id, prev_month, prev_year)

        # --- Generate insight cards ---

        # 1. Top category
        if categories:
            top_cat = categories[0]
            pct = round((top_cat["total"] / current_spend * 100), 0) if current_spend > 0 else 0
            insights.append({
                "type": "top_category",
                "icon": "🏷️",
                "title": f"{top_cat['name']} is your biggest expense",
                "description": f"You spent ₹{top_cat['total']:,.0f} on {top_cat['name']} — {pct:.0f}% of total spending.",
                "severity": "info",
            })

        # 2. Top merchant
        if top_merchants:
            top_m = top_merchants[0]
            insights.append({
                "type": "top_merchant",
                "icon": "🏪",
                "title": f"Most spent at {top_m['name']}",
                "description": f"₹{top_m['total']:,.0f} across {top_m['count']} transaction{'s' if top_m['count'] > 1 else ''}.",
                "severity": "info",
            })

        # 3. Month-over-month comparison
        if prev_spend > 0 and current_spend > 0:
            change_pct = ((current_spend - prev_spend) / prev_spend) * 100
            if change_pct > 15:
                insights.append({
                    "type": "spending_trend",
                    "icon": "📈",
                    "title": f"Spending up {change_pct:.0f}% vs last month",
                    "description": f"₹{current_spend:,.0f} this month vs ₹{prev_spend:,.0f} last month. Consider reviewing your expenses.",
                    "severity": "warning",
                })
            elif change_pct < -10:
                insights.append({
                    "type": "spending_trend",
                    "icon": "📉",
                    "title": f"Spending down {abs(change_pct):.0f}% — great job!",
                    "description": f"₹{current_spend:,.0f} this month vs ₹{prev_spend:,.0f} last month.",
                    "severity": "success",
                })
            else:
                insights.append({
                    "type": "spending_trend",
                    "icon": "➡️",
                    "title": "Spending steady vs last month",
                    "description": f"₹{current_spend:,.0f} this month vs ₹{prev_spend:,.0f} last month ({change_pct:+.0f}%).",
                    "severity": "info",
                })
        elif current_spend > 0 and prev_spend == 0:
            insights.append({
                "type": "spending_trend",
                "icon": "🆕",
                "title": "First month of data!",
                "description": f"Total spend: ₹{current_spend:,.0f}. Next month we'll compare trends.",
                "severity": "info",
            })

        # 4. Savings rate
        if current_income > 0:
            savings_rate = ((current_income - current_spend) / current_income) * 100
            if savings_rate >= 30:
                insights.append({
                    "type": "savings_rate",
                    "icon": "💰",
                    "title": f"Excellent savings rate: {savings_rate:.0f}%",
                    "description": f"You saved ₹{current_income - current_spend:,.0f} out of ₹{current_income:,.0f} income.",
                    "severity": "success",
                })
            elif savings_rate >= 10:
                insights.append({
                    "type": "savings_rate",
                    "icon": "💵",
                    "title": f"Savings rate: {savings_rate:.0f}%",
                    "description": f"You saved ₹{current_income - current_spend:,.0f}. Target 30%+ for financial health.",
                    "severity": "info",
                })
            elif savings_rate >= 0:
                insights.append({
                    "type": "savings_rate",
                    "icon": "⚠️",
                    "title": f"Low savings rate: {savings_rate:.0f}%",
                    "description": f"Only ₹{current_income - current_spend:,.0f} saved. Review non-essential spending.",
                    "severity": "warning",
                })
            else:
                insights.append({
                    "type": "savings_rate",
                    "icon": "🚨",
                    "title": "Spending exceeds income!",
                    "description": f"You spent ₹{current_spend - current_income:,.0f} more than you earned.",
                    "severity": "danger",
                })

        # 5. Recurring payments
        if recurring:
            total_recurring = sum(r["avg_amount"] for r in recurring)
            insights.append({
                "type": "recurring",
                "icon": "🔁",
                "title": f"{len(recurring)} recurring payment{'s' if len(recurring) > 1 else ''} detected",
                "description": f"Estimated ₹{total_recurring:,.0f}/month in subscriptions and recurring charges.",
                "severity": "info",
            })

        # 6. High-spend day detection
        if daily_trend:
            amounts = [d["total"] for d in daily_trend if d["total"] > 0]
            if len(amounts) >= 3:
                avg_daily = sum(amounts) / len(amounts)
                max_day = max(daily_trend, key=lambda d: d["total"])
                if max_day["total"] > avg_daily * 2.5 and max_day["total"] > 500:
                    insights.append({
                        "type": "anomaly",
                        "icon": "🔍",
                        "title": f"Spending spike on {max_day['date']}",
                        "description": f"₹{max_day['total']:,.0f} spent — {max_day['total'] / avg_daily:.1f}× your daily average of ₹{avg_daily:,.0f}.",
                        "severity": "warning",
                    })

        # 7. Average parse confidence
        if avg_confidence is not None and avg_confidence < 0.8:
            insights.append({
                "type": "quality",
                "icon": "🎯",
                "title": f"Parse accuracy: {avg_confidence * 100:.0f}%",
                "description": "Some transactions may need review. Check items with ⚠️ badges.",
                "severity": "warning",
            })

        # 8. Category diversity
        if len(categories) >= 4:
            # Check if top category is > 50% — low diversification
            top_pct = categories[0]["total"] / current_spend * 100 if current_spend > 0 else 0
            if top_pct > 50:
                insights.append({
                    "type": "diversification",
                    "icon": "📊",
                    "title": f"{categories[0]['name']} dominates at {top_pct:.0f}%",
                    "description": "Over half your spending is in one category. Consider diversifying.",
                    "severity": "info",
                })

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
                "insight_count": len(insights),
            },
        }

    # ──────────────────────────────────────────
    # Data queries
    # ──────────────────────────────────────────

    async def _total_spend(self, user_id: str, month: int, year: int) -> float:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        return float(result.scalar())

    async def _total_income(self, user_id: str, month: int, year: int) -> float:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.CREDIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        return float(result.scalar())

    async def _category_breakdown(self, user_id: str, month: int, year: int) -> list[dict]:
        result = await self.db.execute(
            select(
                Category.name,
                Category.icon,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        return [
            {"name": row.name or "Uncategorized", "icon": row.icon or "📦",
             "total": float(row.total), "count": row.count}
            for row in result.all()
        ]

    async def _top_merchants(self, user_id: str, month: int, year: int) -> list[dict]:
        result = await self.db.execute(
            select(
                Transaction.merchant_normalized,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.merchant_normalized)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(5)
        )
        return [
            {"name": row.merchant_normalized or "Unknown", "total": float(row.total), "count": row.count}
            for row in result.all()
        ]

    async def _daily_spending_trend(self, user_id: str, month: int, year: int) -> list[dict]:
        """Returns daily spend totals for the given month — data for line chart."""
        result = await self.db.execute(
            select(
                Transaction.transaction_date,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
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
        for day in range(1, days_in_month + 1):
            d = date(year, month, day)
            if d > date.today():
                break  # Don't include future dates
            entry = daily_map.get(day, {"total": 0, "count": 0})
            trend.append({
                "date": d.strftime("%d %b"),
                "day": day,
                "total": entry["total"],
                "count": entry["count"],
            })

        return trend

    async def _detect_recurring(self, user_id: str) -> list[dict]:
        """
        Detect recurring payments: same merchant appearing 2+ times
        with similar amounts (within ±10%).
        """
        result = await self.db.execute(
            select(
                Transaction.merchant_normalized,
                func.count(Transaction.id).label("occurrences"),
                func.avg(Transaction.amount).label("avg_amount"),
                func.min(Transaction.amount).label("min_amount"),
                func.max(Transaction.amount).label("max_amount"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.merchant_normalized.isnot(None),
            )
            .group_by(Transaction.merchant_normalized)
            .having(func.count(Transaction.id) >= 2)
            .order_by(func.avg(Transaction.amount).desc())
        )

        recurring = []
        for row in result.all():
            avg = float(row.avg_amount)
            mn = float(row.min_amount)
            mx = float(row.max_amount)

            # Check if amounts are consistent (max within ±15% of min)
            if mn > 0 and mx / mn <= 1.15:
                recurring.append({
                    "merchant": row.merchant_normalized,
                    "occurrences": row.occurrences,
                    "avg_amount": round(avg, 2),
                    "is_consistent": True,
                })

        return recurring

    async def _avg_confidence(self, user_id: str, month: int, year: int) -> Optional[float]:
        result = await self.db.execute(
            select(func.avg(Transaction.confidence_score)).where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        val = result.scalar()
        return float(val) if val is not None else None
