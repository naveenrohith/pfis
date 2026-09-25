"""Transparent, deterministic personal-finance guidance."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Literal, cast

from sqlalchemy import extract, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.transaction import Transaction
from app.models.workspace import RecommendationOutcome, RecommendationState
from app.schemas.dashboard import RecommendationResolution, WorkspaceResponse
from app.schemas.guidance import (
    GuidanceAction,
    GuidanceBrief,
    GuidanceEvidence,
    GuidanceMetric,
    GuidancePeriod,
    GuidanceQueryResult,
    RecommendationEvidence,
    RecommendationFeedbackReason,
    RecommendationOutcomeCreate,
    RecommendationOutcomeKind,
    RecommendationOutcomeResponse,
    RecommendationStateResponse,
    RecommendationStateUpdate,
    RecommendationUserState,
)
from app.services.account_service import AccountService
from app.services.card_due_runway_service import CardDueRunwayService
from app.services.card_portfolio_payment_plan_service import CardPortfolioPaymentPlanService
from app.services.card_portfolio_upcoming_service import CardPortfolioUpcomingStateService
from app.services.card_upcoming_state_service import CardUpcomingStateService
from app.services.dashboard_service import WorkspaceService
from app.services.financial_clock import user_financial_today
from app.services.financial_position_service import FinancialPositionService
from app.services.guidance.query_planner import (
    READ_MODELS,
    GuidanceIntent,
    GuidanceQueryRefusal,
    TypedGuidanceQueryPlan,
    normalize_query,
    plan_guidance_query,
)
from app.services.insights_service import InsightsService
from app.services.intelligence_service import IntelligenceService
from app.services.knowledge.ruleset_registry import RECOMMENDATION_OUTCOME
from app.services.recommendation_utils import recommendation_id
from app.services.transaction_aggregates import (
    spend_effect_expression,
    spend_event_predicate,
)

RULESET_VERSION = "pfis-guidance-3"
QUERY_PLAN_VERSION = "pfis-guidance-query-plan-1"
SUPPORTED_EXAMPLES = [
    "How much did I spend this month?",
    "What is my current bank balance?",
    "Is it safe to spend before my next income?",
    "What is my current card outstanding?",
    "Can I pay my card and still cover upcoming cash needs?",
    "What happens next with my card?",
    "What is coming up across my cards?",
    "Compare minimum and total card payment plans",
    "When is my next card payment or statement close?",
    "What is my current net worth?",
    "Show recurring charges",
    "How are my budgets doing?",
    "Compare this month with last month",
    "How much did I spend at Coffee Bar?",
]


GuidanceQueryPlan = TypedGuidanceQueryPlan


_QUERY_EVIDENCE_SOURCES: dict[str, tuple[str, ...]] = {
    intent.value: sources for intent, sources in READ_MODELS.items()
} | {
    "bank_position_blocked": ("financial_accounts", "account_balance_sources"),
    "safe_to_spend_blocked": ("cash_plans", "financial_accounts"),
}


class GuidanceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def brief(self, user_id: str, period: GuidancePeriod, as_of: date) -> GuidanceBrief:
        workspace = await WorkspaceService(self.db).get_workspace(user_id, as_of.month, as_of.year)
        health = workspace.financial_health
        comparison = workspace.month_comparison
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
                    smallest_action=rec.smallest_action,
                    consequence=rec.consequence,
                    conflicts=rec.conflicts,
                    goal_links=rec.goal_links,
                    resolution=rec.resolution,
                    confidence=rec.confidence,
                    freshness_as_of=rec.freshness_as_of,
                    urgency=rec.urgency,
                    reversibility=rec.reversibility,
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
        query = normalize_query(raw_query)
        plan = self._query_plan(raw_query)
        if plan is None:
            return self._unsupported_query_result(month, year)
        if plan.intent == GuidanceIntent.CARD_DUE_AFFORDABILITY:
            return await self._card_due_affordability_query(user_id, plan, month, year, currency)
        if plan.intent == GuidanceIntent.CARD_UPCOMING_STATE:
            return await self._card_upcoming_state_query(user_id, month, year, currency)
        if plan.intent == GuidanceIntent.CARD_PORTFOLIO_UPCOMING:
            return await self._card_portfolio_upcoming_query(user_id, month, year, currency)
        if plan.intent == GuidanceIntent.CARD_PORTFOLIO_PAYMENT_PLAN:
            return await self._card_portfolio_payment_plan_query(user_id, month, year, currency)
        if plan.intent in {
            GuidanceIntent.SAFE_TO_SPEND,
            GuidanceIntent.CURRENT_NET_WORTH,
            GuidanceIntent.CARD_POSITION,
            GuidanceIntent.CARD_POSITIONS,
            GuidanceIntent.BANK_POSITION,
        }:
            return await self._current_position_query(user_id, query, month, year, currency)
        if plan.intent == GuidanceIntent.RECURRING_CHARGES:
            insights = await InsightsService(self.db).generate_insights(user_id, month, year)
            recurring = insights.get("recurring_payments", [])
            total = sum(
                float(item.get("monthly_equivalent", item.get("avg_amount", 0)))
                for item in recurring
            )
            return self._result(
                "recurring_charges",
                f"PFIS found {len(recurring)} recurring charge{'s' if len(recurring) != 1 else ''} averaging {self._money(total, currency)} per month.",
                [GuidanceMetric(label="Monthly recurring", value=self._money(total, currency))],
                month,
                year,
                ["Open recurring charges", "Review unused subscriptions"],
            )

        if plan.intent == GuidanceIntent.BUDGET_STATUS:
            rows = await IntelligenceService(self.db)._budget_adherence(user_id, month, year)
            if rows is None:
                return self._result(
                    "budget_status",
                    "No monthly budgets are configured yet, so PFIS has not calculated adherence.",
                    [GuidanceMetric(label="Budget adherence", value="Not configured")],
                    month,
                    year,
                    ["Open budgets", "Set a first category guardrail"],
                )
            return self._result(
                "budget_status",
                f"Your deterministic budget-adherence score is {rows:.0f}% for this month.",
                [GuidanceMetric(label="Budget adherence", value=f"{rows:.0f}%")],
                month,
                year,
                ["Open budgets", "Review categories over 80%"],
            )

        if plan.intent == GuidanceIntent.MONTH_COMPARISON:
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

        if plan.intent == GuidanceIntent.MERCHANT_SPEND and plan.slots.get("merchant"):
            merchant = plan.slots["merchant"]
            total = await self._merchant_total(user_id, month, year, merchant)
            return self._result(
                "merchant_spend",
                f"You spent {self._money(total, currency)} at merchants matching “{merchant}” in the selected month.",
                [GuidanceMetric(label="Merchant spend", value=self._money(total, currency))],
                month,
                year,
                ["Open transactions", "Review merchant details"],
            )

        if plan.intent in {
            GuidanceIntent.MONTHLY_SPEND,
            GuidanceIntent.MONTHLY_INCOME,
            GuidanceIntent.MONTHLY_SAVINGS,
        }:
            summary = await IntelligenceService(self.db).monthly_income_spend(user_id, month, year)
            income, spend = summary
            if plan.intent == GuidanceIntent.MONTHLY_INCOME:
                intent, value, label = "monthly_income", income, "Income"
            elif plan.intent == GuidanceIntent.MONTHLY_SAVINGS:
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

        return self._unsupported_query_result(month, year)

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
        if state is not None and state.state != data.state:
            outcome_exists = await self.db.scalar(
                select(RecommendationOutcome.id).where(
                    RecommendationOutcome.decision_id == state.id,
                    RecommendationOutcome.user_id == user_id,
                )
            )
            if outcome_exists is not None:
                raise ValueError(
                    "Recommendation decision is immutable after its outcome is recorded"
                )
        if data.state == "active":
            if state is None:
                raise LookupError("Recommendation decision not found")
            state.state = "active"
            state.snoozed_until = None
            state.decision_note = data.note
            state.decision_reason = None
            state.updated_at = datetime.now(UTC)
            await self.db.commit()
            await self.db.refresh(state)
            return self._state_response(state)

        now = datetime.now(UTC)
        if data.state == "snoozed" and data.snoozed_until and data.snoozed_until <= now:
            raise ValueError("Snooze resume time must be in the future")
        effective_as_of = data.as_of or await user_financial_today(self.db, user_id)
        workspace = await WorkspaceService(self.db).get_workspace(
            user_id, effective_as_of.month, effective_as_of.year
        )
        recommendation = next(
            (item for item in workspace.recommendations if item.id == rec_id), None
        )
        if recommendation is None:
            raise LookupError("Recommendation not found for the selected period")
        if data.state == "accepted" and recommendation.resolution.status == "blocked":
            raise ValueError(
                "Resolve the blocking recommendation evidence before accepting this action"
            )

        if state is None:
            state = RecommendationState(user_id=user_id, recommendation_id=rec_id, state=data.state)
            self.db.add(state)
        state.state = data.state
        state.snoozed_until = data.snoozed_until if data.state == "snoozed" else None
        state.recommendation_type = recommendation.type
        state.title = recommendation.title
        state.target = recommendation.target
        state.expected_impact = recommendation.expected_impact
        state.smallest_action = recommendation.smallest_action
        state.consequence_json = (
            json.dumps(recommendation.consequence.model_dump(), sort_keys=True)
            if recommendation.consequence
            else None
        )
        state.conflicts_json = json.dumps(
            [item.model_dump() for item in recommendation.conflicts],
            sort_keys=True,
            separators=(",", ":"),
        )
        state.goal_links_json = json.dumps(
            [item.model_dump() for item in recommendation.goal_links],
            sort_keys=True,
            separators=(",", ":"),
        )
        state.resolution_json = json.dumps(
            recommendation.resolution.model_dump(),
            sort_keys=True,
            separators=(",", ":"),
        )
        state.confidence = Decimal(str(recommendation.confidence))
        state.freshness_as_of = recommendation.freshness_as_of
        state.urgency = recommendation.urgency
        state.reversibility = recommendation.reversibility
        state.evidence_json = json.dumps(
            recommendation.evidence, sort_keys=True, separators=(",", ":")
        )
        state.reason_codes_json = json.dumps(
            recommendation.reason_codes, sort_keys=True, separators=(",", ":")
        )
        state.guidance_ruleset_version = RULESET_VERSION
        state.decision_as_of = effective_as_of
        state.decision_note = data.note
        state.decision_reason = data.reason or (
            "not_relevant" if data.state == "not_relevant" else None
        )
        metric = self._recommendation_metric(recommendation.type, workspace)
        state.baseline_metric_key = metric[0] if metric else None
        state.baseline_metric_value = metric[1] if metric else None
        state.baseline_metric_unit = metric[2] if metric else None
        state.decided_at = now
        state.updated_at = now
        await self.db.commit()
        await self.db.refresh(state)
        return self._state_response(state)

    async def list_decisions(self, user_id: str) -> list[RecommendationStateResponse]:
        rows = list(
            (
                await self.db.scalars(
                    select(RecommendationState)
                    .where(RecommendationState.user_id == user_id)
                    .order_by(RecommendationState.updated_at.desc())
                )
            ).all()
        )
        return [self._state_response(row) for row in rows]

    async def record_outcome(
        self,
        user_id: str,
        decision_id: str,
        data: RecommendationOutcomeCreate,
    ) -> RecommendationOutcomeResponse:
        decision = await self.db.scalar(
            select(RecommendationState).where(
                RecommendationState.id == decision_id,
                RecommendationState.user_id == user_id,
            )
        )
        if decision is None:
            raise LookupError("Recommendation decision not found")
        if decision.state != "accepted":
            raise ValueError("Only accepted recommendations can record an outcome")
        existing = await self.db.scalar(
            select(RecommendationOutcome).where(
                RecommendationOutcome.decision_id == decision_id,
                RecommendationOutcome.user_id == user_id,
            )
        )
        if existing is not None:
            if (
                existing.outcome != data.outcome
                or existing.note != data.note
                or existing.actual_impact_value != data.actual_impact_value
                or existing.actual_impact_unit != data.actual_impact_unit
            ):
                raise ValueError("Recommendation outcome is immutable once recorded")
            return self._outcome_response(existing)
        row = RecommendationOutcome(
            user_id=user_id,
            decision_id=decision_id,
            outcome=data.outcome,
            note=data.note,
            actual_impact_value=data.actual_impact_value,
            actual_impact_unit=data.actual_impact_unit,
            outcome_ruleset_version=RECOMMENDATION_OUTCOME.version,
        )
        if (
            decision.baseline_metric_key
            and decision.baseline_metric_value is not None
            and decision.decision_as_of is not None
            and decision.recommendation_type
        ):
            workspace = await WorkspaceService(self.db).get_workspace(
                user_id,
                decision.decision_as_of.month,
                decision.decision_as_of.year,
            )
            observed = self._recommendation_metric(decision.recommendation_type, workspace)
            if observed and observed[0] == decision.baseline_metric_key:
                lower_is_better = observed[0] in {
                    "budget_risk_count",
                    "monthly_recurring_amount",
                    "unresolved_review_count",
                }
                row.metric_key = observed[0]
                row.metric_unit = observed[2]
                row.baseline_metric_value = decision.baseline_metric_value
                row.observed_metric_value = observed[1]
                row.automatic_impact_value = (
                    decision.baseline_metric_value - observed[1]
                    if lower_is_better
                    else observed[1] - decision.baseline_metric_value
                )
        try:
            async with self.db.begin_nested():
                self.db.add(row)
                await self.db.flush()
        except IntegrityError as exc:
            concurrent = await self.db.scalar(
                select(RecommendationOutcome).where(
                    RecommendationOutcome.decision_id == decision_id,
                    RecommendationOutcome.user_id == user_id,
                )
            )
            if concurrent is None:
                raise
            if (
                concurrent.outcome != data.outcome
                or concurrent.note != data.note
                or concurrent.actual_impact_value != data.actual_impact_value
                or concurrent.actual_impact_unit != data.actual_impact_unit
            ):
                raise ValueError("Recommendation outcome is immutable once recorded") from exc
            row = concurrent
        await self.db.commit()
        return self._outcome_response(row)

    async def list_outcomes(self, user_id: str) -> list[RecommendationOutcomeResponse]:
        rows = list(
            (
                await self.db.scalars(
                    select(RecommendationOutcome)
                    .where(RecommendationOutcome.user_id == user_id)
                    .order_by(RecommendationOutcome.observed_at.desc())
                )
            ).all()
        )
        return [self._outcome_response(row) for row in rows]

    async def _hidden_recommendations(self, user_id: str) -> set[str]:
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(RecommendationState).where(RecommendationState.user_id == user_id)
        )
        hidden = set()
        for state in result.scalars().all():
            if state.state in {"dismissed", "accepted", "not_relevant"} or (
                state.state == "snoozed" and state.snoozed_until and state.snoozed_until > now
            ):
                hidden.add(state.recommendation_id)
        return hidden

    @staticmethod
    def _state_response(state: RecommendationState) -> RecommendationStateResponse:
        evidence = json.loads(state.evidence_json) if state.evidence_json else []
        reason_codes = json.loads(state.reason_codes_json) if state.reason_codes_json else []
        consequence = json.loads(state.consequence_json) if state.consequence_json else None
        conflicts = json.loads(state.conflicts_json) if state.conflicts_json else []
        goal_links = json.loads(state.goal_links_json) if state.goal_links_json else []
        resolution = json.loads(state.resolution_json) if state.resolution_json else None
        return RecommendationStateResponse(
            id=state.id,
            recommendation_id=state.recommendation_id,
            state=cast(RecommendationUserState, state.state),
            snoozed_until=state.snoozed_until,
            recommendation_type=state.recommendation_type,
            title=state.title,
            target=state.target,
            expected_impact=state.expected_impact,
            smallest_action=state.smallest_action,
            consequence=consequence,
            conflicts=conflicts,
            goal_links=goal_links,
            resolution=RecommendationResolution.model_validate(
                resolution
                or {
                    "status": "ready",
                    "label": "Ready to review",
                    "next_step": "Review the evidence before acting.",
                    "rationale": "This decision predates the persisted resolution contract.",
                }
            ),
            confidence=float(state.confidence or 0),
            freshness_as_of=state.freshness_as_of,
            urgency=cast(Literal["now", "this_period", "monitor"], state.urgency),
            reversibility=cast(Literal["reversible", "review_required"], state.reversibility),
            evidence=[RecommendationEvidence.model_validate(item) for item in evidence],
            reason_codes=reason_codes,
            guidance_ruleset_version=state.guidance_ruleset_version,
            decision_as_of=state.decision_as_of,
            decision_note=state.decision_note,
            decision_reason=(
                cast(RecommendationFeedbackReason, state.decision_reason)
                if state.decision_reason
                else None
            ),
            baseline_metric_key=state.baseline_metric_key,
            baseline_metric_value=(
                float(state.baseline_metric_value)
                if state.baseline_metric_value is not None
                else None
            ),
            baseline_metric_unit=state.baseline_metric_unit,
            decided_at=state.decided_at,
            updated_at=state.updated_at,
        )

    @staticmethod
    def _outcome_response(row: RecommendationOutcome) -> RecommendationOutcomeResponse:
        return RecommendationOutcomeResponse(
            id=row.id,
            decision_id=row.decision_id,
            outcome=cast(RecommendationOutcomeKind, row.outcome),
            note=row.note,
            actual_impact_value=(
                float(row.actual_impact_value) if row.actual_impact_value is not None else None
            ),
            actual_impact_unit=row.actual_impact_unit,
            baseline_metric_value=(
                float(row.baseline_metric_value) if row.baseline_metric_value is not None else None
            ),
            observed_metric_value=(
                float(row.observed_metric_value) if row.observed_metric_value is not None else None
            ),
            automatic_impact_value=(
                float(row.automatic_impact_value)
                if row.automatic_impact_value is not None
                else None
            ),
            metric_key=row.metric_key,
            metric_unit=row.metric_unit,
            outcome_ruleset_version=row.outcome_ruleset_version,
            observed_at=row.observed_at,
        )

    @staticmethod
    def _recommendation_metric(
        recommendation_type: str, workspace: WorkspaceResponse
    ) -> tuple[str, Decimal, str] | None:
        if recommendation_type == "review":
            return (
                "unresolved_review_count",
                Decimal(workspace.review_summary.low_confidence_count),
                "records",
            )
        if recommendation_type == "budget":
            return (
                "budget_risk_count",
                Decimal(workspace.snapshot.budget_risk_count),
                "records",
            )
        if recommendation_type == "recurring":
            total = sum(
                (
                    Decimal(str(item.get("monthly_equivalent", item.get("avg_amount", 0))))
                    for item in workspace.recurring_commitments
                ),
                Decimal(0),
            )
            return "monthly_recurring_amount", total, "currency"
        if recommendation_type == "savings" and workspace.snapshot.income > 0:
            rate = (
                Decimal(str(workspace.snapshot.savings))
                / Decimal(str(workspace.snapshot.income))
                * Decimal(100)
            )
            return "savings_rate", rate.quantize(Decimal("0.01")), "percentage_points"
        return None

    @staticmethod
    def _query_plan(query: str) -> GuidanceQueryPlan | None:
        """Classify only named, auditable intents before touching read models."""

        result = plan_guidance_query(query)
        if isinstance(result, GuidanceQueryRefusal):
            return None
        return result

    @staticmethod
    def _unsupported_query_result(month: int, year: int) -> GuidanceQueryResult:
        return GuidanceQueryResult(
            supported=False,
            answer="I can answer a defined set of finance questions without guessing.",
            filters={"month": month, "year": year},
            plan=[
                "Recognize a supported financial intent",
                "Select a typed read model and temporal cutoff",
                "Refuse when no grounded plan is available",
            ],
            uncertainty=[
                "No financial read model was queried because this question is outside the supported intent set."
            ],
            confidence=0.0,
            temporal_scope="selected_calendar_month",
            suggested_actions=["Choose one of the supported examples"],
            supported_examples=SUPPORTED_EXAMPLES,
            ruleset_version=RULESET_VERSION,
        )

    @staticmethod
    def _asks_card_portfolio_payment_plan(query: str) -> bool:
        """Recognize explicit comparisons of minimum- and total-due plans."""

        plan = GuidanceService._query_plan(query)
        return plan is not None and plan.intent == GuidanceIntent.CARD_PORTFOLIO_PAYMENT_PLAN

    @staticmethod
    def _asks_card_due_affordability(query: str) -> bool:
        """Recognize card-payment questions that require a due-date runway."""

        plan = GuidanceService._query_plan(query)
        return plan is not None and plan.intent == GuidanceIntent.CARD_DUE_AFFORDABILITY

    @staticmethod
    def _asks_card_portfolio_upcoming(query: str) -> bool:
        """Recognize explicit cross-card upcoming-state questions."""

        plan = GuidanceService._query_plan(query)
        return plan is not None and plan.intent == GuidanceIntent.CARD_PORTFOLIO_UPCOMING

    @staticmethod
    def _asks_card_upcoming_state(query: str) -> bool:
        """Recognize dated card-next-state questions without broad generation."""

        plan = GuidanceService._query_plan(query)
        return plan is not None and plan.intent == GuidanceIntent.CARD_UPCOMING_STATE

    async def _card_portfolio_upcoming_query(
        self,
        user_id: str,
        month: int,
        year: int,
        currency: str,
    ) -> GuidanceQueryResult:
        """Answer cross-card upcoming questions from per-card evidence."""

        portfolio = await CardPortfolioUpcomingStateService(self.db).upcoming(user_id)
        state_label = portfolio.state.replace("_", " ")
        if portfolio.state == "no_active_cards":
            answer = "No active credit-card accounts are confirmed, so PFIS cannot build a portfolio timeline."
            actions = ["Open Cards", "Confirm a credit-card account"]
            next_signal = "None"
            next_date = "Not available"
        else:
            due_text = (
                self._money(portfolio.issuer_total_due, currency)
                if portfolio.issuer_total_due is not None
                else "Unavailable"
            )
            due_coverage = (
                "complete"
                if portfolio.issuer_total_due_complete
                else f"partial ({portfolio.issuer_total_due_cards}/{portfolio.card_count} cards)"
            )
            if portfolio.next_event is None:
                next_signal = "None dated"
                next_date = "Not available"
                event_text = "no dated event is available"
            else:
                next_signal = portfolio.next_event.label
                next_date = portfolio.next_event.date.isoformat()
                event_text = (
                    f"the next signal is {portfolio.next_event.label} on {next_date} "
                    f"({portfolio.next_event.status} evidence)"
                )
            answer = (
                f"Across {portfolio.card_count} active cards, the portfolio state is {state_label}; "
                f"{event_text}. Known issuer total due is {due_text} ({due_coverage}). "
                "PFIS keeps each issuer's position separate and does not claim live total available credit."
            )
            if portfolio.state == "limit_pressure":
                actions = ["Open Card portfolio", "Reduce limit-risk spend", "Review payment plans"]
            elif portfolio.state == "target_pressure":
                actions = [
                    "Open Card portfolio",
                    "Review utilization targets",
                    "Review payment plans",
                ]
            elif portfolio.state == "payment_due":
                actions = ["Open Card portfolio", "Open Card due runway"]
            elif portfolio.state == "review_evidence":
                actions = ["Open Card portfolio", "Refresh card evidence"]
            else:
                actions = ["Open Card portfolio", "Review upcoming card events"]

        return self._result(
            "card_portfolio_upcoming",
            answer,
            [
                GuidanceMetric(label="Portfolio state", value=state_label),
                GuidanceMetric(label="Active cards", value=str(portfolio.card_count)),
                GuidanceMetric(
                    label="Known issuer total due",
                    value=(
                        self._money(portfolio.issuer_total_due, currency)
                        if portfolio.issuer_total_due is not None
                        else "Unavailable"
                    ),
                ),
                GuidanceMetric(label="Next dated signal", value=next_signal),
                GuidanceMetric(label="Next signal date", value=next_date),
                GuidanceMetric(
                    label="Cards needing review", value=str(portfolio.cards_needing_review)
                ),
                GuidanceMetric(label="Confidence", value=f"{portfolio.confidence:.0%}"),
            ],
            month,
            year,
            actions,
            confidence=portfolio.confidence,
            temporal_scope="current_card_cycle",
            evidence_cutoff=portfolio.as_of,
        )

    async def _card_portfolio_payment_plan_query(
        self,
        user_id: str,
        month: int,
        year: int,
        currency: str,
    ) -> GuidanceQueryResult:
        """Compare minimum- and total-due targets without recommending a payment."""

        portfolio = await CardPortfolioPaymentPlanService(self.db).compare(user_id)
        if portfolio.state == "no_active_cards":
            answer = "No active credit-card accounts are confirmed, so PFIS cannot compare payment plans."
            actions = ["Open Cards", "Confirm a credit-card account"]
        else:
            minimum = portfolio.minimum_due_plan
            total = portfolio.total_due_plan
            minimum_target = (
                self._money(minimum.issuer_payment_target_total, currency)
                if minimum.issuer_payment_target_total is not None
                else "Unavailable"
            )
            total_target = (
                self._money(total.issuer_payment_target_total, currency)
                if total.issuer_payment_target_total is not None
                else "Unavailable"
            )
            minimum_additional = (
                self._money(minimum.additional_payment_total, currency)
                if minimum.additional_payment_total is not None
                else "Unavailable"
            )
            total_additional = (
                self._money(total.additional_payment_total, currency)
                if total.additional_payment_total is not None
                else "Unavailable"
            )
            answer = (
                f"Across {portfolio.card_count} active cards, the minimum-due plan targets "
                f"{minimum_target} ({minimum.status.replace('_', ' ')}) and would require "
                f"{minimum_additional} beyond existing planned payments. The total-due plan "
                f"targets {total_target} ({total.status.replace('_', ' ')}) and would require "
                f"{total_additional} more. PFIS replays shared funding paths conservatively; "
                "these are planning scenarios, not payment instructions or live bank guarantees."
            )
            actions = ["Open Card payment plan", "Review funding accounts"]
            if portfolio.cards_needing_review:
                actions.append("Resolve card evidence")

        minimum = portfolio.minimum_due_plan
        total = portfolio.total_due_plan
        return self._result(
            "card_portfolio_payment_plan",
            answer,
            [
                GuidanceMetric(label="Plan state", value=portfolio.state.replace("_", " ")),
                GuidanceMetric(label="Active cards", value=str(portfolio.card_count)),
                GuidanceMetric(
                    label="Minimum-due target",
                    value=(
                        self._money(minimum.issuer_payment_target_total, currency)
                        if minimum.issuer_payment_target_total is not None
                        else "Unavailable"
                    ),
                ),
                GuidanceMetric(
                    label="Total-due target",
                    value=(
                        self._money(total.issuer_payment_target_total, currency)
                        if total.issuer_payment_target_total is not None
                        else "Unavailable"
                    ),
                ),
                GuidanceMetric(
                    label="Minimum additional",
                    value=(
                        self._money(minimum.additional_payment_total, currency)
                        if minimum.additional_payment_total is not None
                        else "Unavailable"
                    ),
                ),
                GuidanceMetric(
                    label="Total additional",
                    value=(
                        self._money(total.additional_payment_total, currency)
                        if total.additional_payment_total is not None
                        else "Unavailable"
                    ),
                ),
                GuidanceMetric(
                    label="Cards needing review", value=str(portfolio.cards_needing_review)
                ),
                GuidanceMetric(label="Confidence", value=f"{portfolio.confidence:.0%}"),
            ],
            month,
            year,
            actions,
            confidence=portfolio.confidence,
            temporal_scope="current_card_cycle",
            evidence_cutoff=portfolio.as_of,
        )

    async def _card_upcoming_state_query(
        self,
        user_id: str,
        month: int,
        year: int,
        currency: str,
    ) -> GuidanceQueryResult:
        """Answer dated card-next-state questions from the composed timeline."""

        cards = list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.account_type == "credit_card",
                    )
                )
            ).all()
        )
        if not cards:
            return self._result(
                "card_upcoming_state",
                "No active credit-card account is confirmed, so PFIS cannot build an upcoming card timeline.",
                [GuidanceMetric(label="Upcoming card state", value="Not available")],
                month,
                year,
                ["Open Cards", "Confirm a credit-card account"],
                confidence=0.0,
                temporal_scope="current_card_cycle",
            )
        if len(cards) > 1:
            return self._result(
                "card_upcoming_state",
                "You have more than one active card. Open Cards and choose the issuer so PFIS does not combine different due dates, limits, or statement cycles.",
                [GuidanceMetric(label="Active cards", value=str(len(cards)))],
                month,
                year,
                ["Open Cards", "Choose a card upcoming state"],
                confidence=0.0,
                temporal_scope="current_card_cycle",
            )

        card = cards[0]
        upcoming = await CardUpcomingStateService(self.db).upcoming(user_id, card.id)
        next_event = upcoming.next_event
        state_label = upcoming.state.replace("_", " ")
        if next_event is None:
            answer = (
                f"{card.institution_name}'s upcoming card state is {state_label}, but PFIS has no "
                "dated event it can safely show yet. Import or refresh evidence before treating "
                "the absence of an event as a clear cycle."
            )
            next_event_label = "None dated"
            next_event_date = "Not available"
        else:
            event_date = next_event.date.isoformat()
            relative = (
                "today"
                if next_event.days_from_today == 0
                else (
                    f"in {next_event.days_from_today} day"
                    f"{'s' if next_event.days_from_today != 1 else ''}"
                )
            )
            amount = (
                f" for {self._money(next_event.amount, currency)}"
                if next_event.amount is not None
                else ""
            )
            answer = (
                f"{card.institution_name}'s upcoming card state is {state_label}. The next dated "
                f"signal is {next_event.label}{amount} on {event_date} ({relative}); it is "
                f"{next_event.status} evidence from {next_event.source_kind}. PFIS is not submitting "
                "a payment or claiming live available credit."
            )
            next_event_label = next_event.label
            next_event_date = event_date

        if upcoming.state == "limit_pressure":
            actions = ["Reduce card spend", "Open Card projection", "Review a payment plan"]
        elif upcoming.state == "target_pressure":
            actions = ["Review utilization target", "Open Card projection", "Review a payment plan"]
        elif upcoming.state == "payment_due":
            actions = ["Open Card due runway", "Review card statement"]
        elif upcoming.state == "review_evidence":
            actions = ["Refresh card position", "Import the card statement"]
        else:
            actions = ["Open Card upcoming state", "Review Card projection"]

        return self._result(
            "card_upcoming_state",
            answer,
            [
                GuidanceMetric(label="Upcoming card state", value=state_label),
                GuidanceMetric(label="Next dated signal", value=next_event_label),
                GuidanceMetric(label="Next signal date", value=next_event_date),
                GuidanceMetric(label="Dated events", value=str(len(upcoming.events))),
                GuidanceMetric(label="Confidence", value=f"{upcoming.confidence:.0%}"),
            ],
            month,
            year,
            actions,
            confidence=upcoming.confidence,
            temporal_scope="current_card_cycle",
            evidence_cutoff=upcoming.as_of,
        )

    @staticmethod
    def _asks_current_position(query: str) -> bool:
        """Recognize questions that must use position evidence, not spend totals."""

        plan = GuidanceService._query_plan(query)
        return plan is not None and plan.intent in {
            GuidanceIntent.BANK_POSITION,
            GuidanceIntent.CARD_POSITION,
            GuidanceIntent.CARD_POSITIONS,
            GuidanceIntent.SAFE_TO_SPEND,
            GuidanceIntent.CURRENT_NET_WORTH,
        }

    async def _card_due_affordability_query(
        self,
        user_id: str,
        query: str | GuidanceQueryPlan,
        month: int,
        year: int,
        currency: str,
    ) -> GuidanceQueryResult:
        """Answer card-payment affordability from the due-runway read model.

        The runway is deliberately conservative: it compares the issuer-stated
        total due with the lower forecast band of a selected funding account.
        It never creates a payment, treats a statement as a live balance, or
        hides missing anchors and funding mappings.
        """

        cards = list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.account_type == "credit_card",
                    )
                )
            ).all()
        )
        if not cards:
            return self._result(
                "card_due_affordability",
                "No active credit-card account is confirmed, so PFIS cannot evaluate a payment runway.",
                [GuidanceMetric(label="Card due runway", value="Not available")],
                month,
                year,
                ["Open Cards", "Confirm a credit-card account"],
            )
        if len(cards) > 1:
            return self._result(
                "card_due_affordability",
                "You have more than one active card. Open Cards and choose the issuer so PFIS does not combine different due dates or funding paths.",
                [GuidanceMetric(label="Active cards", value=str(len(cards)))],
                month,
                year,
                ["Open Cards", "Choose a card due runway"],
            )

        card = cards[0]
        runway = await CardDueRunwayService(self.db).runway(user_id, card.id)
        if runway is None:
            return self._result(
                "card_due_affordability",
                "The selected card is no longer active, so PFIS did not make a payment conclusion.",
                [GuidanceMetric(label="Card due runway", value="Unavailable")],
                month,
                year,
                ["Refresh Cards", "Review account status"],
            )

        label = card.institution_name
        due_text = (
            self._money(runway.total_due, runway.currency)
            if runway.total_due is not None
            else "Unavailable"
        )
        due_date = runway.due_date.isoformat() if runway.due_date else "not available"
        conservative_cash = (
            self._money(runway.funding_balance_before_due_low, runway.currency)
            if runway.funding_balance_before_due_low is not None
            else "Unavailable"
        )
        gap = (
            self._money(runway.lower_band_cash_gap, runway.currency)
            if runway.lower_band_cash_gap is not None
            else "Unavailable"
        )
        confidence = f"{runway.confidence:.0%}"
        if runway.status == "covered":
            answer = (
                f"Based on the conservative funding path, {label} can cover the issuer-stated "
                f"total due of {due_text} by {due_date}. PFIS is not submitting a payment, "
                "and this is not a live bank or issuer guarantee."
            )
            actions = ["Open Card due runway", "Review the funding account"]
        elif runway.status == "at_risk":
            answer = (
                f"I would not treat {label}'s issuer-stated total due of {due_text} as safely "
                f"covered by {due_date}: the conservative path shows a shortfall of {gap}. "
                "Review the funding account or payment plan before acting."
            )
            actions = [
                "Open Card due runway",
                "Review the funding account",
                "Compare payment scenarios",
            ]
        elif runway.status == "needs_payment_account":
            answer = (
                f"{label} has an issuer-stated total due of {due_text} by {due_date}, but no "
                "funding account is selected. PFIS will not call the amount affordable without one."
            )
            actions = ["Choose a funding account", "Open Card due runway"]
        elif runway.status == "needs_statement":
            answer = (
                f"PFIS cannot evaluate {label}'s payment runway because no issuer statement total "
                "due is available. Import or confirm the statement first."
            )
            actions = ["Import the card statement", "Open Cards"]
        elif runway.status == "due_passed":
            answer = (
                f"{label}'s issuer due date has passed. PFIS will not assume that a payment settled "
                "or that the balance is safe until the account reports the next verified position."
            )
            actions = ["Review card activity", "Refresh the card position"]
        else:
            answer = (
                f"PFIS cannot safely conclude whether {label}'s total due of {due_text} is covered "
                f"by {due_date}. The runway is {runway.status.replace('_', ' ')} and needs review."
            )
            actions = ["Open Card due runway", "Review missing evidence"]

        return self._result(
            "card_due_affordability",
            answer,
            [
                GuidanceMetric(label="Issuer total due", value=due_text),
                GuidanceMetric(label="Due date", value=due_date),
                GuidanceMetric(label="Conservative cash before due", value=conservative_cash),
                GuidanceMetric(label="Lower-band shortfall", value=gap),
                GuidanceMetric(label="Runway state", value=runway.status.replace("_", " ")),
                GuidanceMetric(label="Confidence", value=confidence),
            ],
            month,
            year,
            actions,
        )

    async def _current_position_query(
        self,
        user_id: str,
        query: str | GuidanceQueryPlan,
        month: int,
        year: int,
        currency: str,
    ) -> GuidanceQueryResult:
        """Answer balance questions from the same read models as the UI.

        This is intentionally deterministic. It reports an estimate and its
        evidence state, or refuses a spendability conclusion when the position
        is incomplete; it never infers a provider-live balance from alerts.
        """

        if isinstance(query, TypedGuidanceQueryPlan):
            planned_intent = query.intent
            normalized_query = ""
        else:
            selected = self._query_plan(query)
            planned_intent = (
                selected.intent if selected is not None else GuidanceIntent.BANK_POSITION
            )
            normalized_query = normalize_query(query)

        position_service = FinancialPositionService(self.db)
        if planned_intent == GuidanceIntent.SAFE_TO_SPEND:
            plan = await position_service.cash_plan(user_id)
            if plan.readiness == "ready" and plan.flexible_money is not None:
                return self._result(
                    "safe_to_spend",
                    f"You can plan {self._money(plan.flexible_money, currency)} until "
                    f"{plan.next_income_date or 'the next confirmed income date'}. "
                    "This is a current-position estimate, not an issuer-live balance.",
                    [
                        GuidanceMetric(
                            label="Planning position",
                            value=self._money(
                                plan.planning_balance or plan.estimated_balance or 0, currency
                            ),
                        ),
                        GuidanceMetric(
                            label="Flexible money", value=self._money(plan.flexible_money, currency)
                        ),
                        GuidanceMetric(label="Position state", value=plan.position_status),
                    ],
                    month,
                    year,
                    ["Open Safe to spend", "Review confirmed commitments"],
                )
            reason = (
                plan.assumptions[0]
                if plan.assumptions
                else "Required position evidence is incomplete."
            )
            estimated = plan.estimated_balance
            return self._result(
                "safe_to_spend_blocked",
                "I cannot safely calculate spendable money yet. "
                f"{reason} The estimate remains visible for review, but it is not spendable.",
                [
                    GuidanceMetric(
                        label="Estimated position",
                        value=(
                            self._money(estimated, currency)
                            if estimated is not None
                            else "Unavailable"
                        ),
                    ),
                    GuidanceMetric(label="Readiness", value=plan.readiness),
                    GuidanceMetric(
                        label="Pending impact",
                        value=self._money(
                            (plan.pending_increase or 0) + (plan.pending_decrease or 0), currency
                        ),
                    ),
                ],
                month,
                year,
                ["Open Safe to spend", "Review uncertain activity", "Record a fresh balance"],
            )

        if planned_intent == GuidanceIntent.CURRENT_NET_WORTH:
            series = await AccountService(self.db).net_worth(user_id)
            status = series.current_position_status
            if status in {"observed", "estimated"}:
                label = "observed" if status == "observed" else "estimated"
                answer = (
                    f"Your current net worth is {self._money(series.net_worth, currency)} "
                    f"({label} position, as of {series.current_position_as_of or series.as_of})."
                )
            elif series.as_of is not None:
                answer = (
                    f"Your latest verified net worth is {self._money(series.net_worth, currency)} "
                    f"as of {series.as_of}, but I cannot call it current: {status}."
                )
            else:
                answer = (
                    "I cannot calculate net worth until each account has a verified observation."
                )
            return self._result(
                "current_net_worth",
                answer,
                [
                    GuidanceMetric(label="Assets", value=self._money(series.assets, currency)),
                    GuidanceMetric(
                        label="Liabilities", value=self._money(series.liabilities, currency)
                    ),
                    GuidanceMetric(label="Position state", value=status),
                ],
                month,
                year,
                ["Open Net worth", "Review account positions"],
            )

        if planned_intent in {GuidanceIntent.CARD_POSITION, GuidanceIntent.CARD_POSITIONS}:
            cards = list(
                (
                    await self.db.scalars(
                        select(FinancialAccount).where(
                            FinancialAccount.user_id == user_id,
                            FinancialAccount.is_active.is_(True),
                            FinancialAccount.account_type == "credit_card",
                        )
                    )
                ).all()
            )
            if not cards:
                return self._result(
                    "card_position",
                    "No active credit-card account is confirmed, so PFIS cannot calculate a card position.",
                    [GuidanceMetric(label="Card position", value="Not available")],
                    month,
                    year,
                    ["Open Verified position", "Confirm a credit-card account"],
                )
            overviews = [await position_service.card_overview(user_id, card.id) for card in cards]
            if len(overviews) == 1:
                card = cards[0]
                overview = overviews[0]
                provider_observed = (
                    overview.provider_current_outstanding is not None
                    and overview.provider_source == "connector"
                    and overview.provider_coverage_complete is True
                )
                estimated = (
                    overview.provider_current_outstanding
                    if provider_observed
                    else overview.estimated_current_balance
                )
                available_credit = (
                    overview.provider_available_credit
                    if provider_observed and overview.provider_available_credit is not None
                    else overview.available_credit_limit
                )
                today = await user_financial_today(self.db, user_id)
                stale = (
                    overview.observed_balance_as_of is not None
                    and overview.observed_balance_as_of < date.fromordinal(today.toordinal() - 7)
                )
                if "available credit" in normalized_query:
                    if available_credit is None:
                        answer = (
                            "This card has no issuer-reported available-credit observation, "
                            "so PFIS will not infer one from the credit limit."
                        )
                    else:
                        available_credit_as_of = (
                            overview.provider_current_outstanding_as_of
                            if provider_observed
                            else (overview.statement_date or overview.observed_balance_as_of)
                        )
                        available_credit_note = (
                            "the provider observation is inside its coverage window."
                            if provider_observed
                            else "it is not a live hold-aware amount."
                        )
                        answer = (
                            f"The {'provider-observed' if provider_observed else 'issuer-reported'} available credit is "
                            f"{self._money(available_credit, currency)} as of "
                            f"{available_credit_as_of}; {available_credit_note}"
                        )
                elif estimated is None:
                    answer = "This card has no verified statement anchor, so its current outstanding is unavailable."
                elif provider_observed:
                    answer = (
                        f"{card.institution_name} has a provider-observed current outstanding of "
                        f"{self._money(estimated, currency)} as of {overview.provider_current_outstanding_as_of}."
                    )
                elif stale:
                    answer = (
                        f"The last observed card balance was {self._money(estimated, currency)}, "
                        f"but its anchor is stale (as of {overview.observed_balance_as_of}); I cannot call it current."
                    )
                elif overview.balance_status == "needs_review":
                    answer = (
                        f"The card's estimated outstanding is {self._money(estimated, currency)}, "
                        "but activity needs review before PFIS treats the position as reliable."
                    )
                else:
                    answer = (
                        f"{card.institution_name} has an estimated current outstanding of "
                        f"{self._money(estimated, currency)} as of {overview.estimated_current_as_of}."
                    )
                return self._result(
                    "card_position",
                    answer,
                    [
                        GuidanceMetric(
                            label=(
                                "Provider current outstanding"
                                if provider_observed
                                else "Estimated outstanding"
                            ),
                            value=(
                                self._money(estimated, currency)
                                if estimated is not None
                                else "Unavailable"
                            ),
                        ),
                        GuidanceMetric(
                            label="Statement due",
                            value=(
                                self._money(overview.total_due, currency)
                                if overview.total_due is not None
                                else "Unavailable"
                            ),
                        ),
                        GuidanceMetric(
                            label="Issuer available credit",
                            value=(
                                self._money(available_credit, currency)
                                if available_credit is not None
                                else "Unavailable"
                            ),
                        ),
                        GuidanceMetric(
                            label="Position state",
                            value="stale" if stale else overview.balance_status,
                        ),
                    ],
                    month,
                    year,
                    ["Open Cards", "Review card activity"],
                )
            today = await user_financial_today(self.db, user_id)
            stale_cutoff = date.fromordinal(today.toordinal() - 7)
            provider_values = [
                (
                    item.provider_current_outstanding
                    if item.provider_source == "connector"
                    and item.provider_coverage_complete is True
                    else None
                )
                for item in overviews
            ]
            estimates = [
                provider_value if provider_value is not None else item.estimated_current_balance
                for item, provider_value in zip(overviews, provider_values, strict=True)
            ]
            provider_ready = all(value is not None for value in provider_values)
            current_ready = all(
                value is not None
                and (provider_value is not None or item.balance_status in {"observed", "estimated"})
                and not item.balance_reason_codes
                and (
                    provider_value is not None
                    or (
                        item.observed_balance_as_of is not None
                        and item.observed_balance_as_of >= stale_cutoff
                    )
                )
                for item, value, provider_value in zip(
                    overviews, estimates, provider_values, strict=True
                )
            )
            if "available credit" in normalized_query:
                answer = (
                    f"PFIS found {len(cards)} cards. Available credit is shown per issuer "
                    "statement; it is not safely totaled as a live amount."
                )
                total_text = "Per-card only"
            elif not current_ready:
                answer = (
                    f"PFIS found {len(cards)} cards, but not every card has a fresh, "
                    "reviewed outstanding position."
                )
                total_text = "Partial"
            else:
                total_text = self._money(sum(cast(float, value) for value in estimates), currency)
                answer = (
                    f"PFIS {'observed' if provider_ready else 'estimates'} total outstanding "
                    f"across {len(cards)} cards at {total_text}."
                )
            return self._result(
                "card_positions",
                answer,
                [
                    GuidanceMetric(label="Cards", value=str(len(cards))),
                    GuidanceMetric(
                        label=(
                            "Provider outstanding" if provider_ready else "Estimated outstanding"
                        ),
                        value=total_text,
                    ),
                    GuidanceMetric(
                        label="Needs review",
                        value=str(sum(item.balance_status == "needs_review" for item in overviews)),
                    ),
                ],
                month,
                year,
                ["Open Cards", "Review card activity"],
            )

        banks = list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.account_type == "bank",
                    )
                )
            ).all()
        )
        if not banks:
            return self._result(
                "bank_position",
                "No active bank account is confirmed, so PFIS cannot calculate current bank cash.",
                [GuidanceMetric(label="Bank position", value="Not available")],
                month,
                year,
                ["Open Verified position", "Confirm a bank account"],
            )
        today = await user_financial_today(self.db, user_id)
        stale_cutoff = date.fromordinal(today.toordinal() - 7)
        try:
            positions: list[Any] = [
                await position_service.account_position(user_id, bank.id) for bank in banks
            ]
        except ValueError:
            positions = []
            for bank in banks:
                snapshot = await self.db.scalar(
                    select(AccountBalanceSnapshot)
                    .where(
                        AccountBalanceSnapshot.user_id == user_id,
                        AccountBalanceSnapshot.financial_account_id == bank.id,
                        AccountBalanceSnapshot.verified.is_(True),
                    )
                    .order_by(
                        AccountBalanceSnapshot.as_of.desc(),
                        AccountBalanceSnapshot.effective_at.desc().nulls_last(),
                        AccountBalanceSnapshot.observed_at.desc(),
                        AccountBalanceSnapshot.created_at.desc(),
                    )
                    .limit(1)
                )
                positions.append(
                    SimpleNamespace(
                        estimated_balance=float(snapshot.amount),
                        position_status=(
                            "observed" if snapshot.source == "connector" else "estimated"
                        ),
                        observed_as_of=snapshot.as_of,
                        position_reason_codes=[],
                        observed_source=snapshot.source,
                        coverage_complete=snapshot.source == "connector",
                    )
                    if snapshot is not None
                    else None
                )
        eligible = [
            item
            for item in positions
            if item is not None
            and item.estimated_balance is not None
            and item.position_status in {"observed", "estimated"}
            and item.observed_as_of is not None
            and item.observed_as_of >= stale_cutoff
            and not item.position_reason_codes
        ]
        if len(eligible) != len(banks):
            return self._result(
                "bank_position_blocked",
                "I found bank activity, but I cannot safely total current cash until every bank position is verified and reconciled.",
                [
                    GuidanceMetric(label="Bank accounts", value=str(len(banks))),
                    GuidanceMetric(label="Eligible positions", value=str(len(eligible))),
                    GuidanceMetric(label="Position state", value="needs_review"),
                ],
                month,
                year,
                ["Open Verified position", "Review uncertain activity"],
            )
        total = sum(cast(float, item.estimated_balance) for item in eligible)
        provider_observed = all(
            item.observed_source == "connector" and item.coverage_complete is True
            for item in eligible
        )
        state = (
            "provider-observed"
            if provider_observed
            else (
                "estimated"
                if any(item.position_status == "estimated" for item in eligible)
                else "observed"
            )
        )
        return self._result(
            "bank_position",
            (
                f"Your current bank cash is {self._money(total, currency)} (provider-observed)."
                if provider_observed
                else f"Your current bank cash is {self._money(total, currency)} ({state}, not provider-live)."
            ),
            [
                GuidanceMetric(label="Current bank cash", value=self._money(total, currency)),
                GuidanceMetric(label="Bank accounts", value=str(len(banks))),
                GuidanceMetric(label="Position state", value=state),
            ],
            month,
            year,
            ["Open Verified position", "Open Safe to spend"],
        )

    async def _merchant_total(self, user_id: str, month: int, year: int, merchant: str) -> float:
        result = await self.db.execute(
            select(func.coalesce(func.sum(spend_effect_expression()), 0)).where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
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
        *,
        confidence: float | None = None,
        temporal_scope: str = "selected_calendar_month",
        evidence_cutoff: date | None = None,
    ) -> GuidanceQueryResult:
        source_types = _QUERY_EVIDENCE_SOURCES.get(intent, ("guidance_read_model",))
        period = f"{year}-{month:02d}"
        evidence = [
            GuidanceEvidence(
                source_type=source_type,
                source_id=f"{source_type}:{period}",
                label="Grounded source",
                value=f"{source_type} read model for {period} as of {evidence_cutoff or date(year, month, 1)}",
                cutoff=evidence_cutoff or date(year, month, 1),
            )
            for source_type in source_types
        ]
        uncertainty = [
            "The answer is limited to eligible records and observations available through the selected period.",
        ]
        if intent in {
            "bank_position",
            "bank_position_blocked",
            "card_position",
            "card_positions",
            "safe_to_spend",
            "safe_to_spend_blocked",
            "current_net_worth",
            "card_due_affordability",
            "card_upcoming_state",
            "card_portfolio_upcoming",
            "card_portfolio_payment_plan",
        }:
            uncertainty.append(
                "Provider freshness, coverage, and reconciliation state can make a position estimated or unavailable."
            )
        return GuidanceQueryResult(
            supported=True,
            intent=intent,
            answer=answer,
            metrics=metrics,
            filters={"month": month, "year": year},
            plan=[
                f"Classify typed intent {intent}",
                f"Read models: {', '.join(source_types)} with a {period} cutoff",
                "Constrain reads to the resolved owner scope",
                "Check arithmetic totals against returned metrics and selected temporal scope",
                "Return an actionable next step without performing a money movement",
            ],
            evidence=evidence,
            uncertainty=uncertainty,
            confidence=(
                confidence
                if confidence is not None
                else (
                    0.9
                    if intent not in {"safe_to_spend_blocked", "bank_position_blocked"}
                    else 0.45
                )
            ),
            temporal_scope=temporal_scope,
            suggested_actions=actions,
            supported_examples=SUPPORTED_EXAMPLES,
            ruleset_version=RULESET_VERSION,
        )
