"""Tests for the Financial Decision Workspace aggregate endpoint."""

from datetime import date

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import create_user


async def _seed_transaction(client: AsyncClient, user_id: str, category_id: str, **overrides):
    payload = {
        "amount": 1000.0,
        "currency": "INR",
        "transaction_type": "debit",
        "merchant_raw": "MERCHANT",
        "merchant_normalized": "Merchant",
        "category_id": category_id,
        "transaction_date": date.today().isoformat(),
        "confidence_score": 0.9,
        "reference_id": f"REF-{date.today().isoformat()}-{overrides.get('reference_id', '0')}",
    }
    payload.update({k: v for k, v in overrides.items() if k != "reference_id"})
    resp = await client.post(f"/api/transactions/?user_id={user_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


@pytest.mark.asyncio
async def test_workspace_empty_month_returns_stable_shape(client: AsyncClient):
    """No data still returns the full DTO with zeroed values."""
    user = await create_user(client)
    today = date.today()

    resp = await client.get(
        f"/api/dashboard/workspace?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    data = resp.json()

    for key in (
        "month",
        "year",
        "snapshot",
        "timeline",
        "insights",
        "recommendations",
        "review_summary",
        "sync_summary",
    ):
        assert key in data

    snap = data["snapshot"]
    assert snap["income"] == 0
    assert snap["spend"] == 0
    assert snap["savings"] == 0
    assert snap["transaction_count"] == 0
    assert snap["review_count"] == 0
    assert snap["budget_risk_count"] == 0
    assert data["timeline"] == []
    assert data["recommendations"] == []


@pytest.mark.asyncio
async def test_workspace_snapshot_and_timeline_with_data(client: AsyncClient):
    """Snapshot metrics and timeline events reflect stored transactions."""
    user = await create_user(client)
    cats = (await client.get(f"/api/categories/?user_id={user['id']}")).json()
    cat_id = cats[0]["id"]
    today = date.today()

    await _seed_transaction(
        client, user["id"], cat_id,
        amount=50000.0, transaction_type="credit",
        merchant_normalized="Employer", confidence_score=0.95, reference_id="salary",
    )
    await _seed_transaction(
        client, user["id"], cat_id,
        amount=1200.0, transaction_type="debit",
        merchant_normalized="Grocery Store", confidence_score=0.92, reference_id="grocery",
    )
    # Low-confidence, unreviewed transaction for review summary
    await _seed_transaction(
        client, user["id"], cat_id,
        amount=800.0, transaction_type="debit",
        merchant_normalized="Unknown Shop", confidence_score=0.5, reference_id="lowconf",
    )
    # Refund -> should map to an "in" direction refund event
    await _seed_transaction(
        client, user["id"], cat_id,
        amount=300.0, transaction_type="refund",
        merchant_normalized="Online Store", confidence_score=0.9, reference_id="refund",
    )

    resp = await client.get(
        f"/api/dashboard/workspace?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    data = resp.json()

    snap = data["snapshot"]
    assert snap["income"] == 50000.0
    assert snap["spend"] == 2000.0
    assert snap["savings"] == 48000.0
    assert snap["net_cash_flow"] == 48000.0
    assert snap["transaction_count"] == 4

    review = data["review_summary"]
    # High-confidence transactions are auto-reviewed on creation; only the
    # low-confidence one stays pending.
    assert review["low_confidence_count"] == 1
    assert review["pending_count"] == 1

    # Timeline classification
    types = {e["type"] for e in data["timeline"]}
    assert "income" in types
    assert "refund" in types
    assert any(e["direction"] == "in" for e in data["timeline"])
    assert any(e["direction"] == "out" for e in data["timeline"])
    assert all("payment_method" in event for event in data["timeline"])

    # Low-confidence cleanup recommendation should be present
    rec_types = {r["type"] for r in data["recommendations"]}
    assert "review" in rec_types


@pytest.mark.asyncio
async def test_workspace_budget_risk_recommendation(client: AsyncClient):
    """An over-limit budget surfaces a budget_risk count and recommendation."""
    user = await create_user(client)
    cats = (await client.get(f"/api/categories/?user_id={user['id']}")).json()
    cat_id = cats[0]["id"]
    today = date.today()

    await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": cat_id, "monthly_limit": 500.0},
    )
    await _seed_transaction(
        client, user["id"], cat_id,
        amount=2000.0, transaction_type="debit", reference_id="overspend",
    )

    resp = await client.get(
        f"/api/dashboard/workspace?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["snapshot"]["budget_risk_count"] >= 1
    assert any(r["type"] == "budget" for r in data["recommendations"])


@pytest.mark.asyncio
async def test_workspace_does_not_leak_raw_email_or_secrets(client: AsyncClient):
    """The workspace payload must never contain email bodies, tokens, or secrets."""
    user = await create_user(client)
    cats = (await client.get(f"/api/categories/?user_id={user['id']}")).json()
    await _seed_transaction(client, user["id"], cats[0]["id"], reference_id="clean")
    today = date.today()

    resp = await client.get(
        f"/api/dashboard/workspace?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    body = resp.text.lower()
    for banned in ("body", "access_token", "refresh_token", "password", "token_ref"):
        assert banned not in body
