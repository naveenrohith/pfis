"""Budget CRUD and tracking tests."""

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import create_user


@pytest.mark.asyncio
async def test_create_budget_returns_201(client: AsyncClient):
    """Creating a budget returns 201 with the budget ID."""
    user = await create_user(client)
    # Get categories first
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()
    assert len(categories) > 0

    resp = await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": categories[0]["id"], "monthly_limit": 5000.0},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["status"] == "created"


@pytest.mark.asyncio
async def test_create_duplicate_budget_returns_409(client: AsyncClient):
    """Creating a duplicate budget for same category returns 409."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": categories[0]["id"], "monthly_limit": 5000.0},
    )
    resp = await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": categories[0]["id"], "monthly_limit": 3000.0},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_budgets_returns_category_info(client: AsyncClient):
    """Listing budgets includes category name and icon."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": categories[0]["id"], "monthly_limit": 5000.0},
    )

    resp = await client.get(f"/api/budgets/?user_id={user['id']}")
    assert resp.status_code == 200
    budgets = resp.json()
    assert len(budgets) >= 1
    assert budgets[0]["category_name"] is not None


@pytest.mark.asyncio
async def test_update_budget_limit(client: AsyncClient):
    """Updating a budget changes its monthly limit."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    create_resp = await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": categories[0]["id"], "monthly_limit": 5000.0},
    )
    budget_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/budgets/{budget_id}",
        json={"monthly_limit": 8000.0},
    )
    assert resp.status_code == 200
    assert resp.json()["monthly_limit"] == 8000.0


@pytest.mark.asyncio
async def test_delete_budget(client: AsyncClient):
    """Deleting a budget removes it."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    create_resp = await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": categories[0]["id"], "monthly_limit": 5000.0},
    )
    budget_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/budgets/{budget_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Verify it's gone
    list_resp = await client.get(f"/api/budgets/?user_id={user['id']}")
    budget_ids = [b["id"] for b in list_resp.json()]
    assert budget_id not in budget_ids


@pytest.mark.asyncio
async def test_track_budgets_shows_usage_percentage(client: AsyncClient):
    """Tracking budgets returns usage percentage and status."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": categories[0]["id"], "monthly_limit": 10000.0},
    )

    from datetime import date

    today = date.today()
    resp = await client.get(
        f"/api/budgets/track?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    trackers = resp.json()
    assert len(trackers) >= 1
    assert "usage_pct" in trackers[0]
    assert "status" in trackers[0]
    assert trackers[0]["status"] in ("under", "warning", "over")
