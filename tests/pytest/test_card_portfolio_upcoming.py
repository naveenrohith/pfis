"""Coverage for the conservative multi-card upcoming-state portfolio."""

from datetime import date, timedelta

from tests.pytest.helpers import create_user


async def _card(client, user_id: str, suffix: str, label: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": label,
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def _statement(client, user_id: str, card_id: str, fingerprint: str, due_date: date, total: str):
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
            MINIMUM AMOUNT DUE: 100.00
            PAYMENT DUE DATE: {due_date:%d/%m/%Y}
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 99,000.00
            """,
        },
    )
    response.raise_for_status()


async def test_card_portfolio_upcoming_state_keeps_per_card_evidence_and_known_due_totals(
    client,
):
    user = await create_user(client, "card-portfolio-upcoming")
    today = date.today()
    first = await _card(client, user["id"], "1111", "Portfolio Card One")
    second = await _card(client, user["id"], "2222", "Portfolio Card Two")
    first_due = today + timedelta(days=5)
    second_due = today + timedelta(days=12)
    await _statement(client, user["id"], first["id"], "p" * 64, first_due, "6,000.00")
    await _statement(client, user["id"], second["id"], "q" * 64, second_due, "4,000.00")

    response = await client.get(
        f"/api/cards/portfolio/upcoming-state?user_id={user['id']}"
    )
    response.raise_for_status()
    body = response.json()

    assert body["state"] == "payment_due"
    assert body["ruleset_version"] == "pfis-card-portfolio-upcoming-1"
    assert body["card_count"] == 2
    assert body["cards_with_due"] == 2
    assert body["issuer_total_due"] == 10_000
    assert body["issuer_total_due_cards"] == 2
    assert body["issuer_total_due_complete"] is True
    assert body["earliest_due_date"] == first_due.isoformat()
    assert body["next_event"]["date"] == first_due.isoformat()
    assert "Portfolio Card One" in body["next_event"]["label"]
    assert {item["label"] for item in body["cards"]} == {
        "Portfolio Card One",
        "Portfolio Card Two",
    }
    assert all(item["financial_account_id"] for item in body["cards"])
    assert all("statement text" not in item["label"].lower() for item in body["cards"])

    guidance = await client.post(
        f"/api/guidance/query?user_id={user['id']}",
        json={
            "query": "What is coming up across my cards?",
            "month": today.month,
            "year": today.year,
        },
    )
    guidance.raise_for_status()
    guidance_body = guidance.json()
    assert guidance_body["intent"] == "card_portfolio_upcoming"
    assert guidance_body["temporal_scope"] == "current_card_cycle"
    assert "10,000" in guidance_body["answer"]
    assert "not claim live total available credit" in guidance_body["answer"]
