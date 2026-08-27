"""Focused coverage for the composed card upcoming-state timeline."""

from datetime import date, timedelta

from tests.pytest.helpers import create_user


async def _card(client, user_id: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Upcoming Bank",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****9090",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_card_upcoming_state_composes_due_and_planned_payment_without_projection(
    client,
):
    user = await create_user(client, "card-upcoming-state")
    card = await _card(client, user["id"])
    today = date.today()
    statement_date = today - timedelta(days=5)
    due_date = today + timedelta(days=10)

    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "u" * 64,
            "statement_text": f"""
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: {statement_date:%d/%m/%Y}
            STATEMENT PERIOD: {(statement_date - timedelta(days=30)):%d/%m/%Y} TO {statement_date:%d/%m/%Y}
            TOTAL AMOUNT DUE: 6,000.00
            MINIMUM AMOUNT DUE: 600.00
            PAYMENT DUE DATE: {due_date:%d/%m/%Y}
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 94,000.00
            """,
        },
    )
    imported.raise_for_status()

    planned = await client.post(
        f"/api/cards/{card['id']}/payment-intents?user_id={user['id']}",
        json={
            "amount": 1000,
            "planned_for": (due_date - timedelta(days=2)).isoformat(),
            "note": "Upcoming partial card payment",
        },
    )
    planned.raise_for_status()

    response = await client.get(f"/api/cards/{card['id']}/upcoming-state?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["state"] == "payment_due"
    assert body["ruleset_version"] == "pfis-card-upcoming-state-1"
    assert body["next_event"]["event_type"] == "planned_payment"
    assert body["next_event"]["date"] == (due_date - timedelta(days=2)).isoformat()
    assert body["next_event"]["source_kind"] == "user"
    assert body["next_event"]["status"] == "planned"
    assert any(item["event_type"] == "payment_due" for item in body["events"])
    assert "statement_projection_unavailable" in body["reason_codes"]
    assert all("source text" not in item["label"].lower() for item in body["events"])
