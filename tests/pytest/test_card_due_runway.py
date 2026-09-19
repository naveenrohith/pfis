"""Focused integration coverage for card due-date affordability."""

from datetime import date, timedelta
from decimal import Decimal

from app.services.card_due_runway_service import CardDueRunwayService

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Runway Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_card_due_runway_compares_total_due_with_conservative_bank_path(client):
    user = await create_user(client, "card-due-runway-covered")
    bank = await _account(client, user["id"], "bank", "1001")
    card = await _account(client, user["id"], "credit_card", "1002")
    today = date.today()
    statement_date = today - timedelta(days=5)
    due_date = today + timedelta(days=10)

    anchor = await client.post(
        f"/api/accounts/{bank['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": today.isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    anchor.raise_for_status()

    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "d" * 64,
            "statement_text": f"""
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: {statement_date:%d/%m/%Y}
            STATEMENT PERIOD: {(statement_date - timedelta(days=30)):%d/%m/%Y} TO {statement_date:%d/%m/%Y}
            TOTAL AMOUNT DUE: 6,000.00
            MINIMUM AMOUNT DUE: 600.00
            PAYMENT DUE DATE: {due_date:%d/%m/%Y}
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 94,000.00
            {(statement_date - timedelta(days=4)):%d/%m/%Y} RUNWAY MERCHANT 6,000.00
            """,
        },
    )
    imported.raise_for_status()

    preference = await client.put(
        f"/api/cards/{card['id']}/preferences?user_id={user['id']}",
        json={"preferred_payment_account_id": bank["id"]},
    )
    preference.raise_for_status()

    planned = await client.post(
        f"/api/cards/{card['id']}/payment-intents?user_id={user['id']}",
        json={
            "paying_account_id": bank["id"],
            "amount": 3000,
            "planned_for": (due_date - timedelta(days=2)).isoformat(),
            "note": "Planned partial payment for runway evidence",
        },
    )
    planned.raise_for_status()

    response = await client.get(f"/api/cards/{card['id']}/due-runway?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "covered"
    assert body["total_due"] == 6000
    assert body["minimum_due"] == 600
    assert body["funding_account_id"] == bank["id"]
    assert body["planned_payment_total"] == 3000
    assert body["funding_balance_before_due_low"] == 10000
    assert body["expected_balance_after_total_due"] == 4000
    assert body["expected_total_due_covered"] is True
    assert body["lower_band_total_due_covered"] is True
    assert body["issuer_available_credit_limit"] == 94000
    assert body["ruleset_version"] == "pfis-card-due-runway-2"
    scenarios = {item["scenario"]: item for item in body["payment_scenarios"]}
    assert scenarios["minimum_due"]["payment_amount"] == 600
    assert scenarios["minimum_due"]["planned_payment_applied"] == 600
    assert scenarios["minimum_due"]["additional_payment_amount"] == 0
    assert scenarios["minimum_due"]["effective_payment_amount"] == 3000
    assert scenarios["minimum_due"]["remaining_total_due"] == 3000
    assert scenarios["minimum_due"]["lower_band_covered"] is True
    assert scenarios["total_due"]["payment_amount"] == 6000
    assert scenarios["total_due"]["planned_payment_applied"] == 3000
    assert scenarios["total_due"]["additional_payment_amount"] == 3000
    assert scenarios["total_due"]["effective_payment_amount"] == 6000
    assert scenarios["total_due"]["remaining_total_due"] == 0
    assert scenarios["total_due"]["lower_band_funding_balance_after"] == 4000
    assert scenarios["total_due"]["lower_band_covered"] is True


async def test_card_due_runway_fails_closed_when_funding_account_is_missing(client):
    user = await create_user(client, "card-due-runway-missing-funding")
    card = await _account(client, user["id"], "credit_card", "1003")
    today = date.today()
    statement_date = today - timedelta(days=3)
    due_date = today + timedelta(days=7)

    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "e" * 64,
            "statement_text": f"""
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: {statement_date:%d/%m/%Y}
            STATEMENT PERIOD: {(statement_date - timedelta(days=30)):%d/%m/%Y} TO {statement_date:%d/%m/%Y}
            TOTAL AMOUNT DUE: 2,000.00
            MINIMUM AMOUNT DUE: 200.00
            PAYMENT DUE DATE: {due_date:%d/%m/%Y}
            TOTAL CREDIT LIMIT: 50,000.00
            AVAILABLE CREDIT LIMIT: 48,000.00
            """,
        },
    )
    imported.raise_for_status()

    response = await client.get(f"/api/cards/{card['id']}/due-runway?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "needs_payment_account"
    assert body["total_due"] == 2000
    assert body["funding_account_id"] is None
    assert body["expected_total_due_covered"] is None
    assert body["lower_band_total_due_covered"] is None
    assert {item["scenario"] for item in body["payment_scenarios"]} == {
        "minimum_due",
        "total_due",
    }
    assert all(item["status"] == "unavailable" for item in body["payment_scenarios"])
    assert all(item["expected_funding_balance_after"] is None for item in body["payment_scenarios"])


def test_card_payment_scenarios_keep_expected_and_lower_band_states_separate():
    scenarios = CardDueRunwayService._payment_scenarios(
        total_due=Decimal("6000"),
        minimum_due=Decimal("600"),
        due_date=date(2026, 8, 20),
        planned_payment_total=Decimal("3000"),
        expected=Decimal("7000"),
        low=Decimal("5000"),
        high=Decimal("9000"),
    )
    by_name = {item.scenario: item for item in scenarios}

    assert by_name["minimum_due"].status == "covered"
    assert by_name["minimum_due"].effective_payment_amount == 3000
    assert by_name["minimum_due"].lower_band_cash_gap == 0
    assert by_name["total_due"].status == "at_risk"
    assert by_name["total_due"].expected_covered is True
    assert by_name["total_due"].lower_band_covered is False
    assert by_name["total_due"].lower_band_cash_gap == 1000
