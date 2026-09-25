"""Dashboard preference API contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

WidgetSize = Literal["small", "medium", "large"]
ThemePreference = Literal["system", "light", "dark"]
DensityPreference = Literal["comfortable", "compact"]
OnboardingGoal = Literal["budgeting", "saving", "recurring_reduction", "cleanup"]
BriefingCadence = Literal["daily", "weekly", "monthly"]


class DashboardWidget(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    visible: bool = True
    size: WidgetSize = "medium"


class DashboardPreferenceUpdate(BaseModel):
    layout_version: int | None = Field(None, ge=1)
    widgets: list[DashboardWidget] | None = None
    theme: ThemePreference | None = None
    density: DensityPreference | None = None
    briefing_cadence: BriefingCadence | None = None
    favorites: list[str] | None = None
    onboarding_goal: OnboardingGoal | None = None


class DashboardPreferenceResponse(BaseModel):
    user_id: str
    layout_version: int
    widgets: list[DashboardWidget]
    theme: ThemePreference
    density: DensityPreference
    briefing_cadence: BriefingCadence
    favorites: list[str]
    onboarding_goal: OnboardingGoal | None = None
    updated_at: datetime | None = None


RecommendationKind = Literal[
    "anomaly",
    "budget",
    "card_payment",
    "cash_reserve",
    "debt_payment",
    "goal_contribution",
    "keep_reserve",
    "pay_card_full",
    "recurring",
    "reserve",
    "review",
    "savings",
]


class UserPreferencePolicy(BaseModel):
    alert_threshold_pct: float = Field(default=20.0, ge=1.0, le=100.0)
    briefing_cadence: BriefingCadence = "daily"
    reserve_floor: float = Field(default=0.0, ge=0.0, le=10_000_000.0)
    dismissed_recommendation_kinds: list[RecommendationKind] = Field(default_factory=list)
    excluded_recommendation_types: list[RecommendationKind] = Field(default_factory=list)
    excluded_merchants: list[str] = Field(default_factory=list, max_length=100)
    excluded_categories: list[str] = Field(default_factory=list, max_length=100)

    @field_validator(
        "dismissed_recommendation_kinds",
        "excluded_recommendation_types",
        "excluded_merchants",
        "excluded_categories",
    )
    @classmethod
    def _dedupe_values(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip().casefold()
            if not item or item in seen:
                continue
            seen.add(item)
            normalized.append(item)
        return normalized


class UserPreferencePolicyUpdate(UserPreferencePolicy):
    pass


class UserPreferencePolicyVersionResponse(BaseModel):
    id: str
    user_id: str
    version: int
    based_on_version: int | None = None
    policy: UserPreferencePolicy
    created_at: datetime | None = None


class UserPreferencePolicyRollbackRequest(BaseModel):
    version: int = Field(..., ge=1)
