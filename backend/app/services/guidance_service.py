"""Transparent, deterministic personal-finance guidance."""

import re
from datetime import UTC, date, datetime

from sqlalchemy import extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionType
from app.models.workspace import RecommendationState
from app.schemas.guidance import (
    GuidanceAction,
    GuidanceBrief,
    GuidanceMetric,
    GuidancePeriod,
    GuidanceQueryResult,
    RecommendationEvidence,
    RecommendationStateResponse,
    RecommendationStateUpdate,
)
from app.services.dashboard_service import WorkspaceService
from app.services.insights_service import InsightsService
from app.services.intelligence_service import IntelligenceService
from app.services.recommendation_utils import recommendation_id

RULESET_VERSION = "pfis-guidance-1"
SUPPORTED_EXAMPLES = [
    "How much did I spend this month?",
    "Show recurring charges",
    "How are my budgets doing?",
    "Compare this month with last month",
    "How much did I spend at Coffee Bar?",
]


class GuidanceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def brief(self, user_id: str, period: GuidancePeriod, as_of: date) -> GuidanceBrief:
        workspace = await WorkspaceService(self.db).get_workspace(user_id, as_of.month, as_of.year)
        health = await IntelligenceService(self.db).financial_health(
            user_id, as_of.month, as_of.year
        )
        comparison = await IntelligenceService(self.db).month_comparison(
            user_id, as_of.month, as_of.year
        )
        hidden = await self._hidden_recommendations(user_id)
        actions: list[GuidanceAction] = []
        for index, rec in enumerate(workspace.recommendations):
            rec_id = rec.id or recommendation_id(rec.type, rec.target, rec.title)
            if rec_id in hidden:
                continue
            actions.append(
                GuidanceAction(
                    id=rec_id,
                    type=rec.type,
                    priority=rec.priority or max(10, 100 - index * 10),
                    title=rec.title,
                    description=rec.description,
                    action_label=rec.action_label,
                    target=rec.target,
                    reason_codes=rec.reason_codes or [rec.type, rec.severity],
                    evidence=[
                        RecommendationEvidence(
                            label="Selected period", value=f"{as_of.year}-{as_of.month:02d}"
                        ),
                    ],
                    expected_impact=rec.expected_impact or self._expected_impact(rec.type),
                )
            )

        snapshot = workspace.snapshot
        if snapshot.transaction_count == 0:
            headline = "Connect or add activity to begin your brief"
            summary = "PFIS has no transactions for this period yet."
            status = "waiting_for_data"
        elif actions:
            headline = actions[0].title
            summary = (
                f"{len(actions)} transparent action{'s' if len(actions) != 1 else ''} are ready."
            )
            status = "attention"
        else:
            headline = "Your financial workspace is on track"
            summary = "No urgent deterministic guidance is active for this period."
            status = "on_track"

        changes = [
            (
                f"Spending is {abs(comparison.spend_change_pct):.0f}% {'higher' if comparison.spend_change_pct and comparison.spend_change_pct > 0 else 'lower'} than last month."
                if comparison.spend_change_pct is not None
                else "A prior-month spending comparison is not available."
            ),
            f"Monthly net cash flow is ₹{snapshot.net_cash_flow:,.0f}.",
        ]
        return GuidanceBrief(
            period=period,
            as_of=as_of,
            headline=headline,
            summary=summary,
            health_score=health.score,
            status=status,
            changes=changes,
            actions=actions,
            data_through=as_of,
            ruleset_version=RULESET_VERSION,
        )

    async def query(
        self, user_id: str, raw_query: str, month: int, year: int, currency: str = "INR"
    ) -> GuidanceQueryResult:
        query = " ".join(raw_query.lower().split())
        if any(term in query for term in ("recurring", "subscription", "subscriptions")):
            insights = await InsightsService(self.db).generate_insights(user_id, month, year)
            recurring = insights.get("recurring_payments", [])
            total = sum(float(item.get("avg_amount", 0)) for item in recurring)
            return self._result(
                "recurring_charges",
                f"PFIS found {len(recurring)} recurring charge{'s' if len(recurring) != 1 else ''} averaging {self._money(total, currency)} per month.",
                [GuidanceMetric(label="Monthly recurring", value=self._money(total, currency))],
                month,
                year,
                ["Open recurring charges", "Review unused subscriptions"],
            )

        if "budget" in query:
            rows = await IntelligenceService(self.db)._budget_adherence(user_id, month, year)
            return self._result(
                "budget_status",
                f"Your deterministic budget-adherence score is {rows:.0f}% for this month.",
                [GuidanceMetric(label="Budget adherence", value=f"{rows:.0f}%")],
                month,
                year,
                ["Open budgets", "Review categories over 80%"],
            )

        if any(term in query for term in ("compare", "last month", "previous month")):
            comparison = await IntelligenceService(self.db).month_comparison(user_id, month, year)
            change = comparison.spend_change_pct
            change_text = (
                "not comparable"
                if change is None
                else f"{abs(change):.0f}% {'higher' if change > 0 else 'lower'}"
            )
            return self._result(
                "month_comparison",
                f"Spending is {change_text} than the previous month.",
                [
                    GuidanceMetric(
                        label="This month", value=self._money(comparison.spend, currency)
                    ),
                    GuidanceMetric(
                        label="Previous month",
                        value=self._money(comparison.previous_spend, currency),
                    ),
                ],
                month,
                year,
                ["Open insights", "Review the largest category changes"],
            )

        merchant_match = re.search(
            r"(?:at|from)\s+(.+?)(?:\s+this month|\s+last month|\?|$)", query
        )
        if merchant_match:
            merchant = merchant_match.group(1).strip()
            total = await self._merchant_total(user_id, month, year, merchant)
            return self._result(
                "merchant_spend",
                f"You spent {self._money(total, currency)} at merchants matching “{merchant}” in the selected month.",
                [GuidanceMetric(label="Merchant spend", value=self._money(total, currency))],
                month,
                year,
                ["Open transactions", "Review merchant details"],
            )

        if any(term in query for term in ("spend", "spent", "expenses", "income", "saved")):
            summary = await IntelligenceService(self.db)._monthly_income_spend(user_id, month, year)
            income, spend = summary
            if "income" in query:
                intent, value, label = "monthly_income", income, "Income"
            elif "saved" in query:
                intent, value, label = "monthly_savings", income - spend, "Savings"
            else:
                intent, value, label = "monthly_spend", spend, "Spending"
            return self._result(
                intent,
                f"{label} for the selected month is {self._money(value, currency)}.",
                [GuidanceMetric(label=label, value=self._money(value, currency))],
                month,
                year,
                ["Open transactions", "Compare with last month"],
            )

        return GuidanceQueryResult(
            supported=False,
            answer="I can answer a defined set of finance questions without guessing.",
            suggested_actions=["Choose one of the supported examples"],
            supported_examples=SUPPORTED_EXAMPLES,
            ruleset_version=RULESET_VERSION,
        )

    async def set_state(
        self, user_id: str, rec_id: str, data: RecommendationStateUpdate
    ) -> RecommendationStateResponse:
        result = await self.db.execute(
            select(RecommendationState).where(
                RecommendationState.user_id == user_id,
                RecommendationState.recommendation_id == rec_id,
            )
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = RecommendationState(user_id=user_id, recommendation_id=rec_id, state=data.state)
            self.db.add(state)
        state.state = data.state
        state.snoozed_until = data.snoozed_until if data.state == "snoozed" else None
        state.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(state)
        return RecommendationStateResponse(
            recommendation_id=state.recommendation_id,
            state=state.state,
            snoozed_until=state.snoozed_until,
            updated_at=state.updated_at,
        )

    async def _hidden_recommendations(self, user_id: str) -> set[str]:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(RecommendationState).where(RecommendationState.user_id == user_id)
        )
        hidden = set()
        for state in result.scalars().all():
            if state.state == "dismissed" or (
                state.state == "snoozed" and state.snoozed_until and state.snoozed_until > now
            ):
                hidden.add(state.recommendation_id)
        return hidden

    async def _merchant_total(self, user_id: str, month: int, year: int, merchant: str) -> float:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
                or_(
                    func.lower(Transaction.merchant_normalized).contains(merchant.lower()),
                    func.lower(Transaction.merchant_raw).contains(merchant.lower()),
                ),
            )
        )
        return float(result.scalar() or 0)

    @staticmethod
    def _expected_impact(kind: str) -> str:
        return {
            "budget": "Reduce the risk of exceeding a monthly category limit.",
            "recurring": "Identify avoidable monthly commitments.",
            "review": "Improve the reliability of financial totals.",
            "anomaly": "Confirm whether unusual activity is expected.",
            "savings": "Improve projected monthly savings.",
        }.get(kind, "Improve the quality of the selected financial decision.")

    @staticmethod
    def _money(value: float, currency: str) -> str:
        symbol = "₹" if currency == "INR" else f"{currency} "
        return f"{symbol}{value:,.0f}"

    @staticmethod
    def _result(
        intent: str,
        answer: str,
        metrics: list[GuidanceMetric],
        month: int,
        year: int,
        actions: list[str],
    ) -> GuidanceQueryResult:
        return GuidanceQueryResult(
            supported=True,
            intent=intent,
            answer=answer,
            metrics=metrics,
            filters={"month": month, "year": year},
            suggested_actions=actions,
            supported_examples=SUPPORTED_EXAMPLES,
            ruleset_version=RULESET_VERSION,
        )
