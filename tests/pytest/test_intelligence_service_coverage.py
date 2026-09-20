"""Branch coverage for the user-scoped intelligence read models."""

from __future__ import annotations

from app.models.transaction import Transaction
from sqlalchemy import update

from tests.pytest.helpers import create_user


async def _add_transaction(client, user_id: str, **values: object) -> dict:
    payload = {
        "amount": 100,
        "transaction_type": "debit",
        "merchant_raw": "Coverage Cafe",
        "merchant_normalized": "Coverage Cafe",
        "transaction_date": "2026-08-15",
        "confidence_score": 0.9,
        **values,
    }
    response = await client.post(f"/api/transactions/?user_id={user_id}", json=payload)
    response.raise_for_status()
    return response.json()


async def test_empty_intelligence_surfaces_keep_missing_history_explicit(client):
    user = await create_user(client, "intelligence-empty")
    query = f"user_id={user['id']}&month=8&year=2026"

    category = await client.get(f"/api/categories/intelligence?{query}")
    cash_flow = await client.get(f"/api/analytics/cash-flow?{query}")
    comparison = await client.get(f"/api/analytics/month-comparison?{query}")
    health = await client.get(f"/api/analytics/financial-health?{query}")
    coverage = await client.get(f"/api/analytics/source-coverage?user_id={user['id']}")

    for response in (category, cash_flow, comparison, health, coverage):
        response.raise_for_status()
    assert comparison.json()["spend"] == 0
    assert comparison.json()["spend_change_pct"] is None
    assert cash_flow.json()["projected_spend"] == 0
    assert health.json()["score"] == 0
    assert coverage.json()["overall_score"] == 0
    assert any(item["status"] == "unknown" for item in coverage.json()["sources"])


async def test_intelligence_uses_income_spend_history_and_review_quality(
    client, test_session_factory
):
    user = await create_user(client, "intelligence-populated")
    await _add_transaction(client, user["id"], amount=250, transaction_type="credit")
    await _add_transaction(client, user["id"], amount=100)
    await _add_transaction(
        client,
        user["id"],
        amount=101,
        transaction_status="pending",
        confidence_score=0.4,
    )
    reviewed = await _add_transaction(
        client,
        user["id"],
        amount=75,
        transaction_date="2026-07-15",
        confidence_score=0.5,
    )
    async with test_session_factory() as session:
        await session.execute(
            update(Transaction)
            .where(Transaction.id == reviewed["id"])
            .values(review_outcome="needs_review")
        )
        await session.commit()

    comparison = await client.get(
        f"/api/analytics/month-comparison?user_id={user['id']}&month=8&year=2026"
    )
    health = await client.get(
        f"/api/analytics/financial-health?user_id={user['id']}&month=8&year=2026"
    )
    category = await client.get(
        f"/api/categories/intelligence?user_id={user['id']}&month=8&year=2026"
    )
    for response in (comparison, health, category):
        response.raise_for_status()

    assert comparison.json()["income"] == 250
    assert comparison.json()["spend"] == 100
    assert comparison.json()["spend_change_pct"] == 33.3
    conflicts = next(
        item for item in health.json()["data_confidence_breakdown"] if item["key"] == "conflicts"
    )
    assert conflicts["score"] < 100
    assert any(item["transaction_count"] == 1 for item in category.json()["categories"])


async def test_source_coverage_rejects_unknown_user(client):
    response = await client.get("/api/analytics/source-coverage?user_id=missing-user")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "User not found"
