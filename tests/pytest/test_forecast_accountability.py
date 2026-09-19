"""Prospective forecast snapshot and observed-outcome lifecycle tests."""

from datetime import date
from decimal import Decimal

import pytest
from app.models.forecast import CashFlowForecastSnapshot
from httpx import AsyncClient

from tests.pytest.helpers import auth_headers, create_user, register_user


def _shift_month(value: date, offset: int) -> tuple[int, int]:
    absolute = value.year * 12 + value.month - 1 + offset
    return absolute % 12 + 1, absolute // 12


async def _seed_spend(
    client: AsyncClient,
    user_id: str,
    category_id: str,
    *,
    amount: float,
    transaction_date: date,
    reference: str,
) -> dict:
    response = await client.post(
        f"/api/transactions/?user_id={user_id}",
        json={
            "amount": amount,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": "FORECAST ACCOUNTABILITY",
            "merchant_normalized": "Forecast Accountability",
            "category_id": category_id,
            "transaction_date": transaction_date.isoformat(),
            "confidence_score": 0.95,
            "reference_id": reference,
        },
    )
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
async def test_forecast_snapshot_is_immutable_idempotent_and_future_bounded(
    client: AsyncClient,
):
    user = await create_user(client, "forecast-snapshot")
    other = await create_user(client, "forecast-snapshot-other")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = date.today()
    await _seed_spend(
        client,
        user["id"],
        category_id,
        amount=250,
        transaction_date=today,
        reference="forecast-snapshot-before",
    )
    endpoint = f"/api/analytics/cash-flow/snapshots?user_id={user['id']}"
    created = await client.post(endpoint, json={"month": today.month, "year": today.year})
    created.raise_for_status()
    first = created.json()
    assert first["cutoff_date"] == today.isoformat()
    assert first["forecast_ruleset_version"] == "pfis-cash-flow-6"
    assert first["temporal_ruleset_version"] == "pfis-temporal-events-1"
    assert first["evidence"]
    assert first["assumptions"]

    await _seed_spend(
        client,
        user["id"],
        category_id,
        amount=5000,
        transaction_date=today,
        reference="forecast-snapshot-after",
    )
    repeated = await client.post(endpoint, json={"month": today.month, "year": today.year})
    repeated.raise_for_status()
    assert repeated.json() == first

    listed = await client.get(endpoint)
    assert listed.status_code == 200
    assert listed.json() == [first]
    other_list = await client.get(f"/api/analytics/cash-flow/snapshots?user_id={other['id']}")
    assert other_list.json() == []

    previous_month, previous_year = _shift_month(today, -1)
    past = await client.post(
        endpoint,
        json={"month": previous_month, "year": previous_year},
    )
    assert past.status_code == 422
    far_month, far_year = _shift_month(today, 13)
    too_far = await client.post(endpoint, json={"month": far_month, "year": far_year})
    assert too_far.status_code == 422

    current_evaluation = await client.post(
        f"/api/analytics/cash-flow/outcomes/evaluate?user_id={user['id']}"
    )
    current_evaluation.raise_for_status()
    assert current_evaluation.json()["evaluated_count"] == 0
    assert current_evaluation.json()["ineligible_count"] == 1


@pytest.mark.asyncio
async def test_completed_forecast_outcome_is_measured_once_and_remains_queryable(
    client: AsyncClient,
    test_session_factory,
):
    user = await create_user(client, "forecast-outcome")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = date.today()
    target_month, target_year = _shift_month(today, -1)
    target_date = date(target_year, target_month, 5)
    await _seed_spend(
        client,
        user["id"],
        category_id,
        amount=1000,
        transaction_date=target_date,
        reference="forecast-outcome-actual",
    )

    async with test_session_factory() as db:
        db.add(
            CashFlowForecastSnapshot(
                user_id=user["id"],
                target_month=target_month,
                target_year=target_year,
                cutoff_date=date(target_year, target_month, 1),
                forecast_ruleset_version="pfis-cash-flow-5",
                temporal_ruleset_version="pfis-temporal-events-1",
                projected_spend=Decimal("800.00"),
                projected_net=Decimal("-800.00"),
                projected_range_low=Decimal("700.00"),
                projected_range_high=Decimal("900.00"),
                expected_income=Decimal("0.00"),
                temporal_expected_income=Decimal("0.00"),
                temporal_expected_outflows=Decimal("0.00"),
                temporal_conflicted_outflows=Decimal("0.00"),
                confidence=Decimal("0.600"),
                data_sufficiency="medium",
                evidence_json="[]",
                assumptions_json="[]",
            )
        )
        await db.commit()

    endpoint = f"/api/analytics/cash-flow/outcomes/evaluate?user_id={user['id']}"
    evaluated = await client.post(endpoint)
    evaluated.raise_for_status()
    body = evaluated.json()
    assert body["evaluation_version"] == "pfis-cash-flow-outcome-1"
    assert body["evaluated_count"] == 1
    assert body["already_evaluated_count"] == 0
    assert body["ineligible_count"] == 0
    outcome = body["outcomes"][0]
    assert outcome["actual_spend"] == 1000.0
    assert outcome["spend_absolute_error"] == 200.0
    assert outcome["spend_absolute_percentage_error"] == 20.0
    assert outcome["spend_range_covered"] is False

    repeated = await client.post(endpoint)
    repeated.raise_for_status()
    assert repeated.json()["evaluated_count"] == 0
    assert repeated.json()["already_evaluated_count"] == 1

    listed = await client.get(f"/api/analytics/cash-flow/outcomes?user_id={user['id']}")
    listed.raise_for_status()
    assert listed.json() == [outcome]


@pytest.mark.asyncio
async def test_forecast_accountability_rejects_cross_user_scope(
    client: AsyncClient,
    auth_required,
):
    owner, token = await register_user(client, "forecast-accountability-owner")
    other, _ = await register_user(client, "forecast-accountability-other")

    response = await client.get(
        f"/api/analytics/cash-flow/snapshots?user_id={other['id']}",
        headers=auth_headers(token),
    )

    assert owner["id"] != other["id"]
    assert response.status_code == 403
