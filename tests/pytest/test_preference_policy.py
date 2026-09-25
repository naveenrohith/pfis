"""Versioned explicit preference policy regressions."""

from app.models.workspace import UserPreferencePolicyVersion
from sqlalchemy import select

from tests.pytest.helpers import auth_headers, register_user


async def test_preference_policy_versions_history_rollback_and_cross_user_isolation(
    client, auth_required, test_session_factory
):
    owner, owner_token = await register_user(client, "policy-owner")
    other, other_token = await register_user(client, "policy-other")

    first = await client.put(
        f"/api/preferences/policy?user_id={owner['id']}",
        headers=auth_headers(owner_token),
        json={
            "alert_threshold_pct": 15,
            "briefing_cadence": "weekly",
            "reserve_floor": 5000,
            "dismissed_recommendation_kinds": ["budget", "budget"],
            "excluded_recommendation_types": ["recurring"],
            "excluded_merchants": [" Amazon ", "amazon"],
            "excluded_categories": ["Groceries"],
        },
    )
    first.raise_for_status()
    assert first.json()["version"] == 1
    assert first.json()["policy"]["excluded_merchants"] == ["amazon"]

    second = await client.put(
        f"/api/preferences/policy?user_id={owner['id']}",
        headers=auth_headers(owner_token),
        json={
            "alert_threshold_pct": 25,
            "briefing_cadence": "monthly",
            "reserve_floor": 1000,
            "dismissed_recommendation_kinds": [],
            "excluded_recommendation_types": ["savings"],
            "excluded_merchants": [],
            "excluded_categories": [],
        },
    )
    second.raise_for_status()
    assert second.json()["version"] == 2
    assert second.json()["based_on_version"] == 1

    history = await client.get(
        f"/api/preferences/policy/history?user_id={owner['id']}",
        headers=auth_headers(owner_token),
    )
    history.raise_for_status()
    assert [item["version"] for item in history.json()] == [2, 1]

    rollback = await client.post(
        f"/api/preferences/policy/rollback?user_id={owner['id']}",
        headers=auth_headers(owner_token),
        json={"version": 1},
    )
    rollback.raise_for_status()
    payload = rollback.json()
    assert payload["version"] == 3
    assert payload["based_on_version"] == 1
    assert payload["policy"]["reserve_floor"] == 5000

    cross_user = await client.get(
        f"/api/preferences/policy?user_id={owner['id']}",
        headers=auth_headers(other_token),
    )
    assert cross_user.status_code == 403

    async with test_session_factory() as db:
        rows = list(
            (
                await db.scalars(
                    select(UserPreferencePolicyVersion).where(
                        UserPreferencePolicyVersion.user_id == other["id"]
                    )
                )
            ).all()
        )
    assert rows == []


async def test_preference_policy_bounds_are_rejected(client, auth_required):
    user, token = await register_user(client, "policy-bounds")

    response = await client.put(
        f"/api/preferences/policy?user_id={user['id']}",
        headers=auth_headers(token),
        json={
            "alert_threshold_pct": 0.5,
            "briefing_cadence": "daily",
            "reserve_floor": -1,
            "dismissed_recommendation_kinds": [],
            "excluded_recommendation_types": [],
            "excluded_merchants": [],
            "excluded_categories": [],
        },
    )

    assert response.status_code == 422
