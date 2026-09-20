"""Focused coverage for conservative imported transfer matching."""

from datetime import date

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Matching Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def _transaction(
    client,
    user_id: str,
    account_id: str,
    *,
    transaction_type: str,
    payment_method: str,
    payment_rail: str,
    card_event: str,
    merchant: str,
):
    response = await client.post(
        f"/api/transactions/?user_id={user_id}",
        json={
            "amount": 1500,
            "currency": "INR",
            "transaction_type": transaction_type,
            "payment_method": payment_method,
            "payment_rail": payment_rail,
            "card_event": card_event,
            "transaction_status": "completed",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": merchant,
            "merchant_normalized": merchant,
            "financial_account_id": account_id,
        },
    )
    response.raise_for_status()
    return response.json()


async def test_imported_card_payment_can_be_reviewed_and_linked(client):
    user = await create_user(client, "transfer-matching")
    bank = await _account(client, user["id"], "bank", "1122")
    card = await _account(client, user["id"], "credit_card", "3344")
    debit = await _transaction(
        client,
        user["id"],
        bank["id"],
        transaction_type="debit",
        payment_method="other",
        payment_rail="other",
        card_event="none",
        merchant="Card payment to Matching Bank card",
    )
    credit = await _transaction(
        client,
        user["id"],
        card["id"],
        transaction_type="credit",
        payment_method="credit_card",
        payment_rail="other",
        card_event="payment",
        merchant="Payment received",
    )

    candidates = await client.get(
        f"/api/transactions/transfer-match-candidates?user_id={user['id']}"
    )
    candidates.raise_for_status()
    candidate = next(
        item
        for item in candidates.json()
        if item["debit_transaction_id"] == debit["id"]
        and item["credit_transaction_id"] == credit["id"]
    )
    assert candidate["kind"] == "card_payment"
    assert candidate["ambiguous"] is False
    assert "bank_to_card_counterparty" in candidate["reason_codes"]

    bank_candidates = await client.get(
        f"/api/transactions/transfer-match-candidates?user_id={user['id']}&account_id={bank['id']}"
    )
    bank_candidates.raise_for_status()
    assert any(
        item["debit_transaction_id"] == debit["id"]
        and item["credit_transaction_id"] == credit["id"]
        for item in bank_candidates.json()
    )

    linked = await client.post(
        f"/api/transactions/{debit['id']}/transfer-link?user_id={user['id']}",
        json={
            "counterparty_transaction_id": credit["id"],
            "kind": "card_payment",
        },
    )
    linked.raise_for_status()
    assert linked.json()["debit_transaction_id"] == debit["id"]
    assert linked.json()["credit_transaction_id"] == credit["id"]

    repeated = await client.post(
        f"/api/transactions/{debit['id']}/transfer-link?user_id={user['id']}",
        json={
            "counterparty_transaction_id": credit["id"],
            "kind": "card_payment",
        },
    )
    repeated.raise_for_status()
    assert repeated.json()["transfer_group_id"] == linked.json()["transfer_group_id"]

    refreshed = await client.get(f"/api/transactions/{credit['id']}?user_id={user['id']}")
    refreshed.raise_for_status()
    assert refreshed.json()["is_transfer"] is True
    assert refreshed.json()["card_event"] == "payment"


async def test_imported_asset_transfer_uses_transfer_evidence_and_links_both_legs(client):
    user = await create_user(client, "asset-transfer-matching")
    bank = await _account(client, user["id"], "bank", "4455")
    cash = await _account(client, user["id"], "cash", "6677")
    debit = await _transaction(
        client,
        user["id"],
        bank["id"],
        transaction_type="debit",
        payment_method="bank_transfer",
        payment_rail="transfer",
        card_event="none",
        merchant="Self transfer to cash",
    )
    credit = await _transaction(
        client,
        user["id"],
        cash["id"],
        transaction_type="credit",
        payment_method="bank_transfer",
        payment_rail="transfer",
        card_event="none",
        merchant="Self transfer from bank",
    )

    candidates = await client.get(
        f"/api/transactions/transfer-match-candidates?user_id={user['id']}"
    )
    candidates.raise_for_status()
    candidate = next(
        item
        for item in candidates.json()
        if item["debit_transaction_id"] == debit["id"]
        and item["credit_transaction_id"] == credit["id"]
    )
    assert candidate["kind"] == "account_transfer"
    assert "asset_counterparty" in candidate["reason_codes"]
    assert "transfer_evidence" in candidate["reason_codes"]

    linked = await client.post(
        f"/api/transactions/{debit['id']}/transfer-link?user_id={user['id']}",
        json={
            "counterparty_transaction_id": credit["id"],
            "kind": "account_transfer",
        },
    )
    linked.raise_for_status()
    assert linked.json()["payment_rail"] == "transfer"

    refreshed = await client.get(f"/api/transactions/{credit['id']}?user_id={user['id']}")
    refreshed.raise_for_status()
    assert refreshed.json()["is_transfer"] is True
    assert refreshed.json()["card_event"] == "none"
