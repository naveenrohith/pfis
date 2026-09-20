"""Deterministic coverage for dashboard preference persistence policy."""

import json
from datetime import UTC, datetime

import pytest
from app.models.workspace import DashboardPreference
from app.schemas.preferences import DashboardPreferenceUpdate, DashboardWidget
from app.services.preferences_service import PreferencesService, _goal_widgets


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _PreferencesDb:
    def __init__(self, values=()):
        self.values = list(values)
        self.added = []
        self.commit_count = 0

    async def execute(self, _statement):
        return _Result(self.values.pop(0) if self.values else None)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, value):
        if value.updated_at is None:
            value.updated_at = datetime.now(UTC)


def test_goal_widgets_order_every_supported_goal_and_default():
    assert [item.id for item in _goal_widgets(None)] == [
        "income",
        "spent",
        "savings",
        "net-cash-flow",
        "attention",
        "next-action",
    ]
    for goal in ("budgeting", "saving", "recurring_reduction", "cleanup"):
        widgets = _goal_widgets(goal)
        assert len(widgets) == 6
        assert len({widget.id for widget in widgets}) == 6


@pytest.mark.asyncio
async def test_preferences_service_covers_create_update_fallback_and_reset():
    created_db = _PreferencesDb([None])
    created = await PreferencesService(created_db).update(
        "user-1",
        DashboardPreferenceUpdate(
            layout_version=2,
            widgets=[DashboardWidget(id="custom", visible=True, size="large")],
            theme="dark",
            density="compact",
            briefing_cadence="weekly",
            favorites=["merchant:Amazon"],
            onboarding_goal="budgeting",
        ),
    )
    assert created.theme == "dark"
    assert created.widgets[0].id == "spent"
    assert created.favorites == ["merchant:Amazon"]
    assert created_db.commit_count == 1

    existing = DashboardPreference(
        user_id="user-1",
        layout_version=1,
        widgets_json="[]",
        favorites_json="not-json",
        theme="system",
        density="comfortable",
        briefing_cadence="daily",
        onboarding_goal="saving",
        updated_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    update_db = _PreferencesDb([existing, existing])
    service = PreferencesService(update_db)
    goal_update = await service.update(
        "user-1", DashboardPreferenceUpdate(onboarding_goal="saving")
    )
    assert goal_update.onboarding_goal == "saving"
    assert goal_update.widgets
    fallback = await service.get("user-1")
    assert fallback.favorites == []
    assert fallback.widgets

    invalid = DashboardPreference(
        user_id="user-2",
        layout_version=1,
        widgets_json=json.dumps([{"id": "bad", "size": "invalid"}]),
        favorites_json=json.dumps([1, "two"]),
        theme="light",
        density="comfortable",
        briefing_cadence="monthly",
        onboarding_goal=None,
        updated_at=None,
    )
    invalid_response = PreferencesService(_PreferencesDb())._response("user-2", invalid)
    assert invalid_response.widgets
    assert invalid_response.favorites == ["1", "two"]

    reset = await PreferencesService(_PreferencesDb()).reset("user-1")
    assert reset.layout_version == 1
    assert reset.updated_at is None
