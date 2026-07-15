"""Dashboard preference API contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WidgetSize = Literal["small", "medium", "large"]
ThemePreference = Literal["system", "light", "dark"]
DensityPreference = Literal["comfortable", "compact"]
OnboardingGoal = Literal["budgeting", "saving", "recurring_reduction", "cleanup"]


class DashboardWidget(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    visible: bool = True
    size: WidgetSize = "medium"


class DashboardPreferenceUpdate(BaseModel):
    layout_version: int | None = Field(None, ge=1)
    widgets: list[DashboardWidget] | None = None
    theme: ThemePreference | None = None
    density: DensityPreference | None = None
    favorites: list[str] | None = None
    onboarding_goal: OnboardingGoal | None = None


class DashboardPreferenceResponse(BaseModel):
    user_id: str
    layout_version: int
    widgets: list[DashboardWidget]
    theme: ThemePreference
    density: DensityPreference
    favorites: list[str]
    onboarding_goal: OnboardingGoal | None = None
    updated_at: datetime | None = None
