"""Regression tests for Phase 2-4 intelligence, analytics, goals, and explanations."""

from datetime import date

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import create_user


async def _seed_transaction(client: AsyncClient, user_id: str, category_id: str, **overrides):
    today = date.today()
    payload = {
        "amount": 1000.0,
        "currency": "INR",
        "transaction_type": "debit",
        "merchant_raw": "MERCHANT",
        "merchant_normalized": "Merchant",
        "category_id": category_id,
        "transaction_date": today.isoformat(),
        "confidence_score": 0.9,
        "reference_id": f"INTEL-{today.isoformat()}-{overrides.get('reference_id', '0')}",
    }
    payload.update({k: v for k, v in overrides.items() if k != "reference_id"})
    response = await client.post(f"/api/transactions/?user_id={user_id}", json=payload)
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
async def test_merchant_and_category_intelligence(client: AsyncClient):
    user = await create_user(client)
    categories = (await client.get("/api/categories/")).json()
    cat_id = categories[0]["id"]
    today = date.today()

    await _seed_transaction(
        client,
        user["id"],
        cat_id,
        merchant_normalized="Coffee Bar",
        amount=250.0,
        reference_id="coffee-1",
    )
    await _seed_transaction(
        client,
        user["id"],
        cat_id,
        merchant_normalized="Coffee Bar",
        amount=255.0,
        reference_id="coffee-2",
    )

    merchants_resp = await client.get(
        f"/api/merchants/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert merchants_resp.status_code == 200
    merchants = merchants_resp.json()
    coffee = next(m for m in merchants if m["name"] == "Coffee Bar")
    assert coffee["transaction_count"] == 2
    assert coffee["recurrence_likelihood"] >= 0.9

    detail_resp = await client.get(
        f"/api/merchants/Coffee%20Bar?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert detail_resp.status_code == 200
    assert len(detail_resp.json()["latest_transactions"]) == 2

    category_resp = await client.get(
        f"/api/categories/intelligence?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert category_resp.status_code == 200
    category_payload = category_resp.json()
    assert category_payload["categories"]
    assert any(c["top_merchants"] for c in category_payload["categories"])


@pytest.mark.asyncio
async def test_analytics_goals_and_explain_endpoint(client: AsyncClient):
    user = await create_user(client)
    categories = (await client.get("/api/categories/")).json()
    cat_id = categories[0]["id"]
    today = date.today()

    await _seed_transaction(
        client,
        user["id"],
        cat_id,
        amount=50000,
        transaction_type="credit",
        merchant_normalized="Employer",
        reference_id="income",
    )
    await _seed_transaction(
        client,
        user["id"],
        cat_id,
        amount=10000,
        transaction_type="debit",
        merchant_normalized="Rent",
        reference_id="rent",
    )

    cash_flow = await client.get(
        f"/api/analytics/cash-flow?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert cash_flow.status_code == 200
    assert cash_flow.json()["net_to_date"] == 40000

    transactions_before = await client.get(
        f"/api/transactions/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    transaction_ids_before = [item["id"] for item in transactions_before.json()]

    scenario = await client.post(
        f"/api/analytics/scenario?user_id={user['id']}",
        json={
            "month": today.month,
            "year": today.year,
            "flexible_spend_reduction": 1000,
            "recurring_reduction": 500,
            "additional_income": 2000,
        },
    )
    assert scenario.status_code == 200
    scenario_body = scenario.json()
    assert scenario_body["monthly_impact"] >= 2000
    assert scenario_body["scenario_projected_net"] == (
        scenario_body["baseline_projected_net"] + scenario_body["monthly_impact"]
    )
    assert "do not change financial records" in " ".join(scenario_body["assumptions"])

    transactions_after = await client.get(
        f"/api/transactions/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert [item["id"] for item in transactions_after.json()] == transaction_ids_before

    capped_scenario = await client.post(
        f"/api/analytics/scenario?user_id={user['id']}",
        json={
            "month": today.month,
            "year": today.year,
            "flexible_spend_reduction": 9_000_000,
            "recurring_reduction": 9_000_000,
        },
    )
    assert capped_scenario.status_code == 200
    capped_body = capped_scenario.json()
    assert capped_body["effective_flexible_spend_reduction"] <= cash_flow.json()["projected_spend"]
    assert capped_body["effective_recurring_reduction"] <= cash_flow.json()["recurring_commitments"]
    assert capped_body["scenario_projected_spend"] >= 0

    health = await client.get(
        f"/api/analytics/financial-health?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert health.status_code == 200
    assert 0 <= health.json()["score"] <= 100

    goal_resp = await client.post(
        f"/api/goals/?user_id={user['id']}",
        json={
            "goal_type": "savings",
            "label": "Save this month",
            "target_amount": 30000,
            "target_month": today.month,
            "target_year": today.year,
        },
    )
    assert goal_resp.status_code == 201
    assert goal_resp.json()["status"] == "achieved"

    goals = await client.get(
        f"/api/goals/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert goals.status_code == 200
    assert len(goals.json()) == 1

    explain = await client.post(
        "/api/ai/explain",
        json={
            "surface": "financial health",
            "title": "Health score",
            "metrics": {"score": health.json()["score"]},
        },
    )
    assert explain.status_code == 200
    body = explain.json()
    assert "raw email" in body["safety_note"].lower()
    assert body["next_actions"]
