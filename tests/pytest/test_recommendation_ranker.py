"""Constraint-aware deterministic recommendation ranker tests."""

from datetime import date

from app.schemas.dashboard import RecommendationConsequence, WorkspaceRecommendation
from app.services.recommendation_ranker import (
    RANKER_RULESET_VERSION,
    RecommendationRankerContext,
    rank_recommendations,
)


def _recommendation(
    kind: str,
    *,
    identifier: str,
    title: str,
    amount: float | None = None,
    confidence: float = 0.8,
    urgency: str = "this_period",
    reversibility: str = "reversible",
) -> WorkspaceRecommendation:
    return WorkspaceRecommendation(
        id=identifier,
        type=kind,
        severity="warning",
        title=title,
        description="Review the evidence before acting.",
        action_label="Review",
        target="workspace",
        confidence=confidence,
        urgency=urgency,
        reversibility=reversibility,
        consequence=(
            RecommendationConsequence(
                metric="cash needed",
                unit="currency",
                low=amount,
                high=amount,
                currency="INR",
                basis="Test candidate impact.",
            )
            if amount is not None
            else None
        ),
    )


def _context(**overrides) -> RecommendationRankerContext:
    values = {
        "as_of": date(2026, 9, 25),
        "evidence_cutoff": date(2026, 9, 24),
        "available_liquidity": 1000.0,
        "safe_to_spend": 1000.0,
        "reserve_floor": 200.0,
    }
    values.update(overrides)
    return RecommendationRankerContext(**values)


def test_conflict_resolution_keeps_feasible_reserve_item_and_records_reason():
    pay_card = _recommendation(
        "pay_card_full",
        identifier="card-full",
        title="Pay card in full",
        amount=1200,
        urgency="now",
    )
    reserve = _recommendation(
        "reserve",
        identifier="reserve",
        title="Keep emergency reserve protected",
        amount=None,
        confidence=0.9,
    )

    ranked = rank_recommendations([pay_card, reserve], _context(safe_to_spend=900.0))

    assert ranked[0].id == "reserve"
    withheld = next(item for item in ranked if item.id == "card-full")
    assert withheld.recommendation_status == "withheld"
    assert any(check.name == "candidate_conflict" for check in withheld.constraint_checks)
    assert any(reason.code == "conflict_resolution" for reason in withheld.rank_reasons)


def test_liquidity_infeasible_action_is_safely_withheld():
    candidate = _recommendation(
        "debt_payment",
        identifier="debt",
        title="Pay extra toward debt",
        amount=700,
    )

    ranked = rank_recommendations([candidate], _context(safe_to_spend=500.0))

    assert ranked[0].recommendation_status == "withheld"
    assert ranked[0].ruleset_version == RANKER_RULESET_VERSION
    assert ranked[0].ranker_ruleset_version == RANKER_RULESET_VERSION
    liquidity = next(check for check in ranked[0].constraint_checks if check.name == "liquidity")
    assert liquidity.status == "failed"
    assert "exceeds available safe-to-spend" in liquidity.reason


def test_user_exclusion_is_honored():
    candidate = _recommendation(
        "recurring",
        identifier="recurring-review",
        title="Review subscriptions",
    )

    ranked = rank_recommendations(
        [candidate],
        _context(feedback_exclusions={"recurring": 1}),
    )

    assert ranked[0].recommendation_status == "excluded"
    assert ranked[0].rank_score == 0
    assert any(check.name == "user_exclusion" for check in ranked[0].constraint_checks)


def test_deterministic_ordering_uses_stable_tie_breakers():
    alpha = _recommendation("budget", identifier="b", title="Beta budget", confidence=0.8)
    bravo = _recommendation("budget", identifier="a", title="Alpha budget", confidence=0.8)

    first = rank_recommendations([alpha, bravo], _context())
    second = rank_recommendations([bravo, alpha], _context())

    assert [item.id for item in first] == ["a", "b"]
    assert [item.id for item in second] == ["a", "b"]


def test_missing_evidence_withholds_candidate_with_missing_evidence_list():
    candidate = _recommendation(
        "goal_contribution",
        identifier="goal",
        title="Move money to goal",
        amount=100,
    )

    ranked = rank_recommendations(
        [candidate],
        _context(evidence_cutoff=None, safe_to_spend=None, available_liquidity=None),
    )

    assert ranked[0].recommendation_status == "withheld"
    assert set(ranked[0].missing_evidence) >= {
        "evidence_cutoff",
        "available_liquidity",
        "reserve_liquidity",
    }
    assert any(check.name == "evidence_cutoff" for check in ranked[0].constraint_checks)


def test_ranker_returns_copies_and_preserves_input_ownership():
    candidate = _recommendation(
        "budget",
        identifier="budget",
        title="Food budget",
    )

    ranked = rank_recommendations([candidate], _context())

    assert ranked[0] is not candidate
    assert candidate.ranker_ruleset_version is None
    assert candidate.constraint_checks == []
    assert ranked[0].constraint_checks
