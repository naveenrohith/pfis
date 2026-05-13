"""API regression tests for email counts, correction learning, and pipeline behavior."""

# pyright: reportMissingImports=false

from __future__ import annotations

from sqlalchemy import select

from app.models.category import Category, Merchant
from app.models.sync import UserCorrection
from app.services.parser.normalizer import normalize_merchant
from tests.pytest.helpers import create_user


async def test_gmail_email_counts_respect_filters(client):
    user = await create_user(client, "counts")

    sync_response = await client.post(f"/api/gmail/demo-sync?user_id={user['id']}")
    sync_response.raise_for_status()
    assert sync_response.json()["stats"]["emails_stored"] == 13

    unprocessed = await client.get(f"/api/gmail/emails?user_id={user['id']}&processed=false")
    unprocessed.raise_for_status()
    unprocessed_payload = unprocessed.json()
    assert unprocessed_payload["total"] == 13
    assert unprocessed_payload["all_total"] == 13
    assert unprocessed_payload["processed_total"] == 0
    assert unprocessed_payload["unprocessed_total"] == 13
    assert len(unprocessed_payload["emails"]) == 13

    pipeline_response = await client.post(f"/api/pipeline/process?user_id={user['id']}")
    pipeline_response.raise_for_status()
    assert pipeline_response.json()["stats"]["stored"] == 13

    processed = await client.get(f"/api/gmail/emails?user_id={user['id']}&processed=false")
    processed.raise_for_status()
    processed_payload = processed.json()
    assert processed_payload["total"] == 0
    assert processed_payload["processed_total"] == 13
    assert processed_payload["unprocessed_total"] == 0


async def test_correction_learning_updates_alias_and_history(client, test_session_factory):
    user = await create_user(client, "learning")
    categories_response = await client.get("/api/categories/")
    categories_response.raise_for_status()
    categories = categories_response.json()
    food = next(category for category in categories if category["name"] == "Food")

    create_response = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 245.0,
            "transaction_type": "debit",
            "merchant_raw": "LOCAL CAFE BLR",
            "merchant_normalized": "Local Cafe Blr",
            "category_id": food["id"],
            "transaction_date": "2026-05-05",
            "account_last4": "1234",
            "reference_id": "LCB245",
            "confidence_score": 0.72,
        },
    )
    create_response.raise_for_status()
    transaction = create_response.json()

    correction_response = await client.patch(
        f"/api/transactions/{transaction['id']}",
        json={
            "merchant_normalized": "Cafe Nero",
            "category_id": food["id"],
            "amount": 250.0,
        },
    )
    correction_response.raise_for_status()
    corrected = correction_response.json()
    assert corrected["merchant_normalized"] == "Cafe Nero"
    assert corrected["amount"] == 250.0
    assert corrected["reviewed_flag"] is True
    assert corrected["reviewed_at"] is not None

    async with test_session_factory() as db:
        correction_rows = await db.execute(
            select(UserCorrection).where(UserCorrection.transaction_id == transaction["id"])
        )
        corrections = correction_rows.scalars().all()
        assert {row.field_corrected for row in corrections} >= {"merchant_normalized", "amount"}

        merchant_result = await db.execute(
            select(Merchant).where(Merchant.normalized_name == "Cafe Nero")
        )
        merchant = merchant_result.scalar_one()
        assert "LOCAL CAFE BLR" in merchant.aliases

        normalized_name, category_id = await normalize_merchant(db, "LOCAL CAFE BLR")
        assert normalized_name == "Cafe Nero"
        assert category_id == food["id"]


async def test_pipeline_dedup_remains_user_scoped(client):
    first_user = await create_user(client, "scopea")
    second_user = await create_user(client, "scopeb")
    categories_response = await client.get("/api/categories/")
    categories = categories_response.json()
    food = next(category for category in categories if category["name"] == "Food")

    payload = {
        "amount": 450.0,
        "transaction_type": "debit",
        "merchant_raw": "SWIGGY",
        "merchant_normalized": "Swiggy",
        "category_id": food["id"],
        "transaction_date": "2026-05-05",
        "account_last4": "1234",
        "reference_id": "shared-fingerprint",
        "confidence_score": 0.9,
    }

    response_one = await client.post(f"/api/transactions/?user_id={first_user['id']}", json=payload)
    response_two = await client.post(f"/api/transactions/?user_id={second_user['id']}", json=payload)

    response_one.raise_for_status()
    response_two.raise_for_status()
    assert response_one.json()["id"] != response_two.json()["id"]


async def test_bulk_review_updates_apply_shared_changes(client):
    user = await create_user(client, "bulkreview")
    categories_response = await client.get("/api/categories/")
    categories_response.raise_for_status()
    categories = categories_response.json()
    transport = next(category for category in categories if category["name"] == "Transport")

    created_ids = []
    for idx in range(2):
        response = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 120.0 + idx,
                "transaction_type": "debit",
                "merchant_raw": f"AUTO RICKSHAW {idx}",
                "merchant_normalized": f"Auto Rickshaw {idx}",
                "category_id": None,
                "transaction_date": "2026-05-06",
                "account_last4": "9876",
                "reference_id": f"bulk-{idx}",
                "confidence_score": 0.52,
            },
        )
        response.raise_for_status()
        payload = response.json()
        assert payload["reviewed_flag"] is False
        created_ids.append(payload["id"])

    bulk_response = await client.patch(
        f"/api/transactions/bulk-update?user_id={user['id']}",
        json={
            "transaction_ids": created_ids,
            "category_id": transport["id"],
            "transaction_type": "debit",
            "reviewed_flag": True,
        },
    )
    bulk_response.raise_for_status()
    bulk_payload = bulk_response.json()
    assert bulk_payload["requested_count"] == 2
    assert bulk_payload["updated_count"] == 2
    assert bulk_payload["failed"] == []

    list_response = await client.get(f"/api/transactions/?user_id={user['id']}&month=5&year=2026")
    list_response.raise_for_status()
    transactions = list_response.json()
    assert len(transactions) == 2
    assert all(txn["category_id"] == transport["id"] for txn in transactions)
    assert all(txn["reviewed_flag"] is True for txn in transactions)
    assert all(txn["reviewed_at"] is not None for txn in transactions)