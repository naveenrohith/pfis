"""Insights service unit tests."""

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import create_user


@pytest.mark.asyncio
async def test_insights_with_no_data_returns_empty(client: AsyncClient):
    """Insights with no transactions returns empty insights list."""
    user = await create_user(client)
    from datetime import date

    today = date.today()

    resp = await client.get(
        f"/api/insights/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "insights" in data
    assert "daily_trend" in data
    assert "meta" in data
    assert data["meta"]["total_spend"] == 0


@pytest.mark.asyncio
async def test_insights_with_transactions(client: AsyncClient):
    """Insights generates cards when transaction data exists."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    from datetime import date

    today = date.today()

    # Create some debit transactions
    for i in range(3):
        await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 1000.0 + i * 500,
                "currency": "INR",
                "transaction_type": "debit",
                "merchant_raw": f"MERCHANT_{i}",
                "merchant_normalized": f"Merchant {i}",
                "category_id": categories[0]["id"],
                "transaction_date": today.isoformat(),
                "confidence_score": 0.9,
                "reference_id": f"REF{i}_{today.isoformat()}",
            },
        )

    resp = await client.get(
        f"/api/insights/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["total_spend"] > 0
    assert len(data["daily_trend"]) >= 1


@pytest.mark.asyncio
async def test_insights_savings_rate_computed(client: AsyncClient):
    """Savings rate insight is generated when income exists."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    from datetime import date

    today = date.today()

    # Create income
    await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 50000.0,
            "currency": "INR",
            "transaction_type": "credit",
            "merchant_raw": "EMPLOYER",
            "merchant_normalized": "Employer",
            "category_id": categories[0]["id"],
            "transaction_date": today.isoformat(),
            "confidence_score": 0.95,
            "reference_id": f"SALARY_{today.isoformat()}",
        },
    )

    # Create spending
    await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10000.0,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": "GROCER",
            "merchant_normalized": "Grocer",
            "category_id": categories[0]["id"],
            "transaction_date": today.isoformat(),
            "confidence_score": 0.9,
            "reference_id": f"SHOP_{today.isoformat()}",
        },
    )

    resp = await client.get(
        f"/api/insights/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    data = resp.json()
    # Should have savings rate insight
    types = [i["type"] for i in data["insights"]]
    assert "savings_rate" in types


@pytest.mark.asyncio
async def test_insights_recurring_detection(client: AsyncClient):
    """Recurring detection finds merchants appearing 2+ times with similar amounts."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    from datetime import date, timedelta

    today = date.today()

    # Create recurring transactions (same merchant, similar amounts)
    for i in range(3):
        txn_date = today - timedelta(days=i * 30)
        await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 499.0,
                "currency": "INR",
                "transaction_type": "debit",
                "merchant_raw": "NETFLIX",
                "merchant_normalized": "Netflix",
                "category_id": categories[0]["id"],
                "transaction_date": txn_date.isoformat(),
                "confidence_score": 0.95,
                "reference_id": f"NFLX_{i}_{txn_date.isoformat()}",
            },
        )

    resp = await client.get(
        f"/api/insights/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recurring_payments"]) >= 1
    assert data["recurring_payments"][0]["merchant"] == "Netflix"
