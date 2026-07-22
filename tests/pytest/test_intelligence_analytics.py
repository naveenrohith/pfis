"""Regression tests for Phase 2-4 intelligence, analytics, goals, and explanations."""

from datetime import date, timedelta

import pytest
from app.models.category import Merchant, UserMerchantRule
from app.models.sync import UserCorrection
from app.models.transaction import Transaction
from app.services.parser.normalizer import resolve_merchant
from httpx import AsyncClient
from sqlalchemy import select

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
    assert coffee["recurrence_likelihood"] == 0
    assert coffee["recurrence_status"] == "candidate"

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
async def test_recurring_intelligence_uses_cadence_maturity_and_evidence(client: AsyncClient):
    user = await create_user(client, "recurring-knowledge")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = date.today()
    for index, days_ago in enumerate((91, 61, 31, 1)):
        await _seed_transaction(
            client,
            user["id"],
            category_id,
            merchant_normalized="Monthly Service",
            amount=499 + index,
            transaction_date=(today - timedelta(days=days_ago)).isoformat(),
            reference_id=f"monthly-{index}",
        )

    response = await client.get(
        f"/api/insights/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert response.status_code == 200
    recurring = next(
        item
        for item in response.json()["recurring_payments"]
        if item["merchant"] == "Monthly Service"
    )
    assert recurring["cadence"] == "monthly"
    assert recurring["status"] == "mature"
    assert recurring["confidence"] >= 0.8
    assert recurring["monthly_equivalent"] > 0
    assert recurring["evidence"]


@pytest.mark.asyncio
async def test_merchant_edit_is_user_scoped_and_preserves_ledger_invariants(
    client: AsyncClient, test_session_factory
):
    first = await create_user(client, "merchant-edit-first")
    second = await create_user(client, "merchant-edit-second")
    categories = (await client.get("/api/categories/")).json()
    food = next(category for category in categories if category["name"] == "Food")
    shopping = next(category for category in categories if category["name"] == "Shopping")
    today = date.today()

    first_txn = await _seed_transaction(
        client,
        first["id"],
        food["id"],
        merchant_raw="COFFEE BAR BLR",
        merchant_normalized="Coffee Bar",
        amount=250.0,
        reference_id="first-coffee",
    )
    second_txn = await _seed_transaction(
        client,
        second["id"],
        food["id"],
        merchant_raw="COFFEE BAR BLR",
        merchant_normalized="Coffee Bar",
        amount=250.0,
        reference_id="second-coffee",
    )

    learned_rule_id = ""
    async with test_session_factory() as db:
        original_first_record = await db.get(Transaction, first_txn["id"])
        assert original_first_record is not None
        original_first_fingerprint = original_first_record.fingerprint

    summary_before = await client.get(
        f"/api/transactions/summary?user_id={first['id']}&month={today.month}&year={today.year}"
    )
    assert summary_before.status_code == 200

    invalid_category = await client.patch(
        f"/api/merchants/Coffee%20Bar?user_id={first['id']}&month={today.month}&year={today.year}",
        json={"normalized_name": "Cafe Prime", "default_category_id": "missing-category"},
    )
    assert invalid_category.status_code == 409

    response = await client.patch(
        f"/api/merchants/Coffee%20Bar?user_id={first['id']}&month={today.month}&year={today.year}",
        json={
            "normalized_name": "Cafe Prime",
            "default_category_id": shopping["id"],
            "aliases": ["COFFEE PRIME BLR"],
            "apply_existing": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Cafe Prime"
    assert "COFFEE BAR BLR" in response.json()["aliases"]
    assert "COFFEE PRIME BLR" in response.json()["aliases"]

    first_rows = await client.get(f"/api/transactions/?user_id={first['id']}")
    second_rows = await client.get(f"/api/transactions/?user_id={second['id']}")
    assert first_rows.json()[0]["merchant_normalized"] == "Cafe Prime"
    assert first_rows.json()[0]["category_id"] == shopping["id"]
    assert first_rows.json()[0]["merchant_resolution_source"] == "user_rule"
    assert second_rows.json()[0]["merchant_normalized"] == "Coffee Bar"
    assert second_rows.json()[0]["category_id"] == food["id"]

    summary_after = await client.get(
        f"/api/transactions/summary?user_id={first['id']}&month={today.month}&year={today.year}"
    )
    assert summary_after.status_code == 200
    assert summary_after.json()["top_merchants"][0]["name"] == "Cafe Prime"

    async with test_session_factory() as db:
        first_record = await db.get(Transaction, first_txn["id"])
        second_record = await db.get(Transaction, second_txn["id"])
        assert first_record is not None and second_record is not None
        assert first_record.fingerprint != original_first_fingerprint
        assert second_record.merchant_normalized == "Coffee Bar"

        corrections = await db.execute(
            select(UserCorrection).where(UserCorrection.transaction_id == first_txn["id"])
        )
        assert {row.field_corrected for row in corrections.scalars().all()} >= {
            "merchant_normalized",
            "category_id",
        }

        rules = await db.execute(
            select(UserMerchantRule).where(UserMerchantRule.user_id == first["id"])
        )
        learned_rules = list(rules.scalars().all())
        assert {rule.raw_descriptor for rule in learned_rules} >= {
            "COFFEE BAR BLR",
            "COFFEE PRIME BLR",
        }
        learned_rule_id = learned_rules[0].id
        other_rules = await db.execute(
            select(UserMerchantRule).where(UserMerchantRule.user_id == second["id"])
        )
        assert other_rules.scalars().all() == []

        global_merchant = await db.execute(
            select(Merchant).where(Merchant.normalized_name == "Cafe Prime")
        )
        assert global_merchant.scalar_one_or_none() is None

        own_resolution = await resolve_merchant(db, "COFFEE PRIME BLR", user_id=first["id"])
        other_resolution = await resolve_merchant(db, "COFFEE PRIME BLR", user_id=second["id"])
        assert own_resolution.normalized_name == "Cafe Prime"
        assert own_resolution.source == "user_rule"
        assert other_resolution.normalized_name == "Coffee Prime Blr"
        assert other_resolution.source == "cleaned_fallback"

    listed_rules = await client.get(f"/api/merchants/learned-rules?user_id={first['id']}")
    assert listed_rules.status_code == 200
    assert {rule["raw_descriptor"] for rule in listed_rules.json()} >= {
        "COFFEE BAR BLR",
        "COFFEE PRIME BLR",
    }
    cannot_delete_other_user = await client.delete(
        f"/api/merchants/learned-rules/{learned_rule_id}?user_id={second['id']}"
    )
    assert cannot_delete_other_user.status_code == 404
    deleted = await client.delete(
        f"/api/merchants/learned-rules/{learned_rule_id}?user_id={first['id']}"
    )
    assert deleted.status_code == 204


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
    assert health.json()["score"] == health.json()["monthly_stability"]
    assert 0 <= health.json()["data_confidence"] <= 100
    assert health.json()["ruleset_version"] == "pfis-stability-1"
    assert health.json()["budget_adherence"] is None
    assert cash_flow.json()["ruleset_version"] == "pfis-cash-flow-3"
    assert cash_flow.json()["evidence"]

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
