"""Financial Horizon route coverage."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import auth_headers, create_user, register_user


async def _account(client: AsyncClient, user_id: str, suffix: str, *, headers=None) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        headers=headers,
        json={
            "institution_name": "Horizon Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def _verified_balance(
    client: AsyncClient, user_id: str, account_id: str, amount: int, as_of: date
) -> None:
    response = await client.post(
        f"/api/accounts/{account_id}/balances?user_id={user_id}",
        json={"amount": amount, "as_of": as_of.isoformat(), "verified": True},
    )
    response.raise_for_status()


async def test_financial_horizon_success_composes_existing_read_models(client: AsyncClient):
    user = await create_user(client, "horizon-success")
    account = await _account(client, user["id"], "8101")
    today = date.today()
    await _verified_balance(client, user["id"], account["id"], 10000, today)

    plan = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (today + timedelta(days=10)).isoformat(),
            "next_income_amount": 5000,
        },
    )
    plan.raise_for_status()
    commitment = await client.post(
        f"/api/commitments?user_id={user['id']}",
        json={
            "label": "Rent",
            "commitment_type": "rent",
            "amount": 2000,
            "due_date": (today + timedelta(days=3)).isoformat(),
            "confirmed": True,
        },
    )
    commitment.raise_for_status()

    response = await client.get(f"/api/horizon?user_id={user['id']}&days=30")
    response.raise_for_status()
    body = response.json()

    assert body["ruleset_version"] == "pfis-horizon-1"
    assert body["status"] == "healthy"
    assert body["horizon_days"] == 30
    assert body["current_position"]["verified"]["assets"] == 10000
    assert body["current_position"]["provisional"]["assets"] == 0
    assert body["current_position"]["safe_to_spend"] == 8000
    assert body["lowest_projected_point"] is not None
    event_sources = {event["source"] for event in body["events"]}
    assert {"cash_plan", "commitment"} <= event_sources
    rent = next(event for event in body["events"] if event["label"] == "Rent")
    assert rent["status"] == "verified"
    assert rent["confidence"] >= 0.9


async def test_financial_horizon_low_data_fails_closed(client: AsyncClient):
    user = await create_user(client, "horizon-low-data")

    response = await client.get(f"/api/horizon?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "low_data"
    assert body["current_position"]["verified"]["assets"] == 0
    assert "active_financial_account" in body["missing_evidence"]
    assert body["lowest_projected_point"] is None


async def test_financial_horizon_marks_stale_sources(client: AsyncClient):
    user = await create_user(client, "horizon-stale")
    account = await _account(client, user["id"], "8102")
    old_day = date.today() - timedelta(days=14)
    await _verified_balance(client, user["id"], account["id"], 7000, old_day)
    plan = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (date.today() + timedelta(days=8)).isoformat(),
            "next_income_amount": 3000,
        },
    )
    plan.raise_for_status()

    response = await client.get(f"/api/horizon?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "stale"
    assert any(signal["code"] == "stale_source" for signal in body["risk_signals"])
    assert any("stale" in code for code in body["source_health"][0]["reason_codes"])


@pytest.mark.asyncio
async def test_financial_horizon_enforces_user_scope(client: AsyncClient, auth_required):
    owner, owner_token = await register_user(client, "horizon-owner")
    _, attacker_token = await register_user(client, "horizon-attacker")
    client.cookies.clear()
    await _account(client, owner["id"], "8103", headers=auth_headers(owner_token))

    forbidden = await client.get(
        f"/api/horizon?user_id={owner['id']}", headers=auth_headers(attacker_token)
    )
    assert forbidden.status_code == 403

    anonymous = await client.get(f"/api/horizon?user_id={owner['id']}")
    assert anonymous.status_code == 401

    scoped = await client.get("/api/horizon", headers=auth_headers(owner_token))
    assert scoped.status_code == 200


async def test_financial_horizon_days_bounds_are_validated(client: AsyncClient):
    user = await create_user(client, "horizon-bounds")

    too_short = await client.get(f"/api/horizon?user_id={user['id']}&days=6")
    too_long = await client.get(f"/api/horizon?user_id={user['id']}&days=91")

    assert too_short.status_code == 422
    assert too_long.status_code == 422


async def test_financial_horizon_no_forecast_fallback_keeps_lowest_point_null(
    client: AsyncClient,
):
    user = await create_user(client, "horizon-no-forecast")
    account = await _account(client, user["id"], "8104")
    await _verified_balance(client, user["id"], account["id"], 5000, date.today())

    response = await client.get(f"/api/horizon?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["lowest_projected_point"] is None
    assert body["lowest_projected_point_unavailable_reason"] == "cash_plan_primary_account_required"
    assert "balance_forecast" in body["missing_evidence"]
    assert body["status"] == "low_data"
