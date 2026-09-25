"""Regression tests for the evidence-backed `/api/ai/explain` contract."""

from datetime import date

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import auth_headers, create_user, register_user


async def _seed_spend(
    client: AsyncClient, user_id: str, category_id: str, amount: float, ref: str
) -> None:
    today = date.today()
    response = await client.post(
        f"/api/transactions/?user_id={user_id}",
        json={
            "amount": amount,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": "CORNER CAFE",
            "merchant_normalized": "Corner Cafe",
            "category_id": category_id,
            "transaction_date": today.isoformat(),
            "confidence_score": 0.95,
            "reference_id": f"EXPLAIN-{ref}",
        },
    )
    response.raise_for_status()


async def _category_item(client: AsyncClient, user_id: str, category_id: str) -> dict:
    today = date.today()
    response = await client.get(
        f"/api/categories/intelligence?user_id={user_id}&month={today.month}&year={today.year}"
    )
    response.raise_for_status()
    return next(c for c in response.json()["categories"] if c["category_id"] == category_id)


@pytest.mark.asyncio
async def test_explain_without_scope_qualifies_metrics_and_states_missing_evidence(
    client: AsyncClient,
):
    response = await client.post(
        "/api/ai/explain",
        json={
            "surface": "Category",
            "title": "Dining",
            "description": "Spend summary",
            "metrics": {
                "total_spend": 1200,
                "budget_usage_pct": -5,
                "month_change_pct": "high",
                "access_token": "should-not-echo",
                "custom_note": "x" * 200,
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ruleset_version"] == "pfis-explain-1"
    assert body["surface_kind"] == "category"
    assert body["evidence_status"] == "unverified"
    assert body["source"] == "client_supplied"
    assert body["as_of"] is None
    assert body["coverage"] == []
    assert any("user scope" in item for item in body["missing_evidence"])
    statuses = {metric["key"]: metric for metric in body["metrics"]}
    assert statuses["total_spend"]["status"] == "unverified"
    assert statuses["budget_usage_pct"]["status"] == "invalid"
    assert statuses["month_change_pct"]["status"] == "invalid"
    assert statuses["access_token"]["status"] == "withheld"
    assert statuses["access_token"]["supplied_value"] is None
    assert len(statuses["custom_note"]["supplied_value"]) <= 80
    assert "should-not-echo" not in response.text
    assert body["next_actions"] == [action["label"] for action in body["actions"]]
    assert any("signed in" in action for action in body["next_actions"])
    assert "raw email" in body["safety_note"].lower()


@pytest.mark.asyncio
async def test_explain_category_verifies_against_read_model_and_flags_conflicts(
    client: AsyncClient,
):
    user = await create_user(client)
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    await _seed_spend(client, user["id"], category_id, 400.0, "a")
    await _seed_spend(client, user["id"], category_id, 600.0, "b")
    item = await _category_item(client, user["id"], category_id)
    today = date.today()
    base = {
        "surface": "category",
        "title": item["name"],
        "month": today.month,
        "year": today.year,
        "subject_id": category_id,
    }

    verified = await client.post(
        f"/api/ai/explain?user_id={user['id']}",
        json={
            **base,
            "metrics": {
                "total_spend": item["total_spend"],
                "transaction_count": item["transaction_count"],
            },
        },
    )
    assert verified.status_code == 200
    body = verified.json()
    assert body["evidence_status"] == "verified"
    assert body["source"] == "pfis_read_model"
    assert body["as_of"] is not None
    assert body["period_month"] == today.month
    assert body["coverage_score"] is not None
    assert {source["key"] for source in body["coverage"]} >= {"gmail", "ledger"}
    assert body["assumptions"]
    assert all(metric["status"] == "verified" for metric in body["metrics"])
    assert any("Corner Cafe" in driver for driver in body["drivers"])
    targets = {action["target"] for action in body["actions"]}
    assert "budgets" in targets
    assert any("monthly limit" in action for action in body["next_actions"])

    conflict = await client.post(
        f"/api/ai/explain?user_id={user['id']}",
        json={**base, "metrics": {"total_spend": 99999}},
    )
    assert conflict.status_code == 200
    conflict_body = conflict.json()
    assert conflict_body["evidence_status"] == "conflict"
    metric = conflict_body["metrics"][0]
    assert metric["status"] == "mismatch"
    assert metric["verified_value"] == "1000"
    assert conflict_body["next_actions"][0].startswith("Refresh this view")


@pytest.mark.asyncio
async def test_explain_reports_missing_period_and_unmatched_subject(client: AsyncClient):
    user = await create_user(client)
    today = date.today()

    no_period = await client.post(
        f"/api/ai/explain?user_id={user['id']}",
        json={"surface": "category", "title": "Dining", "metrics": {"total_spend": 10}},
    )
    assert no_period.status_code == 200
    body = no_period.json()
    assert body["evidence_status"] == "unverified"
    assert body["as_of"] is not None
    assert any("month and year" in item for item in body["missing_evidence"])

    unmatched = await client.post(
        f"/api/ai/explain?user_id={user['id']}",
        json={
            "surface": "merchant",
            "title": "Nowhere Merchant",
            "month": today.month,
            "year": today.year,
            "metrics": {"total_spend": 10},
        },
    )
    assert unmatched.status_code == 200
    unmatched_body = unmatched.json()
    assert unmatched_body["evidence_status"] == "unverified"
    assert any("No owned merchant" in item for item in unmatched_body["missing_evidence"])

    general = await client.post(
        f"/api/ai/explain?user_id={user['id']}",
        json={"surface": "budget-cash-overview", "title": "Overview", "metrics": {"x": 1}},
    )
    assert general.status_code == 200
    assert general.json()["surface_kind"] == "general"
    assert any("no verification read model" in m for m in general.json()["missing_evidence"])


@pytest.mark.asyncio
async def test_explain_financial_health_uses_confidence_remediation(client: AsyncClient):
    user = await create_user(client)
    today = date.today()
    health = await client.get(
        f"/api/analytics/financial-health?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    health.raise_for_status()
    score = health.json()["score"]

    response = await client.post(
        f"/api/ai/explain?user_id={user['id']}",
        json={
            "surface": "financial health",
            "title": "Health score",
            "month": today.month,
            "year": today.year,
            "metrics": {"score": score},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["surface_kind"] == "financial_health"
    assert body["evidence_status"] == "verified"
    assert any(item["label"] == "Health ruleset" for item in body["evidence"])
    remediation = {
        dim["remediation_label"]
        for dim in health.json()["data_confidence_breakdown"]
        if dim.get("remediation_label")
    }
    assert remediation & set(body["next_actions"])
    assert 1 <= len(body["next_actions"]) <= 4


@pytest.mark.asyncio
async def test_explain_enforces_user_scope_when_auth_required(client: AsyncClient, auth_required):
    owner, owner_token = await register_user(client, "explain-owner")
    _, other_token = await register_user(client, "explain-other")
    client.cookies.clear()
    payload = {"surface": "category", "title": "Dining", "metrics": {"total_spend": 1}}

    forbidden = await client.post(
        f"/api/ai/explain?user_id={owner['id']}",
        json=payload,
        headers=auth_headers(other_token),
    )
    assert forbidden.status_code == 403

    anonymous = await client.post(f"/api/ai/explain?user_id={owner['id']}", json=payload)
    assert anonymous.status_code == 401

    scoped = await client.post("/api/ai/explain", json=payload, headers=auth_headers(owner_token))
    assert scoped.status_code == 200
    assert scoped.json()["as_of"] is not None
