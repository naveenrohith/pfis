"""End-to-end coverage for immutable balance drift intervals."""

from datetime import date, timedelta

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Reconciliation Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_balance_reconciliation_persists_known_movement_and_residual(client):
    user = await create_user(client, "balance-reconciliation-e2e")
    bank = await _account(client, user["id"], "bank", "8111")
    opening = date.today() - timedelta(days=3)
    movement = date.today() - timedelta(days=2)
    closing = date.today() - timedelta(days=1)

    for amount, as_of in ((1000, opening),):
        response = await client.post(
            f"/api/accounts/{bank['id']}/balances?user_id={user['id']}",
            json={"amount": amount, "as_of": as_of.isoformat(), "verified": True},
        )
        response.raise_for_status()

    transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 100,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": movement.isoformat(),
            "merchant_raw": "Reconciled debit",
            "financial_account_id": bank["id"],
            "reference_id": "reconciliation-bank-debit",
        },
    )
    transaction.raise_for_status()

    response = await client.post(
        f"/api/accounts/{bank['id']}/balances?user_id={user['id']}",
        json={"amount": 900, "as_of": closing.isoformat(), "verified": True},
    )
    response.raise_for_status()

    response = await client.get(
        f"/api/accounts/{bank['id']}/balance-reconciliations?user_id={user['id']}"
    )
    response.raise_for_status()
    reconciled = response.json()
    assert len(reconciled) == 1
    assert reconciled[0]["reconciliation_status"] == "reconciled"
    assert reconciled[0]["known_movement"] == -100
    assert reconciled[0]["residual"] == 0
    assert reconciled[0]["eligible_transaction_ids"] == [transaction.json()["id"]]

    response = await client.post(
        f"/api/accounts/{bank['id']}/balances?user_id={user['id']}",
        json={"amount": 850, "as_of": date.today().isoformat(), "verified": True},
    )
    response.raise_for_status()
    response = await client.get(
        f"/api/accounts/{bank['id']}/balance-reconciliations?user_id={user['id']}"
    )
    response.raise_for_status()
    drift = response.json()[0]
    assert drift["reconciliation_status"] == "needs_review"
    assert drift["residual"] == -50
    assert "unexplained_balance_movement" in drift["reason_codes"]


async def test_balance_reconciliation_applies_liability_signs(client):
    user = await create_user(client, "balance-reconciliation-card")
    card = await _account(client, user["id"], "credit_card", "8222")
    opening = date.today() - timedelta(days=2)
    closing = date.today() - timedelta(days=1)

    response = await client.post(
        f"/api/accounts/{card['id']}/balances?user_id={user['id']}",
        json={"amount": 1000, "as_of": opening.isoformat(), "verified": True},
    )
    response.raise_for_status()
    transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 200,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": closing.isoformat(),
            "merchant_raw": "Card purchase",
            "card_event": "purchase",
            "payment_method": "credit_card",
            "financial_account_id": card["id"],
            "reference_id": "reconciliation-card-purchase",
        },
    )
    transaction.raise_for_status()
    response = await client.post(
        f"/api/accounts/{card['id']}/balances?user_id={user['id']}",
        json={"amount": 1200, "as_of": closing.isoformat(), "verified": True},
    )
    response.raise_for_status()

    response = await client.get(
        f"/api/accounts/{card['id']}/balance-reconciliations?user_id={user['id']}"
    )
    response.raise_for_status()
    body = response.json()[0]
    assert body["reconciliation_status"] == "reconciled"
    assert body["known_movement"] == 200
    assert body["expected_closing_balance"] == 1200
    assert body["eligible_transaction_ids"] == [transaction.json()["id"]]


async def test_balance_reconciliation_never_attributes_another_account_transaction(client):
    user = await create_user(client, "balance-reconciliation-account-isolation")
    first = await _account(client, user["id"], "bank", "8333")
    second = await _account(client, user["id"], "bank", "8444")
    opening = date.today() - timedelta(days=3)
    movement = date.today() - timedelta(days=2)
    closing = date.today() - timedelta(days=1)

    for account in (first, second):
        response = await client.post(
            f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
            json={"amount": 1000, "as_of": opening.isoformat(), "verified": True},
        )
        response.raise_for_status()

    other_account_transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 100,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": movement.isoformat(),
            "merchant_raw": "Other account debit",
            "financial_account_id": second["id"],
            "reference_id": "reconciliation-other-account",
        },
    )
    other_account_transaction.raise_for_status()

    response = await client.post(
        f"/api/accounts/{first['id']}/balances?user_id={user['id']}",
        json={"amount": 1000, "as_of": closing.isoformat(), "verified": True},
    )
    response.raise_for_status()
    response = await client.get(
        f"/api/accounts/{first['id']}/balance-reconciliations?user_id={user['id']}"
    )
    response.raise_for_status()
    body = response.json()[0]
    assert body["known_movement"] == 0
    assert body["residual"] == 0
    assert other_account_transaction.json()["id"] not in body["eligible_transaction_ids"]
