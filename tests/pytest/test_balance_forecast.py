"""Focused coverage for evidence-labelled account balance paths."""

from datetime import date, timedelta

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Forecast Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_account_balance_forecast_combines_anchor_history_and_dated_evidence(client):
    user = await create_user(client, "balance-forecast")
    account = await _account(client, user["id"], "bank", "9134")
    today = date.today()

    anchor = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={"amount": 10000, "as_of": today.isoformat(), "verified": True},
    )
    anchor.raise_for_status()
    cash_plan = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (today + timedelta(days=4)).isoformat(),
            "next_income_amount": 5000,
        },
    )
    cash_plan.raise_for_status()
    commitment = await client.post(
        f"/api/commitments?user_id={user['id']}",
        json={
            "label": "Rent",
            "commitment_type": "rent",
            "amount": 2000,
            "due_date": (today + timedelta(days=2)).isoformat(),
            "financial_account_id": account["id"],
            "confirmed": True,
        },
    )
    commitment.raise_for_status()
    for offset in (3, 2, 1):
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 100,
                "currency": "INR",
                "transaction_type": "debit",
                "transaction_status": "settled",
                "transaction_date": (today - timedelta(days=offset)).isoformat(),
                "merchant_raw": "Grocer",
                "confidence_score": 1.0,
                "financial_account_id": account["id"],
            },
        )
        transaction.raise_for_status()

    response = await client.get(
        f"/api/accounts/{account['id']}/balance-forecast?user_id={user['id']}&horizon_days=7"
    )
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "ready"
    assert body["starting_balance"] == 10000
    assert body["starting_balance_basis"] == "estimated"
    assert body["historical_activity_count"] == 3
    assert body["scheduled_decrease_total"] == 2000
    assert body["scheduled_increase_total"] == 5000
    assert len(body["points"]) == 8
    rent_day = next(
        point
        for point in body["points"]
        if point["date"] == (today + timedelta(days=2)).isoformat()
    )
    income_day = next(
        point
        for point in body["points"]
        if point["date"] == (today + timedelta(days=4)).isoformat()
    )
    assert rent_day["scheduled_decrease"] == 2000
    assert income_day["scheduled_increase"] == 5000
    assert body["first_shortfall_date"] is None


async def test_card_balance_forecast_keeps_payment_intention_as_liability_decrease(client):
    user = await create_user(client, "card-balance-forecast")
    card = await _account(client, user["id"], "credit_card", "9135")
    today = date.today()

    anchor = await client.post(
        f"/api/accounts/{card['id']}/balances?user_id={user['id']}",
        json={"amount": 5000, "as_of": today.isoformat(), "source": "statement"},
    )
    anchor.raise_for_status()
    intent = await client.post(
        f"/api/cards/{card['id']}/payment-intents?user_id={user['id']}",
        json={
            "amount": 1500,
            "planned_for": (today + timedelta(days=3)).isoformat(),
        },
    )
    intent.raise_for_status()

    response = await client.get(
        f"/api/accounts/{card['id']}/balance-forecast?user_id={user['id']}&horizon_days=5"
    )
    response.raise_for_status()
    body = response.json()

    assert body["balance_kind"] == "liability"
    assert body["starting_balance"] == 5000
    assert body["scheduled_decrease_total"] == 1500
    payment_day = next(
        point
        for point in body["points"]
        if point["date"] == (today + timedelta(days=3)).isoformat()
    )
    assert payment_day["scheduled_decrease"] == 1500


async def test_balance_forecast_fails_closed_without_verified_anchor(client):
    user = await create_user(client, "balance-forecast-no-anchor")
    account = await _account(client, user["id"], "bank", "9136")

    response = await client.get(
        f"/api/accounts/{account['id']}/balance-forecast?user_id={user['id']}&horizon_days=14"
    )
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "needs_anchor"
    assert body["starting_balance"] is None
    assert body["points"] == []


async def test_balance_forecast_marks_old_manual_anchor_for_review(client):
    user = await create_user(client, "balance-forecast-stale")
    account = await _account(client, user["id"], "bank", "9137")

    anchor = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 12000,
            "as_of": (date.today() - timedelta(days=14)).isoformat(),
            "verified": True,
        },
    )
    anchor.raise_for_status()

    response = await client.get(
        f"/api/accounts/{account['id']}/balance-forecast?user_id={user['id']}&horizon_days=7"
    )
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "needs_review"
    assert body["position_status"] == "stale"
    assert "balance_observation_stale" in body["position_reason_codes"]
