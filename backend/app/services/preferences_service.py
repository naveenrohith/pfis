"""Persistence for user-owned dashboard preferences."""

import json
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import DashboardPreference
from app.schemas.preferences import (
    DashboardPreferenceResponse,
    DashboardPreferenceUpdate,
    DashboardWidget,
)

DEFAULT_WIDGETS = [
    DashboardWidget(id="income", visible=True, size="small"),
    DashboardWidget(id="spent", visible=True, size="small"),
    DashboardWidget(id="savings", visible=True, size="small"),
    DashboardWidget(id="net-cash-flow", visible=True, size="small"),
    DashboardWidget(id="attention", visible=True, size="large"),
    DashboardWidget(id="next-action", visible=True, size="medium"),
]
CURRENT_LAYOUT_VERSION = 1


def _goal_widgets(goal: str | None) -> list[DashboardWidget]:
    orders = {
        "budgeting": ["spent", "net-cash-flow", "income", "savings", "attention", "next-action"],
        "saving": ["savings", "net-cash-flow", "income", "spent", "next-action", "attention"],
        "recurring_reduction": [
            "spent",
            "savings",
            "net-cash-flow",
            "income",
            "next-action",
            "attention",
        ],
        "cleanup": ["income", "spent", "net-cash-flow", "savings", "attention", "next-action"],
    }
    order = orders.get(goal or "", [widget.id for widget in DEFAULT_WIDGETS])
    by_id = {widget.id: widget.model_copy(deep=True) for widget in DEFAULT_WIDGETS}
    return [by_id[widget_id] for widget_id in order]


class PreferencesService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: str) -> DashboardPreferenceResponse:
        result = await self.db.execute(
            select(DashboardPreference).where(DashboardPreference.user_id == user_id)
        )
        preference = result.scalar_one_or_none()
        return self._response(user_id, preference)

    async def update(
        self, user_id: str, data: DashboardPreferenceUpdate
    ) -> DashboardPreferenceResponse:
        result = await self.db.execute(
            select(DashboardPreference).where(DashboardPreference.user_id == user_id)
        )
        preference = result.scalar_one_or_none()
        if preference is None:
            preference = DashboardPreference(user_id=user_id)
            self.db.add(preference)

        values = data.model_dump(exclude_unset=True)
        if "widgets" in values:
            preference.widgets_json = json.dumps(
                [
                    widget.model_dump() if isinstance(widget, DashboardWidget) else widget
                    for widget in data.widgets or []
                ]
            )
        if "favorites" in values:
            preference.favorites_json = json.dumps(data.favorites or [])
        if "onboarding_goal" in values and "widgets" not in values:
            preference.widgets_json = json.dumps(
                [widget.model_dump() for widget in _goal_widgets(data.onboarding_goal)]
            )
        for field in ("layout_version", "theme", "density", "onboarding_goal"):
            if field in values:
                setattr(preference, field, values[field])
        preference.updated_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(preference)
        return self._response(user_id, preference)

    async def reset(self, user_id: str) -> DashboardPreferenceResponse:
        await self.db.execute(
            delete(DashboardPreference).where(DashboardPreference.user_id == user_id)
        )
        await self.db.commit()
        return self._response(user_id, None)

    @staticmethod
    def _response(
        user_id: str, preference: DashboardPreference | None
    ) -> DashboardPreferenceResponse:
        if preference is None:
            return DashboardPreferenceResponse(
                user_id=user_id,
                layout_version=CURRENT_LAYOUT_VERSION,
                widgets=_goal_widgets(None),
                theme="system",
                density="comfortable",
                favorites=[],
                onboarding_goal=None,
                updated_at=None,
            )
        if preference.layout_version != CURRENT_LAYOUT_VERSION:
            widgets = _goal_widgets(preference.onboarding_goal)
        else:
            try:
                widgets = [
                    DashboardWidget.model_validate(item)
                    for item in json.loads(preference.widgets_json)
                ]
            except (json.JSONDecodeError, TypeError, ValueError):
                widgets = _goal_widgets(preference.onboarding_goal)
        try:
            favorites = [str(item) for item in json.loads(preference.favorites_json)]
        except (json.JSONDecodeError, TypeError):
            favorites = []
        return DashboardPreferenceResponse(
            user_id=user_id,
            layout_version=CURRENT_LAYOUT_VERSION,
            widgets=widgets or _goal_widgets(preference.onboarding_goal),
            theme=preference.theme,
            density=preference.density,
            favorites=favorites,
            onboarding_goal=preference.onboarding_goal,
            updated_at=preference.updated_at,
        )
