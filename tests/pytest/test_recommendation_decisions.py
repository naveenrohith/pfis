"""Recommendation acceptance, relevance, and outcome lifecycle tests."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.models.transaction import Transaction
from app.models.workspace import RecommendationOutcome, RecommendationState
from httpx import AsyncClient
from sqlalchemy import select

from tests.pytest.helpers import create_user


async def _review_recommendation(client: AsyncClient, user_id: str, suffix: str) -> dict:
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = date.today()
    created = await client.post(
        f"/api/transactions/?user_id={user_id}",
        json={
            "amount": 750,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": f"UNCERTAIN {suffix}",
            "merchant_normalized": "Uncertain Activity",
            "category_id": category_id,
            "transaction_date": today.isoformat(),
            "confidence_score": 0.35,
            "reference_id": f"recommendation-decision-{suffix}",
        },
    )
    created.raise_for_status()
    brief = await client.get(
        f"/api/guidance/brief?user_id={user_id}&period=daily&as_of={today.isoformat()}"
    )
    brief.raise_for_status()
    return next(action for action in brief.json()["actions"] if action["type"] == "review")


@pytest.mark.asyncio
async def test_accepted_recommendation_preserves_evidence_and_records_one_outcome(
    client: AsyncClient,
    test_session_factory,
):
    user = await create_user(client, "recommendation-accepted")
    other = await create_user(client, "recommendation-accepted-other")
    today = date.today()
    action = await _review_recommendation(client, user["id"], "accepted")

    missing = await client.patch(
        f"/api/guidance/not-a-current-recommendation/state?user_id={user['id']}",
        json={"state": "accepted", "as_of": today.isoformat()},
    )
    assert missing.status_code == 404

    accepted = await client.patch(
        f"/api/guidance/{action['id']}/state?user_id={user['id']}",
        json={
            "state": "accepted",
            "as_of": today.isoformat(),
            "note": "I will review these records this week",
        },
    )
    accepted.raise_for_status()
    decision = accepted.json()
    assert decision["state"] == "accepted"
    assert decision["title"] == action["title"]
    assert decision["target"] == action["target"]
    assert decision["expected_impact"] == action["expected_impact"]
    assert decision["evidence"]
    assert decision["reason_codes"]
    assert decision["guidance_ruleset_version"] == "pfis-guidance-3"
    assert decision["decision_as_of"] == today.isoformat()
    assert decision["baseline_metric_key"] == "unresolved_review_count"
    assert decision["baseline_metric_value"] == 1.0
    assert decision["baseline_metric_unit"] == "records"

    hidden = await client.get(
        f"/api/guidance/brief?user_id={user['id']}&period=daily&as_of={today.isoformat()}"
    )
    assert all(item["id"] != action["id"] for item in hidden.json()["actions"])
    decisions = await client.get(f"/api/guidance/decisions?user_id={user['id']}")
    assert decisions.json() == [decision]
    assert (await client.get(f"/api/guidance/decisions?user_id={other['id']}")).json() == []

    outcome_url = f"/api/guidance/decisions/{decision['id']}/outcome?user_id={user['id']}"
    payload = {
        "outcome": "helped",
        "note": "All 3 uncertain records were corrected",
        "actual_impact_value": 3,
        "actual_impact_unit": "records",
    }
    async with test_session_factory() as db:
        transaction = await db.scalar(select(Transaction).where(Transaction.user_id == user["id"]))
        assert transaction is not None
        transaction.confidence_score = Decimal("0.95")
        transaction.reviewed_flag = True
        await db.commit()
    outcome = await client.post(outcome_url, json=payload)
    outcome.raise_for_status()
    outcome_body = outcome.json()
    assert outcome_body["outcome_ruleset_version"] == "pfis-recommendation-outcome-1"
    assert outcome_body["actual_impact_value"] == 3.0
    assert outcome_body["actual_impact_unit"] == "records"
    assert outcome_body["metric_key"] == "unresolved_review_count"
    assert outcome_body["baseline_metric_value"] == 1.0
    assert outcome_body["observed_metric_value"] == 0.0
    assert outcome_body["automatic_impact_value"] == 1.0
    assert outcome_body["metric_unit"] == "records"
    repeated = await client.post(outcome_url, json=payload)
    assert repeated.status_code == 200
    assert repeated.json() == outcome_body
    changed = await client.post(outcome_url, json={"outcome": "no_change"})
    assert changed.status_code == 409
    cross_user = await client.post(
        f"/api/guidance/decisions/{decision['id']}/outcome?user_id={other['id']}",
        json=payload,
    )
    assert cross_user.status_code == 404
    changed_decision = await client.patch(
        f"/api/guidance/{action['id']}/state?user_id={user['id']}",
        json={"state": "not_relevant", "as_of": today.isoformat()},
    )
    assert changed_decision.status_code == 422
    listed_outcomes = await client.get(f"/api/guidance/outcomes?user_id={user['id']}")
    assert listed_outcomes.json() == [outcome_body]


@pytest.mark.asyncio
async def test_not_relevant_feedback_hides_advice_and_cannot_claim_an_outcome(
    client: AsyncClient,
):
    user = await create_user(client, "recommendation-not-relevant")
    today = date.today()
    action = await _review_recommendation(client, user["id"], "not-relevant")
    invalid_snooze = await client.patch(
        f"/api/guidance/{action['id']}/state?user_id={user['id']}",
        json={"state": "snoozed", "as_of": today.isoformat()},
    )
    assert invalid_snooze.status_code == 422

    response = await client.patch(
        f"/api/guidance/{action['id']}/state?user_id={user['id']}",
        json={
            "state": "not_relevant",
            "as_of": today.isoformat(),
            "note": "This activity was already verified elsewhere",
        },
    )
    response.raise_for_status()
    decision = response.json()
    assert decision["state"] == "not_relevant"
    assert decision["decision_note"] == "This activity was already verified elsewhere"
    brief = await client.get(
        f"/api/guidance/brief?user_id={user['id']}&period=daily&as_of={today.isoformat()}"
    )
    assert all(item["id"] != action["id"] for item in brief.json()["actions"])

    outcome = await client.post(
        f"/api/guidance/decisions/{decision['id']}/outcome?user_id={user['id']}",
        json={"outcome": "helped"},
    )
    assert outcome.status_code == 409


@pytest.mark.asyncio
async def test_effectiveness_report_suppresses_small_cohorts_and_versions_results(
    client: AsyncClient,
    test_session_factory,
):
    users = [
        await create_user(client, f"recommendation-effectiveness-{index}") for index in range(5)
    ]

    async def add_outcomes(count: int, *, start: int = 0) -> None:
        async with test_session_factory() as db:
            for index in range(start, start + count):
                user = users[index % len(users)]
                decision = RecommendationState(
                    user_id=user["id"],
                    recommendation_id=f"review-effectiveness-{index}",
                    state="accepted",
                    recommendation_type="review",
                    guidance_ruleset_version="pfis-guidance-3",
                    decided_at=datetime.now(UTC),
                )
                db.add(decision)
                await db.flush()
                outcome_kind = "helped" if index < 6 else "no_change" if index < 8 else "worse"
                impact = Decimal("1") if outcome_kind == "helped" else Decimal("0")
                if outcome_kind == "worse":
                    impact = Decimal("-1")
                db.add(
                    RecommendationOutcome(
                        user_id=user["id"],
                        decision_id=decision.id,
                        outcome=outcome_kind,
                        baseline_metric_value=Decimal("2"),
                        observed_metric_value=Decimal("1"),
                        automatic_impact_value=impact,
                        metric_key="unresolved_review_count",
                        metric_unit="records",
                        outcome_ruleset_version="pfis-recommendation-outcome-1",
                        observed_at=datetime.now(UTC),
                    )
                )
            await db.commit()

    await add_outcomes(9)
    suppressed = await client.get(f"/api/guidance/effectiveness?user_id={users[0]['id']}")
    suppressed.raise_for_status()
    assert suppressed.json()["evidence_status"] == "insufficient_sample"
    assert suppressed.json()["eligible_outcome_count"] == 0
    assert suppressed.json()["suppressed_cohort_count"] == 1
    assert suppressed.json()["cohorts"] == []

    await add_outcomes(1, start=9)
    response = await client.get(f"/api/guidance/effectiveness?user_id={users[0]['id']}")
    response.raise_for_status()
    report = response.json()
    assert report["evidence_status"] == "available"
    assert report["minimum_sample_size"] == 10
    assert report["minimum_unique_users"] == 5
    assert report["eligible_outcome_count"] == 10
    assert report["suppressed_cohort_count"] == 0
    assert report["effectiveness_ruleset_version"] == "pfis-recommendation-effectiveness-1"
    assert report["window_days"] == 180
    assert len(report["cohorts"]) == 1
    cohort = report["cohorts"][0]
    assert cohort == {
        "recommendation_type": "review",
        "guidance_ruleset_version": "pfis-guidance-3",
        "outcome_ruleset_version": "pfis-recommendation-outcome-1",
        "metric_key": "unresolved_review_count",
        "metric_unit": "records",
        "sample_size": 10,
        "unique_users": 5,
        "completed_rate": 1.0,
        "helped_rate": 0.6,
        "measured_evidence_status": "available",
        "measured_sample_size": 10,
        "measured_unique_users": 5,
        "measured_improvement_rate": 0.6,
        "mean_automatic_impact": 0.4,
        "user_measurement_agreement_rate": 1.0,
    }
