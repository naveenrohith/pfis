"""Conflict-aware, deterministic recommendation policy.

This module only enriches and ranks already-derived recommendations. It never
creates a financial estimate from missing Cash Plan or goal evidence.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

from app.schemas.dashboard import (
    RecommendationConflict,
    RecommendationConsequence,
    RecommendationGoalLink,
    RecommendationResolution,
    ReviewSummary,
    WorkspaceRecommendation,
)
from app.schemas.financial_position import CashPlanResponse
from app.schemas.intelligence import GoalResponse
from app.schemas.preferences import UserPreferencePolicy
from app.services.recommendation_ranker import (
    RecommendationRankerContext,
    rank_recommendations,
)


@dataclass(frozen=True)
class RecommendationFeedback:
    """Explicit user feedback eligible for bounded ranking and constraint adjustments."""

    completed_outcomes: int = 0
    helped: int = 0
    worse: int = 0
    no_change: int = 0
    not_relevant: int = 0
    not_feasible: int = 0
    too_risky: int = 0
    already_done: int = 0
    wrong_timing: int = 0

    @property
    def eligible(self) -> bool:
        return self.completed_outcomes >= 3

    @property
    def learning_status(self) -> Literal["insufficient_sample", "learning", "drift"]:
        """Describe whether feedback may adapt ranking or must freeze it.

        A small cohort never changes policy. Once the minimum sample exists,
        repeated negative outcomes are treated as drift and produce a bounded
        suppression signal rather than allowing positive feedback elsewhere to
        compensate for a safety regression.
        """

        if not self.eligible:
            return "insufficient_sample"
        if self.worse > self.helped:
            return "drift"
        return "learning"

    @property
    def adjustment(self) -> int:
        if not self.eligible:
            return 0
        return max(-6, min(6, round((self.helped - self.worse) / self.completed_outcomes * 6)))


def apply_recommendation_policy(
    recommendations: list[WorkspaceRecommendation],
    *,
    income: float,
    spend: float,
    budgets: Sequence[dict],
    recurring: Sequence[dict],
    review: ReviewSummary,
    cash_plan: CashPlanResponse | None,
    goals: Sequence[GoalResponse],
    currency: str,
    as_of: date,
    source_coverage_score: int = 0,
    feedback: dict[str, RecommendationFeedback] | None = None,
    preference_policy: UserPreferencePolicy | None = None,
) -> list[WorkspaceRecommendation]:
    """Attach bounded consequences, conflicts, and safe ranking signals."""

    recurring_total = sum(
        float(item.get("monthly_equivalent", item.get("avg_amount", 0))) for item in recurring
    )
    recurring_confidence = (
        sum(float(item.get("confidence", 0)) for item in recurring) / len(recurring)
        if recurring
        else 0.0
    )
    has_budget_action = any(item.type == "budget" for item in recommendations)
    has_recurring_action = any(item.type == "recurring" for item in recommendations)
    feedback = feedback or {}
    policy = preference_policy or UserPreferencePolicy()

    for recommendation in recommendations:
        recommendation.freshness_as_of = as_of
        recommendation.urgency = cast(
            Literal["now", "this_period", "monitor"],
            {
                "danger": "now",
                "warning": "this_period",
                "info": "monitor",
                "success": "monitor",
            }.get(recommendation.severity, "monitor"),
        )
        recommendation.reversibility = cast(
            Literal["reversible", "review_required"],
            "review_required" if recommendation.type in {"review", "anomaly"} else "reversible",
        )
        recommendation.confidence = _confidence(
            recommendation.type, review, recurring_confidence, income, spend
        )
        recommendation.consequence = _consequence(
            recommendation,
            income=income,
            spend=spend,
            budgets=budgets,
            recurring_total=recurring_total,
            currency=currency,
        )
        recommendation.smallest_action = _smallest_action(recommendation.type)
        recommendation.goal_links = _goal_links(
            recommendation, budgets=budgets, goals=goals, currency=currency
        )
        recommendation.conflicts = _conflicts(
            recommendation,
            recommendations=recommendations,
            review=review,
            cash_plan=cash_plan,
            goals=goals,
            consequence=recommendation.consequence,
            has_budget_action=has_budget_action,
            has_recurring_action=has_recurring_action,
            source_coverage_score=source_coverage_score,
        )
        recommendation.resolution = _resolution(
            recommendation,
            recommendations=recommendations,
            goals=goals,
            cash_plan=cash_plan,
        )
        recommendation.reason_codes = _reason_codes(recommendation)
        _priority(recommendation, income=income)
        _apply_feedback(recommendation, feedback.get(recommendation.type))

    return rank_recommendations(
        recommendations,
        RecommendationRankerContext(
            as_of=as_of,
            evidence_cutoff=as_of,
            available_liquidity=(
                float(getattr(cash_plan, "flexible_money", 0.0) or 0.0)
                if cash_plan is not None and getattr(cash_plan, "flexible_money", None) is not None
                else None
            ),
            safe_to_spend=(
                float(getattr(cash_plan, "flexible_money", 0.0) or 0.0)
                if cash_plan is not None and getattr(cash_plan, "flexible_money", None) is not None
                else None
            ),
            reserve_floor=(
                max(
                    float(getattr(cash_plan, "approved_reserve_total", 0.0) or 0.0),
                    policy.reserve_floor,
                )
                if cash_plan is not None
                else policy.reserve_floor
            ),
            alert_threshold_pct=policy.alert_threshold_pct,
            excluded_types=frozenset(
                [*policy.dismissed_recommendation_kinds, *policy.excluded_recommendation_types]
            ),
            excluded_merchants=frozenset(policy.excluded_merchants),
            excluded_categories=frozenset(policy.excluded_categories),
            feedback_exclusions={
                kind: values.not_relevant
                for kind, values in feedback.items()
                if values.not_relevant > 0
            },
        ),
    )


def _resolution(
    recommendation: WorkspaceRecommendation,
    *,
    recommendations: Sequence[WorkspaceRecommendation],
    goals: Sequence[GoalResponse],
    cash_plan: CashPlanResponse | None,
) -> RecommendationResolution:
    """Turn conflict signals into one deterministic next step.

    Ranking alone is not enough when an action is blocked by evidence or when
    several active goals compete for the same confirmed flexibility. The
    resolution is deliberately advisory: it never silently chooses a money
    movement or changes a user's goal.
    """

    blocking = [item for item in recommendation.conflicts if item.severity == "blocking"]
    warnings = [item for item in recommendation.conflicts if item.severity == "warning"]
    overlaps = [item for item in recommendation.conflicts if item.kind == "overlap"]
    related_ids = [
        item.id
        for item in recommendations
        if item.id
        and item.id != recommendation.id
        and (
            (recommendation.type == "savings" and item.type in {"budget", "recurring"})
            or (recommendation.type in {"budget", "recurring"} and item.type == "savings")
        )
    ]

    active_goals = [goal for goal in goals if goal.is_active]
    linked_goal_ids = {link.goal_id for link in recommendation.goal_links}
    competing_goals: list[GoalResponse] = []
    primary_goal: GoalResponse | None = None
    if (
        cash_plan is not None
        and cash_plan.readiness == "ready"
        and cash_plan.flexible_money is not None
        and linked_goal_ids
        and len(active_goals) > 1
    ):
        remaining_total = sum(
            max(float(goal.target_amount) - float(goal.current_amount), 0.0)
            for goal in active_goals
        )
        if remaining_total > max(float(cash_plan.flexible_money), 0.0):
            ordered_goals = sorted(active_goals, key=_goal_priority_key)
            primary_goal = ordered_goals[0]
            competing_goals = [goal for goal in ordered_goals if goal.id not in linked_goal_ids]

    if blocking:
        conflict = blocking[0]
        if conflict.code == "totals_need_review":
            next_step = "Confirm the uncertain records in Review before accepting this action."
        elif conflict.code == "cash_plan_incomplete":
            next_step = "Complete the Cash Plan evidence before accepting this action."
        elif conflict.code == "source_coverage_incomplete":
            next_step = "Sync or import more source history before accepting this action."
        else:
            next_step = "Resolve the blocking evidence conflict before accepting this action."
        return RecommendationResolution(
            status="blocked",
            label="Blocked until evidence is resolved",
            next_step=next_step,
            rationale=conflict.description,
            related_recommendation_ids=related_ids,
            primary_goal_id=primary_goal.id if primary_goal else None,
            competing_goal_ids=[goal.id for goal in competing_goals],
        )

    if competing_goals and primary_goal is not None:
        return RecommendationResolution(
            status="choose",
            label="Choose one priority",
            next_step=(
                f"Choose whether {primary_goal.label} comes first; keep the other goal(s) visible "
                "before committing the same flexible money twice."
            ),
            rationale=(
                "Confirmed flexible money is smaller than the remaining active-goal demands. "
                "PFIS surfaces the earliest goal as a deterministic starting point, but leaves "
                "the final priority with you."
            ),
            related_recommendation_ids=related_ids,
            primary_goal_id=primary_goal.id,
            competing_goal_ids=[goal.id for goal in competing_goals],
        )

    if overlaps:
        return RecommendationResolution(
            status="choose",
            label="Choose one reduction path",
            next_step="Choose one overlapping action and count its impact once.",
            rationale=overlaps[0].description,
            related_recommendation_ids=related_ids,
        )

    if warnings:
        return RecommendationResolution(
            status="needs_review",
            label="Review evidence before acting",
            next_step="Review the warning boundary, then decide whether this action still fits.",
            rationale=warnings[0].description,
            related_recommendation_ids=related_ids,
        )

    return RecommendationResolution(
        status="ready",
        label="Ready to review",
        next_step="Review the evidence and accept the smallest feasible step if it fits.",
        rationale="No blocking conflict or competing goal was detected.",
        related_recommendation_ids=related_ids,
    )


def _goal_priority_key(goal: GoalResponse) -> tuple[int, int, int, str]:
    """Order goals by explicit due date, then remaining need, then stable ID."""

    due_date_key = 0 if goal.target_year is not None and goal.target_month is not None else 1
    target_year = goal.target_year if goal.target_year is not None else 9999
    target_month = goal.target_month if goal.target_month is not None else 12
    remaining = max(float(goal.target_amount) - float(goal.current_amount), 0.0)
    return due_date_key, target_year * 100 + target_month, -round(remaining), goal.id


def _apply_feedback(
    recommendation: WorkspaceRecommendation, feedback: RecommendationFeedback | None
) -> None:
    if feedback is None:
        return
    adjustment = feedback.adjustment if feedback.eligible else 0
    constraint_adjustment = 0
    if feedback.not_feasible >= 2:
        constraint_adjustment -= 6
    if feedback.too_risky >= 2 and recommendation.type in {"anomaly", "review"}:
        constraint_adjustment -= 6
    if feedback.already_done >= 2:
        constraint_adjustment -= 3
    if feedback.wrong_timing >= 2:
        constraint_adjustment -= 2
    if feedback.not_relevant >= 2:
        constraint_adjustment -= 2
    if feedback.learning_status == "drift":
        # Drift is a freeze/rollback signal. Keep the recommendation visible
        # only when the current deterministic policy still requires it, and do
        # not let a reward in another outcome category offset the suppression.
        adjustment = -6
        recommendation.reason_codes.append("personalization_drift")
    else:
        adjustment = max(-6, min(6, adjustment + constraint_adjustment))
    if adjustment == 0:
        return
    recommendation.priority = max(1, min(100, recommendation.priority + adjustment))
    if feedback.eligible:
        recommendation.evidence.append(
            {
                "label": (
                    "Personalization drift"
                    if feedback.learning_status == "drift"
                    else "Personalization"
                ),
                "value": (
                    f"{feedback.completed_outcomes} explicit {recommendation.type} outcomes; "
                    + (
                        "adaptation frozen after negative-outcome drift"
                        if feedback.learning_status == "drift"
                        else "ranking adjustment capped at 6 points"
                    )
                ),
            }
        )
    if constraint_adjustment:
        recommendation.evidence.append(
            {
                "label": "Constraint feedback",
                "value": "Recent relevance, timing, feasibility, or risk feedback is reducing repeated prompts",
            }
        )


def _confidence(
    recommendation_type: str,
    review: ReviewSummary,
    recurring_confidence: float,
    income: float,
    spend: float,
) -> float:
    if recommendation_type == "review":
        return round(max(0.0, min(1.0, 1.0 - (review.avg_confidence or 0.0))), 4)
    if recommendation_type == "recurring":
        return round(max(0.0, min(1.0, recurring_confidence)), 4)
    if recommendation_type == "savings":
        return round(max(0.0, min(1.0, 0.9 if income > 0 and spend >= 0 else 0.5)), 4)
    if review.low_confidence_count:
        return 0.7
    return 0.8


def _consequence(
    recommendation: WorkspaceRecommendation,
    *,
    income: float,
    spend: float,
    budgets: Sequence[dict],
    recurring_total: float,
    currency: str,
) -> RecommendationConsequence | None:
    if recommendation.type == "review":
        count = max(1, len([code for code in recommendation.reason_codes if code == "review"]))
        # The title is the stable server-derived count; avoid trusting client text.
        digits = "".join(character for character in recommendation.title if character.isdigit())
        count = int(digits) if digits else count
        return RecommendationConsequence(
            metric="records needing confirmation",
            unit="records",
            low=1,
            high=float(count),
            basis="One correction may resolve one or more low-confidence records.",
        )
    if recommendation.type == "recurring":
        return RecommendationConsequence(
            metric="monthly commitment exposure",
            unit="currency",
            low=0,
            high=round(max(0.0, recurring_total), 2),
            currency=currency,
            basis="Avoidable amount is unknown until the user confirms which charges can change.",
        )
    if recommendation.type == "savings":
        shortfall = max(0.0, income * 0.10 - (income - spend))
        return RecommendationConsequence(
            metric="monthly savings shortfall to 10%",
            unit="currency",
            low=round(shortfall, 2),
            high=round(shortfall, 2),
            currency=currency,
            basis="Observed income and spend; no future income or category behavior is guessed.",
        )
    if recommendation.type == "budget":
        category = recommendation.title.split(" budget", 1)[0]
        budget = next((item for item in budgets if str(item.get("category", "")) == category), None)
        if budget is None:
            return None
        actual = float(budget.get("actual", 0))
        limit = float(budget.get("limit", 0))
        if actual >= limit:
            low = high = actual - limit
            basis = "Observed category spend already exceeds the configured monthly limit."
        else:
            low = 0
            high = limit - actual
            basis = "Remaining category headroom; future spend is not forecast in this range."
        return RecommendationConsequence(
            metric="category limit exposure",
            unit="currency",
            low=round(low, 2),
            high=round(high, 2),
            currency=currency,
            basis=basis,
        )
    return None


def _smallest_action(recommendation_type: str) -> str:
    return {
        "budget": "Pause one discretionary purchase in this category and recheck the limit.",
        "recurring": "Open one recurring charge and confirm whether you still use it.",
        "review": "Confirm one uncertain record before changing a financial plan.",
        "anomaly": "Confirm whether the unusual activity is expected before acting.",
        "savings": "Choose one discretionary reduction that fits your confirmed cash position.",
    }.get(recommendation_type, "Review the evidence before acting.")


def _goal_links(
    recommendation: WorkspaceRecommendation,
    *,
    budgets: Sequence[dict],
    goals: Sequence[GoalResponse],
    currency: str,
) -> list[RecommendationGoalLink]:
    category = recommendation.title.split(" budget", 1)[0].strip().lower()
    links: list[RecommendationGoalLink] = []
    for goal in goals:
        if not goal.is_active:
            continue
        target_key = (goal.target_key or "").strip().lower()
        supports = (
            (recommendation.type == "savings" and goal.goal_type == "savings")
            or (recommendation.type == "recurring" and goal.goal_type == "recurring_reduction")
            or (
                recommendation.type == "budget"
                and goal.goal_type == "category_reduction"
                and target_key == category
            )
        )
        if supports:
            links.append(
                RecommendationGoalLink(
                    goal_id=goal.id,
                    label=goal.label,
                    relationship="supports",
                    remaining_amount=round(max(goal.target_amount - goal.current_amount, 0), 2),
                    currency=currency,
                )
            )
    return links


def _conflicts(
    recommendation: WorkspaceRecommendation,
    *,
    recommendations: Sequence[WorkspaceRecommendation],
    review: ReviewSummary,
    cash_plan: CashPlanResponse | None,
    goals: Sequence[GoalResponse],
    consequence: RecommendationConsequence | None,
    has_budget_action: bool,
    has_recurring_action: bool,
    source_coverage_score: int,
) -> list[RecommendationConflict]:
    conflicts: list[RecommendationConflict] = []
    if (
        recommendation.type in {"budget", "recurring", "savings"}
        and review.low_confidence_count > 0
        and recommendation.type != "review"
    ):
        conflicts.append(
            RecommendationConflict(
                code="totals_need_review",
                kind="data_gap",
                severity="warning",
                title="Totals may change after review",
                description=(
                    f"{review.low_confidence_count} low-confidence record(s) can change the "
                    "amount behind this action. Confirm evidence before making a fixed plan."
                ),
                related_type="review",
            )
        )
    if recommendation.type in {"budget", "recurring", "savings"} and (
        cash_plan is None or cash_plan.readiness != "ready"
    ):
        conflicts.append(
            RecommendationConflict(
                code="cash_plan_incomplete",
                kind="data_gap",
                severity="warning" if recommendation.type != "savings" else "blocking",
                title="Confirmed cash position is incomplete",
                description=(
                    "PFIS cannot confirm how this action fits before the next income date "
                    "until the Cash Plan evidence is current."
                ),
                related_type="cash_plan",
            )
        )
    if recommendation.type in {"budget", "recurring", "savings"} and source_coverage_score < 55:
        conflicts.append(
            RecommendationConflict(
                code="source_coverage_incomplete",
                kind="data_gap",
                severity="blocking" if source_coverage_score < 35 else "warning",
                title="Source history is incomplete",
                description=(
                    "PFIS has limited observed source history, so this action may be based on an "
                    "incomplete view of income or spending."
                ),
                related_type="inbox",
            )
        )
    if (
        recommendation.type == "savings"
        and cash_plan is not None
        and cash_plan.readiness == "ready"
        and consequence is not None
        and cash_plan.flexible_money is not None
        and consequence.high > max(cash_plan.flexible_money, 0)
    ):
        conflicts.append(
            RecommendationConflict(
                code="protect_confirmed_obligations",
                kind="tradeoff",
                severity="blocking",
                title="Protect confirmed obligations first",
                description=(
                    "The savings shortfall is larger than the flexible money PFIS can confirm "
                    "before the next income date; do not fund the gap from protected obligations."
                ),
                related_type="cash_plan",
            )
        )
    if recommendation.type == "savings" and (has_budget_action or has_recurring_action):
        related = "budget" if has_budget_action else "recurring"
        conflicts.append(
            RecommendationConflict(
                code="impact_overlap",
                kind="overlap",
                severity="info",
                title="Actions may target the same money",
                description=(
                    "Count one spending reduction once; this action can overlap with the "
                    f"{related} recommendation."
                ),
                related_type=related,
            )
        )
    if recommendation.type == "savings" and cash_plan is not None:
        for goal in goals:
            if goal.is_active and goal.goal_type == "savings":
                remaining = max(goal.target_amount - goal.current_amount, 0)
                if cash_plan.flexible_money is not None and remaining > max(
                    cash_plan.flexible_money, 0
                ):
                    conflicts.append(
                        RecommendationConflict(
                            code="goal_exceeds_flexible_money",
                            kind="tradeoff",
                            severity="warning",
                            title="Goal is larger than confirmed flexible money",
                            description=(
                                f"{goal.label} still needs more than the flexible money PFIS "
                                "can safely allocate before the next income date."
                            ),
                            related_goal_id=goal.id,
                        )
                    )
    return conflicts


def _reason_codes(recommendation: WorkspaceRecommendation) -> list[str]:
    values = [recommendation.type, recommendation.severity]
    values.extend(conflict.code for conflict in recommendation.conflicts)
    values.extend(f"goal_{link.relationship}" for link in recommendation.goal_links)
    return list(dict.fromkeys(values))


def _priority(recommendation: WorkspaceRecommendation, *, income: float) -> int:
    severity_points = {"danger": 30, "warning": 20, "info": 10, "success": 5}
    urgency_points = {"now": 25, "this_period": 18, "monitor": 10}
    materiality = 10.0
    if recommendation.consequence is not None:
        if recommendation.consequence.unit == "currency":
            materiality = min(30.0, recommendation.consequence.high / max(income, 1) * 100)
        elif recommendation.consequence.unit == "records":
            materiality = min(30.0, recommendation.consequence.high * 4)
        else:
            materiality = min(30.0, recommendation.consequence.high * 2)
    penalty = sum(
        {"blocking": 20, "warning": 7, "info": 1}[item.severity]
        for item in recommendation.conflicts
    )
    goal_bonus = min(8, len(recommendation.goal_links) * 4)
    score = (
        materiality
        + recommendation.confidence * 20
        + severity_points.get(recommendation.severity, 10)
        + urgency_points.get(recommendation.urgency, 10)
        + 18
        + goal_bonus
        - penalty
    )
    recommendation.priority = int(round(max(1.0, min(100.0, score))))
    return recommendation.priority
