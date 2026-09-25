"""Deterministic constraint-aware ranking for recommendation candidates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.schemas.dashboard import WorkspaceRecommendation
from app.schemas.intelligence import RecommendationConstraintCheck, RecommendationRankReason

RANKER_RULESET_VERSION = "pfis-recs-1"

_CONSUMES_LIQUIDITY = {
    "card_payment",
    "debt_payment",
    "goal_contribution",
    "pay_card_full",
    "savings",
}
_PROTECTS_RESERVE = {"budget", "cash_reserve", "keep_reserve", "recurring", "reserve"}


@dataclass(frozen=True)
class RecommendationRankerContext:
    """Inputs required to rank candidates without database or clock access."""

    as_of: date
    evidence_cutoff: date | None
    available_liquidity: float | None = None
    safe_to_spend: float | None = None
    reserve_floor: float = 0.0
    alert_threshold_pct: float = 20.0
    excluded_ids: frozenset[str] = frozenset()
    excluded_types: frozenset[str] = frozenset()
    excluded_merchants: frozenset[str] = frozenset()
    excluded_categories: frozenset[str] = frozenset()
    feedback_exclusions: Mapping[str, int] = field(default_factory=dict)


def rank_recommendations(
    candidates: Sequence[WorkspaceRecommendation],
    context: RecommendationRankerContext,
) -> list[WorkspaceRecommendation]:
    """Return ranked copies with constraints, refusals, reasons, and stable ties."""

    ranked = [_rank_candidate(candidate, context) for candidate in candidates]
    ranked = _resolve_candidate_conflicts(ranked)
    ranked.sort(
        key=lambda item: (
            _status_order(item.recommendation_status),
            -(item.rank_score or 0.0),
            -(item.priority or 0),
            item.type,
            item.id or "",
            item.title,
        )
    )
    for index, item in enumerate(ranked):
        if item.recommendation_status == "ranked":
            item.priority = max(1, min(100, int(round((item.rank_score or 0) - index * 0.01))))
    return ranked


def _rank_candidate(
    candidate: WorkspaceRecommendation, context: RecommendationRankerContext
) -> WorkspaceRecommendation:
    item = candidate.model_copy(deep=True)
    item.ruleset_version = RANKER_RULESET_VERSION
    item.ranker_ruleset_version = RANKER_RULESET_VERSION
    item.evidence_cutoff = context.evidence_cutoff
    item.missing_evidence = []
    item.constraint_checks = []
    item.rank_reasons = []
    item.recommendation_status = "ranked"

    excluded_count = context.feedback_exclusions.get(item.type, 0)
    explicit_exclusion = _explicit_exclusion_reason(item, context)
    if explicit_exclusion is not None or excluded_count > 0:
        item.recommendation_status = "excluded"
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="user_exclusion",
                status="failed",
                reason=explicit_exclusion
                or "The user has explicitly dismissed or excluded this recommendation.",
            )
        )
        item.rank_reasons.append(
            RecommendationRankReason(
                code="user_exclusion",
                detail="User feedback suppresses repeated prompting.",
                weight=-100.0,
            )
        )

    _append_evidence_cutoff_check(item, context)
    urgency_score = _urgency_score(item, context.as_of)
    liquidity_score = _liquidity_score(item, context)
    reserve_score = _reserve_score(item, context)
    debt_score = _debt_interest_score(item)
    confidence_score = round(max(0.0, min(1.0, item.confidence)) * 20.0, 4)
    effort_score = _effort_score(item)
    reversibility_score = 8.0 if item.reversibility == "reversible" else 3.0
    conflict_penalty = _conflict_penalty(item)

    item.rank_reasons.extend(
        [
            RecommendationRankReason(
                code="urgency",
                detail=_urgency_detail(item, context.as_of),
                weight=urgency_score,
            ),
            RecommendationRankReason(
                code="liquidity",
                detail="Impact was compared with available safe-to-spend evidence.",
                weight=liquidity_score,
            ),
            RecommendationRankReason(
                code="reserve_protection",
                detail="Protected reserve and confirmed obligations are not spent down.",
                weight=reserve_score,
            ),
            RecommendationRankReason(
                code="debt_interest_cost",
                detail="Debt or interest-cost reduction is prioritized when explicit.",
                weight=debt_score,
            ),
            RecommendationRankReason(
                code="evidence_confidence",
                detail=f"Underlying evidence confidence is {item.confidence:.2f}.",
                weight=confidence_score,
            ),
            RecommendationRankReason(
                code="effort",
                detail="Smaller, lower-effort actions rank higher.",
                weight=effort_score,
            ),
            RecommendationRankReason(
                code="reversibility",
                detail=f"Action reversibility is {item.reversibility}.",
                weight=reversibility_score,
            ),
            RecommendationRankReason(
                code="candidate_conflicts",
                detail="Blocking and warning conflicts reduce rank deterministically.",
                weight=-conflict_penalty,
            ),
        ]
    )

    raw_score = (
        urgency_score
        + liquidity_score
        + reserve_score
        + debt_score
        + confidence_score
        + effort_score
        + reversibility_score
        - conflict_penalty
    )
    if item.recommendation_status == "excluded":
        raw_score = 0.0
    if item.missing_evidence and item.recommendation_status != "excluded":
        item.recommendation_status = "withheld"
    item.rank_score = round(max(0.0, min(100.0, raw_score)), 4)
    return item


def _append_evidence_cutoff_check(
    item: WorkspaceRecommendation, context: RecommendationRankerContext
) -> None:
    if context.evidence_cutoff is None:
        item.missing_evidence.append("evidence_cutoff")
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="evidence_cutoff",
                status="failed",
                reason="PFIS cannot rank this recommendation without an evidence cutoff.",
            )
        )
        return
    item.constraint_checks.append(
        RecommendationConstraintCheck(
            name="evidence_cutoff",
            status="passed",
            reason=f"Evidence is bounded through {context.evidence_cutoff.isoformat()}.",
        )
    )


def _urgency_score(item: WorkspaceRecommendation, as_of: date) -> float:
    days = _days_to_due(item, as_of)
    if days <= 0:
        return 20.0
    if days <= 3:
        return 17.0
    if days <= 7:
        return 13.0
    if days <= 30:
        return 8.0
    return 4.0


def _urgency_detail(item: WorkspaceRecommendation, as_of: date) -> str:
    days = _days_to_due(item, as_of)
    return f"Estimated action window is {max(days, 0)} day(s) from {as_of.isoformat()}."


def _days_to_due(item: WorkspaceRecommendation, as_of: date) -> int:
    due_date = item.freshness_as_of
    if due_date is None:
        due_date = {
            "now": as_of,
            "this_period": as_of + timedelta(days=7),
            "monitor": as_of + timedelta(days=30),
        }.get(item.urgency, as_of + timedelta(days=30))
    return (due_date - as_of).days


def _liquidity_score(item: WorkspaceRecommendation, context: RecommendationRankerContext) -> float:
    impact = _liquidity_impact(item)
    available = (
        context.safe_to_spend if context.safe_to_spend is not None else context.available_liquidity
    )
    if impact <= 0:
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="liquidity",
                status="passed",
                reason="This recommendation does not require spending available liquidity.",
            )
        )
        return 10.0
    if available is None:
        item.missing_evidence.append("available_liquidity")
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="liquidity",
                status="failed",
                reason="Available safe-to-spend evidence is missing.",
            )
        )
        return -20.0
    if impact > max(available, 0.0):
        item.recommendation_status = "withheld"
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="liquidity",
                status="failed",
                reason=(
                    f"Required amount {impact:.2f} exceeds available safe-to-spend "
                    f"{max(available, 0.0):.2f}."
                ),
            )
        )
        return -25.0
    item.constraint_checks.append(
        RecommendationConstraintCheck(
            name="liquidity",
            status="passed",
            reason=f"Required amount {impact:.2f} fits available safe-to-spend {available:.2f}.",
        )
    )
    return 14.0


def _reserve_score(item: WorkspaceRecommendation, context: RecommendationRankerContext) -> float:
    impact = _liquidity_impact(item)
    available = (
        context.safe_to_spend if context.safe_to_spend is not None else context.available_liquidity
    )
    if impact <= 0 or available is None:
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="reserve_protection",
                status="passed" if impact <= 0 else "failed",
                reason=(
                    "This action does not draw from protected reserves."
                    if impact <= 0
                    else "Reserve protection cannot be proved without liquidity evidence."
                ),
            )
        )
        if impact > 0:
            item.missing_evidence.append("reserve_liquidity")
        return 8.0 if impact <= 0 else -12.0
    remaining = available - impact
    if remaining < context.reserve_floor:
        item.recommendation_status = "withheld"
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="reserve_protection",
                status="failed",
                reason=(
                    f"Action would leave {remaining:.2f}, below protected reserve "
                    f"{context.reserve_floor:.2f}."
                ),
            )
        )
        return -22.0
    item.constraint_checks.append(
        RecommendationConstraintCheck(
            name="reserve_protection",
            status="passed",
            reason=f"Action leaves {remaining:.2f}, above protected reserve {context.reserve_floor:.2f}.",
        )
    )
    return 12.0


def _liquidity_impact(item: WorkspaceRecommendation) -> float:
    if item.type not in _CONSUMES_LIQUIDITY or item.consequence is None:
        return 0.0
    if item.consequence.unit != "currency":
        return 0.0
    return max(float(item.consequence.high), 0.0)


def _explicit_exclusion_reason(
    item: WorkspaceRecommendation, context: RecommendationRankerContext
) -> str | None:
    if item.id in context.excluded_ids:
        return "The user has explicitly excluded this recommendation."
    if item.type in context.excluded_types:
        return "The user has explicitly excluded this recommendation kind."
    target_text = f"{item.target} {item.title} {item.description}".casefold()
    if any(merchant and merchant in target_text for merchant in context.excluded_merchants):
        return "The user has excluded this merchant from recommendations."
    if any(category and category in target_text for category in context.excluded_categories):
        return "The user has excluded this category from recommendations."
    return None


def _debt_interest_score(item: WorkspaceRecommendation) -> float:
    text = f"{item.type} {item.title} {item.description}".casefold()
    if any(token in text for token in ("interest", "debt", "card", "minimum due", "late fee")):
        return 12.0
    return 2.0


def _effort_score(item: WorkspaceRecommendation) -> float:
    if item.type in {"review", "anomaly"}:
        return 10.0
    if item.type in {"budget", "recurring"}:
        return 8.0
    return 5.0


def _conflict_penalty(item: WorkspaceRecommendation) -> float:
    return sum(
        {"blocking": 25.0, "warning": 8.0, "info": 2.0}.get(conflict.severity, 0.0)
        for conflict in item.conflicts
    )


def _resolve_candidate_conflicts(
    candidates: Iterable[WorkspaceRecommendation],
) -> list[WorkspaceRecommendation]:
    ranked = list(candidates)
    reserve_candidates = [
        item
        for item in ranked
        if item.type in _PROTECTS_RESERVE and item.recommendation_status == "ranked"
    ]
    if not reserve_candidates:
        return ranked
    for item in ranked:
        if item.type not in _CONSUMES_LIQUIDITY or item.recommendation_status != "withheld":
            continue
        related = [candidate.id for candidate in reserve_candidates if candidate.id]
        item.constraint_checks.append(
            RecommendationConstraintCheck(
                name="candidate_conflict",
                status="failed",
                reason=(
                    "Conflicts with reserve-protecting recommendation while liquidity or reserve "
                    "constraints fail; keep the feasible reserve-protecting item."
                ),
            )
        )
        item.rank_reasons.append(
            RecommendationRankReason(
                code="conflict_resolution",
                detail=(
                    "Liquidity-infeasible action is withheld in favor of feasible "
                    f"reserve-protecting candidate(s): {', '.join(related) or 'available'}."
                ),
                weight=-30.0,
            )
        )
    return ranked


def _status_order(status: str) -> int:
    return {"ranked": 0, "withheld": 1, "excluded": 2}.get(status, 3)
