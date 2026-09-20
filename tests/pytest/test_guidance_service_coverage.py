"""Branch coverage for deterministic guidance query behavior."""

from __future__ import annotations

from tests.pytest.helpers import auth_headers, create_user, register_user


async def _add_transaction(client, user_id: str, **values: object) -> None:
    payload = {
        "amount": 120,
        "transaction_type": "debit",
        "merchant_raw": "Guidance Cafe",
        "merchant_normalized": "Guidance Cafe",
        "transaction_date": "2026-08-15",
        **values,
    }
    response = await client.post(f"/api/transactions/?user_id={user_id}", json=payload)
    response.raise_for_status()


async def test_guidance_reports_unsupported_and_degraded_position_queries(client):
    user = await create_user(client, "guidance-degraded")
    endpoint = f"/api/guidance/query?user_id={user['id']}"

    unsupported = await client.post(endpoint, json={"query": "tell me a joke"})
    bank = await client.post(
        endpoint,
        json={"query": "what is my current bank balance", "month": 8, "year": 2026},
    )
    safe_to_spend = await client.post(
        endpoint,
        json={"query": "is it safe to spend", "month": 8, "year": 2026},
    )
    for response in (unsupported, bank, safe_to_spend):
        response.raise_for_status()

    assert unsupported.json()["supported"] is False
    assert unsupported.json()["confidence"] == 0
    assert bank.json()["intent"] == "bank_position"
    assert "No active bank account" in bank.json()["answer"]
    assert safe_to_spend.json()["confidence"] == 0.45
    assert safe_to_spend.json()["intent"] == "safe_to_spend_blocked"


async def test_guidance_returns_grounded_populated_spend_and_savings(client):
    user = await create_user(client, "guidance-populated")
    await _add_transaction(client, user["id"], amount=500, transaction_type="credit")
    await _add_transaction(client, user["id"], amount=120)

    endpoint = f"/api/guidance/query?user_id={user['id']}"
    spend = await client.post(
        endpoint,
        json={"query": "how much did I spend at Guidance Cafe", "month": 8, "year": 2026},
    )
    savings = await client.post(
        endpoint,
        json={"query": "how much were my savings", "month": 8, "year": 2026},
    )
    for response in (spend, savings):
        response.raise_for_status()

    assert spend.json()["intent"] == "merchant_spend"
    assert spend.json()["metrics"][0]["value"] == "₹120"
    assert spend.json()["evidence"][0]["source_type"] == "transactions"
    assert savings.json()["intent"] == "monthly_savings"
    assert savings.json()["metrics"][0]["value"] == "₹380"


async def test_guidance_enforces_authenticated_user_scope(client, auth_required):
    first, token = await register_user(client, "guidance-scope")
    second, _ = await register_user(client, "guidance-other")

    response = await client.post(
        f"/api/guidance/query?user_id={second['id']}",
        headers=auth_headers(token),
        json={"query": "what was my income", "month": 8, "year": 2026},
    )

    assert first["id"] != second["id"]
    assert response.status_code == 403
