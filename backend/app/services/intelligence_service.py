"""Derived intelligence services for merchants, categories, analytics, and goals."""

from __future__ import annotations

import calendar
import statistics
from datetime import UTC, date, datetime
from typing import cast
from urllib.parse import unquote

from sqlalchemy import case, extract, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category, Merchant, UserMerchantRule, parse_merchant_aliases
from app.models.sync import Budget, Goal
from app.models.transaction import Transaction, TransactionType
from app.schemas.intelligence import (
    CashFlowProjection,
    CategoryIntelligenceItem,
    CategoryIntelligenceResponse,
    CategoryTopMerchant,
    DataSufficiency,
    EvidenceItem,
    FinancialHealthScore,
    GoalCreate,
    GoalResponse,
    GoalType,
    GoalUpdate,
    LearnedMerchantRule,
    MerchantDetail,
    MerchantSummary,
    MerchantUpdate,
    MonthComparison,
    ScenarioRequest,
    ScenarioResponse,
    TransactionPreview,
)
from app.services.knowledge.recurring_knowledge import RecurringPattern, RecurringPatternService
from app.services.knowledge.ruleset_registry import CASH_FLOW, MONTHLY_STABILITY
from app.services.transaction_service import TransactionService


def _prev_month(month: int, year: int) -> tuple[int, int]:
    return (month - 1, year) if month > 1 else (12, year - 1)


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _merchant_key(value: str | None) -> str:
    return (value or "Unknown").strip()


def _shift_month(month: int, year: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + month - 1 + offset
    return absolute % 12 + 1, absolute // 12


class IntelligenceService:
    """Read-model service for higher-level financial intelligence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_merchants(self, user_id: str, month: int, year: int) -> list[MerchantSummary]:
        previous_month, previous_year = _prev_month(month, year)
        previous_spend = await self._merchant_spend_map(user_id, previous_month, previous_year)
        recurring_patterns = await RecurringPatternService(self.db).analyze(user_id)
        recurrence_by_merchant: dict[str, RecurringPattern] = {}
        for pattern in recurring_patterns:
            key = pattern.merchant.casefold()
            if (
                key not in recurrence_by_merchant
                or pattern.confidence > recurrence_by_merchant[key].confidence
            ):
                recurrence_by_merchant[key] = pattern

        result = await self.db.execute(
            select(
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                ).label("merchant"),
                Category.id.label("category_id"),
                Category.name.label("category_name"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
                func.count(Transaction.id).label("transaction_count"),
                func.avg(Transaction.amount).label("avg"),
                func.max(Transaction.transaction_date).label("latest"),
                func.min(Transaction.amount).label("min_amount"),
                func.max(Transaction.amount).label("max_amount"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                ),
                Category.id,
                Category.name,
            )
            .order_by(func.sum(Transaction.amount).desc())
        )

        merchants: list[MerchantSummary] = []
        for row in result.all():
            name = _merchant_key(row.merchant)
            selected_pattern = recurrence_by_merchant.get(name.casefold())
            recurrence = selected_pattern.confidence if selected_pattern else 0.0
            merchants.append(
                MerchantSummary(
                    merchant_key=name,
                    name=name,
                    total_spend=float(row.total or 0),
                    transaction_count=int(row.transaction_count or 0),
                    avg_spend=float(row.avg or 0),
                    month_change_pct=_pct_change(
                        float(row.total or 0), previous_spend.get(name.lower(), 0.0)
                    ),
                    category=row.category_name,
                    category_id=row.category_id,
                    recurrence_likelihood=recurrence,
                    recurrence_status=(
                        selected_pattern.status if selected_pattern else "candidate"
                    ),
                    recurrence_cadence=(selected_pattern.cadence if selected_pattern else None),
                    recurrence_confidence=recurrence,
                    next_expected_date=(
                        selected_pattern.next_expected_date if selected_pattern else None
                    ),
                    data_sufficiency=cast(
                        DataSufficiency,
                        selected_pattern.data_sufficiency if selected_pattern else "low",
                    ),
                    latest_transaction_date=row.latest,
                )
            )
        return merchants

    async def list_learned_merchant_rules(self, user_id: str) -> list[LearnedMerchantRule]:
        result = await self.db.execute(
            select(UserMerchantRule)
            .where(UserMerchantRule.user_id == user_id)
            .order_by(UserMerchantRule.updated_at.desc())
        )
        return [
            LearnedMerchantRule.model_validate(rule, from_attributes=True)
            for rule in result.scalars()
        ]

    async def delete_learned_merchant_rule(self, user_id: str, rule_id: str) -> bool:
        result = await self.db.execute(
            select(UserMerchantRule).where(
                UserMerchantRule.id == rule_id,
                UserMerchantRule.user_id == user_id,
            )
        )
        rule = result.scalar_one_or_none()
        if rule is None:
            return False
        await self.db.delete(rule)
        await self.db.commit()
        return True

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
        user_rules = await self._user_merchant_rules(user_id, merchant_name)
        txns = await self._merchant_transactions(user_id, merchant_name, month, year)
        aliases = parse_merchant_aliases(merchant_row.aliases) if merchant_row else []
        aliases.extend(rule.raw_descriptor for rule in user_rules)
        user_category_id = next(
            (rule.category_id for rule in user_rules if rule.category_id is not None), None
        )

        return MerchantDetail(
            **summary.model_dump(),
            aliases=sorted({alias for alias in aliases if alias}),
            default_category_id=(
                user_category_id
                or (merchant_row.category_default_id if merchant_row else summary.category_id)
            ),
            latest_transactions=txns,
        )

    async def update_merchant(
        self, user_id: str, merchant_key: str, data: MerchantUpdate, month: int, year: int
    ) -> MerchantDetail:
        merchant_name = _merchant_key(unquote(merchant_key))
        normalized_name = (data.normalized_name or merchant_name).strip()
        current_detail = await self.get_merchant_detail(user_id, merchant_name, month, year)
        rule_category_id = (
            data.default_category_id
            if data.default_category_id is not None
            else current_detail.default_category_id
        )
        await TransactionService(self.db).bulk_correct_merchant(
            user_id=user_id,
            current_name=merchant_name,
            normalized_name=normalized_name,
            category_id=data.default_category_id,
            rule_category_id=rule_category_id,
            aliases=data.aliases or [],
            apply_existing=data.apply_existing,
        )
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
                func.count(Transaction.id).label("transaction_count"),
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
        spend_totals: dict[str | None, float] = {}
        spend_counts: dict[str | None, int] = {}
        for row in spend_result.all():
            spend_totals[row.category_id] = float(row.total or 0)
            spend_counts[row.category_id] = int(row.transaction_count or 0)

        budget_result = await self.db.execute(
            select(Budget.category_id, Budget.monthly_limit).where(Budget.user_id == user_id)
        )
        budget_map = {row.category_id: float(row.monthly_limit) for row in budget_result.all()}

        top_merchants = await self._category_top_merchants(user_id, month, year)

        out: list[CategoryIntelligenceItem] = []
        seen: set[str | None] = set()
        for category in categories:
            seen.add(category.id)
            category_spend = spend_totals.get(category.id, 0.0)
            budget_limit = budget_map.get(category.id)
            out.append(
                CategoryIntelligenceItem(
                    category_id=category.id,
                    name=category.name,
                    parent_category_id=category.parent_category_id,
                    parent_name=category_names.get(category.parent_category_id),
                    icon=category.icon,
                    total_spend=category_spend,
                    transaction_count=spend_counts.get(category.id, 0),
                    month_change_pct=_pct_change(
                        category_spend, previous_spend.get(category.id, 0.0)
                    ),
                    budget_limit=budget_limit,
                    budget_usage_pct=(
                        round(category_spend / budget_limit * 100, 1)
                        if budget_limit and budget_limit > 0
                        else None
                    ),
                    top_merchants=top_merchants.get(category.id, []),
                )
            )

        if None in spend_totals and None not in seen:
            uncategorized_spend = spend_totals[None]
            out.append(
                CategoryIntelligenceItem(
                    category_id=None,
                    name="Uncategorized",
                    total_spend=uncategorized_spend,
                    transaction_count=spend_counts.get(None, 0),
                    month_change_pct=_pct_change(
                        uncategorized_spend, previous_spend.get(None, 0.0)
                    ),
                    top_merchants=top_merchants.get(None, []),
                )
            )

        out.sort(key=lambda c: (c.total_spend == 0, -c.total_spend, c.name))
        return CategoryIntelligenceResponse(month=month, year=year, categories=out)

    async def cash_flow_projection(
        self,
        user_id: str,
        month: int,
        year: int,
        *,
        recurring_patterns: list[RecurringPattern] | None = None,
        historical_periods: list[tuple[float, float]] | None = None,
    ) -> CashFlowProjection:
        income, spend = await self._monthly_income_spend(user_id, month, year)
        days_in_month = calendar.monthrange(year, month)[1]
        today = date.today()
        if today.year == year and today.month == month:
            days_elapsed = max(today.day, 1)
            rate_projection = spend / days_elapsed * days_in_month if spend > 0 else 0.0
        else:
            days_elapsed = days_in_month
            rate_projection = spend
        patterns = recurring_patterns
        if patterns is None:
            patterns = await RecurringPatternService(self.db).analyze(
                user_id, as_of=min(today, date(year, month, days_in_month))
            )
        confirmed_commitments = sum(
            pattern.monthly_equivalent
            for pattern in patterns
            if pattern.status in {"mature", "missed"}
        )
        early_commitments = sum(
            pattern.monthly_equivalent for pattern in patterns if pattern.status == "early"
        )
        recurring_commitments = confirmed_commitments + early_commitments
        projected_spend = max(rate_projection, spend, confirmed_commitments)

        history = historical_periods
        if history is None:
            history = await self.historical_income_spend(user_id, month, year, 6)
        historical_spend = [item[1] for item in history if item[1] > 0]
        historical_income = [item[0] for item in history if item[0] > 0]
        is_current = today.year == year and today.month == month
        expected_income = (
            max(income, statistics.median(historical_income))
            if is_current and historical_income
            else income
        )
        category_spend = await self._category_spend_map(user_id, month, year)
        budgets_result = await self.db.execute(select(Budget).where(Budget.user_id == user_id))
        budgeted_remaining = sum(
            max(float(budget.monthly_limit) - category_spend.get(budget.category_id, 0.0), 0.0)
            for budget in budgets_result.scalars().all()
        )
        if len(historical_spend) >= 3:
            historical_median = statistics.median(historical_spend)
            historical_mad = statistics.median(
                abs(value - historical_median) for value in historical_spend
            )
            range_width = max(historical_mad * 1.4826, projected_spend * 0.05)
            data_sufficiency = "high" if len(historical_spend) >= 5 else "medium"
        else:
            range_width = projected_spend * 0.2
            data_sufficiency = "low"
        confidence = min(0.95, 0.35 + len(historical_spend) * 0.1 + min(len(patterns), 3) * 0.05)
        return CashFlowProjection(
            month=month,
            year=year,
            income=income,
            spend_to_date=spend,
            net_to_date=income - spend,
            projected_spend=round(projected_spend, 2),
            projected_net=round(expected_income - projected_spend, 2),
            daily_spend_rate=round(spend / days_elapsed, 2) if days_elapsed else 0.0,
            days_elapsed=days_elapsed,
            days_in_month=days_in_month,
            recurring_commitments=round(recurring_commitments, 2),
            confirmed_commitments=round(confirmed_commitments, 2),
            expected_income=round(expected_income, 2),
            flexible_spend_projection=round(max(projected_spend - confirmed_commitments, 0.0), 2),
            budgeted_remaining=round(budgeted_remaining, 2),
            projected_range_low=round(max(projected_spend - range_width, 0.0), 2),
            projected_range_high=round(projected_spend + range_width, 2),
            assumptions=[
                "Flexible spending continues at the observed daily rate.",
                "Only mature recurring streams are treated as confirmed commitments.",
                "The range reflects historical monthly variation and is not a guarantee.",
            ],
            evidence=[
                EvidenceItem(label="Observed transactions", value=f"Through day {days_elapsed}"),
                EvidenceItem(label="History", value=f"{len(historical_spend)} comparable months"),
                EvidenceItem(
                    label="Confirmed streams",
                    value=str(sum(1 for p in patterns if p.status in {"mature", "missed"})),
                ),
            ],
            confidence=round(confidence, 2),
            data_sufficiency=cast(DataSufficiency, data_sufficiency),
            historical_months=len(historical_spend),
            data_through=(
                today
                if today.year == year and today.month == month
                else date(year, month, days_in_month)
            ),
            ruleset_version=CASH_FLOW.version,
        )

    async def preview_scenario(self, user_id: str, request: ScenarioRequest) -> ScenarioResponse:
        """Preview an adjustment without mutating ledger, goals, or preferences."""
        projection = await self.cash_flow_projection(user_id, request.month, request.year)
        flexible_spend = max(projection.projected_spend - projection.recurring_commitments, 0.0)
        effective_flexible = min(request.flexible_spend_reduction, flexible_spend)
        spend_after_flexible = max(projection.projected_spend - effective_flexible, 0.0)
        effective_recurring = min(
            request.recurring_reduction,
            projection.recurring_commitments,
            spend_after_flexible,
        )
        scenario_spend = max(spend_after_flexible - effective_recurring, 0.0)
        scenario_net = projection.expected_income + request.additional_income - scenario_spend
        impact = scenario_net - projection.projected_net

        return ScenarioResponse(
            month=request.month,
            year=request.year,
            baseline_projected_net=projection.projected_net,
            scenario_projected_net=round(scenario_net, 2),
            scenario_projected_spend=round(scenario_spend, 2),
            monthly_impact=round(impact, 2),
            requested_flexible_spend_reduction=request.flexible_spend_reduction,
            effective_flexible_spend_reduction=round(effective_flexible, 2),
            requested_recurring_reduction=request.recurring_reduction,
            effective_recurring_reduction=round(effective_recurring, 2),
            additional_income=request.additional_income,
            assumptions=[
                *projection.assumptions,
                "Adjustments are a deterministic preview and do not change financial records.",
                "Reductions are capped by projected flexible spend and detected recurring commitments.",
                "Expected income is user supplied and is not verified by PFIS.",
            ],
            data_through=projection.data_through,
        )

    async def month_comparison(self, user_id: str, month: int, year: int) -> MonthComparison:
        previous_month, previous_year = _prev_month(month, year)
        income, spend = await self._monthly_income_spend(user_id, month, year)
        prev_income, prev_spend = await self._monthly_income_spend(
            user_id, previous_month, previous_year
        )

        current_categories = await self._category_name_spend_map(user_id, month, year)
        previous_categories = await self._category_name_spend_map(
            user_id, previous_month, previous_year
        )
        delta_rows: list[tuple[str, float, float, float | None]] = []
        for name in sorted(set(current_categories) | set(previous_categories)):
            current = current_categories.get(name, 0.0)
            previous = previous_categories.get(name, 0.0)
            delta_rows.append((name, current, previous, _pct_change(current, previous)))
        delta_rows.sort(key=lambda item: abs(item[1] - item[2]), reverse=True)
        category_deltas = [
            {
                "category": name,
                "current": current,
                "previous": previous,
                "change_pct": change_pct,
            }
            for name, current, previous, change_pct in delta_rows[:8]
        ]

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
            category_deltas=category_deltas,
        )

    async def financial_health(
        self,
        user_id: str,
        month: int,
        year: int,
        *,
        recurring_patterns: list[RecurringPattern] | None = None,
        historical_periods: list[tuple[float, float]] | None = None,
    ) -> FinancialHealthScore:
        income, spend = await self._monthly_income_spend(user_id, month, year)
        savings_rate = ((income - spend) / income * 100) if income > 0 else 0.0
        budget_adherence = await self._budget_adherence(user_id, month, year)
        review_cleanliness = await self._review_cleanliness(user_id, month, year)
        patterns = recurring_patterns
        if patterns is None:
            period_end = date(year, month, calendar.monthrange(year, month)[1])
            patterns = await RecurringPatternService(self.db).analyze(
                user_id, as_of=min(period_end, date.today())
            )
        recurring_total = sum(
            pattern.monthly_equivalent
            for pattern in patterns
            if pattern.status in {"early", "mature", "missed"}
        )
        recurring_burden = recurring_total / income * 100 if income > 0 else 0.0

        history = historical_periods
        if history is None:
            history = await self.historical_income_spend(user_id, month, year, 6)
        historical_spend = [item[1] for item in history if item[1] > 0]
        if len(historical_spend) >= 2:
            median_spend = statistics.median(historical_spend)
            mad = statistics.median(abs(value - median_spend) for value in historical_spend)
            spending_volatility = min(mad / median_spend * 100, 100.0) if median_spend else 0.0
        else:
            spending_volatility = 0.0

        savings_component = max(0.0, min(100.0, (savings_rate + 10.0) / 0.4))
        recurring_component = max(0.0, 100.0 - recurring_burden * 2.5)
        volatility_component = max(0.0, 100.0 - spending_volatility)
        if budget_adherence is None:
            monthly_stability = (
                savings_component * 0.5 + recurring_component * 0.25 + volatility_component * 0.25
            )
        else:
            monthly_stability = (
                savings_component * 0.4
                + budget_adherence * 0.25
                + recurring_component * 0.2
                + volatility_component * 0.15
            )

        quality = await self._data_quality_metrics(user_id, month, year)
        if income == 0 and spend == 0 and quality["parse_confidence"] == 0:
            monthly_stability = 0.0
        history_component = min(len(historical_spend) / 5 * 100, 100.0)
        data_confidence = (
            quality["parse_confidence"] * 45
            + quality["merchant_confidence"] * 20
            + review_cleanliness * 0.2
            + history_component * 0.15
        )
        if income == 0 and spend == 0 and quality["parse_confidence"] == 0:
            data_confidence = 0.0
        score = int(round(max(0, min(monthly_stability, 100))))
        confidence_score = int(round(max(0, min(data_confidence, 100))))
        sufficiency = (
            "high"
            if confidence_score >= 80 and len(historical_spend) >= 3
            else "medium" if confidence_score >= 55 else "low"
        )

        signals: list[dict] = [
            {
                "label": "Savings rate",
                "value": round(savings_rate, 1),
                "severity": "success" if savings_rate >= 20 else "warning",
            },
            {
                "label": "Budget adherence",
                "value": round(budget_adherence, 1) if budget_adherence is not None else None,
                "severity": (
                    "success"
                    if budget_adherence is not None and budget_adherence >= 80
                    else "warning" if budget_adherence is not None else "info"
                ),
            },
            {
                "label": "Recurring burden",
                "value": round(recurring_burden, 1),
                "severity": "warning" if recurring_burden >= 25 else "info",
            },
            {
                "label": "Spending volatility",
                "value": round(spending_volatility, 1),
                "severity": "warning" if spending_volatility >= 30 else "info",
            },
        ]
        return FinancialHealthScore(
            score=score,
            monthly_stability=score,
            data_confidence=confidence_score,
            data_sufficiency=cast(DataSufficiency, sufficiency),
            savings_rate=round(savings_rate, 1),
            budget_adherence=(round(budget_adherence, 1) if budget_adherence is not None else None),
            recurring_burden=round(recurring_burden, 1),
            review_cleanliness=round(review_cleanliness, 1),
            spending_volatility=round(spending_volatility, 1),
            ruleset_version=MONTHLY_STABILITY.version,
            signals=signals,
        )

    async def list_goals(self, user_id: str, month: int, year: int) -> list[GoalResponse]:
        result = await self.db.execute(
            select(Goal)
            .where(Goal.user_id == user_id)
            .order_by(Goal.is_active.desc(), Goal.created_at.desc())
        )
        return [
            await self._goal_response(goal, user_id, month, year) for goal in result.scalars().all()
        ]

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
        target_amount = float(goal.target_amount)
        if goal.goal_type == "savings":
            progress = current / target_amount * 100 if target_amount > 0 else 0.0
            status = "achieved" if current >= target_amount else "tracking"
        else:
            progress = (target_amount - current) / target_amount * 100 if target_amount > 0 else 0.0
            status = "at_risk" if current > target_amount else "tracking"
        return GoalResponse(
            id=goal.id,
            user_id=goal.user_id,
            goal_type=cast(GoalType, goal.goal_type),
            label=goal.label,
            target_amount=target_amount,
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
        patterns = await RecurringPatternService(self.db).analyze(user_id)
        return sum(
            pattern.monthly_equivalent
            for pattern in patterns
            if pattern.status in {"early", "mature", "missed"}
        )

    async def _monthly_income_spend(
        self, user_id: str, month: int, year: int
    ) -> tuple[float, float]:
        result = await self.db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.transaction_type == TransactionType.CREDIT,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("income"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.transaction_type == TransactionType.DEBIT,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("spend"),
            ).where(
                Transaction.user_id == user_id,
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        row = result.one()
        return float(row.income or 0), float(row.spend or 0)

    async def historical_income_spend(
        self, user_id: str, month: int, year: int, count: int
    ) -> list[tuple[float, float]]:
        history: list[tuple[float, float]] = []
        for offset in range(-count, 0):
            historical_month, historical_year = _shift_month(month, year, offset)
            history.append(
                await self._monthly_income_spend(user_id, historical_month, historical_year)
            )
        return history

    async def _data_quality_metrics(self, user_id: str, month: int, year: int) -> dict[str, float]:
        result = await self.db.execute(
            select(
                func.count(Transaction.id).label("transaction_count"),
                func.avg(Transaction.confidence_score).label("parse_confidence"),
                func.avg(Transaction.merchant_resolution_confidence).label("merchant_confidence"),
            ).where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        row = result.one()
        if int(row.transaction_count or 0) == 0:
            return {"parse_confidence": 0.0, "merchant_confidence": 0.0}
        return {
            "parse_confidence": max(0.0, min(float(row.parse_confidence or 0), 1.0)),
            "merchant_confidence": max(0.0, min(float(row.merchant_confidence or 0), 1.0)),
        }

    async def _merchant_spend_map(self, user_id: str, month: int, year: int) -> dict[str, float]:
        result = await self.db.execute(
            select(
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                ).label("merchant"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                )
            )
        )
        return {_merchant_key(row.merchant).lower(): float(row.total or 0) for row in result.all()}

    async def _category_spend_map(
        self, user_id: str, month: int, year: int
    ) -> dict[str | None, float]:
        result = await self.db.execute(
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
        return {row.category_id: float(row.total or 0) for row in result.all()}

    async def _category_name_spend_map(
        self, user_id: str, month: int, year: int
    ) -> dict[str, float]:
        result = await self.db.execute(
            select(
                func.coalesce(Category.name, literal_column("'Uncategorized'")).label("category"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(func.coalesce(Category.name, literal_column("'Uncategorized'")))
        )
        return {row.category: float(row.total or 0) for row in result.all()}

    async def _category_top_merchants(
        self, user_id: str, month: int, year: int
    ) -> dict[str | None, list[CategoryTopMerchant]]:
        result = await self.db.execute(
            select(
                Transaction.category_id,
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                ).label("merchant"),
                func.coalesce(func.sum(Transaction.amount), 0).label("total"),
                func.count(Transaction.id).label("transaction_count"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(
                Transaction.category_id,
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                ),
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
                        count=int(row.transaction_count or 0),
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

    async def _user_merchant_rules(
        self, user_id: str, merchant_name: str
    ) -> list[UserMerchantRule]:
        result = await self.db.execute(
            select(UserMerchantRule)
            .where(
                UserMerchantRule.user_id == user_id,
                func.lower(UserMerchantRule.normalized_name) == merchant_name.lower(),
            )
            .order_by(UserMerchantRule.updated_at.desc())
        )
        return list(result.scalars().all())

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
            Transaction.is_transfer.is_(False),
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        ]
        if target_key:
            conditions.append(
                or_(Transaction.category_id == target_key, Category.name == target_key)
            )
        result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(*conditions)
        )
        return float(result.scalar() or 0)

    async def _budget_adherence(self, user_id: str, month: int, year: int) -> float | None:
        category_spend = await self._category_spend_map(user_id, month, year)
        result = await self.db.execute(select(Budget).where(Budget.user_id == user_id))
        budgets = list(result.scalars().all())
        if not budgets:
            return None
        scores = []
        for budget in budgets:
            limit = float(budget.monthly_limit)
            usage = category_spend.get(budget.category_id, 0.0) / limit if limit > 0 else 0
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
