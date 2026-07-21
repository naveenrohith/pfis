"""
Workspace Service — Financial Decision Workspace aggregate.

Composes a single DTO for `GET /api/dashboard/workspace` by reusing existing
deterministic services and lightweight queries:

- snapshot        : monthly headline metrics (income, spend, savings, counts)
- timeline        : recent financial movements classified into event types
- insights        : action-oriented cards from InsightsService
- recommendations : deterministic, actionable suggestions derived from analytics
- review_summary  : low-confidence / unreviewed rollup
- sync_summary    : latest sync status and email processing counts

Security: this service never returns raw email bodies, tokens, or secrets. Only
aggregated transaction, insight, budget, and sync-status data is surfaced.
"""

import logging
from calendar import monthrange
from datetime import date

from sqlalchemy import case, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.email import GmailAccount, RawEmail
from app.models.sync import Budget, SyncRun
from app.models.transaction import Transaction, TransactionType
from app.schemas.dashboard import (
    ReviewSummary,
    SyncSummary,
    TimelineEvent,
    WorkspaceInsight,
    WorkspaceRecommendation,
    WorkspaceResponse,
    WorkspaceSnapshot,
)
from app.schemas.intelligence import (
    CashFlowProjection,
    FinancialHealthScore,
    MonthComparison,
)
from app.services.insights_service import InsightsService
from app.services.intelligence_service import IntelligenceService
from app.services.knowledge.recurring_knowledge import RecurringPatternService
from app.services.knowledge.ruleset_registry import RECOMMENDATION_RANKING
from app.services.recommendation_utils import recommendation_id

logger = logging.getLogger(__name__)

# Confidence below this needs review (matches the frontend review threshold).
REVIEW_THRESHOLD = 0.85
TIMELINE_LIMIT = 40


class WorkspaceService:
    """Aggregates the Financial Decision Workspace snapshot for a user/month."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_workspace(self, user_id: str, month: int, year: int) -> WorkspaceResponse:
        period_metrics = await self._period_metrics(user_id, month, year)
        sync = await self._sync_summary(user_id)
        if period_metrics["transaction_count"] == 0:
            return self._empty_workspace(month, year, sync)

        period_end = date(year, month, monthrange(year, month)[1])
        recurring_patterns = await RecurringPatternService(self.db).analyze(
            user_id, as_of=min(period_end, date.today())
        )
        insights_payload = await InsightsService(self.db).generate_insights(
            user_id, month, year, recurring_patterns=recurring_patterns
        )
        recurring = insights_payload.get("recurring_payments", [])
        intelligence = IntelligenceService(self.db)
        historical_periods = await intelligence.historical_income_spend(user_id, month, year, 6)
        projection = await intelligence.cash_flow_projection(
            user_id,
            month,
            year,
            recurring_patterns=recurring_patterns,
            historical_periods=historical_periods,
        )
        comparison = await intelligence.month_comparison(user_id, month, year)
        financial_health = await intelligence.financial_health(
            user_id,
            month,
            year,
            recurring_patterns=recurring_patterns,
            historical_periods=historical_periods,
        )

        spend = period_metrics["spend"]
        income = period_metrics["income"]
        txn_count = period_metrics["transaction_count"]
        review = period_metrics["review"]
        budgets = await self._budget_status(user_id, month, year)
        budget_risk = sum(1 for b in budgets if b["status"] in ("warning", "over"))
        recurring_merchants = {
            str(r.get("merchant", "")).strip().lower() for r in recurring if r.get("merchant")
        }
        timeline = await self._timeline(user_id, month, year, recurring_merchants)

        snapshot = WorkspaceSnapshot(
            income=income,
            spend=spend,
            savings=income - spend,
            net_cash_flow=income - spend,
            transaction_count=txn_count,
            review_count=review.pending_count,
            budget_risk_count=budget_risk,
            sync_status=sync.latest_status or "idle",
        )

        insights = [
            WorkspaceInsight(
                type=card.get("type"),
                icon=card.get("icon"),
                title=card.get("title", ""),
                description=card.get("description", ""),
                severity=card.get("severity", "info"),
            )
            for card in insights_payload.get("insights", [])
        ]

        recommendations = self._recommendations(
            income=income,
            spend=spend,
            budgets=budgets,
            recurring=recurring,
            review=review,
            insights=insights_payload.get("insights", []),
        )
        recommendations = self._rank_recommendations(
            recommendations,
            income=income,
            recurring=recurring,
            review=review,
        )
        for recommendation in recommendations:
            recommendation.id = recommendation_id(
                recommendation.type, recommendation.target, recommendation.title
            )
            recommendation.reason_codes = [recommendation.type, recommendation.severity]
            recommendation.expected_impact = self._expected_impact(recommendation.type)

        return WorkspaceResponse(
            month=month,
            year=year,
            snapshot=snapshot,
            timeline=timeline,
            insights=insights,
            recommendations=recommendations,
            review_summary=review,
            sync_summary=sync,
            projection=projection,
            month_comparison=comparison,
            financial_health=financial_health,
            recurring_commitments=recurring,
        )

    # ──────────────────────────────────────────
    # Data queries
    # ──────────────────────────────────────────

    async def _period_metrics(self, user_id: str, month: int, year: int) -> dict:
        result = await self.db.execute(
            select(
                func.count(Transaction.id).label("transaction_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (Transaction.transaction_type == TransactionType.DEBIT)
                                & Transaction.is_transfer.is_(False),
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("spend"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (Transaction.transaction_type == TransactionType.CREDIT)
                                & Transaction.is_transfer.is_(False),
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("income"),
                func.coalesce(
                    func.sum(case((Transaction.reviewed_flag.is_(False), 1), else_=0)), 0
                ).label("pending"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (Transaction.reviewed_flag.is_(False))
                                & (Transaction.confidence_score < REVIEW_THRESHOLD),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("low_conf"),
                func.avg(Transaction.confidence_score).label("avg_conf"),
            ).where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        row = result.one()
        return {
            "transaction_count": int(row.transaction_count or 0),
            "spend": float(row.spend or 0),
            "income": float(row.income or 0),
            "review": ReviewSummary(
                pending_count=int(row.pending or 0),
                low_confidence_count=int(row.low_conf or 0),
                avg_confidence=(float(row.avg_conf) if row.avg_conf is not None else None),
            ),
        }

    async def _budget_status(self, user_id: str, month: int, year: int) -> list[dict]:
        budget_result = await self.db.execute(
            select(Budget, Category.name)
            .join(Category, Budget.category_id == Category.id)
            .where(Budget.user_id == user_id)
        )
        budgets = budget_result.all()
        if not budgets:
            return []

        spend_result = await self.db.execute(
            select(
                Transaction.category_id,
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.category_id)
        )
        spend_map = {row.category_id: float(row.total) for row in spend_result.all()}

        out: list[dict] = []
        for budget, cat_name in budgets:
            actual = spend_map.get(budget.category_id, 0.0)
            limit = float(budget.monthly_limit)
            pct = (actual / limit * 100) if limit > 0 else 0.0
            if pct >= 100:
                status = "over"
            elif pct >= 80:
                status = "warning"
            else:
                status = "under"
            out.append(
                {
                    "category": cat_name,
                    "limit": float(budget.monthly_limit),
                    "actual": actual,
                    "usage_pct": round(pct, 1),
                    "status": status,
                }
            )
        return out

    async def _timeline(
        self, user_id: str, month: int, year: int, recurring_merchants: set[str]
    ) -> list[TimelineEvent]:
        result = await self.db.execute(
            select(Transaction, Category.name.label("category_name"))
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .order_by(Transaction.transaction_date.desc())
            .limit(TIMELINE_LIMIT)
        )

        events: list[TimelineEvent] = []
        for txn, category_name in result.all():
            merchant = txn.merchant_normalized or txn.merchant_raw or "Unknown"
            event_type = self._classify_event(txn, category_name, recurring_merchants)
            direction = (
                "in"
                if txn.transaction_type in (TransactionType.CREDIT, TransactionType.REFUND)
                else "out"
            )
            events.append(
                TimelineEvent(
                    type=event_type,
                    label=merchant,
                    merchant=merchant,
                    category=category_name,
                    amount=float(txn.amount),
                    direction=direction,
                    date=txn.transaction_date.isoformat(),
                    payment_method=txn.payment_method.value,
                    transaction_status=txn.transaction_status,
                    confidence=float(txn.confidence_score or 0.0),
                )
            )
        return events

    @staticmethod
    def _classify_event(
        txn: Transaction, category_name: str | None, recurring_merchants: set[str]
    ) -> str:
        if txn.is_transfer:
            return "transfer"
        if txn.transaction_type == TransactionType.REFUND:
            return "refund"
        if txn.transaction_type == TransactionType.CREDIT:
            return "income"
        merchant_key = (txn.merchant_normalized or txn.merchant_raw or "").strip().lower()
        if merchant_key and merchant_key in recurring_merchants:
            return "subscription"
        if category_name and category_name.lower() in {"bills", "utilities", "rent", "emi"}:
            return "bill"
        return "shopping"

    async def _sync_summary(self, user_id: str) -> SyncSummary:
        latest_status = (
            select(SyncRun)
            .where(SyncRun.user_id == user_id)
            .order_by(SyncRun.start_time.desc())
            .limit(1)
            .with_only_columns(SyncRun.status)
            .scalar_subquery()
        )
        last_synced = (
            select(func.max(GmailAccount.last_synced_at))
            .where(GmailAccount.user_id == user_id)
            .scalar_subquery()
        )
        result = await self.db.execute(
            select(
                latest_status.label("latest_status"),
                last_synced.label("last_synced_at"),
                func.count(RawEmail.id).label("total"),
                func.coalesce(
                    func.sum(case((RawEmail.processed_flag.is_(True), 1), else_=0)), 0
                ).label("processed"),
            ).where(RawEmail.user_id == user_id)
        )
        email_row = result.one()
        total = int(email_row.total or 0)
        processed = int(email_row.processed or 0)

        return SyncSummary(
            latest_status=(
                email_row.latest_status.value
                if hasattr(email_row.latest_status, "value")
                else email_row.latest_status
            ),
            last_synced_at=(
                email_row.last_synced_at.isoformat() if email_row.last_synced_at else None
            ),
            processed_total=processed,
            unprocessed_total=max(total - processed, 0),
        )

    @staticmethod
    def _empty_workspace(month: int, year: int, sync: SyncSummary) -> WorkspaceResponse:
        previous_month = 12 if month == 1 else month - 1
        previous_year = year - 1 if month == 1 else year
        days_in_month = monthrange(year, month)[1]
        today = date.today()
        selected_start = date(year, month, 1)
        selected_end = date(year, month, days_in_month)
        if selected_end < today:
            data_through = selected_end
            days_elapsed = days_in_month
        elif selected_start <= today:
            data_through = today
            days_elapsed = today.day
        else:
            data_through = None
            days_elapsed = 0
        return WorkspaceResponse(
            month=month,
            year=year,
            snapshot=WorkspaceSnapshot(sync_status=sync.latest_status or "idle"),
            timeline=[],
            insights=[],
            recommendations=[],
            review_summary=ReviewSummary(),
            sync_summary=sync,
            projection=CashFlowProjection(
                month=month,
                year=year,
                days_elapsed=days_elapsed,
                days_in_month=days_in_month,
                data_through=data_through,
            ),
            month_comparison=MonthComparison(
                month=month,
                year=year,
                previous_month=previous_month,
                previous_year=previous_year,
            ),
            financial_health=FinancialHealthScore(
                score=0,
                monthly_stability=0,
                data_confidence=0,
                data_sufficiency="low",
                budget_adherence=None,
            ),
            recurring_commitments=[],
        )

    # ──────────────────────────────────────────
    # Recommendation rules (deterministic)
    # ──────────────────────────────────────────

    def _recommendations(
        self,
        *,
        income: float,
        spend: float,
        budgets: list[dict],
        recurring: list[dict],
        review: ReviewSummary,
        insights: list[dict],
    ) -> list[WorkspaceRecommendation]:
        recs: list[WorkspaceRecommendation] = []

        # 1. Budget warnings
        at_risk = [b for b in budgets if b["status"] in ("warning", "over")]
        for b in at_risk[:3]:
            over = b["status"] == "over"
            recs.append(
                WorkspaceRecommendation(
                    type="budget",
                    severity="danger" if over else "warning",
                    title=(
                        f"{b['category']} budget exceeded"
                        if over
                        else f"{b['category']} budget at {b['usage_pct']:.0f}%"
                    ),
                    description=(
                        f"Spent ₹{b['actual']:,.0f} of a ₹{b['limit']:,.0f} limit. "
                        + (
                            "Review this category before it grows."
                            if over
                            else "Slow down to stay on track."
                        )
                    ),
                    action_label="Open budgets",
                    target="budgets",
                )
            )

        # 2. Recurring charge review
        if recurring:
            total_recurring = sum(
                float(r.get("monthly_equivalent", r.get("avg_amount", 0))) for r in recurring
            )
            recs.append(
                WorkspaceRecommendation(
                    type="recurring",
                    severity="info",
                    title=f"Review {len(recurring)} recurring charge(s)",
                    description=(
                        f"About ₹{total_recurring:,.0f}/month recurs. "
                        "Cancel anything you no longer use."
                    ),
                    action_label="View recurring",
                    target="insights",
                )
            )

        # 3. Low-confidence cleanup
        if review.low_confidence_count > 0:
            recs.append(
                WorkspaceRecommendation(
                    type="review",
                    severity="warning",
                    title=f"{review.low_confidence_count} transaction(s) need review",
                    description="Low-confidence parses may be mis-categorized. Confirm or correct them.",
                    action_label="Open review queue",
                    target="review",
                )
            )

        # 4. Anomaly alert (reuse insight anomaly card, if present)
        anomaly = next((c for c in insights if c.get("type") == "anomaly"), None)
        if anomaly:
            recs.append(
                WorkspaceRecommendation(
                    type="anomaly",
                    severity="warning",
                    title=anomaly.get("title", "Unusual spending detected"),
                    description=anomaly.get("description", ""),
                    action_label="See timeline",
                    target="timeline",
                )
            )

        # 5. Savings suggestion
        if income > 0:
            savings_rate = (income - spend) / income * 100
            if savings_rate < 10:
                recs.append(
                    WorkspaceRecommendation(
                        type="savings",
                        severity="warning" if savings_rate >= 0 else "danger",
                        title="Boost your savings rate",
                        description=(
                            f"You saved {savings_rate:.0f}% of income this month. "
                            "Trim discretionary spending to build a buffer."
                        ),
                        action_label="See insights",
                        target="insights",
                    )
                )

        return recs

    @staticmethod
    def _rank_recommendations(
        recommendations: list[WorkspaceRecommendation],
        *,
        income: float,
        recurring: list[dict],
        review: ReviewSummary,
    ) -> list[WorkspaceRecommendation]:
        """Rank actions by materiality, confidence, urgency, and actionability."""
        recurring_total = sum(
            float(item.get("monthly_equivalent", item.get("avg_amount", 0))) for item in recurring
        )
        recurring_confidence = (
            sum(float(item.get("confidence", 0)) for item in recurring) / len(recurring)
            if recurring
            else 0.0
        )
        severity_points = {"danger": 30, "warning": 20, "info": 10, "success": 5}
        for recommendation in recommendations:
            materiality = 10.0
            confidence = 15.0
            if recommendation.type == "recurring":
                materiality = min(25.0, recurring_total / max(income, 1) * 100)
                confidence = recurring_confidence * 20
                recommendation.evidence = [
                    {"label": "Monthly equivalent", "value": f"₹{recurring_total:,.0f}"},
                    {"label": "Knowledge ruleset", "value": RECOMMENDATION_RANKING.version},
                ]
            elif recommendation.type == "review":
                materiality = min(25.0, review.low_confidence_count * 5.0)
                confidence = 20.0
                recommendation.evidence = [
                    {"label": "Needs review", "value": str(review.low_confidence_count)},
                    {
                        "label": "Average confidence",
                        "value": f"{(review.avg_confidence or 0) * 100:.0f}%",
                    },
                ]
            else:
                recommendation.evidence = [
                    {"label": "Selected period", "value": "Current workspace month"},
                    {"label": "Ruleset", "value": RECOMMENDATION_RANKING.version},
                ]
            urgency = severity_points.get(recommendation.severity, 10)
            actionability = 20.0 if recommendation.action_label and recommendation.target else 0.0
            recommendation.priority = int(
                round(min(100.0, materiality + confidence + urgency + actionability))
            )
        return sorted(recommendations, key=lambda item: item.priority, reverse=True)

    @staticmethod
    def _expected_impact(kind: str) -> str:
        return {
            "budget": "Reduce the risk of exceeding a monthly category limit.",
            "recurring": "Identify avoidable monthly commitments.",
            "review": "Improve the reliability of financial totals.",
            "anomaly": "Confirm whether unusual activity is expected.",
            "savings": "Improve projected monthly savings.",
        }.get(kind, "Improve the quality of the selected financial decision.")
