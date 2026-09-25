"""Transaction notes, tags, and split-allocation invariants."""

from datetime import date

import pytest
from app.models.sync import UserCorrection
from httpx import AsyncClient
from sqlalchemy import select

from tests.pytest.helpers import auth_headers, create_user, register_user


async def _transaction(client: AsyncClient, user_id: str, *, amount: int = 1000) -> dict:
    response = await client.post(
        f"/api/transactions/?user_id={user_id}",
        json={
            "amount": amount,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": f"Managed purchase {amount}",
            "reference_id": f"managed-{user_id}-{amount}",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_notes_and_tags_are_normalized_and_preserve_correction_history(
    client: AsyncClient, test_session_factory
):
    user = await create_user(client, "transaction-metadata")
    transaction = await _transaction(client, user["id"])

    updated = await client.patch(
        f"/api/transactions/{transaction['id']}",
        json={
            "note": "Dinner with the project team",
            "tags": [" Work ", "client", "work", ""],
        },
    )

    assert updated.status_code == 200
    assert updated.json()["note"] == "Dinner with the project team"
    assert updated.json()["tags"] == ["Work", "client"]
    async with test_session_factory() as session:
        fields = set(
            (
                await session.scalars(
                    select(UserCorrection.field_corrected).where(
                        UserCorrection.transaction_id == transaction["id"]
                    )
                )
            ).all()
        )
    assert {"note", "tags"} <= fields


@pytest.mark.asyncio
async def test_transaction_list_filters_notes_and_tags_with_user_scope(client: AsyncClient):
    owner = await create_user(client, "transaction-search-owner")
    other = await create_user(client, "transaction-search-other")
    first = await _transaction(client, owner["id"], amount=1100)
    second = await _transaction(client, owner["id"], amount=1200)
    other_txn = await _transaction(client, other["id"], amount=1300)

    await client.patch(
        f"/api/transactions/{first['id']}",
        json={"note": "Cash reimbursement from office", "tags": ["Reimbursable", "cash"]},
    )
    await client.patch(
        f"/api/transactions/{second['id']}",
        json={"note": "Personal dinner", "tags": ["food"]},
    )
    await client.patch(
        f"/api/transactions/{other_txn['id']}",
        json={"note": "Cash reimbursement from office", "tags": ["Reimbursable"]},
    )

    by_note = await client.get(
        f"/api/transactions/?user_id={owner['id']}&note=reimbursement&limit=10"
    )
    by_note.raise_for_status()
    assert by_note.headers["X-Total-Count"] == "1"
    assert by_note.json()[0]["id"] == first["id"]

    by_tag = await client.get(f"/api/transactions/?user_id={owner['id']}&tag=reimbursable")
    by_tag.raise_for_status()
    assert by_tag.headers["X-Total-Count"] == "1"
    assert by_tag.json()[0]["id"] == first["id"]

    by_q = await client.get(f"/api/transactions/?user_id={owner['id']}&q=cash")
    by_q.raise_for_status()
    assert {item["id"] for item in by_q.json()} == {first["id"]}

    owner_search_from_other_user = await client.get(
        f"/api/transactions/?user_id={other['id']}&tag=reimbursable"
    )
    owner_search_from_other_user.raise_for_status()
    assert {item["id"] for item in owner_search_from_other_user.json()} == {other_txn["id"]}

    injection_probe = await client.get(
        f"/api/transactions/?user_id={owner['id']}&note=%25' OR 1=1 --"
    )
    injection_probe.raise_for_status()
    assert injection_probe.headers["X-Total-Count"] == "0"
    assert injection_probe.json() == []

    invalid_tag = await client.get(f"/api/transactions/?user_id={owner['id']}&tag={'x' * 33}")
    assert invalid_tag.status_code == 422


@pytest.mark.asyncio
async def test_splits_replace_allocations_without_changing_ledger_spend(client: AsyncClient):
    user = await create_user(client, "transaction-splits")
    transaction = await _transaction(client, user["id"], amount=1000)
    categories = (await client.get("/api/categories/")).json()

    replaced = await client.put(
        f"/api/transactions/{transaction['id']}/splits?user_id={user['id']}",
        json={
            "splits": [
                {"label": "Groceries", "amount": 650, "category_id": categories[0]["id"]},
                {"label": "Household", "amount": 350, "category_id": categories[1]["id"]},
            ]
        },
    )
    assert replaced.status_code == 200
    assert sum(item["amount"] for item in replaced.json()) == 1000

    listed = await client.get(f"/api/transactions/{transaction['id']}/splits?user_id={user['id']}")
    assert listed.status_code == 200
    assert {item["label"] for item in listed.json()} == {"Groceries", "Household"}

    today = date.today()
    summary = await client.get(
        f"/api/transactions/summary?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert summary.json()["total_spend"] == 1000
    assert summary.json()["transaction_count"] == 1

    invalid = await client.put(
        f"/api/transactions/{transaction['id']}/splits?user_id={user['id']}",
        json={"splits": [{"label": "A", "amount": 400}, {"label": "B", "amount": 400}]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["message"] == "Split amounts must equal the transaction amount"


@pytest.mark.asyncio
async def test_split_routes_reject_cross_user_scope(client: AsyncClient, auth_required):
    owner, owner_token = await register_user(client, "split-owner")
    attacker, attacker_token = await register_user(client, "split-attacker")
    transaction = await client.post(
        f"/api/transactions/?user_id={owner['id']}",
        headers=auth_headers(owner_token),
        json={
            "amount": 100,
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": "Private purchase",
        },
    )
    assert transaction.status_code == 201

    response = await client.get(
        f"/api/transactions/{transaction.json()['id']}/splits?user_id={owner['id']}",
        headers=auth_headers(attacker_token),
    )

    assert attacker["id"] != owner["id"]
    assert response.status_code == 403
