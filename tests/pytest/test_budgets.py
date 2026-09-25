"""Budget CRUD and tracking tests."""

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import auth_headers, create_user, register_user


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


@pytest.mark.asyncio
async def test_budget_tracking_excludes_internal_transfers(client: AsyncClient):
    """A categorized transfer debit must not consume a spending budget."""
    from datetime import date

    user = await create_user(client, "budget-transfer")
    categories = (await client.get(f"/api/categories/?user_id={user['id']}")).json()
    category_id = categories[0]["id"]
    await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": category_id, "monthly_limit": 1000},
    )

    account_ids = []
    for suffix in ("1111", "2222"):
        response = await client.post(
            f"/api/accounts?user_id={user['id']}",
            json={
                "institution_name": f"Transfer Bank {suffix}",
                "account_type": "bank",
                "masked_number": f"****{suffix}",
                "currency": "INR",
            },
        )
        account_ids.append(response.json()["id"])

    today = date.today()
    transfer = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": account_ids[0],
            "to_account_id": account_ids[1],
            "amount": 750,
            "currency": "INR",
            "transaction_date": today.isoformat(),
        },
    )
    debit_id = transfer.json()["debit_transaction_id"]
    categorized = await client.patch(
        f"/api/transactions/{debit_id}", json={"category_id": category_id}
    )
    assert categorized.status_code == 200

    response = await client.get(
        f"/api/budgets/track?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert response.status_code == 200
    assert response.json()[0]["actual_spend"] == 0
    assert response.json()[0]["usage_pct"] == 0


@pytest.mark.asyncio
async def test_budget_mutations_reject_cross_user_tokens(client: AsyncClient, auth_required):
    """Authenticated users cannot update or delete another user's budget."""
    owner, owner_token = await register_user(client, "budget-owner")
    _, attacker_token = await register_user(client, "budget-attacker")
    categories = (
        await client.get(
            f"/api/categories/?user_id={owner['id']}", headers=auth_headers(owner_token)
        )
    ).json()
    created = await client.post(
        f"/api/budgets/?user_id={owner['id']}",
        headers=auth_headers(owner_token),
        json={"category_id": categories[0]["id"], "monthly_limit": 5000},
    )
    budget_id = created.json()["id"]

    update = await client.patch(
        f"/api/budgets/{budget_id}",
        headers=auth_headers(attacker_token),
        json={"monthly_limit": 1},
    )
    delete = await client.delete(f"/api/budgets/{budget_id}", headers=auth_headers(attacker_token))

    assert update.status_code == 403
    assert delete.status_code == 403


async def _post_txn(client: AsyncClient, user_id: str, **overrides):
    payload = {
        "amount": 100,
        "transaction_type": "debit",
        "merchant_raw": "Drilldown Merchant",
        "transaction_date": "2026-05-10",
        "confidence_score": 0.9,
    }
    payload.update(overrides)
    response = await client.post(f"/api/transactions/?user_id={user_id}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_budget_drilldown_lists_contributing_transactions(client: AsyncClient):
    """Drill-down rows reconcile with the tracker's actual spend and remaining."""
    user = await create_user(client, "budget-drilldown")
    categories = (await client.get(f"/api/categories/?user_id={user['id']}")).json()
    category_id, other_category_id = categories[0]["id"], categories[1]["id"]
    created = await client.post(
        f"/api/budgets/?user_id={user['id']}",
        json={"category_id": category_id, "monthly_limit": 1000},
    )
    budget_id = created.json()["id"]

    debit_one = await _post_txn(
        client, user["id"], amount=600, category_id=category_id, reference_id="dd-1"
    )
    debit_two = await _post_txn(
        client,
        user["id"],
        amount=300,
        category_id=category_id,
        transaction_date="2026-05-20",
        reference_id="dd-2",
    )
    refund = await _post_txn(
        client,
        user["id"],
        amount=50,
        transaction_type="refund",
        category_id=category_id,
        transaction_date="2026-05-22",
        reference_id="dd-3",
    )
    # Excluded: other category, other month, income credit, pending debit.
    await _post_txn(
        client, user["id"], amount=999, category_id=other_category_id, reference_id="x1"
    )
    await _post_txn(
        client,
        user["id"],
        amount=999,
        category_id=category_id,
        transaction_date="2026-04-30",
        reference_id="x2",
    )
    await _post_txn(
        client,
        user["id"],
        amount=999,
        transaction_type="credit",
        category_id=category_id,
        reference_id="x3",
    )
    await _post_txn(
        client,
        user["id"],
        amount=999,
        category_id=category_id,
        transaction_status="pending",
        reference_id="x4",
    )

    response = await client.get(f"/api/budgets/{budget_id}/drilldown?month=5&year=2026")
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == 5 and body["year"] == 2026
    assert body["transaction_count"] == 3
    assert body["has_more"] is False
    assert [row["id"] for row in body["transactions"]] == [
        refund["id"],
        debit_two["id"],
        debit_one["id"],
    ]
    assert [row["spend_effect"] for row in body["transactions"]] == [-50.0, 300.0, 600.0]
    assert body["transactions"][0]["transaction_type"] == "refund"
    assert body["transactions"][0]["merchant"]
    assert body["budget"]["actual_spend"] == 850.0
    assert body["budget"]["remaining"] == 150.0
    assert body["budget"]["status"] == "warning"

    tracked = (
        await client.get(f"/api/budgets/track?user_id={user['id']}&month=5&year=2026")
    ).json()
    assert tracked[0]["actual_spend"] == body["budget"]["actual_spend"]
    assert tracked[0]["remaining"] == body["budget"]["remaining"]

    limited = (
        await client.get(f"/api/budgets/{budget_id}/drilldown?month=5&year=2026&limit=1")
    ).json()
    assert limited["transaction_count"] == 3
    assert limited["has_more"] is True
    assert len(limited["transactions"]) == 1
    assert limited["budget"]["actual_spend"] == 850.0


@pytest.mark.asyncio
async def test_budget_drilldown_unknown_budget_returns_404(client: AsyncClient):
    response = await client.get("/api/budgets/missing-budget/drilldown?month=5&year=2026")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_budget_drilldown_rejects_cross_user_tokens(client: AsyncClient, auth_required):
    """Authenticated users cannot read another user's budget drill-down."""
    owner, owner_token = await register_user(client, "drilldown-owner")
    _, attacker_token = await register_user(client, "drilldown-attacker")
    categories = (
        await client.get(
            f"/api/categories/?user_id={owner['id']}", headers=auth_headers(owner_token)
        )
    ).json()
    created = await client.post(
        f"/api/budgets/?user_id={owner['id']}",
        headers=auth_headers(owner_token),
        json={"category_id": categories[0]["id"], "monthly_limit": 5000},
    )
    budget_id = created.json()["id"]

    denied = await client.get(
        f"/api/budgets/{budget_id}/drilldown?month=5&year=2026",
        headers=auth_headers(attacker_token),
    )
    allowed = await client.get(
        f"/api/budgets/{budget_id}/drilldown?month=5&year=2026",
        headers=auth_headers(owner_token),
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
