"""Regression coverage for premium workspace APIs."""

from datetime import date, timedelta

import pytest
from app.models.workspace import DashboardPreference
from app.security import create_access_token

from tests.pytest.helpers import auth_headers, create_user, user_today


async def _transaction(client, user_id: str, **overrides):
    payload = {
        "amount": 250.0,
        "currency": "INR",
        "transaction_type": "debit",
        "payment_method": "upi",
        "merchant_raw": "Coffee Bar",
        "merchant_normalized": "Coffee Bar",
        "transaction_date": date.today().isoformat(),
        "confidence_score": 1.0,
        "reference_id": f"premium-{overrides.get('reference_id', 'default')}",
    }
    payload.update({key: value for key, value in overrides.items() if key != "reference_id"})
    response = await client.post(f"/api/transactions/?user_id={user_id}", json=payload)
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
async def test_transaction_filters_and_deterministic_guidance(client):
    user = await create_user(client, "guidance")
    today = user_today(user)
    await _transaction(client, user["id"], amount=250, reference_id="coffee")
    await _transaction(
        client,
        user["id"],
        amount=1000,
        merchant_raw="Grocery Store",
        merchant_normalized="Grocery Store",
        payment_method="credit_card",
        reference_id="grocery",
    )

    response = await client.get(
        f"/api/transactions/?user_id={user['id']}&month={today.month}&year={today.year}"
        "&q=coffee&payment_method=upi&amount_min=200&amount_max=300&sort=amount&direction=asc"
    )
    assert response.status_code == 200
    assert response.headers["X-Total-Count"] == "1"
    assert response.json()[0]["merchant_normalized"] == "Coffee Bar"

    additive_aliases = await client.get(
        f"/api/transactions/?user_id={user['id']}&text=coffee&type=debit"
        "&review_state=reviewed&sort_field=amount&sort_direction=asc"
    )
    assert additive_aliases.status_code == 200
    assert additive_aliases.headers["X-Total-Count"] == "1"

    brief = await client.get(
        f"/api/guidance/brief?user_id={user['id']}&period=daily&as_of={today.isoformat()}"
    )
    assert brief.status_code == 200
    assert brief.json()["ruleset_version"] == "pfis-guidance-3"

    supported = await client.post(
        f"/api/guidance/query?user_id={user['id']}",
        json={
            "query": "How much did I spend this month?",
            "month": today.month,
            "year": today.year,
        },
    )
    assert supported.status_code == 200
    assert supported.json()["supported"] is True
    assert supported.json()["intent"] == "monthly_spend"
    assert supported.json()["plan"]
    assert supported.json()["evidence"][0]["source_type"] == "transactions"
    assert supported.json()["temporal_scope"] == "selected_calendar_month"
    assert supported.json()["uncertainty"]

    unsupported = await client.post(
        f"/api/guidance/query?user_id={user['id']}",
        json={"query": "Predict the stock market", "month": today.month, "year": today.year},
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["supported"] is False
    assert unsupported.json()["supported_examples"]
    assert "No financial read model was queried" in unsupported.json()["uncertainty"][0]


@pytest.mark.asyncio
async def test_guidance_current_position_uses_balance_read_model(client):
    user = await create_user(client, "guidance-position")
    today = user_today(user)
    account = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Guidance Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "****7711",
            "currency": "INR",
        },
    )
    account.raise_for_status()
    balance = await client.post(
        f"/api/accounts/{account.json()['id']}/balances?user_id={user['id']}",
        json={"amount": 10000, "as_of": today.isoformat(), "source": "manual"},
    )
    balance.raise_for_status()

    current = await client.post(
        f"/api/guidance/query?user_id={user['id']}",
        json={
            "query": "What is my current bank balance?",
            "month": today.month,
            "year": today.year,
        },
    )
    current.raise_for_status()
    assert current.json()["intent"] == "bank_position"
    assert "10,000" in current.json()["answer"]
    assert "not provider-live" in current.json()["answer"]

    plan = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account.json()["id"],
            "next_income_date": (today + timedelta(days=5)).isoformat(),
        },
    )
    plan.raise_for_status()
    safe = await client.post(
        f"/api/guidance/query?user_id={user['id']}",
        json={
            "query": "Is it safe to spend before my next income?",
            "month": today.month,
            "year": today.year,
        },
    )
    safe.raise_for_status()
    assert safe.json()["intent"] == "safe_to_spend"
    assert safe.json()["metrics"][1]["value"] == "₹10,000"


@pytest.mark.asyncio
async def test_guidance_card_upcoming_state_uses_timeline_read_model(client):
    user = await create_user(client, "guidance-card-upcoming")
    today = user_today(user)
    card = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Guidance Card Bank",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****8181",
            "currency": "INR",
        },
    )
    card.raise_for_status()
    due_date = today + timedelta(days=5)
    statement_date = today - timedelta(days=5)
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card.json()["id"],
            "document_fingerprint": "g" * 64,
            "statement_text": f"""
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: {statement_date:%d/%m/%Y}
            STATEMENT PERIOD: {(statement_date - timedelta(days=30)):%d/%m/%Y} TO {statement_date:%d/%m/%Y}
            TOTAL AMOUNT DUE: 4,000.00
            MINIMUM AMOUNT DUE: 400.00
            PAYMENT DUE DATE: {due_date:%d/%m/%Y}
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 96,000.00
            """,
        },
    )
    imported.raise_for_status()

    response = await client.post(
        f"/api/guidance/query?user_id={user['id']}",
        json={
            "query": "What happens next with my card?",
            "month": today.month,
            "year": today.year,
        },
    )
    response.raise_for_status()
    body = response.json()

    assert body["supported"] is True
    assert body["intent"] == "card_upcoming_state"
    assert body["temporal_scope"] == "current_card_cycle"
    assert body["metrics"][0]["label"] == "Upcoming card state"
    assert body["metrics"][1]["label"] == "Next dated signal"
    assert body["metrics"][2]["value"] == due_date.isoformat()
    assert body["evidence"][0]["source_type"] == "credit_card_statements"
    assert body["evidence"][0]["cutoff"] == today.isoformat()
    assert "not submitting a payment" in body["answer"]


@pytest.mark.asyncio
async def test_preferences_are_user_owned(client, auth_required):
    first = await create_user(client, "prefs-first")
    second = await create_user(client, "prefs-second")
    first_token = create_access_token(first["id"])
    second_token = create_access_token(second["id"])

    update = await client.patch(
        f"/api/preferences/dashboard?user_id={first['id']}",
        headers=auth_headers(first_token),
        json={
            "density": "compact",
            "briefing_cadence": "weekly",
            "onboarding_goal": "saving",
        },
    )
    assert update.status_code == 200
    assert update.json()["density"] == "compact"
    assert update.json()["briefing_cadence"] == "weekly"

    forbidden = await client.get(
        f"/api/preferences/dashboard?user_id={first['id']}",
        headers=auth_headers(second_token),
    )
    assert forbidden.status_code == 403

    scenario_forbidden = await client.post(
        f"/api/analytics/scenario?user_id={first['id']}",
        headers=auth_headers(second_token),
        json={"month": date.today().month, "year": date.today().year},
    )
    assert scenario_forbidden.status_code == 403

    own = await client.get(
        f"/api/preferences/dashboard?user_id={second['id']}",
        headers=auth_headers(second_token),
    )
    assert own.status_code == 200
    assert own.json()["density"] == "comfortable"
    assert own.json()["briefing_cadence"] == "daily"


@pytest.mark.asyncio
async def test_old_dashboard_layout_uses_current_defaults(client, test_session_factory):
    user = await create_user(client, "prefs-migration")
    async with test_session_factory() as session:
        session.add(
            DashboardPreference(
                user_id=user["id"],
                layout_version=0,
                widgets_json='[{"id":"obsolete","visible":true,"size":"large"}]',
                onboarding_goal="saving",
            )
        )
        await session.commit()

    response = await client.get(f"/api/preferences/dashboard?user_id={user['id']}")
    assert response.status_code == 200
    assert response.json()["layout_version"] == 1
    assert response.json()["widgets"][0]["id"] == "savings"
    assert all(widget["id"] != "obsolete" for widget in response.json()["widgets"])


@pytest.mark.asyncio
async def test_net_worth_and_transfer_exclusion(client):
    user = await create_user(client, "networth")
    today = user_today(user)

    asset = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Primary Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "****1111",
            "currency": "INR",
        },
    )
    liability = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Credit Card",
            "account_type": "credit",
            "balance_kind": "liability",
            "masked_number": "****2222",
            "currency": "INR",
        },
    )
    assert asset.status_code == liability.status_code == 201
    asset_id = asset.json()["id"]
    liability_id = liability.json()["id"]

    for account_id, amount in ((asset_id, 100000), (liability_id, 25000)):
        balance = await client.post(
            f"/api/accounts/{account_id}/balances?user_id={user['id']}",
            json={"amount": amount, "as_of": today.isoformat()},
        )
        assert balance.status_code == 201

    net_worth = await client.get(f"/api/net-worth?user_id={user['id']}")
    assert net_worth.status_code == 200
    assert net_worth.json()["assets"] == 100000
    assert net_worth.json()["liabilities"] == 25000
    assert net_worth.json()["net_worth"] == 75000

    transfer = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": asset_id,
            "to_account_id": liability_id,
            "amount": 5000,
            "currency": "INR",
            "transaction_date": today.isoformat(),
            "description": "Card payment",
        },
    )
    assert transfer.status_code == 201

    summary = await client.get(
        f"/api/transactions/summary?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert summary.status_code == 200
    assert summary.json()["total_income"] == 0
    assert summary.json()["total_spend"] == 0
    listed = await client.get(f"/api/transactions/?user_id={user['id']}")
    assert len(listed.json()) == 2
    assert all(item["is_transfer"] for item in listed.json())
