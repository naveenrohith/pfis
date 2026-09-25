"""Derived intelligence services for merchants, categories, analytics, and goals."""

from __future__ import annotations

import calendar
import math
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any, Literal, TypedDict, cast
from urllib.parse import unquote

from sqlalchemy import case, extract, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.category import Category, Merchant, UserMerchantRule, parse_merchant_aliases
from app.models.email import GmailAccount, RawEmail
from app.models.sync import Budget, Goal, ParseFailure, SyncRun, SyncStatus
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.intelligence import (
    CashFlowBacktestReport,
    CashFlowProjection,
    CategoryIntelligenceItem,
    CategoryIntelligenceResponse,
    CategoryTopMerchant,
    DataConfidenceDimension,
    DataConfidenceStatus,
    DataSufficiency,
    EvidenceItem,
    FinancialHealthScore,
    ForecastBacktestExclusion,
    ForecastCalibrationStatus,
    ForecastHorizonMetrics,
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
    SourceCoverage,
    SourceCoverageCompleteness,
    SourceCoverageResponse,
    SourceCoverageStatus,
    TransactionPreview,
)
from app.services.financial_clock import user_financial_today
from app.services.knowledge.recurring_knowledge import RecurringPattern, RecurringPatternService
from app.services.knowledge.ruleset_registry import (
    CASH_FLOW,
    CASH_FLOW_BACKTEST,
    DATA_CONFIDENCE,
    MONTHLY_STABILITY,
)
from app.services.temporal_event_service import TemporalEventService
from app.services.temporal_source_history import historical_source_snapshots
from app.services.transaction_aggregates import (
    financial_activity_predicate,
    income_effect_expression,
    is_settled_transaction_status,
    spend_effect_expression,
    spend_event_predicate,
)
from app.services.transaction_service import TransactionService

FORECAST_INTERVAL_TARGET_COVERAGE_PCT = 80.0


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


class _DataQualityMetrics(TypedDict):
    transaction_count: int
    parse_confidence: float
    merchant_confidence: float
    pending_count: int
    conflict_count: int
    latest_transaction_date: date | None
    latest_sync_at: datetime | None
    sync_status: str
    unprocessed_email_count: int


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
                func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
                func.count(Transaction.id).label("transaction_count"),
                func.avg(Transaction.amount).label("avg"),
                func.max(Transaction.transaction_date).label("latest"),
                func.min(Transaction.amount).label("min_amount"),
                func.max(Transaction.amount).label("max_amount"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .having(func.sum(spend_effect_expression()) > 0)
            .group_by(
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                ),
                Category.id,
                Category.name,
            )
            .order_by(func.sum(spend_effect_expression()).desc())
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
                func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
                func.count(Transaction.id).label("transaction_count"),
            )
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.category_id)
            .having(func.sum(spend_effect_expression()) > 0)
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
        income, spend = await self.monthly_income_spend(user_id, month, year)
        today = await user_financial_today(self.db, user_id)
        days_in_month = calendar.monthrange(year, month)[1]
        selected_start = date(year, month, 1)
        selected_end = date(year, month, days_in_month)
        if today.year == year and today.month == month:
            days_elapsed = max(today.day, 1)
            rate_projection = spend / days_elapsed * days_in_month if spend > 0 else 0.0
        elif selected_end < today:
            days_elapsed = days_in_month
            rate_projection = spend
        else:
            days_elapsed = 0
            rate_projection = 0.0
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
        history = historical_periods
        if history is None:
            history = await self.historical_income_spend(user_id, month, year, 6)
        historical_spend = [item[1] for item in history if item[1] > 0]
        historical_income = [item[0] for item in history if item[0] > 0]
        is_current = today.year == year and today.month == month
        is_future = selected_start > today
        historical_spend_baseline = (
            statistics.median(historical_spend) if is_future and historical_spend else 0.0
        )

        temporal_expected_income = 0.0
        temporal_expected_outflows = 0.0
        temporal_conflicted_outflows = 0.0
        temporal_event_count = 0
        temporal_conflict_count = 0
        temporal_ruleset_version: str | None = None
        pay_cycle_status: ForecastCalibrationStatus = "not_applicable"
        pay_cycle_sample_count = 0
        if selected_end >= today:
            temporal = await TemporalEventService(self.db).timeline(
                user_id,
                range_start=selected_start,
                range_end=selected_end,
            )
            temporal_ruleset_version = temporal.ruleset_version
            income_events = [
                event
                for event in temporal.events
                if event.kind == "income"
                and event.direction == "inflow"
                and event.cadence is not None
                and event.state in {"expected", "overdue", "missed"}
            ]
            pay_cycle_sample_count = sum(
                1
                for event in income_events
                for evidence in event.evidence
                if evidence.source_type == "transaction" and evidence.role == "pattern_observation"
            )
            pay_cycle_status = (
                "supported"
                if income_events and pay_cycle_sample_count >= 3
                else "insufficient_history"
            )
            active_states = {"expected", "overdue", "missed"}
            for event in temporal.events:
                amount = event.amount.expected
                if amount is None or event.direction not in {"inflow", "outflow"}:
                    continue
                if event.state == "conflict":
                    temporal_conflict_count += 1
                    if event.direction == "outflow":
                        temporal_conflicted_outflows += amount
                    continue
                if event.state not in active_states:
                    continue
                temporal_event_count += 1
                if event.direction == "inflow":
                    temporal_expected_income += amount
                else:
                    temporal_expected_outflows += amount

        event_backed_spend_floor = spend + temporal_expected_outflows
        if is_current or is_future:
            category_mix_baseline, category_mix_sample_months, category_mix_status = (
                await self._category_mix_baseline(user_id, month, year, historical_spend)
            )
        else:
            category_mix_baseline, category_mix_sample_months, category_mix_status = (
                None,
                0,
                "not_applicable",
            )
        projected_spend = max(
            rate_projection,
            spend,
            confirmed_commitments,
            historical_spend_baseline,
            event_backed_spend_floor,
            category_mix_baseline or 0.0,
        )
        category_mix_adjustment = (
            round(category_mix_baseline - historical_spend_baseline, 2)
            if category_mix_baseline is not None and historical_spend_baseline > 0
            else 0.0
        )
        expected_income = income
        if historical_income and (is_current or is_future):
            expected_income = max(expected_income, statistics.median(historical_income))
        expected_income = max(expected_income, income + temporal_expected_income)
        category_spend = await self._category_spend_map(user_id, month, year)
        budgets_result = await self.db.execute(select(Budget).where(Budget.user_id == user_id))
        budgeted_remaining = sum(
            max(float(budget.monthly_limit) - category_spend.get(budget.category_id, 0.0), 0.0)
            for budget in budgets_result.scalars().all()
        )
        interval_calibration: Literal["same_cutoff_empirical", "robust_history", "low_evidence"] = (
            "low_evidence"
        )
        interval_calibration_samples = 0
        empirical_width: float | None = None
        if is_current and days_elapsed > 0:
            empirical_width, interval_calibration_samples = await self._same_cutoff_interval_width(
                user_id,
                month,
                year,
                days_elapsed,
            )
        if len(historical_spend) >= 3:
            historical_median = statistics.median(historical_spend)
            historical_mad = statistics.median(
                abs(value - historical_median) for value in historical_spend
            )
            range_width = max(historical_mad * 1.4826, projected_spend * 0.05)
            if empirical_width is not None:
                range_width = max(range_width, empirical_width)
                interval_calibration = "same_cutoff_empirical"
            else:
                interval_calibration = "robust_history"
            data_sufficiency = "high" if len(historical_spend) >= 5 else "medium"
        else:
            range_width = projected_spend * 0.2
            data_sufficiency = "low"
        confidence = min(
            0.95,
            max(
                0.1,
                0.35
                + len(historical_spend) * 0.1
                + min(len(patterns), 3) * 0.05
                + min(temporal_event_count, 3) * 0.03
                - min(temporal_conflict_count, 3) * 0.08,
            ),
        )
        assumptions = [
            (
                "Future flexible spending uses comparable history when available; no selected-month pace is observed."
                if is_future
                else "Flexible spending continues at the observed daily rate."
            ),
            "Dated unresolved inflows and outflows set forecast floors; they are not added twice when the pace projection is already higher.",
            "Only mature recurring streams are treated as confirmed commitments.",
            "The range reflects historical variation and a same-cutoff residual calibration when enough comparable months exist; it is not a guarantee.",
        ]
        if is_future and historical_spend:
            assumptions.append("Future flexible spending starts from the median comparable month.")
        if temporal_conflict_count:
            assumptions.append(
                "Conflicting dated outflows widen the upper range but are excluded from the central projection."
            )
        if interval_calibration == "same_cutoff_empirical":
            assumptions.append(
                f"The interval uses the 80th percentile error from {interval_calibration_samples} comparable same-cutoff months."
            )
        elif interval_calibration == "robust_history":
            assumptions.append(
                "No same-cutoff residual cohort is available, so the interval falls back to robust monthly variation."
            )
        if category_mix_status == "same_month_supported":
            assumptions.append(
                f"Category mix uses median settled spend from {category_mix_sample_months} prior same-month periods."
            )
        elif category_mix_status == "mix_supported":
            assumptions.append(
                f"Category mix uses median settled category spend from {category_mix_sample_months} comparable periods."
            )
        else:
            assumptions.append(
                "Category mix is not applied until at least two categories have repeated settled history."
            )
        if pay_cycle_status == "supported":
            assumptions.append(
                f"Expected income includes cadence evidence from {pay_cycle_sample_count} settled income observations."
            )
        elif pay_cycle_status == "insufficient_history":
            assumptions.append(
                "No recurring income cadence has enough settled observations to calibrate pay-cycle timing."
            )
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
            projected_range_high=round(
                projected_spend + range_width + temporal_conflicted_outflows, 2
            ),
            interval_calibration=interval_calibration,
            interval_calibration_samples=interval_calibration_samples,
            interval_target_coverage_pct=FORECAST_INTERVAL_TARGET_COVERAGE_PCT,
            category_mix_status=category_mix_status,
            category_mix_sample_months=category_mix_sample_months,
            category_mix_adjustment=category_mix_adjustment,
            pay_cycle_status=pay_cycle_status,
            pay_cycle_sample_count=pay_cycle_sample_count,
            temporal_expected_income=round(temporal_expected_income, 2),
            temporal_expected_outflows=round(temporal_expected_outflows, 2),
            temporal_conflicted_outflows=round(temporal_conflicted_outflows, 2),
            temporal_event_count=temporal_event_count,
            temporal_conflict_count=temporal_conflict_count,
            temporal_ruleset_version=temporal_ruleset_version,
            assumptions=assumptions,
            evidence=[
                EvidenceItem(
                    label="Observed transactions",
                    value=(
                        f"Through day {days_elapsed}"
                        if days_elapsed
                        else "No days observed in selected month"
                    ),
                ),
                EvidenceItem(label="History", value=f"{len(historical_spend)} comparable months"),
                EvidenceItem(
                    label="Confirmed streams",
                    value=str(sum(1 for p in patterns if p.status in {"mature", "missed"})),
                ),
                EvidenceItem(
                    label="Dated events",
                    value=(f"{temporal_event_count} active, {temporal_conflict_count} conflicting"),
                ),
                EvidenceItem(
                    label="Interval calibration",
                    value=(
                        f"80th percentile residual · {interval_calibration_samples} comparable cutoffs"
                        if interval_calibration == "same_cutoff_empirical"
                        else (
                            "Robust history fallback"
                            if interval_calibration == "robust_history"
                            else "Insufficient calibration history"
                        )
                    ),
                ),
                EvidenceItem(
                    label="Category mix calibration",
                    value=(
                        f"{category_mix_status} · {category_mix_sample_months} periods"
                        if category_mix_status != "insufficient_history"
                        else "Insufficient repeated category history"
                    ),
                ),
                EvidenceItem(
                    label="Pay-cycle calibration",
                    value=(
                        f"{pay_cycle_sample_count} settled income observations"
                        if pay_cycle_status == "supported"
                        else "Insufficient recurring income history"
                    ),
                ),
            ],
            confidence=round(confidence, 2),
            data_sufficiency=cast(DataSufficiency, data_sufficiency),
            historical_months=len(historical_spend),
            data_through=min(today, selected_end),
            ruleset_version=CASH_FLOW.version,
        )

    async def _category_mix_baseline(
        self,
        user_id: str,
        month: int,
        year: int,
        historical_spend: list[float],
    ) -> tuple[float | None, int, ForecastCalibrationStatus]:
        """Return a category-aware baseline only when repeated history supports it."""

        if len(historical_spend) < 3:
            return None, 0, "insufficient_history"
        history_month, history_year = _shift_month(month, year, -24)
        history_start = date(history_year, history_month, 1)
        rows = (
            await self.db.execute(
                select(
                    Transaction.transaction_date,
                    Transaction.category_id,
                    spend_effect_expression().label("spend_effect"),
                ).where(
                    Transaction.user_id == user_id,
                    Transaction.transaction_date >= history_start,
                    Transaction.transaction_date < date(year, month, 1),
                    spend_event_predicate(),
                )
            )
        ).all()
        by_month_category: dict[tuple[int, int], dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for row in rows:
            key = (row.transaction_date.year, row.transaction_date.month)
            category = row.category_id or "uncategorized"
            by_month_category[key][category] += float(row.spend_effect or 0.0)

        observed_months = sorted(
            key for key, values in by_month_category.items() if max(sum(values.values()), 0.0) > 0
        )
        if len(observed_months) < 3:
            return None, len(observed_months), "insufficient_history"

        same_months = [key for key in observed_months if key[1] == month]
        if len(same_months) >= 2:
            selected_months = same_months
            status: ForecastCalibrationStatus = "same_month_supported"
        else:
            selected_months = observed_months[-6:]
            status = "mix_supported"

        category_values: dict[str, list[float]] = defaultdict(list)
        for key in selected_months:
            for category, amount in by_month_category[key].items():
                if amount > 0:
                    category_values[category].append(amount)
        repeated_categories = {
            category: values for category, values in category_values.items() if len(values) >= 2
        }
        if len(repeated_categories) < 2:
            return None, len(selected_months), "insufficient_history"
        baseline = sum(statistics.median(values) for values in repeated_categories.values())
        if baseline <= 0:
            return None, len(selected_months), "insufficient_history"
        return round(baseline, 2), len(selected_months), status

    @classmethod
    def _category_mix_baseline_from_transactions(
        cls,
        transactions: list[Transaction],
        snapshots: dict[str, dict[str, Any]],
        *,
        month: int,
        year: int,
        as_of: date,
        currency: str,
    ) -> tuple[float | None, int, ForecastCalibrationStatus]:
        """Evaluate category mix from the transaction state known at a cutoff.

        The live projection can query current settled rows directly. Historical
        backtests must instead use the immutable snapshot payload available at
        each cutoff, otherwise a later category or status correction leaks into
        the earlier forecast.
        """

        history_month, history_year = _shift_month(month, year, -24)
        history_start = date(history_year, history_month, 1)
        target_start = date(year, month, 1)
        by_month_category: dict[tuple[int, int], dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        for transaction in transactions:
            if (
                transaction.transaction_date < history_start
                or transaction.transaction_date >= target_start
            ):
                continue
            if transaction.created_at.date() > as_of:
                continue
            payload = snapshots.get(transaction.id)
            amount = cls._transaction_spend_effect(transaction, payload, currency=currency)
            if amount == 0:
                continue
            category_value = (
                payload.get("category_id")
                if payload is not None and payload.get("category_id")
                else transaction.category_id
            )
            category = str(category_value or "uncategorized")
            key = (transaction.transaction_date.year, transaction.transaction_date.month)
            by_month_category[key][category] += amount

        observed_months = sorted(
            key for key, values in by_month_category.items() if max(sum(values.values()), 0.0) > 0
        )
        if len(observed_months) < 3:
            return None, len(observed_months), "insufficient_history"

        same_months = [key for key in observed_months if key[1] == month]
        if len(same_months) >= 2:
            selected_months = same_months
            status: ForecastCalibrationStatus = "same_month_supported"
        else:
            selected_months = observed_months[-6:]
            status = "mix_supported"

        category_values: dict[str, list[float]] = defaultdict(list)
        for key in selected_months:
            for category, amount in by_month_category[key].items():
                if amount > 0:
                    category_values[category].append(amount)
        repeated_categories = {
            category: values for category, values in category_values.items() if len(values) >= 2
        }
        if len(repeated_categories) < 2:
            return None, len(selected_months), "insufficient_history"
        baseline = sum(statistics.median(values) for values in repeated_categories.values())
        if baseline <= 0:
            return None, len(selected_months), "insufficient_history"
        return round(baseline, 2), len(selected_months), status

    async def _same_cutoff_interval_width(
        self,
        user_id: str,
        month: int,
        year: int,
        cutoff_day: int,
    ) -> tuple[float | None, int]:
        """Estimate interval width from prior same-cutoff projection residuals."""

        first_month, first_year = _shift_month(month, year, -6)
        history_start = date(first_year, first_month, 1)
        rows = (
            await self.db.execute(
                select(
                    Transaction.transaction_date,
                    spend_effect_expression().label("spend_effect"),
                ).where(
                    Transaction.user_id == user_id,
                    Transaction.transaction_date >= history_start,
                    Transaction.transaction_date < date(year, month, 1),
                    financial_activity_predicate(),
                )
            )
        ).all()
        daily: dict[tuple[int, int], dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for row in rows:
            daily[(row.transaction_date.year, row.transaction_date.month)][
                row.transaction_date.day
            ] += float(row.spend_effect or 0)

        residuals: list[float] = []
        for offset in range(-6, 0):
            prior_month, prior_year = _shift_month(month, year, offset)
            days_in_prior_month = calendar.monthrange(prior_year, prior_month)[1]
            total = max(sum(daily[(prior_year, prior_month)].values()), 0.0)
            if total <= 0:
                continue
            cutoff = min(cutoff_day, days_in_prior_month)
            through_cutoff = max(
                sum(
                    amount
                    for day, amount in daily[(prior_year, prior_month)].items()
                    if day <= cutoff
                ),
                0.0,
            )
            residuals.append(abs(through_cutoff / cutoff * days_in_prior_month - total))
        if len(residuals) < 3:
            return None, len(residuals)
        residuals.sort()
        index = min(len(residuals) - 1, max(0, math.ceil(len(residuals) * 0.8) - 1))
        return residuals[index], len(residuals)

    @staticmethod
    def _transaction_spend_effect(
        transaction: Transaction,
        payload: dict[str, Any] | None,
        *,
        currency: str,
    ) -> float:
        """Apply the historical transaction state without reclassifying evidence."""

        def value(name: str) -> Any:
            return (
                payload[name]
                if payload is not None and name in payload
                else getattr(transaction, name)
            )

        def enum_value(item: Any) -> str:
            return str(getattr(item, "value", item))

        if value("currency") != currency:
            return 0.0
        if not is_settled_transaction_status(value("transaction_status")):
            return 0.0
        if bool(value("is_transfer")) or bool(value("is_accounting_adjustment")):
            return 0.0
        if value("review_outcome") == "ignored_by_rule":
            return 0.0
        if enum_value(value("card_event")) == "payment":
            return 0.0
        amount = float(value("amount") or 0)
        transaction_type = enum_value(value("transaction_type"))
        if transaction_type == "debit":
            return amount
        if transaction_type == "refund":
            return -amount
        return 0.0

    @classmethod
    def _daily_spend_for_cutoff(
        cls,
        transactions: list[Transaction],
        *,
        as_of: date | None,
        currency: str,
        snapshots: dict[str, dict[str, Any]] | None = None,
    ) -> dict[tuple[int, int], dict[int, float]]:
        daily: dict[tuple[int, int], dict[int, float]] = defaultdict(lambda: defaultdict(float))
        snapshot_map = snapshots or {}
        for transaction in transactions:
            if as_of is not None and transaction.created_at.date() > as_of:
                continue
            effect = cls._transaction_spend_effect(
                transaction,
                snapshot_map.get(transaction.id),
                currency=currency,
            )
            if effect == 0:
                continue
            key = (transaction.transaction_date.year, transaction.transaction_date.month)
            daily[key][transaction.transaction_date.day] += effect
        return daily

    async def cash_flow_backtest(
        self,
        user_id: str,
        *,
        months: int = 6,
        cutoff_days: tuple[int, ...] = (7, 14, 21),
    ) -> CashFlowBacktestReport:
        """Evaluate retained-ledger forecast behavior at historical cutoffs."""

        today = await user_financial_today(self.db, user_id)
        targets = [_shift_month(today.month, today.year, offset) for offset in range(-months, 0)]
        first_month, first_year = targets[0]
        history_month, history_year = _shift_month(first_month, first_year, -6)
        history_start = date(history_year, history_month, 1)
        latest_month, latest_year = targets[-1]
        history_end = date(
            latest_year,
            latest_month,
            calendar.monthrange(latest_year, latest_month)[1],
        )
        context = await self.db.execute(
            select(User.currency, User.timezone).where(User.id == user_id)
        )
        user_context = context.one()
        transactions = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.transaction_date >= history_start,
                        Transaction.transaction_date <= history_end,
                    )
                )
            ).all()
        )
        settled_transaction_count = sum(
            is_settled_transaction_status(transaction.transaction_status)
            for transaction in transactions
        )
        unsettled_transaction_count = len(transactions) - settled_transaction_count
        daily_spend = self._daily_spend_for_cutoff(
            transactions,
            as_of=None,
            currency=user_context.currency,
        )

        observations: dict[int, list[tuple[float, float, float, float, float]]] = {
            cutoff: [] for cutoff in cutoff_days
        }
        exclusions: list[ForecastBacktestExclusion] = []
        evaluated_months = 0
        temporal_evidence_periods = 0
        temporal_event_count = 0
        transaction_history_cutoffs = 0
        transaction_history_coverage: list[float] = []
        category_mix_supported_periods = 0
        category_mix_applied_periods = 0
        for month, year in targets:
            key = (year, month)
            actual_spend = max(sum(daily_spend[key].values()), 0.0)
            prior_keys = [
                (prior_year, prior_month)
                for offset in range(-6, 0)
                for prior_month, prior_year in [_shift_month(month, year, offset)]
            ]
            prior_spend = [
                total
                for prior_key in prior_keys
                if (total := max(sum(daily_spend[prior_key].values()), 0.0)) > 0
            ]
            if len(prior_spend) < 3:
                exclusions.append(
                    ForecastBacktestExclusion(
                        month=month,
                        year=year,
                        reason="insufficient_prior_history",
                    )
                )
                continue
            if actual_spend <= 0:
                exclusions.append(
                    ForecastBacktestExclusion(
                        month=month,
                        year=year,
                        reason="no_observed_spend",
                    )
                )
                continue

            days_in_month = calendar.monthrange(year, month)[1]
            month_evaluated = False
            for requested_cutoff in cutoff_days:
                cutoff = min(requested_cutoff, days_in_month)
                cutoff_date = date(year, month, cutoff)
                historical_snapshots = await historical_source_snapshots(
                    self.db,
                    user_id=user_id,
                    timezone=user_context.timezone,
                    as_of=cutoff_date,
                )
                transaction_snapshots = {
                    source_id: payload
                    for (source_type, source_id), payload in historical_snapshots.items()
                    if source_type == "transaction"
                }
                if transaction_snapshots:
                    transaction_history_cutoffs += 1
                eligible_transaction_count = sum(
                    transaction.created_at.date() <= cutoff_date for transaction in transactions
                )
                covered_transaction_count = sum(
                    transaction.created_at.date() <= cutoff_date
                    and transaction.id in transaction_snapshots
                    for transaction in transactions
                )
                transaction_history_coverage.append(
                    100.0
                    if eligible_transaction_count == 0
                    else covered_transaction_count / eligible_transaction_count * 100
                )
                cutoff_daily_spend = self._daily_spend_for_cutoff(
                    transactions,
                    as_of=cutoff_date,
                    currency=user_context.currency,
                    snapshots=transaction_snapshots,
                )
                prior_keys = [
                    (prior_year, prior_month)
                    for offset in range(-6, 0)
                    for prior_month, prior_year in [_shift_month(month, year, offset)]
                ]
                prior_spend = [
                    total
                    for prior_key in prior_keys
                    if (total := max(sum(cutoff_daily_spend[prior_key].values()), 0.0)) > 0
                ]
                if len(prior_spend) < 3:
                    continue
                historical_median = statistics.median(prior_spend)
                historical_mad = statistics.median(
                    abs(value - historical_median) for value in prior_spend
                )
                spend_through_cutoff = max(
                    sum(amount for day, amount in cutoff_daily_spend[key].items() if day <= cutoff),
                    0.0,
                )
                pace_projection = spend_through_cutoff / cutoff * days_in_month
                temporal_expected_outflows = 0.0
                temporal_conflicted_outflows = 0.0
                temporal = await TemporalEventService(self.db).timeline(
                    user_id,
                    range_start=date(year, month, 1),
                    range_end=date(year, month, days_in_month),
                    as_of=cutoff_date,
                    historical_safe=True,
                )
                for event in temporal.events:
                    amount = event.amount.expected
                    if (
                        amount is None
                        or event.expected_date <= cutoff_date
                        or event.direction != "outflow"
                    ):
                        continue
                    if event.state == "conflict":
                        temporal_conflicted_outflows += amount
                    elif event.state in {"expected", "overdue", "missed"}:
                        temporal_expected_outflows += amount
                        temporal_event_count += 1
                if temporal_expected_outflows or temporal_conflicted_outflows:
                    temporal_evidence_periods += 1
                category_mix_baseline, _, category_mix_status = (
                    self._category_mix_baseline_from_transactions(
                        transactions,
                        transaction_snapshots,
                        month=month,
                        year=year,
                        as_of=cutoff_date,
                        currency=user_context.currency,
                    )
                )
                if category_mix_status in {"same_month_supported", "mix_supported"}:
                    category_mix_supported_periods += 1
                baseline_projection = max(
                    pace_projection,
                    historical_median,
                    spend_through_cutoff + temporal_expected_outflows,
                )
                projected_spend = max(
                    baseline_projection,
                    category_mix_baseline or 0.0,
                )
                if (
                    category_mix_baseline is not None
                    and category_mix_baseline >= baseline_projection
                ):
                    category_mix_applied_periods += 1
                range_width = (
                    max(
                        historical_mad * 1.4826,
                        projected_spend * 0.05,
                    )
                    + temporal_conflicted_outflows
                )
                absolute_error = abs(projected_spend - actual_spend)
                observations[requested_cutoff].append(
                    (
                        absolute_error,
                        absolute_error / actual_spend,
                        actual_spend,
                        (
                            1.0
                            if max(projected_spend - range_width, 0.0)
                            <= actual_spend
                            <= projected_spend + range_width
                            else 0.0
                        ),
                        range_width * 2,
                    )
                )
                month_evaluated = True
            if month_evaluated:
                evaluated_months += 1

        horizons: list[ForecastHorizonMetrics] = []
        for cutoff in cutoff_days:
            samples = observations[cutoff]
            if not samples:
                horizons.append(ForecastHorizonMetrics(cutoff_day=cutoff, eligible_periods=0))
                continue
            total_actual = sum(sample[2] for sample in samples)
            horizons.append(
                ForecastHorizonMetrics(
                    cutoff_day=cutoff,
                    eligible_periods=len(samples),
                    mean_absolute_error=round(statistics.mean(sample[0] for sample in samples), 2),
                    median_absolute_percentage_error=round(
                        statistics.median(sample[1] for sample in samples) * 100,
                        2,
                    ),
                    weighted_absolute_percentage_error=round(
                        sum(sample[0] for sample in samples) / total_actual * 100,
                        2,
                    ),
                    interval_coverage_pct=round(
                        statistics.mean(sample[3] for sample in samples) * 100,
                        2,
                    ),
                    interval_coverage_gap_pct=round(
                        abs(
                            statistics.mean(sample[3] for sample in samples) * 100
                            - FORECAST_INTERVAL_TARGET_COVERAGE_PCT
                        ),
                        2,
                    ),
                    average_interval_width=round(
                        statistics.mean(sample[4] for sample in samples), 2
                    ),
                )
            )

        return CashFlowBacktestReport(
            ruleset_version=CASH_FLOW.version,
            evaluation_version=CASH_FLOW_BACKTEST.version,
            as_of=today,
            requested_months=months,
            evaluated_months=evaluated_months,
            excluded_months=exclusions,
            horizons=horizons,
            interval_target_coverage_pct=FORECAST_INTERVAL_TARGET_COVERAGE_PCT,
            temporal_evidence_evaluated=evaluated_months > 0,
            temporal_evidence_periods=temporal_evidence_periods,
            temporal_event_count=temporal_event_count,
            transaction_history_evaluated=bool(transaction_history_coverage)
            and min(transaction_history_coverage, default=0.0) >= 95.0,
            transaction_history_cutoffs=transaction_history_cutoffs,
            transaction_history_coverage_pct=round(
                min(transaction_history_coverage, default=0.0),
                2,
            ),
            category_mix_supported_periods=category_mix_supported_periods,
            category_mix_applied_periods=category_mix_applied_periods,
            settled_transaction_count=settled_transaction_count,
            unsettled_transaction_count=unsettled_transaction_count,
            limitations=[
                "Metrics evaluate retained spend-ledger pace, historical-range behavior, and historical-safe transaction-derived temporal patterns.",
                f"Settled movement uses {settled_transaction_count} of {len(transactions)} retained transaction rows; {unsettled_transaction_count} pending, failed, or otherwise unsettled rows remain visible but do not contribute to spend.",
                f"Transaction creation-time and snapshot state was available for {transaction_history_cutoffs} historical cutoff evaluations with a minimum snapshot coverage of {min(transaction_history_coverage, default=0.0):.1f}%; legacy rows without a source snapshot fall back to their current retained state after the creation-time cutoff.",
                "Liability schedules now use versioned snapshots; other mutable status histories without source snapshots cannot yet be reconstructed as they were known at each historical cutoff and are excluded rather than leaked from the future.",
                "Temporal event amounts are floors or uncertainty widening signals; they are not treated as proof that a future payment will occur.",
                f"Category-mix calibration was supported for {category_mix_supported_periods} historical cutoff periods and changed the central projection in {category_mix_applied_periods}; weak category cohorts are left neutral.",
                "Current ledger corrections and review outcomes are applied; their historical decision time is not reconstructed.",
                "Periods with fewer than 3 prior observed-spend months or no observed spend are excluded.",
            ],
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

    async def month_comparison(
        self,
        user_id: str,
        month: int,
        year: int,
        *,
        current_income_spend: tuple[float, float] | None = None,
    ) -> MonthComparison:
        previous_month, previous_year = _prev_month(month, year)
        income, spend = (
            current_income_spend
            if current_income_spend is not None
            else await self.monthly_income_spend(user_id, month, year)
        )
        prev_income, prev_spend = await self.monthly_income_spend(
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
        income, spend = await self.monthly_income_spend(user_id, month, year)
        today = await user_financial_today(self.db, user_id)
        savings_rate = ((income - spend) / income * 100) if income > 0 else 0.0
        budget_adherence = await self._budget_adherence(user_id, month, year)
        quality = await self._data_quality_metrics(user_id, month, year)
        transaction_count = int(quality["transaction_count"])
        pending_count = int(quality["pending_count"])
        conflict_count = int(quality["conflict_count"])
        review_cleanliness = (
            max(0.0, 100.0 - pending_count / transaction_count * 100.0)
            if transaction_count
            else 100.0
        )
        patterns = recurring_patterns
        if patterns is None:
            period_end = date(year, month, calendar.monthrange(year, month)[1])
            patterns = await RecurringPatternService(self.db).analyze(
                user_id, as_of=min(period_end, today)
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

        if income == 0 and spend == 0 and quality["parse_confidence"] == 0:
            monthly_stability = 0.0
        observed_periods = sum(
            1 for period_income, period_spend in history if period_income or period_spend
        )
        if transaction_count:
            observed_periods += 1
        coverage_score = min(observed_periods / 4 * 100.0, 100.0)
        parsing_score = quality["parse_confidence"] * 65 + quality["merchant_confidence"] * 35
        conflict_cleanliness = (
            max(0.0, 100.0 - conflict_count / transaction_count * 100.0)
            if transaction_count
            else 0.0
        )
        review_score = review_cleanliness * 0.7 + conflict_cleanliness * 0.3

        period_end = date(year, month, calendar.monthrange(year, month)[1])
        evidence_cutoff = min(period_end, today)
        latest_transaction_date = quality["latest_transaction_date"]
        if isinstance(latest_transaction_date, date) and latest_transaction_date <= evidence_cutoff:
            stale_days = (evidence_cutoff - latest_transaction_date).days
            freshness_score = (
                100.0
                if stale_days <= 3
                else (
                    80.0
                    if stale_days <= 7
                    else 55.0 if stale_days <= 14 else max(10.0, 55.0 - (stale_days - 14) * 2.5)
                )
            )
        else:
            stale_days = None
            freshness_score = 0.0

        latest_sync_at = quality["latest_sync_at"]
        sync_status = quality["sync_status"]
        unprocessed_email_count = quality["unprocessed_email_count"]
        sync_age_days: int | None = None
        if latest_sync_at is not None:
            sync_instant = latest_sync_at
            if sync_instant.tzinfo is None:
                sync_instant = sync_instant.replace(tzinfo=UTC)
            sync_age_days = max(0, (datetime.now(UTC) - sync_instant.astimezone(UTC)).days)
            sync_score = (
                100.0
                if sync_age_days <= 1
                else (
                    80.0
                    if sync_age_days <= 3
                    else 55.0 if sync_age_days <= 7 else max(10.0, 55.0 - (sync_age_days - 7) * 5.0)
                )
            )
            freshness_score = min(freshness_score, sync_score)
        elif sync_status != "not_connected":
            freshness_score = min(freshness_score, 20.0)
        if sync_status in {"paused", "error", "disconnecting"}:
            freshness_score = min(freshness_score, 35.0)
        if unprocessed_email_count:
            freshness_score = min(freshness_score, 70.0)

        breakdown = self._data_confidence_breakdown(
            coverage_score=coverage_score,
            observed_periods=observed_periods,
            freshness_score=freshness_score,
            stale_days=stale_days,
            latest_transaction_date=latest_transaction_date,
            parsing_score=parsing_score,
            parse_confidence=quality["parse_confidence"],
            merchant_confidence=quality["merchant_confidence"],
            review_score=review_score,
            pending_count=pending_count,
            conflict_count=conflict_count,
            transaction_count=transaction_count,
            latest_sync_at=latest_sync_at,
            sync_status=sync_status,
            sync_age_days=sync_age_days,
            unprocessed_email_count=unprocessed_email_count,
        )
        data_confidence = (
            coverage_score * 0.25
            + freshness_score * 0.2
            + parsing_score * 0.4
            + review_score * 0.15
        )
        if income == 0 and spend == 0 and quality["parse_confidence"] == 0:
            data_confidence = 0.0
        score = int(round(max(0, min(monthly_stability, 100))))
        confidence_score = int(round(max(0, min(data_confidence, 100))))
        coverage = await self.source_coverage(user_id)
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
            data_confidence_breakdown=breakdown,
            data_confidence_ruleset_version=DATA_CONFIDENCE.version,
            source_coverage_score=coverage.overall_score,
            source_coverage_ruleset_version=coverage.ruleset_version,
            source_coverage=coverage.sources,
            data_sufficiency=cast(DataSufficiency, sufficiency),
            savings_rate=round(savings_rate, 1),
            budget_adherence=(round(budget_adherence, 1) if budget_adherence is not None else None),
            recurring_burden=round(recurring_burden, 1),
            review_cleanliness=round(review_cleanliness, 1),
            spending_volatility=round(spending_volatility, 1),
            ruleset_version=MONTHLY_STABILITY.version,
            signals=signals,
        )

    async def source_coverage(self, user_id: str) -> SourceCoverageResponse:
        """Describe observed source coverage without pretending it is provider completeness."""

        user = await self.db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise LookupError("User not found")

        now = datetime.now(UTC)

        def normalized_instant(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            instant = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            return instant.astimezone(UTC)

        def age_days(value: datetime | None) -> int | None:
            instant = normalized_instant(value)
            if instant is None:
                return None
            return max(0, (now - instant).days)

        def date_value(value: object) -> date | None:
            if isinstance(value, datetime):
                return value.date()
            return value if isinstance(value, date) else None

        def freshness_status(
            age: int | None,
            *,
            has_observations: bool,
            error: bool = False,
        ) -> SourceCoverageStatus:
            if error:
                return "error"
            if age is None:
                return "unknown" if not has_observations else "partial"
            if age <= 1:
                return "current"
            if age <= 7:
                return "partial"
            return "stale"

        gmail = await self.db.scalar(
            select(GmailAccount).where(GmailAccount.user_id == user_id).limit(1)
        )
        raw_bounds = await self.db.execute(
            select(
                func.count(RawEmail.id).label("raw_count"),
                func.min(RawEmail.received_at).label("coverage_start"),
                func.max(RawEmail.received_at).label("coverage_end"),
                func.coalesce(
                    func.sum(case((RawEmail.processed_flag.is_(True), 1), else_=0)), 0
                ).label("processed"),
            ).where(RawEmail.user_id == user_id)
        )
        raw_row = raw_bounds.one()
        raw_count = int(raw_row.raw_count or 0)
        processed_count = int(raw_row.processed or 0)
        latest_sync_run = await self.db.scalar(
            select(SyncRun)
            .where(
                SyncRun.user_id == user_id,
                SyncRun.status == SyncStatus.COMPLETED,
                SyncRun.end_time.is_not(None),
            )
            .order_by(SyncRun.end_time.desc())
            .limit(1)
        )
        latest_sync = latest_sync_run.end_time if latest_sync_run is not None else None
        open_failures = int(
            await self.db.scalar(
                select(func.count(ParseFailure.id)).where(
                    ParseFailure.email_id.in_(
                        select(RawEmail.id).where(RawEmail.user_id == user_id)
                    ),
                    ParseFailure.resolved.is_(False),
                )
            )
            or 0
        )
        sync_age = age_days(latest_sync)
        gmail_error = bool(gmail and gmail.auto_sync_status in {"error", "disconnecting"})
        gmail_score = 0
        if gmail is not None:
            freshness_score = (
                100
                if sync_age is not None and sync_age <= 1
                else (
                    80
                    if sync_age is not None and sync_age <= 3
                    else 55 if sync_age is not None and sync_age <= 7 else 20
                )
            )
            processing_score = round(processed_count / raw_count * 100) if raw_count else 25
            gmail_score = round(freshness_score * 0.7 + processing_score * 0.3)
        gmail_status = (
            "disconnected"
            if gmail is None
            else freshness_status(
                sync_age,
                has_observations=raw_count > 0,
                error=gmail_error,
            )
        )
        gmail_limitations = [
            "Gmail search and incremental history are not proof that the entire inbox was covered.",
            "Institution and card-specific layouts remain limited to their measured parser cohorts.",
        ]
        if latest_sync_run is not None and not latest_sync_run.coverage_complete:
            gmail_limitations.insert(
                0,
                "The latest provider query was truncated by its result cap; observed records are not a complete Gmail-history sample.",
            )
        if raw_count == 0:
            gmail_limitations.insert(
                0, "No retained source emails are available for this connector."
            )
        coverage_label = "unknown"
        if raw_count:
            coverage_label = (
                "known"
                if latest_sync_run is not None and latest_sync_run.coverage_complete
                else "partial"
            )
        coverage_evidence = (
            "Complete for the connector query"
            if latest_sync_run is not None and latest_sync_run.coverage_complete
            else (
                "Truncated at the configured cap"
                if latest_sync_run is not None and latest_sync_run.coverage_truncated
                else "No provider pagination evidence"
            )
        )
        gmail_source = SourceCoverage(
            key="gmail",
            label="Gmail source history",
            status=gmail_status,
            completeness=cast(SourceCoverageCompleteness, coverage_label),
            score=gmail_score,
            observed_count=raw_count,
            coverage_start=date_value(raw_row.coverage_start),
            coverage_end=date_value(raw_row.coverage_end),
            freshness_at=normalized_instant(latest_sync),
            freshness_age_days=sync_age,
            evidence=[
                EvidenceItem(label="Retained emails", value=str(raw_count)),
                EvidenceItem(label="Processed emails", value=str(processed_count)),
                EvidenceItem(label="Open parse failures", value=str(open_failures)),
                EvidenceItem(label="Provider query coverage", value=coverage_evidence),
                EvidenceItem(
                    label="Provider result estimate",
                    value=str(
                        latest_sync_run.coverage_result_size_estimate
                        if latest_sync_run is not None
                        else 0
                    ),
                ),
                EvidenceItem(
                    label="Connector status",
                    value=(gmail.auto_sync_status if gmail else "not connected"),
                ),
            ],
            limitations=gmail_limitations,
            remediation_label=("Sync recent activity" if gmail else "Connect Gmail"),
            remediation_target="inbox",
        )

        transaction_rows = list(
            await self.db.scalars(
                select(Transaction.transaction_date).where(Transaction.user_id == user_id)
            )
        )
        transaction_dates = [value for value in transaction_rows if isinstance(value, date)]
        active_months = {(value.year, value.month) for value in transaction_dates}
        latest_transaction_date = max(transaction_dates, default=None)
        history_score = min(len(active_months) * 25, 100)
        ledger_source = SourceCoverage(
            key="ledger",
            label="Owned ledger history",
            status=(
                "current" if history_score >= 80 else "partial" if transaction_dates else "unknown"
            ),
            completeness="unknown",
            score=history_score,
            observed_count=len(transaction_dates),
            coverage_start=min(transaction_dates, default=None),
            coverage_end=latest_transaction_date,
            evidence=[
                EvidenceItem(label="Transactions", value=str(len(transaction_dates))),
                EvidenceItem(label="Observed months", value=str(len(active_months))),
                EvidenceItem(
                    label="Latest transaction date",
                    value=(
                        latest_transaction_date.isoformat() if latest_transaction_date else "None"
                    ),
                ),
            ],
            limitations=[
                "The ledger shows records PFIS has received; it cannot infer missing provider history.",
                "Transfers, accounting adjustments, and ignored evidence remain visible but are not spend or income proof.",
            ],
            remediation_label="Import more history" if history_score < 80 else None,
            remediation_target="inbox" if history_score < 80 else None,
        )

        account_rows = list(
            await self.db.scalars(
                select(FinancialAccount).where(FinancialAccount.user_id == user_id)
            )
        )
        confirmed_accounts = sum(
            1 for account in account_rows if account.identity_status == "confirmed"
        )
        account_score = round(confirmed_accounts / len(account_rows) * 100) if account_rows else 0
        account_source = SourceCoverage(
            key="accounts",
            label="Account identity coverage",
            status=(
                "current"
                if account_rows and confirmed_accounts == len(account_rows)
                else "partial" if account_rows else "unknown"
            ),
            completeness="partial" if account_rows else "unknown",
            score=account_score,
            observed_count=len(account_rows),
            coverage_start=min(
                (account.created_at.date() for account in account_rows), default=None
            ),
            coverage_end=max(
                (account.updated_at.date() for account in account_rows if account.updated_at),
                default=None,
            ),
            evidence=[
                EvidenceItem(label="Owned accounts", value=str(len(account_rows))),
                EvidenceItem(label="Confirmed identities", value=str(confirmed_accounts)),
                EvidenceItem(
                    label="Unresolved identities",
                    value=str(len(account_rows) - confirmed_accounts),
                ),
            ],
            limitations=[
                "PFIS cannot know whether every external account has been connected.",
                "Unresolved identities are excluded from typed position and debt conclusions.",
            ],
            remediation_label="Review account identity" if account_score < 100 else None,
            remediation_target="plan" if account_score < 100 else None,
        )

        pipeline_count = raw_count + open_failures
        pipeline_score = round(processed_count / pipeline_count * 100) if pipeline_count else 0
        pipeline_source = SourceCoverage(
            key="pipeline",
            label="Ingestion processing coverage",
            status=(
                "current"
                if pipeline_count and open_failures == 0 and processed_count == raw_count
                else "partial" if pipeline_count else "unknown"
            ),
            completeness="known" if pipeline_count else "unknown",
            score=pipeline_score,
            observed_count=pipeline_count,
            freshness_at=normalized_instant(latest_sync),
            freshness_age_days=sync_age,
            evidence=[
                EvidenceItem(label="Processed", value=str(processed_count)),
                EvidenceItem(
                    label="Waiting for processing", value=str(raw_count - processed_count)
                ),
                EvidenceItem(label="Open parse failures", value=str(open_failures)),
            ],
            limitations=[
                "Processing completion does not establish parser correctness; quality remains cohort-measured.",
            ],
            remediation_label="Resolve pipeline backlog" if pipeline_score < 100 else None,
            remediation_target="inbox" if pipeline_score < 100 else None,
        )

        sources = [gmail_source, ledger_source, account_source, pipeline_source]
        weights = {"gmail": 0.25, "ledger": 0.4, "accounts": 0.2, "pipeline": 0.15}
        active_sources = [
            source
            for source in sources
            if source.observed_count > 0
            or source.key == "ledger"
            or (source.key == "gmail" and gmail is not None)
        ]
        total_weight = sum(weights[source.key] for source in active_sources)
        overall_score = (
            round(
                sum(source.score * weights[source.key] for source in active_sources) / total_weight
            )
            if total_weight
            else 0
        )
        return SourceCoverageResponse(
            as_of=now,
            overall_score=overall_score,
            sources=sources,
            assumptions=[
                "Coverage describes source records PFIS has observed, not the completeness of a provider inbox or account universe.",
                "A current connector can still have parser or institution-layout gaps; those are measured separately by parser quality cohorts.",
                "Unknown coverage is kept explicit instead of being promoted to a complete financial history.",
            ],
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
            income, spend = await self.monthly_income_spend(user_id, month, year)
            return income - spend
        if goal.goal_type == "category_reduction":
            return await self._category_current_spend(user_id, month, year, goal.target_key)
        patterns = await RecurringPatternService(self.db).analyze(user_id)
        return sum(
            pattern.monthly_equivalent
            for pattern in patterns
            if pattern.status in {"early", "mature", "missed"}
        )

    async def monthly_income_spend(
        self, user_id: str, month: int, year: int
    ) -> tuple[float, float]:
        result = await self.db.execute(
            select(
                func.coalesce(
                    func.sum(income_effect_expression()),
                    0,
                ).label("income"),
                func.coalesce(
                    func.sum(spend_effect_expression()),
                    0,
                ).label("spend"),
            ).where(
                Transaction.user_id == user_id,
                financial_activity_predicate(),
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
                await self.monthly_income_spend(user_id, historical_month, historical_year)
            )
        return history

    @staticmethod
    def _data_confidence_breakdown(
        *,
        coverage_score: float,
        observed_periods: int,
        freshness_score: float,
        stale_days: int | None,
        latest_transaction_date: date | None,
        parsing_score: float,
        parse_confidence: float,
        merchant_confidence: float,
        review_score: float,
        pending_count: int,
        conflict_count: int,
        transaction_count: int,
        latest_sync_at: datetime | None,
        sync_status: str,
        sync_age_days: int | None,
        unprocessed_email_count: int,
    ) -> list[DataConfidenceDimension]:
        def status(score: float) -> DataConfidenceStatus:
            return "strong" if score >= 80 else "watch" if score >= 55 else "limited"

        def action(score: float, label: str, target: str) -> tuple[str | None, str | None]:
            return (None, None) if score >= 80 else (label, target)

        coverage_action = action(coverage_score, "Import more history", "inbox")
        freshness_action = action(freshness_score, "Sync recent activity", "inbox")
        parsing_action = action(parsing_score, "Inspect uncertain records", "review")
        review_action = action(review_score, "Resolve review items", "review")
        if sync_status in {"paused", "error", "disconnecting"}:
            freshness_summary = (
                "The connected inbox needs attention; recent activity may be missing."
            )
        elif unprocessed_email_count:
            freshness_summary = f"{unprocessed_email_count} synced email(s) still need processing before totals settle."
        elif freshness_score >= 80:
            freshness_summary = (
                "Observed activity and the latest connector sync are close to the period boundary."
            )
        elif latest_transaction_date:
            freshness_summary = (
                "Recent activity or connector evidence may be missing from this view."
            )
        elif sync_status == "not_connected":
            freshness_summary = (
                "No live connector is connected; freshness reflects observed ledger activity only."
            )
        else:
            freshness_summary = "No activity was observed for this period."
        return [
            DataConfidenceDimension(
                key="coverage",
                label="History coverage",
                score=round(coverage_score),
                status=status(coverage_score),
                summary=(
                    "Enough active months are available for comparisons."
                    if coverage_score >= 80
                    else "Comparisons have only a short observed history."
                ),
                evidence=[
                    EvidenceItem(label="Active periods", value=f"{observed_periods} of 4 needed")
                ],
                remediation_label=coverage_action[0],
                remediation_target=coverage_action[1],
            ),
            DataConfidenceDimension(
                key="freshness",
                label="Evidence freshness",
                score=round(freshness_score),
                status=status(freshness_score),
                summary=freshness_summary,
                evidence=[
                    EvidenceItem(
                        label="Latest activity",
                        value=(
                            latest_transaction_date.isoformat()
                            if latest_transaction_date
                            else "None observed"
                        ),
                    ),
                    EvidenceItem(
                        label="Age at period boundary",
                        value=f"{stale_days} days" if stale_days is not None else "Unknown",
                    ),
                    EvidenceItem(label="Connector status", value=sync_status.replace("_", " ")),
                    EvidenceItem(
                        label="Last completed sync",
                        value=(
                            latest_sync_at.astimezone(UTC).isoformat()
                            if latest_sync_at is not None
                            else "None"
                        ),
                    ),
                    EvidenceItem(
                        label="Sync age",
                        value=f"{sync_age_days} days" if sync_age_days is not None else "Unknown",
                    ),
                    EvidenceItem(label="Waiting inbox records", value=str(unprocessed_email_count)),
                ],
                remediation_label=freshness_action[0],
                remediation_target=freshness_action[1],
            ),
            DataConfidenceDimension(
                key="parsing",
                label="Parsing quality",
                score=round(parsing_score),
                status=status(parsing_score),
                summary=(
                    "Amounts and merchant labels are consistently resolved."
                    if parsing_score >= 80
                    else "Some extracted fields need human confirmation."
                ),
                evidence=[
                    EvidenceItem(label="Field confidence", value=f"{parse_confidence * 100:.0f}%"),
                    EvidenceItem(
                        label="Merchant confidence", value=f"{merchant_confidence * 100:.0f}%"
                    ),
                ],
                remediation_label=parsing_action[0],
                remediation_target=parsing_action[1],
            ),
            DataConfidenceDimension(
                key="conflicts",
                label="Review & conflicts",
                score=round(review_score),
                status=status(review_score),
                summary=(
                    "No material review backlog is weakening this period."
                    if review_score >= 80
                    else "Unresolved records can change the month after review."
                ),
                evidence=[
                    EvidenceItem(label="Pending review", value=str(pending_count)),
                    EvidenceItem(label="Evidence conflicts", value=str(conflict_count)),
                    EvidenceItem(label="Observed records", value=str(transaction_count)),
                ],
                remediation_label=review_action[0],
                remediation_target=review_action[1],
            ),
        ]

    async def _data_quality_metrics(
        self, user_id: str, month: int, year: int
    ) -> _DataQualityMetrics:
        result = await self.db.execute(
            select(
                func.count(Transaction.id).label("transaction_count"),
                func.avg(Transaction.confidence_score).label("parse_confidence"),
                func.avg(Transaction.merchant_resolution_confidence).label("merchant_confidence"),
                func.coalesce(
                    func.sum(case((Transaction.reviewed_flag.is_(False), 1), else_=0)), 0
                ).label("pending_count"),
                func.coalesce(
                    func.sum(case((Transaction.review_outcome == "needs_review", 1), else_=0)), 0
                ).label("conflict_count"),
                func.max(Transaction.transaction_date).label("latest_transaction_date"),
            ).where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        row = result.one()
        gmail_account = await self.db.scalar(
            select(GmailAccount).where(GmailAccount.user_id == user_id).limit(1)
        )
        latest_completed_sync = await self.db.scalar(
            select(SyncRun.end_time)
            .where(
                SyncRun.user_id == user_id,
                SyncRun.status == SyncStatus.COMPLETED,
                SyncRun.end_time.is_not(None),
            )
            .order_by(SyncRun.end_time.desc())
            .limit(1)
        )
        unprocessed_email_count = int(
            await self.db.scalar(
                select(func.count(RawEmail.id)).where(
                    RawEmail.user_id == user_id,
                    RawEmail.processed_flag.is_(False),
                )
            )
            or 0
        )
        return {
            "transaction_count": int(row.transaction_count or 0),
            "parse_confidence": max(0.0, min(float(row.parse_confidence or 0), 1.0)),
            "merchant_confidence": max(0.0, min(float(row.merchant_confidence or 0), 1.0)),
            "pending_count": int(row.pending_count or 0),
            "conflict_count": int(row.conflict_count or 0),
            "latest_transaction_date": row.latest_transaction_date,
            "latest_sync_at": latest_completed_sync,
            "sync_status": (
                (gmail_account.auto_sync_status or "idle") if gmail_account else "not_connected"
            ),
            "unprocessed_email_count": unprocessed_email_count,
        }

    async def _merchant_spend_map(self, user_id: str, month: int, year: int) -> dict[str, float]:
        result = await self.db.execute(
            select(
                func.coalesce(
                    Transaction.merchant_normalized,
                    Transaction.merchant_raw,
                    literal_column("'Unknown'"),
                ).label("merchant"),
                func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
            )
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
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
            .having(func.sum(spend_effect_expression()) > 0)
        )
        return {_merchant_key(row.merchant).lower(): float(row.total or 0) for row in result.all()}

    async def _category_spend_map(
        self, user_id: str, month: int, year: int
    ) -> dict[str | None, float]:
        result = await self.db.execute(
            select(
                Transaction.category_id,
                func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
            )
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.category_id)
            .having(func.sum(spend_effect_expression()) > 0)
        )
        return {row.category_id: float(row.total or 0) for row in result.all()}

    async def _category_name_spend_map(
        self, user_id: str, month: int, year: int
    ) -> dict[str, float]:
        result = await self.db.execute(
            select(
                func.coalesce(Category.name, literal_column("'Uncategorized'")).label("category"),
                func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(func.coalesce(Category.name, literal_column("'Uncategorized'")))
            .having(func.sum(spend_effect_expression()) > 0)
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
                func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
                func.count(Transaction.id).label("transaction_count"),
            )
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
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
            .having(func.sum(spend_effect_expression()) > 0)
            .order_by(Transaction.category_id, func.sum(spend_effect_expression()).desc())
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
            spend_event_predicate(),
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        ]
        if target_key:
            conditions.append(
                or_(Transaction.category_id == target_key, Category.name == target_key)
            )
        result = await self.db.execute(
            select(func.coalesce(func.sum(spend_effect_expression()), 0))
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
