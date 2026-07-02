"""Derived intelligence services for merchants, categories, analytics, and goals."""

from __future__ import annotations

import calendar
import json
from datetime import UTC, date, datetime
from urllib.parse import unquote

from sqlalchemy import case, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category, Merchant, parse_merchant_aliases
from app.models.sync import Budget, Goal
from app.models.transaction import Transaction, TransactionType
from app.schemas.intelligence import (
    CashFlowProjection,
    CategoryIntelligenceItem,
    CategoryIntelligenceResponse,
    CategoryTopMerchant,
    FinancialHealthScore,
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    MerchantDetail,
    MerchantSummary,
    MerchantUpdate,
    MonthComparison,
    TransactionPreview,
)
from app.services.insights_service import InsightsService
from app.services.parser.normalizer import invalidate_merchant_cache


def _prev_month(month: int, year: int) -> tuple[int, int]:
    return (month - 1, year) if month > 1 else (12, year - 1)


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _merchant_key(value: str | None) -> str:
    return (value or "Unknown").strip()


class IntelligenceService:
    """Read-model service for higher-level financial intelligence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_merchants(self, user_id: str, month: int, year: int) -> list[MerchantSummary]:
        previous_month, previous_year = _prev_month(month, year)
        previous_spend = await self._merchant_spend_map(user_id, previous_month, previous_year)

        result = await self.db.execute(
            select(
                func.coalesce(Transaction.merchant_normalized, Transaction.merchant_raw, "Unknown").label(
                    "merchant"
                ),
                Category.id.label("category_id"),
                Category.name.label("category_name"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
                func.count(Transaction.id).label("count"),
                func.avg(Transaction.amount).label("avg"),
                func.max(Transaction.transaction_date).label("latest"),
                func.min(Transaction.amount).label("min_amount"),
                func.max(Transaction.amount).label("max_amount"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(
                func.coalesce(Transaction.merchant_normalized, Transaction.merchant_raw, "Unknown"),
                Category.id,
                Category.name,
            )
            .order_by(func.sum(Transaction.amount).desc())
        )

        merchants: list[MerchantSummary] = []
        for row in result.all():
            name = _merchant_key(row.merchant)
            min_amount = float(row.min_amount or 0)
            max_amount = float(row.max_amount or 0)
            recurrence = 0.0
            if int(row.count or 0) >= 2:
                recurrence = 0.75
                if min_amount > 0 and max_amount / min_amount <= 1.15:
                    recurrence = 0.95
            merchants.append(
                MerchantSummary(
                    merchant_key=name,
                    name=name,
                    total_spend=float(row.total or 0),
                    transaction_count=int(row.count or 0),
                    avg_spend=float(row.avg or 0),
                    month_change_pct=_pct_change(
                        float(row.total or 0), previous_spend.get(name.lower(), 0.0)
                    ),
                    category=row.category_name,
                    category_id=row.category_id,
                    recurrence_likelihood=recurrence,
                    latest_transaction_date=row.latest,
                )
            )
        return merchants

    async def get_merchant_detail(
        self, user_id: str, merchant_key: str, month: int, year: int
    ) -> MerchantDetail:
        merchant_name = _merchant_key(unquote(merchant_key))
        summaries = await self.list_merchants(user_id, month, year)
        summary = next(
            (m for m in summaries if m.merchant_key.lower() == merchant_name.lower()),
            MerchantSummary(merchant_key=merchant_name, name=merchant_name),
        )

        merchant_row = await self._merchant_row(merchant_name)
        txns = await self._merchant_transactions(user_id, merchant_name, month, year)

        return MerchantDetail(
            **summary.model_dump(),
            aliases=parse_merchant_aliases(merchant_row.aliases) if merchant_row else [],
            default_category_id=merchant_row.category_default_id if merchant_row else summary.category_id,
            latest_transactions=txns,
        )

    async def update_merchant(
        self, user_id: str, merchant_key: str, data: MerchantUpdate, month: int, year: int
    ) -> MerchantDetail:
        merchant_name = _merchant_key(unquote(merchant_key))
        normalized_name = (data.normalized_name or merchant_name).strip()

        merchant = await self._merchant_row(merchant_name)
        if merchant is None and normalized_name.lower() != merchant_name.lower():
            merchant = await self._merchant_row(normalized_name)
        if merchant is None:
            merchant = Merchant(normalized_name=normalized_name, aliases="[]")
            self.db.add(merchant)

        merchant.normalized_name = normalized_name
        if data.default_category_id is not None:
            merchant.category_default_id = data.default_category_id

        aliases = data.aliases if data.aliases is not None else parse_merchant_aliases(merchant.aliases)
        if merchant_name.lower() != normalized_name.lower() and merchant_name not in aliases:
            aliases.append(merchant_name)
        merchant.aliases = json.dumps(sorted({a.strip() for a in aliases if a and a.strip()}))

        if data.apply_existing:
            result = await self.db.execute(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    self._merchant_filter(merchant_name),
                )
            )
            for txn in result.scalars().all():
                txn.merchant_normalized = normalized_name
                if data.default_category_id is not None:
                    txn.category_id = data.default_category_id

        await self.db.commit()
        invalidate_merchant_cache()
        return await self.get_merchant_detail(user_id, normalized_name, month, year)

    async def category_intelligence(
        self, user_id: str, month: int, year: int
    ) -> CategoryIntelligenceResponse:
        previous_month, previous_year = _prev_month(month, year)
        previous_spend = await self._category_spend_map(user_id, previous_month, previous_year)

        category_result = await self.db.execute(select(Category).order_by(Category.name))
        categories = list(category_result.scalars().all())
        category_names = {category.id: category.name for category in categories}

        spend_result = await self.db.execute(
            select(
                Transaction.category_id,
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.category_id)
        )
        spend_map = {
            row.category_id: {"total": float(row.total or 0), "count": int(row.count or 0)}
            for row in spend_result.all()
        }

        budget_result = await self.db.execute(
            select(Budget.category_id, Budget.monthly_limit).where(Budget.user_id == user_id)
        )
        budget_map = {row.category_id: float(row.monthly_limit) for row in budget_result.all()}

        top_merchants = await self._category_top_merchants(user_id, month, year)

        out: list[CategoryIntelligenceItem] = []
        seen: set[str | None] = set()
        for category in categories:
            seen.add(category.id)
            spend = spend_map.get(category.id, {"total": 0.0, "count": 0})
            budget_limit = budget_map.get(category.id)
            out.append(
                CategoryIntelligenceItem(
                    category_id=category.id,
                    name=category.name,
                    parent_category_id=category.parent_category_id,
                    parent_name=category_names.get(category.parent_category_id),
                    icon=category.icon,
                    total_spend=spend["total"],
                    transaction_count=spend["count"],
                    month_change_pct=_pct_change(spend["total"], previous_spend.get(category.id, 0.0)),
                    budget_limit=budget_limit,
                    budget_usage_pct=(
                        round(spend["total"] / budget_limit * 100, 1)
                        if budget_limit and budget_limit > 0
                        else None
                    ),
                    top_merchants=top_merchants.get(category.id, []),
                )
            )

        if None in spend_map and None not in seen:
            spend = spend_map[None]
            out.append(
                CategoryIntelligenceItem(
                    category_id=None,
                    name="Uncategorized",
                    total_spend=spend["total"],
                    transaction_count=spend["count"],
                    month_change_pct=_pct_change(spend["total"], previous_spend.get(None, 0.0)),
                    top_merchants=top_merchants.get(None, []),
                )
            )

        out.sort(key=lambda c: (c.total_spend == 0, -c.total_spend, c.name))
        return CategoryIntelligenceResponse(month=month, year=year, categories=out)

    async def cash_flow_projection(
        self, user_id: str, month: int, year: int
    ) -> CashFlowProjection:
        income, spend = await self._monthly_income_spend(user_id, month, year)
        days_in_month = calendar.monthrange(year, month)[1]
        today = date.today()
        if today.year == year and today.month == month:
            days_elapsed = max(today.day, 1)
            projected_spend = spend / days_elapsed * days_in_month if spend > 0 else 0.0
        else:
            days_elapsed = days_in_month
            projected_spend = spend
        return CashFlowProjection(
            month=month,
            year=year,
            income=income,
            spend_to_date=spend,
            net_to_date=income - spend,
            projected_spend=round(projected_spend, 2),
            projected_net=round(income - projected_spend, 2),
            daily_spend_rate=round(spend / days_elapsed, 2) if days_elapsed else 0.0,
            days_elapsed=days_elapsed,
            days_in_month=days_in_month,
        )

    async def month_comparison(self, user_id: str, month: int, year: int) -> MonthComparison:
        previous_month, previous_year = _prev_month(month, year)
        income, spend = await self._monthly_income_spend(user_id, month, year)
        prev_income, prev_spend = await self._monthly_income_spend(user_id, previous_month, previous_year)

        current_categories = await self._category_name_spend_map(user_id, month, year)
        previous_categories = await self._category_name_spend_map(user_id, previous_month, previous_year)
        category_deltas = []
        for name in sorted(set(current_categories) | set(previous_categories)):
            current = current_categories.get(name, 0.0)
            previous = previous_categories.get(name, 0.0)
            category_deltas.append(
                {
                    "category": name,
                    "current": current,
                    "previous": previous,
                    "change_pct": _pct_change(current, previous),
                }
            )
        category_deltas.sort(key=lambda d: abs(d["current"] - d["previous"]), reverse=True)

        return MonthComparison(
            month=month,
            year=year,
            previous_month=previous_month,
            previous_year=previous_year,
            income=income,
            previous_income=prev_income,
            spend=spend,
            previous_spend=prev_spend,
            savings=income - spend,
            previous_savings=prev_income - prev_spend,
            spend_change_pct=_pct_change(spend, prev_spend),
            income_change_pct=_pct_change(income, prev_income),
            category_deltas=category_deltas[:8],
        )

    async def financial_health(
        self, user_id: str, month: int, year: int
    ) -> FinancialHealthScore:
        income, spend = await self._monthly_income_spend(user_id, month, year)
        savings_rate = ((income - spend) / income * 100) if income > 0 else 0.0
        budget_adherence = await self._budget_adherence(user_id, month, year)
        review_cleanliness = await self._review_cleanliness(user_id, month, year)
        recurring = (await InsightsService(self.db).generate_insights(user_id, month, year)).get(
            "recurring_payments", []
        )
        recurring_total = sum(float(r.get("avg_amount", 0)) for r in recurring)
        recurring_burden = recurring_total / income * 100 if income > 0 else 0.0

        score = 0
        score += min(max(savings_rate, 0), 35)
        score += budget_adherence * 0.3
        score += max(0, 20 - min(recurring_burden, 20))
        score += review_cleanliness * 0.15
        score = int(round(max(0, min(score, 100))))

        signals = [
            {
                "label": "Savings rate",
                "value": round(savings_rate, 1),
                "severity": "success" if savings_rate >= 20 else "warning",
            },
            {
                "label": "Budget adherence",
                "value": round(budget_adherence, 1),
                "severity": "success" if budget_adherence >= 80 else "warning",
            },
            {
                "label": "Recurring burden",
                "value": round(recurring_burden, 1),
                "severity": "warning" if recurring_burden >= 25 else "info",
            },
            {
                "label": "Review cleanliness",
                "value": round(review_cleanliness, 1),
                "severity": "success" if review_cleanliness >= 90 else "warning",
            },
        ]
        return FinancialHealthScore(
            score=score,
            savings_rate=round(savings_rate, 1),
            budget_adherence=round(budget_adherence, 1),
            recurring_burden=round(recurring_burden, 1),
            review_cleanliness=round(review_cleanliness, 1),
            signals=signals,
        )

    async def list_goals(self, user_id: str, month: int, year: int) -> list[GoalResponse]:
        result = await self.db.execute(
            select(Goal)
            .where(Goal.user_id == user_id)
            .order_by(Goal.is_active.desc(), Goal.created_at.desc())
        )
        return [await self._goal_response(goal, user_id, month, year) for goal in result.scalars().all()]

    async def create_goal(self, user_id: str, data: GoalCreate) -> GoalResponse:
        now = datetime.now(UTC)
        goal = Goal(
            user_id=user_id,
            goal_type=data.goal_type,
            label=data.label,
            target_amount=data.target_amount,
            target_key=data.target_key,
            target_month=data.target_month,
            target_year=data.target_year,
            is_active=True,
            created_at=now,
        )
        self.db.add(goal)
        await self.db.commit()
        await self.db.refresh(goal)
        return await self._goal_response(
            goal, user_id, data.target_month or now.month, data.target_year or now.year
        )

    async def update_goal(
        self, goal_id: str, user_id: str, data: GoalUpdate, month: int, year: int
    ) -> GoalResponse | None:
        result = await self.db.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id)
        )
        goal = result.scalar_one_or_none()
        if goal is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(goal, field, value)
        await self.db.commit()
        await self.db.refresh(goal)
        return await self._goal_response(goal, user_id, month, year)

    async def _goal_response(self, goal: Goal, user_id: str, month: int, year: int) -> GoalResponse:
        current = await self._goal_current_amount(goal, user_id, month, year)
        if goal.goal_type == "savings":
            progress = current / goal.target_amount * 100 if goal.target_amount > 0 else 0.0
            status = "achieved" if current >= goal.target_amount else "tracking"
        else:
            progress = (goal.target_amount - current) / goal.target_amount * 100 if goal.target_amount > 0 else 0.0
            status = "at_risk" if current > goal.target_amount else "tracking"
        return GoalResponse(
            id=goal.id,
            user_id=goal.user_id,
            goal_type=goal.goal_type,
            label=goal.label,
            target_amount=goal.target_amount,
            target_key=goal.target_key,
            target_month=goal.target_month,
            target_year=goal.target_year,
            is_active=goal.is_active,
            current_amount=round(current, 2),
            progress_pct=round(max(0.0, min(progress, 100.0)), 1),
            status=status,
            created_at=goal.created_at,
        )

    async def _goal_current_amount(self, goal: Goal, user_id: str, month: int, year: int) -> float:
        if goal.goal_type == "savings":
            income, spend = await self._monthly_income_spend(user_id, month, year)
            return income - spend
        if goal.goal_type == "category_reduction":
            return await self._category_current_spend(user_id, month, year, goal.target_key)
        recurring = (await InsightsService(self.db).generate_insights(user_id, month, year)).get(
            "recurring_payments", []
        )
        return sum(float(r.get("avg_amount", 0)) for r in recurring)

    async def _monthly_income_spend(self, user_id: str, month: int, year: int) -> tuple[float, float]:
        result = await self.db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.transaction_type == TransactionType.CREDIT, Transaction.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).label("income"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.transaction_type == TransactionType.DEBIT, Transaction.amount),
                            else_=0,
                        )
                    ),
                    0,
                ).label("spend"),
            ).where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        row = result.one()
        return float(row.income or 0), float(row.spend or 0)

    async def _merchant_spend_map(self, user_id: str, month: int, year: int) -> dict[str, float]:
        result = await self.db.execute(
            select(
                func.coalesce(Transaction.merchant_normalized, Transaction.merchant_raw, "Unknown").label(
                    "merchant"
                ),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(func.coalesce(Transaction.merchant_normalized, Transaction.merchant_raw, "Unknown"))
        )
        return {_merchant_key(row.merchant).lower(): float(row.total or 0) for row in result.all()}

    async def _category_spend_map(self, user_id: str, month: int, year: int) -> dict[str | None, float]:
        result = await self.db.execute(
            select(
                Transaction.category_id,
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.category_id)
        )
        return {row.category_id: float(row.total or 0) for row in result.all()}

    async def _category_name_spend_map(self, user_id: str, month: int, year: int) -> dict[str, float]:
        result = await self.db.execute(
            select(
                func.coalesce(Category.name, "Uncategorized").label("category"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(func.coalesce(Category.name, "Uncategorized"))
        )
        return {row.category: float(row.total or 0) for row in result.all()}

    async def _category_top_merchants(
        self, user_id: str, month: int, year: int
    ) -> dict[str | None, list[CategoryTopMerchant]]:
        result = await self.db.execute(
            select(
                Transaction.category_id,
                func.coalesce(Transaction.merchant_normalized, Transaction.merchant_raw, "Unknown").label(
                    "merchant"
                ),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(
                Transaction.category_id,
                func.coalesce(Transaction.merchant_normalized, Transaction.merchant_raw, "Unknown"),
            )
            .order_by(Transaction.category_id, func.sum(Transaction.amount).desc())
        )
        out: dict[str | None, list[CategoryTopMerchant]] = {}
        for row in result.all():
            bucket = out.setdefault(row.category_id, [])
            if len(bucket) < 5:
                bucket.append(
                    CategoryTopMerchant(
                        name=_merchant_key(row.merchant),
                        total=float(row.total or 0),
                        count=int(row.count or 0),
                    )
                )
        return out

    async def _merchant_transactions(
        self, user_id: str, merchant_name: str, month: int, year: int
    ) -> list[TransactionPreview]:
        result = await self.db.execute(
            select(Transaction, Category.name.label("category_name"))
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                self._merchant_filter(merchant_name),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .order_by(Transaction.transaction_date.desc())
            .limit(20)
        )
        return [
            TransactionPreview(
                id=txn.id,
                merchant=txn.merchant_normalized or txn.merchant_raw or "Unknown",
                category=category_name,
                amount=float(txn.amount),
                transaction_type=txn.transaction_type.value,
                transaction_date=txn.transaction_date,
                confidence_score=float(txn.confidence_score or 0.0),
                reviewed_flag=bool(txn.reviewed_flag),
            )
            for txn, category_name in result.all()
        ]

    async def _merchant_row(self, merchant_name: str) -> Merchant | None:
        result = await self.db.execute(
            select(Merchant).where(func.lower(Merchant.normalized_name) == merchant_name.lower())
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _merchant_filter(merchant_name: str):
        key = merchant_name.lower()
        return or_(
            func.lower(Transaction.merchant_normalized) == key,
            func.lower(Transaction.merchant_raw) == key,
        )

    async def _category_current_spend(
        self, user_id: str, month: int, year: int, target_key: str | None
    ) -> float:
        conditions = [
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.DEBIT,
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        ]
        if target_key:
            conditions.append(or_(Transaction.category_id == target_key, Category.name == target_key))
        result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(*conditions)
        )
        return float(result.scalar() or 0)

    async def _budget_adherence(self, user_id: str, month: int, year: int) -> float:
        category_spend = await self._category_spend_map(user_id, month, year)
        result = await self.db.execute(select(Budget).where(Budget.user_id == user_id))
        budgets = list(result.scalars().all())
        if not budgets:
            return 100.0
        scores = []
        for budget in budgets:
            usage = category_spend.get(budget.category_id, 0.0) / budget.monthly_limit if budget.monthly_limit > 0 else 0
            scores.append(max(0.0, 100.0 - max(0.0, usage - 1.0) * 100.0))
        return sum(scores) / len(scores)

    async def _review_cleanliness(self, user_id: str, month: int, year: int) -> float:
        result = await self.db.execute(
            select(
                func.count(Transaction.id).label("total"),
                func.coalesce(
                    func.sum(case((Transaction.reviewed_flag.is_(False), 1), else_=0)), 0
                ).label("pending"),
            ).where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        row = result.one()
        total = int(row.total or 0)
        if total == 0:
            return 100.0
        return max(0.0, 100.0 - (int(row.pending or 0) / total * 100.0))
