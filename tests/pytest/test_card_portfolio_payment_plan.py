"""Coverage for the conservative multi-card payment-plan comparison."""

from datetime import date, timedelta

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str, label: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": label,
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def _statement(
    client,
    user_id: str,
    card_id: str,
    fingerprint: str,
    due_date: date,
    total: str,
    minimum: str,
) -> None:
    statement_date = date.today() - timedelta(days=5)
    response = await client.post(
        f"/api/statements/hdfc/text?user_id={user_id}",
        json={
            "financial_account_id": card_id,
            "document_fingerprint": fingerprint,
            "statement_text": f"""
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: {statement_date:%d/%m/%Y}
            STATEMENT PERIOD: {(statement_date - timedelta(days=30)):%d/%m/%Y} TO {statement_date:%d/%m/%Y}
            TOTAL AMOUNT DUE: {total}
            MINIMUM AMOUNT DUE: {minimum}
            PAYMENT DUE DATE: {due_date:%d/%m/%Y}
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 99,000.00
            """,
        },
    )
    response.raise_for_status()


async def test_card_portfolio_payment_plan_replays_shared_funding_path(client):
    user = await create_user(client, "card-portfolio-payment-plan")
    bank = await _account(client, user["id"], "bank", "9001", "Plan Bank")
    first = await _account(client, user["id"], "credit_card", "9002", "Plan Card One")
    second = await _account(client, user["id"], "credit_card", "9003", "Plan Card Two")
    today = date.today()

    anchor = await client.post(
        f"/api/accounts/{bank['id']}/balances?user_id={user['id']}",
        json={
            "amount": 15000,
            "as_of": today.isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    anchor.raise_for_status()
    await _statement(
        client,
        user["id"],
        first["id"],
        "p" * 64,
        today + timedelta(days=5),
        "6,000.00",
        "600.00",
    )
    await _statement(
        client,
        user["id"],
        second["id"],
        "q" * 64,
        today + timedelta(days=12),
        "4,000.00",
        "400.00",
    )
    for card in (first, second):
        preference = await client.put(
            f"/api/cards/{card['id']}/preferences?user_id={user['id']}",
            json={"preferred_payment_account_id": bank["id"]},
        )
        preference.raise_for_status()
    planned = await client.post(
        f"/api/cards/{first['id']}/payment-intents?user_id={user['id']}",
        json={
            "paying_account_id": bank["id"],
            "amount": 2000,
            "planned_for": (today + timedelta(days=3)).isoformat(),
            "note": "Existing plan used by portfolio comparison",
        },
    )
    planned.raise_for_status()

    response = await client.get(f"/api/cards/portfolio/payment-plan?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["ruleset_version"] == "pfis-card-portfolio-payment-plan-1"
    assert body["state"] == "ready"
    assert body["card_count"] == 2
    assert body["cards_with_statement"] == 2
    assert body["minimum_due_plan"]["issuer_payment_target_total"] == 1000
    assert body["minimum_due_plan"]["planned_payment_total"] == 600
    assert body["minimum_due_plan"]["additional_payment_total"] == 400
    assert body["minimum_due_plan"]["status"] == "covered"
    assert body["total_due_plan"]["issuer_payment_target_total"] == 10000
    assert body["total_due_plan"]["planned_payment_total"] == 2000
    assert body["total_due_plan"]["additional_payment_total"] == 8000
    assert body["total_due_plan"]["effective_payment_total"] == 10000
    assert body["total_due_plan"]["status"] == "covered"
    assert body["total_due_plan"]["cards_with_funding_path"] == 2
    assert body["total_due_plan"]["funding_paths"][0]["status"] == "covered"
    assert body["total_due_plan"]["funding_paths"][0]["card_ids"] == [
        first["id"],
        second["id"],
    ]
    assert body["total_due_plan"]["funding_paths"][0]["lowest_lower_band_balance_after"] == 5000
    assert "shared_funding_path_replayed" in body["total_due_plan"]["reason_codes"]

    guidance = await client.post(
        f"/api/guidance/query?user_id={user['id']}",
        json={
            "query": "Compare minimum and total card payment plans",
            "month": today.month,
            "year": today.year,
        },
    )
    guidance.raise_for_status()
    guidance_body = guidance.json()
    assert guidance_body["intent"] == "card_portfolio_payment_plan"
    assert guidance_body["temporal_scope"] == "current_card_cycle"
    assert "10,000" in guidance_body["answer"]
    assert "not payment instructions" in guidance_body["answer"]


async def test_card_portfolio_payment_plan_fails_closed_without_funding_mapping(client):
    user = await create_user(client, "card-portfolio-payment-plan-review")
    card = await _account(client, user["id"], "credit_card", "9010", "Unmapped Card")
    today = date.today()
    await _statement(
        client,
        user["id"],
        card["id"],
        "r" * 64,
        today + timedelta(days=7),
        "2,000.00",
        "200.00",
    )

    response = await client.get(f"/api/cards/portfolio/payment-plan?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["state"] == "needs_review"
    assert body["total_due_plan"]["status"] == "needs_payment_account"
    assert body["total_due_plan"]["issuer_payment_target_total"] == 2000
    assert body["total_due_plan"]["cards_with_funding_path"] == 0
    assert body["total_due_plan"]["cards_unavailable"] == 1
    assert body["cards"][0]["runway_status"] == "needs_payment_account"
    assert "funding_account_missing" in body["cards"][0]["reason_codes"]
