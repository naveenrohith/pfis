"""Regression tests for Phase 2-4 intelligence, analytics, goals, and explanations."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.category import Merchant, UserMerchantRule
from app.models.sync import UserCorrection
from app.models.transaction import Transaction, TransactionType
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
async def test_source_coverage_and_settled_aggregates_keep_pending_rows_explicit(
    client: AsyncClient,
):
    user = await create_user(client, "source-coverage-settled-ledger")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = date.today()

    await _seed_transaction(
        client,
        user["id"],
        category_id,
        amount=100.0,
        transaction_status="completed",
        reference_id="settled-debit",
    )
    await _seed_transaction(
        client,
        user["id"],
        category_id,
        amount=250.0,
        transaction_status="pending",
        reference_id="pending-debit",
    )
    await _seed_transaction(
        client,
        user["id"],
        category_id,
        amount=500.0,
        transaction_type="credit",
        transaction_status="failed",
        reference_id="failed-credit",
    )

    summary = await client.get(
        f"/api/transactions/summary?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    summary.raise_for_status()
    assert summary.json()["total_spend"] == 100.0
    assert summary.json()["total_income"] == 0.0
    assert summary.json()["transaction_count"] == 1

    coverage = await client.get(f"/api/analytics/source-coverage?user_id={user['id']}")
    coverage.raise_for_status()
    coverage_body = coverage.json()
    assert coverage_body["ruleset_version"] == "pfis-source-coverage-1"
    ledger = next(source for source in coverage_body["sources"] if source["key"] == "ledger")
    assert ledger["observed_count"] == 3
    assert ledger["completeness"] == "unknown"
    assert ledger["status"] == "partial"

    health = await client.get(
        f"/api/analytics/financial-health?user_id={user['id']}"
        f"&month={today.month}&year={today.year}"
    )
    health.raise_for_status()
    health_body = health.json()
    assert health_body["source_coverage_score"] == coverage_body["overall_score"]
    assert {source["key"] for source in health_body["source_coverage"]} == {
        "gmail",
        "ledger",
        "accounts",
        "pipeline",
    }


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
async def test_cash_flow_projection_consumes_dated_events_and_surfaces_conflict_range(
    client: AsyncClient,
):
    user = await create_user(client, "event-timed-cash-flow")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = date.today()
    await _seed_transaction(
        client,
        user["id"],
        category_id,
        amount=100,
        transaction_type="debit",
        merchant_normalized="Observed flexible spend",
        reference_id="event-timed-observed-spend",
    )
    bill = await client.post(
        f"/api/bills?user_id={user['id']}",
        json={
            "label": "Dated insurance obligation",
            "bill_type": "insurance",
            "amount": 5000,
            "due_date": today.isoformat(),
            "source_kind": "manual",
            "confirmed": True,
        },
    )
    bill.raise_for_status()

    projection = await client.get(
        f"/api/analytics/cash-flow?user_id={user['id']}" f"&month={today.month}&year={today.year}"
    )
    projection.raise_for_status()
    body = projection.json()
    assert body["ruleset_version"] == "pfis-cash-flow-6"
    assert body["temporal_ruleset_version"] == "pfis-temporal-events-1"
    assert body["temporal_expected_outflows"] == 5000.0
    assert body["temporal_event_count"] == 1
    assert body["projected_spend"] >= body["spend_to_date"] + 5000
    assert "forecast floors" in " ".join(body["assumptions"])

    timeline = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
    )
    event = next(
        item for item in timeline.json()["events"] if item["label"] == "Dated insurance obligation"
    )
    conflict = await client.put(
        f"/api/knowledge/events/{event['id']}/decision?user_id={user['id']}",
        json={"decision": "conflict", "note": "Amount is under provider review"},
    )
    conflict.raise_for_status()

    conflicted_projection = await client.get(
        f"/api/analytics/cash-flow?user_id={user['id']}" f"&month={today.month}&year={today.year}"
    )
    conflicted_projection.raise_for_status()
    conflicted = conflicted_projection.json()
    assert conflicted["temporal_expected_outflows"] == 0
    assert conflicted["temporal_conflicted_outflows"] == 5000.0
    assert conflicted["temporal_conflict_count"] == 1
    assert conflicted["projected_range_high"] >= conflicted["projected_spend"] + 5000
    assert conflicted["confidence"] < body["confidence"]


@pytest.mark.asyncio
async def test_cash_flow_backtest_reports_error_coverage_and_honest_limitations(
    client: AsyncClient,
    test_session_factory,
):
    user = await create_user(client, "cash-flow-backtest")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    cursor = date.today().replace(day=1)
    completed_months: list[tuple[int, int]] = []
    for _ in range(12):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        completed_months.append((cursor.year, cursor.month))

    async with test_session_factory() as db:
        for year, month in completed_months:
            for day, suffix in ((5, "early"), (20, "late")):
                db.add(
                    Transaction(
                        user_id=user["id"],
                        amount=Decimal("500.00"),
                        currency="INR",
                        transaction_type=TransactionType.DEBIT,
                        merchant_raw=f"BACKTEST {year}-{month:02d} {suffix}",
                        merchant_normalized="Backtest Spend",
                        category_id=category_id,
                        transaction_date=date(year, month, day),
                        created_at=datetime(year, month, day, 12, tzinfo=UTC),
                        fingerprint=f"backtest-{year}-{month:02d}-{suffix}",
                    )
                )
        await db.commit()

    response = await client.get(f"/api/analytics/cash-flow/backtest?user_id={user['id']}&months=6")
    response.raise_for_status()
    report = response.json()
    assert report["ruleset_version"] == "pfis-cash-flow-6"
    assert report["evaluation_version"] == "pfis-cash-flow-backtest-2"
    assert report["requested_months"] == 6
    assert report["evaluated_months"] == 6
    assert report["excluded_months"] == []
    assert report["temporal_evidence_evaluated"] is True
    assert report["temporal_evidence_periods"] >= 0
    assert report["temporal_event_count"] >= 0
    assert report["settled_transaction_count"] == 24
    assert report["unsettled_transaction_count"] == 0
    assert "cannot yet be reconstructed" in " ".join(report["limitations"])
    assert [item["cutoff_day"] for item in report["horizons"]] == [7, 14, 21]
    assert all(item["eligible_periods"] == 6 for item in report["horizons"])
    assert all(
        item["weighted_absolute_percentage_error"] is not None for item in report["horizons"]
    )
    assert all(0 <= item["interval_coverage_pct"] <= 100 for item in report["horizons"])

    empty = await create_user(client, "cash-flow-backtest-empty")
    empty_response = await client.get(
        f"/api/analytics/cash-flow/backtest?user_id={empty['id']}&months=3"
    )
    empty_response.raise_for_status()
    empty_report = empty_response.json()
    assert empty_report["evaluated_months"] == 0
    assert len(empty_report["excluded_months"]) == 3
    assert {item["reason"] for item in empty_report["excluded_months"]} == {
        "insufficient_prior_history"
    }
    assert all(item["eligible_periods"] == 0 for item in empty_report["horizons"])


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
        assert other_resolution.source == "descriptor_rules"

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
    assert scenario_body["scenario_projected_net"] == pytest.approx(
        scenario_body["baseline_projected_net"] + scenario_body["monthly_impact"],
        abs=0.01,
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
    confidence = health.json()["data_confidence_breakdown"]
    assert [item["key"] for item in confidence] == [
        "coverage",
        "freshness",
        "parsing",
        "conflicts",
    ]
    assert all(0 <= item["score"] <= 100 for item in confidence)
    assert all(
        item["remediation_label"] and item["remediation_target"]
        for item in confidence
        if item["status"] != "strong"
    )
    assert health.json()["data_confidence_ruleset_version"] == "pfis-data-confidence-2"
    assert health.json()["ruleset_version"] == "pfis-stability-1"
    assert health.json()["budget_adherence"] is None
    assert cash_flow.json()["ruleset_version"] == "pfis-cash-flow-6"
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
