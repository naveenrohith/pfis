"""Privacy-safe aggregate evaluation for recommendation outcomes."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import RecommendationOutcome, RecommendationState
from app.schemas.guidance import (
    RecommendationEffectivenessCohort,
    RecommendationEffectivenessReport,
)

EFFECTIVENESS_RULESET_VERSION = "pfis-recommendation-effectiveness-1"
EFFECTIVENESS_WINDOW_DAYS = 180
MINIMUM_COHORT_OUTCOMES = 10
MINIMUM_COHORT_USERS = 5


@dataclass
class _CohortAccumulator:
    users: set[str] = field(default_factory=set)
    outcomes: list[str] = field(default_factory=list)
    measured: list[tuple[str, Decimal, str]] = field(default_factory=list)


class RecommendationEvaluationService:
    """Evaluate versioned recommendation cohorts without exposing small groups."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def effectiveness_report(self) -> RecommendationEffectivenessReport:
        generated_at = datetime.now(UTC)
        window_started_at = generated_at - timedelta(days=EFFECTIVENESS_WINDOW_DAYS)
        rows = (
            await self.db.execute(
                select(
                    RecommendationState.recommendation_type,
                    RecommendationState.guidance_ruleset_version,
                    RecommendationOutcome.outcome_ruleset_version,
                    RecommendationOutcome.metric_key,
                    RecommendationOutcome.metric_unit,
                    RecommendationOutcome.user_id,
                    RecommendationOutcome.outcome,
                    RecommendationOutcome.automatic_impact_value,
                )
                .join(
                    RecommendationState,
                    RecommendationState.id == RecommendationOutcome.decision_id,
                )
                .join(User, User.id == RecommendationOutcome.user_id)
                .where(
                    RecommendationOutcome.observed_at >= window_started_at,
                    RecommendationState.recommendation_type.is_not(None),
                    RecommendationState.guidance_ruleset_version.is_not(None),
                    User.is_active.is_(True),
                    User.deletion_started_at.is_(None),
                )
            )
        ).all()

        grouped: dict[tuple[str, str, str, str | None, str | None], _CohortAccumulator] = (
            defaultdict(_CohortAccumulator)
        )
        for row in rows:
            key = (
                row.recommendation_type,
                row.guidance_ruleset_version,
                row.outcome_ruleset_version,
                row.metric_key,
                row.metric_unit,
            )
            cohort = grouped[key]
            cohort.users.add(row.user_id)
            cohort.outcomes.append(row.outcome)
            if row.automatic_impact_value is not None and row.outcome != "not_completed":
                cohort.measured.append(
                    (row.user_id, Decimal(row.automatic_impact_value), row.outcome)
                )

        cohorts: list[RecommendationEffectivenessCohort] = []
        suppressed_cohort_count = 0
        for key, cohort in grouped.items():
            if (
                len(cohort.outcomes) < MINIMUM_COHORT_OUTCOMES
                or len(cohort.users) < MINIMUM_COHORT_USERS
            ):
                suppressed_cohort_count += 1
                continue
            cohorts.append(self._cohort_response(key, cohort))

        cohorts.sort(key=lambda item: (-item.sample_size, item.recommendation_type))
        return RecommendationEffectivenessReport(
            generated_at=generated_at,
            window_started_at=window_started_at,
            window_days=EFFECTIVENESS_WINDOW_DAYS,
            minimum_sample_size=MINIMUM_COHORT_OUTCOMES,
            minimum_unique_users=MINIMUM_COHORT_USERS,
            evidence_status="available" if cohorts else "insufficient_sample",
            eligible_outcome_count=sum(item.sample_size for item in cohorts),
            suppressed_cohort_count=suppressed_cohort_count,
            cohorts=cohorts,
            effectiveness_ruleset_version=EFFECTIVENESS_RULESET_VERSION,
        )

    @staticmethod
    def _cohort_response(
        key: tuple[str, str, str, str | None, str | None],
        cohort: _CohortAccumulator,
    ) -> RecommendationEffectivenessCohort:
        recommendation_type, guidance_version, outcome_version, metric_key, metric_unit = key
        completed = [item for item in cohort.outcomes if item != "not_completed"]
        measured_users = {item[0] for item in cohort.measured}
        measured_is_eligible = (
            len(cohort.measured) >= MINIMUM_COHORT_OUTCOMES
            and len(measured_users) >= MINIMUM_COHORT_USERS
        )

        measured_improvement_rate: float | None = None
        mean_automatic_impact: float | None = None
        user_measurement_agreement_rate: float | None = None
        measured_sample_size = 0
        if measured_is_eligible:
            measured_sample_size = len(cohort.measured)
            measured_improvement_rate = RecommendationEvaluationService._rate(
                sum(1 for _, impact, _ in cohort.measured if impact > 0), measured_sample_size
            )
            mean_automatic_impact = round(
                float(sum((impact for _, impact, _ in cohort.measured), Decimal(0)))
                / measured_sample_size,
                4,
            )
            comparable = [
                (impact, outcome)
                for _, impact, outcome in cohort.measured
                if outcome in {"helped", "no_change", "worse"}
            ]
            agreements = sum(
                1
                for impact, outcome in comparable
                if (outcome == "helped" and impact > 0)
                or (outcome == "no_change" and impact == 0)
                or (outcome == "worse" and impact < 0)
            )
            user_measurement_agreement_rate = RecommendationEvaluationService._rate(
                agreements, len(comparable)
            )

        return RecommendationEffectivenessCohort(
            recommendation_type=recommendation_type,
            guidance_ruleset_version=guidance_version,
            outcome_ruleset_version=outcome_version,
            metric_key=metric_key,
            metric_unit=metric_unit,
            sample_size=len(cohort.outcomes),
            unique_users=len(cohort.users),
            completed_rate=RecommendationEvaluationService._rate(
                len(completed), len(cohort.outcomes)
            ),
            helped_rate=RecommendationEvaluationService._rate(
                sum(1 for item in completed if item == "helped"), len(completed)
            ),
            measured_evidence_status=(
                "available" if measured_is_eligible else "insufficient_sample"
            ),
            measured_sample_size=measured_sample_size,
            measured_unique_users=len(measured_users),
            measured_improvement_rate=measured_improvement_rate,
            mean_automatic_impact=mean_automatic_impact,
            user_measurement_agreement_rate=user_measurement_agreement_rate,
        )

    @staticmethod
    def _rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None
