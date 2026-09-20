"""Deep branch coverage for bounded recommendation policy enrichment."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.schemas.dashboard import (
    RecommendationConflict,
    RecommendationGoalLink,
    ReviewSummary,
    WorkspaceRecommendation,
)
from app.schemas.financial_position import CashPlanResponse
from app.schemas.intelligence import GoalResponse
from app.services.recommendation_policy import (
    RecommendationFeedback,
    _resolution,
    apply_recommendation_policy,
)


def _recommendation(kind, *, title, severity="info", identifier=""):
    return WorkspaceRecommendation(
        id=identifier,
        type=kind,
        severity=severity,
        title=title,
        description="Review the evidence before acting.",
        action_label="Review",
        target="workspace",
        reason_codes=[kind],
    )


def _goal(
    identifier,
    label,
    *,
    month,
    year,
    amount=1000,
    current=0,
    goal_type="savings",
    target_key=None,
):
    return GoalResponse.model_construct(
        id=identifier,
        user_id="user-1",
        goal_type=goal_type,
        label=label,
        target_amount=amount,
        target_key=target_key,
        target_month=month,
        target_year=year,
        is_active=True,
        current_amount=current,
        progress_pct=0,
        status="tracking",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_policy_enriches_consequences_conflicts_goals_and_feedback():
    recommendations = [
        _recommendation("budget", title="Food budget", severity="warning", identifier="budget-1"),
        _recommendation(
            "recurring", title="Recurring charge", severity="info", identifier="recurring-1"
        ),
        _recommendation(
            "savings", title="Reduce discretionary spend", severity="danger", identifier="save-1"
        ),
        _recommendation(
            "review", title="Review 3 records", severity="danger", identifier="review-1"
        ),
        _recommendation(
            "anomaly", title="Unexpected activity", severity="warning", identifier="anomaly-1"
        ),
    ]
    cash_plan = CashPlanResponse.model_construct(readiness="ready", flexible_money=50.0)
    goal = _goal("goal-1", "Emergency fund", month=10, year=2026, amount=500, current=0)

    enriched = apply_recommendation_policy(
        recommendations,
        income=1000,
        spend=1000,
        budgets=[{"category": "Food", "actual": 150, "limit": 100}],
        recurring=[{"monthly_equivalent": 200, "confidence": 0.8}],
        review=ReviewSummary(low_confidence_count=2, avg_confidence=0.4),
        cash_plan=cash_plan,
        goals=[goal],
        currency="INR",
        as_of=date(2026, 9, 20),
        source_coverage_score=20,
        feedback={
            "budget": RecommendationFeedback(
                completed_outcomes=4,
                helped=4,
                not_feasible=2,
                already_done=2,
                wrong_timing=2,
                not_relevant=2,
            )
        },
    )

    by_type = {item.type: item for item in enriched}
    assert by_type["budget"].consequence.high == 50
    assert by_type["recurring"].consequence.high == 200
    assert by_type["review"].consequence.high == 3
    assert by_type["anomaly"].consequence is None
    assert by_type["anomaly"].reversibility == "review_required"
    assert by_type["savings"].resolution.status == "blocked"
    assert {item.code for item in by_type["savings"].conflicts} >= {
        "source_coverage_incomplete",
        "protect_confirmed_obligations",
        "impact_overlap",
        "goal_exceeds_flexible_money",
    }
    assert by_type["budget"].evidence[-1]["label"] == "Constraint feedback"
    assert all(item.freshness_as_of == date(2026, 9, 20) for item in enriched)


def test_resolution_covers_competing_goals_warning_overlap_and_blocking_codes():
    recommendation = _recommendation("savings", title="Save more", identifier="save-1")
    recommendation.goal_links = [
        RecommendationGoalLink(
            goal_id="goal-1", label="Earliest goal", relationship="supports", remaining_amount=1000
        )
    ]
    other = _recommendation("budget", title="Food budget", identifier="budget-1")
    goals = [
        _goal("goal-1", "Earliest goal", month=9, year=2026),
        _goal("goal-2", "Later goal", month=12, year=2026),
    ]
    cash_plan = CashPlanResponse.model_construct(readiness="ready", flexible_money=50.0)

    competing = _resolution(
        recommendation,
        recommendations=[recommendation, other],
        goals=goals,
        cash_plan=cash_plan,
    )
    assert competing.status == "choose"
    assert competing.primary_goal_id == "goal-1"
    assert competing.competing_goal_ids == ["goal-2"]
    assert competing.related_recommendation_ids == ["budget-1"]

    warning = RecommendationConflict(
        code="totals_need_review",
        kind="data_gap",
        severity="warning",
        title="Review totals",
        description="Some totals are uncertain.",
    )
    recommendation.conflicts = [warning]
    needs_review = _resolution(
        recommendation,
        recommendations=[recommendation],
        goals=[],
        cash_plan=None,
    )
    assert needs_review.status == "needs_review"

    overlap = RecommendationConflict(
        code="impact_overlap",
        kind="overlap",
        severity="info",
        title="Overlap",
        description="Count the reduction once.",
    )
    recommendation.conflicts = [overlap]
    choose = _resolution(
        recommendation,
        recommendations=[recommendation],
        goals=[],
        cash_plan=None,
    )
    assert choose.status == "choose"

    for code in ("cash_plan_incomplete", "source_coverage_incomplete", "other_blocking_code"):
        recommendation.conflicts = [
            RecommendationConflict(
                code=code,
                kind="data_gap",
                severity="blocking",
                title="Blocking evidence",
                description="Resolve the evidence boundary.",
            )
        ]
        blocked = _resolution(
            recommendation,
            recommendations=[recommendation],
            goals=[],
            cash_plan=None,
        )
        assert blocked.status == "blocked"


def test_policy_boundary_paths_keep_missing_budgets_and_goal_links_explicit():
    recommendations = [
        _recommendation("budget", title="Travel budget", identifier="budget-2"),
        _recommendation("recurring", title="Recurring charge", identifier="recurring-2"),
    ]
    goals = [
        _goal(
            "goal-category",
            "Travel cutback",
            month=11,
            year=2026,
            goal_type="category_reduction",
            target_key="travel",
        ),
        _goal(
            "goal-recurring",
            "Recurring cutback",
            month=11,
            year=2026,
            goal_type="recurring_reduction",
        ),
    ]

    enriched = apply_recommendation_policy(
        recommendations,
        income=2000,
        spend=1000,
        budgets=[],
        recurring=[],
        review=ReviewSummary(),
        cash_plan=None,
        goals=goals,
        currency="INR",
        as_of=date(2026, 9, 20),
        source_coverage_score=45,
    )
    by_type = {item.type: item for item in enriched}
    assert by_type["budget"].consequence is None
    assert [link.goal_id for link in by_type["budget"].goal_links] == ["goal-category"]
    assert [link.goal_id for link in by_type["recurring"].goal_links] == ["goal-recurring"]
    assert by_type["budget"].resolution.status == "needs_review"
    assert {item.code for item in by_type["budget"].conflicts} == {
        "cash_plan_incomplete",
        "source_coverage_incomplete",
    }
