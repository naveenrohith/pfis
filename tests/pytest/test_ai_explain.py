"""Regression tests for the evidence-backed `/api/ai/explain` contract."""

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from app.schemas.intelligence import (
    DataConfidenceDimension,
    ExplainRequest,
    FinancialHealthScore,
    SourceCoverage,
    SourceCoverageResponse,
)
from app.services.explanation_service import _SPECS, ExplanationService, _Subject
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


async def _seed_merchant_spend(
    client: AsyncClient,
    user_id: str,
    *,
    merchant: str,
    amount: float,
    txn_date: date,
    ref: str,
) -> None:
    response = await client.post(
        f"/api/transactions/?user_id={user_id}",
        json={
            "amount": amount,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": merchant.upper(),
            "merchant_normalized": merchant,
            "transaction_date": txn_date.isoformat(),
            "confidence_score": 0.95,
            "reference_id": f"MERCHANT-EXPLAIN-{ref}",
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
async def test_explain_merchant_verifies_uncategorized_spend_and_recommends_review(
    client: AsyncClient,
):
    user = await create_user(client, "explain-merchant")
    today = date.today()
    previous_month = 12 if today.month == 1 else today.month - 1
    previous_year = today.year - 1 if today.month == 1 else today.year
    await _seed_merchant_spend(
        client,
        user["id"],
        merchant="Stream Box",
        amount=100.0,
        txn_date=date(previous_year, previous_month, 5),
        ref="prev",
    )
    await _seed_merchant_spend(
        client,
        user["id"],
        merchant="Stream Box",
        amount=600.0,
        txn_date=date(today.year, today.month, 5),
        ref="a",
    )
    await _seed_merchant_spend(
        client,
        user["id"],
        merchant="Stream Box",
        amount=400.0,
        txn_date=date(today.year, today.month, 15),
        ref="b",
    )
    merchants = await client.get(
        f"/api/merchants/?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    merchants.raise_for_status()
    merchant = next(item for item in merchants.json() if item["name"] == "Stream Box")

    response = await client.post(
        f"/api/ai/explain?user_id={user['id']}",
        json={
            "surface": "merchant",
            "title": "Stream Box",
            "month": today.month,
            "year": today.year,
            "subject_id": merchant["merchant_key"],
            "metrics": {
                "total_spend": merchant["total_spend"],
                "transaction_count": merchant["transaction_count"],
                "avg_spend": merchant["avg_spend"],
                "month_change_pct": merchant["month_change_pct"],
                "nested": {"unsafe": "not accepted"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["surface_kind"] == "merchant"
    assert body["evidence_status"] == "partial"
    by_key = {metric["key"]: metric for metric in body["metrics"]}
    assert by_key["total_spend"]["status"] == "verified"
    assert by_key["transaction_count"]["verified_value"] == "2"
    assert by_key["avg_spend"]["verified_value"] == "500"
    assert by_key["nested"]["status"] == "invalid"
    assert any(
        item["label"] == "Merchant" and item["value"] == "Stream Box" for item in body["evidence"]
    )
    assert any("Assign a default category" in action for action in body["next_actions"])
    assert any("latest transactions" in action for action in body["next_actions"])


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


def test_explanation_helpers_prioritize_surface_specific_actions_and_metric_limits():
    subject = _Subject(
        values={
            "total_spend": 1050.0,
            "transaction_count": 0,
            "budget_usage_pct": 105.0,
            "budget_limit": None,
            "month_change_pct": 30.0,
        },
        evidence=[],
        extra={"top_merchant": "Corner Cafe"},
    )
    data = ExplainRequest(
        surface="category",
        title="Dining",
        metrics={},
    )

    metrics, skipped = ExplanationService._qualify_metrics(
        {
            "spent": 1050,
            "transaction_count": 0,
            "budget_usage_pct": 105,
            "month_change_pct": 30,
            "score": True,
            "nested": {"not": "accepted"},
            **{f"extra_{index}": index for index in range(10)},
        },
        _SPECS["category"],
        subject,
    )
    assert skipped == 4
    by_key = {metric.key: metric for metric in metrics}
    assert by_key["spent"].status == "verified"
    assert by_key["transaction_count"].status == "verified"
    assert by_key["score"].status == "unverified"
    assert by_key["nested"].status == "invalid"

    actions = ExplanationService._actions(
        "category",
        data,
        metrics,
        subject,
        None,
        None,
        "user-1",
    )
    assert [action.target for action in actions] == [
        "transactions",
        "budgets",
        "insights",
        "transactions",
    ]
    assert actions[0].label == "Check whether Dining spend was categorized elsewhere."

    merchant_actions = ExplanationService._actions(
        "merchant",
        ExplainRequest(surface="merchant", title="Corner Cafe", metrics={}),
        [],
        _Subject(
            values={"month_change_pct": 40.0},
            evidence=[],
            extra={"category": None, "recurrence_status": "candidate"},
        ),
        None,
        None,
        "user-1",
    )
    assert [action.label for action in merchant_actions] == [
        "Assign a default category for this merchant.",
        "Review the latest transactions for this merchant.",
    ]

    health_actions = ExplanationService._actions(
        "financial_health",
        ExplainRequest(surface="health", title="Health", metrics={}),
        [],
        _Subject(values={}, evidence=[], extra={}),
        FinancialHealthScore(
            score=62,
            budget_adherence=None,
            data_confidence_breakdown=[
                DataConfidenceDimension(
                    key="coverage",
                    label="Source coverage",
                    score=45,
                    status="limited",
                    summary="Coverage needs attention.",
                    remediation_label="Reconnect Gmail",
                    remediation_target="data",
                )
            ],
        ),
        SourceCoverageResponse(
            as_of=datetime(2026, 9, 25, 12, 0, 0),
            overall_score=30,
            sources=[
                SourceCoverage(
                    key="ledger",
                    label="Ledger",
                    status="partial",
                    completeness="unknown",
                    score=30,
                    remediation_label="Add recent transactions",
                    remediation_target="transactions",
                )
            ],
        ),
        "user-1",
    )
    assert [action.label for action in health_actions] == [
        "Reconnect Gmail",
        "Create budgets for your main categories.",
        "Add recent transactions",
    ]
    assert ExplanationService._summary("Empty", "partial", [], None) == (
        "Empty: no figures were supplied to verify."
    )


@pytest.mark.asyncio
async def test_explanation_subject_helpers_match_by_title_and_emit_evidence():
    service = ExplanationService(db=None)  # type: ignore[arg-type]

    class FakeIntelligence:
        async def category_intelligence(self, user_id: str, month: int, year: int):
            assert (user_id, month, year) == ("user-1", 9, 2026)
            return SimpleNamespace(
                categories=[
                    SimpleNamespace(
                        category_id="cat-food",
                        name="Food",
                        total_spend=750.0,
                        transaction_count=3,
                        month_change_pct=12.5,
                        budget_limit=None,
                        budget_usage_pct=None,
                        top_merchants=[SimpleNamespace(name="Corner Cafe")],
                    )
                ]
            )

        async def list_merchants(self, user_id: str, month: int, year: int):
            assert (user_id, month, year) == ("user-1", 9, 2026)
            return [
                SimpleNamespace(
                    merchant_key="corner-cafe",
                    name="Corner Cafe",
                    total_spend=500.0,
                    transaction_count=2,
                    avg_spend=250.0,
                    month_change_pct=50.0,
                    category=None,
                    recurrence_status="candidate",
                )
            ]

    service.intelligence = FakeIntelligence()  # type: ignore[assignment]

    category = await service._category_subject(
        "user-1",
        9,
        2026,
        ExplainRequest(surface="category", title="Food", metrics={}),
    )
    assert category is not None
    assert category.values["total_spend"] == 750.0
    assert category.extra["top_merchant"] == "Corner Cafe"
    assert [item.label for item in category.evidence] == [
        "Read model",
        "Category",
        "Transactions",
        "Budget limit",
    ]
    assert category.evidence[-1].value == "Not set"

    merchant = await service._merchant_subject(
        "user-1",
        9,
        2026,
        ExplainRequest(surface="merchant", title="Corner Cafe", metrics={}),
    )
    assert merchant is not None
    assert merchant.values["avg_spend"] == 250.0
    assert merchant.extra == {"category": None, "recurrence_status": "candidate"}
    assert any(
        item.label == "Category" and item.value == "Uncategorized" for item in merchant.evidence
    )

    missing = await service._merchant_subject(
        "user-1",
        9,
        2026,
        ExplainRequest(surface="merchant", title="Missing Merchant", metrics={}),
    )
    assert missing is None


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
