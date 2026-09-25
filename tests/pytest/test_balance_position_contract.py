"""Focused invariants for the canonical BalancePosition read model."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Truth Contract Bank",
            "account_type": account_type,
            "balance_kind": (
                "liability" if account_type in {"credit_card", "loan", "pay_later"} else "asset"
            ),
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    assert response.is_success, response.text
    return response.json()


async def _balance(
    client,
    user_id: str,
    account_id: str,
    amount: int,
    as_of: date,
    *,
    source: str = "manual",
    verified: bool = True,
    source_record_id: str | None = None,
    observed_at: datetime | None = None,
    effective_at: datetime | None = None,
    expected_cadence_minutes: int | None = None,
    coverage_start: datetime | None = None,
    coverage_end: datetime | None = None,
    coverage_complete: bool | None = None,
) -> dict:
    payload = {
        "amount": amount,
        "currency": "INR",
        "as_of": as_of.isoformat(),
        "source": source,
        "verified": verified,
    }
    if source_record_id is not None:
        payload["source_record_id"] = source_record_id
    if observed_at is not None:
        payload["observed_at"] = observed_at.isoformat()
    if effective_at is not None:
        payload["effective_at"] = effective_at.isoformat()
    if expected_cadence_minutes is not None:
        payload["expected_cadence_minutes"] = expected_cadence_minutes
    if coverage_complete is not None:
        payload["coverage_complete"] = coverage_complete
    if coverage_start is not None:
        payload["coverage_start"] = coverage_start.isoformat()
    if coverage_end is not None:
        payload["coverage_end"] = coverage_end.isoformat()
    if expected_cadence_minutes is None and coverage_complete is None:
        response = await client.post(
            f"/api/accounts/{account_id}/balances?user_id={user_id}",
            json=payload,
        )
    else:
        payload.pop("source", None)
        payload.pop("verified", None)
        response = await client.post(
            f"/api/accounts/{account_id}/balance-observations?user_id={user_id}",
            json=payload,
        )
    assert response.is_success, response.text
    return response.json()


async def _transaction(
    client,
    user_id: str,
    account_id: str,
    *,
    amount: int,
    transaction_type: str,
    transaction_status: str = "settled",
    transaction_date: date | None = None,
    merchant: str = "Contract merchant",
    reviewed: bool = True,
    card_event: str | None = None,
    payment_rail: str | None = None,
    reference_id: str | None = None,
) -> dict:
    payload = {
        "amount": amount,
        "transaction_type": transaction_type,
        "transaction_status": transaction_status,
        "transaction_date": (transaction_date or date.today()).isoformat(),
        "merchant_raw": merchant,
        "merchant_normalized": merchant,
        "reviewed_flag": reviewed,
        "financial_account_id": account_id,
    }
    if card_event is not None:
        payload["card_event"] = card_event
    if payment_rail is not None:
        payload["payment_rail"] = payment_rail
    if reference_id is not None:
        payload["reference_id"] = reference_id
    response = await client.post(f"/api/transactions/?user_id={user_id}", json=payload)
    response.raise_for_status()
    return response.json()


async def _position(client, user_id: str, account_id: str) -> dict:
    response = await client.get(f"/api/accounts/{account_id}/position?user_id={user_id}")
    response.raise_for_status()
    return response.json()


@pytest.mark.parametrize(
    ("account_type", "expected_kind"),
    [("bank", "asset"), ("cash", "asset"), ("credit_card", "liability")],
)
async def test_balance_position_contract_fields_for_bank_cash_and_card(
    client,
    account_type: str,
    expected_kind: str,
):
    user = await create_user(client, f"position-contract-{account_type}")
    account = await _account(client, user["id"], account_type, account_type[-4:])
    await _balance(client, user["id"], account["id"], 1000, date.today())

    body = await _position(client, user["id"], account["id"])

    assert body["account_id"] == account["id"]
    assert body["financial_account_id"] == account["id"]
    assert body["product_type"] == account_type
    assert body["balance_kind"] == expected_kind
    assert body["currency"] == "INR"
    assert body["observed_balance"] == 1000
    assert body["observed_effective_at"] is None
    assert body["observed_source"] == "manual"
    assert body["settled_movement_since_observation"] == 0
    assert body["estimated_balance"] == 1000
    assert body["estimated_as_of"] == date.today().isoformat()
    assert body["pending_increase"] == 0
    assert body["pending_decrease"] == 0
    assert body["unlinked_count"] == 0
    assert body["unreviewed_count"] == 0
    assert body["duplicate_candidate_count"] == 0
    assert body["status"] == "observed"
    assert body["status"] == body["position_status"]
    assert body["confidence"] == body["position_confidence"]
    assert body["reason_codes"] == body["position_reason_codes"]
    assert body["ruleset_version"] == "pfis-balance-position-1"


async def test_balance_position_applies_asset_liability_signs_and_settled_only(client):
    user = await create_user(client, "position-contract-signs")
    bank = await _account(client, user["id"], "bank", "7711")
    card = await _account(client, user["id"], "credit_card", "7722")
    anchor_date = date.today() - timedelta(days=3)
    await _balance(client, user["id"], bank["id"], 1000, anchor_date)
    await _balance(client, user["id"], card["id"], 1000, anchor_date, source="statement")

    await _transaction(
        client,
        user["id"],
        bank["id"],
        amount=100,
        transaction_type="debit",
        transaction_date=date.today() - timedelta(days=2),
    )
    await _transaction(
        client,
        user["id"],
        bank["id"],
        amount=50,
        transaction_type="credit",
        transaction_date=date.today() - timedelta(days=1),
    )
    await _transaction(
        client,
        user["id"],
        bank["id"],
        amount=25,
        transaction_type="debit",
        transaction_status="pending",
        transaction_date=date.today(),
    )
    await _transaction(
        client,
        user["id"],
        card["id"],
        amount=200,
        transaction_type="debit",
        transaction_date=date.today() - timedelta(days=2),
        card_event="purchase",
    )
    await _transaction(
        client,
        user["id"],
        card["id"],
        amount=100,
        transaction_type="credit",
        transaction_date=date.today() - timedelta(days=1),
        card_event="payment",
        payment_rail="transfer",
    )
    await _transaction(
        client,
        user["id"],
        card["id"],
        amount=40,
        transaction_type="debit",
        transaction_status="pending",
        transaction_date=date.today(),
        card_event="purchase",
    )

    bank_position = await _position(client, user["id"], bank["id"])
    card_position = await _position(client, user["id"], card["id"])

    assert bank_position["settled_movement_since_observation"] == -50
    assert bank_position["estimated_balance"] == 950
    assert bank_position["pending_decrease"] == 25
    assert card_position["settled_movement_since_observation"] == 100
    assert card_position["estimated_balance"] == 1100
    assert card_position["pending_increase"] == 40


async def test_balance_position_uses_verified_anchor_and_reports_provisional_snapshot(client):
    user = await create_user(client, "position-contract-provisional")
    account = await _account(client, user["id"], "bank", "7733")
    await _balance(client, user["id"], account["id"], 1000, date.today() - timedelta(days=1))
    await _balance(
        client,
        user["id"],
        account["id"],
        5000,
        date.today(),
        verified=False,
        source_record_id="provisional-today",
    )

    account_response = await client.get(f"/api/accounts?user_id={user['id']}")
    account_response.raise_for_status()
    listed = account_response.json()[0]
    body = await _position(client, user["id"], account["id"])

    assert listed["latest_balance"] == 1000
    assert listed["latest_observed_balance"] == 5000
    assert listed["latest_observed_verified"] is False
    assert body["observed_balance"] == 1000
    assert body["observed_verified"] is True
    assert body["status"] == "observed"


async def test_balance_position_fail_closed_statuses_and_review_counts(client):
    user = await create_user(client, "position-contract-fail-closed")
    missing = await _account(client, user["id"], "bank", "7744")
    stale = await _account(client, user["id"], "bank", "7755")
    review = await _account(client, user["id"], "bank", "7766")
    unsupported = await _account(client, user["id"], "loan", "7788")

    missing_position = await _position(client, user["id"], missing["id"])
    assert missing_position["status"] == "incomplete"
    assert "verified_observation_required" in missing_position["reason_codes"]

    await _balance(client, user["id"], unsupported["id"], 4000, date.today())
    unsupported_position = await _position(client, user["id"], unsupported["id"])
    assert unsupported_position["status"] == "unsupported"
    assert "unsupported_product_type" in unsupported_position["reason_codes"]

    observed_at = datetime.now(UTC) - timedelta(hours=4)
    await _balance(
        client,
        user["id"],
        stale["id"],
        2000,
        date.today() - timedelta(days=1),
        source="connector",
        source_record_id="stale-connector-record",
        observed_at=observed_at,
        effective_at=observed_at,
        expected_cadence_minutes=60,
        coverage_start=observed_at - timedelta(days=1),
        coverage_end=observed_at,
        coverage_complete=True,
    )
    stale_position = await _position(client, user["id"], stale["id"])
    assert stale_position["status"] == "stale"
    assert stale_position["coverage_status"] == "overdue"
    assert "balance_observation_overdue" in stale_position["reason_codes"]

    await _balance(client, user["id"], review["id"], 3000, date.today() - timedelta(days=2))
    for index in range(2):
        await _transaction(
            client,
            user["id"],
            review["id"],
            amount=123,
            transaction_type="debit",
            transaction_date=date.today() - timedelta(days=1),
            merchant="Duplicated merchant",
            reviewed=False,
            reference_id=f"duplicate-{index}",
        )
    await _transaction(
        client,
        user["id"],
        review["id"],
        amount=500,
        transaction_type="debit",
        transaction_date=date.today() - timedelta(days=1),
        merchant="Card payment",
        payment_rail="transfer",
        card_event="payment",
    )
    review_position = await _position(client, user["id"], review["id"])
    assert review_position["status"] == "needs_review"
    assert review_position["unreviewed_count"] >= 2
    assert review_position["unlinked_count"] == 1
    assert review_position["duplicate_candidate_count"] == 1
    assert {"unreviewed_activity", "unlinked_card_payment", "duplicate_candidate_activity"} <= set(
        review_position["reason_codes"]
    )


async def test_balance_position_route_preserves_cross_user_ownership(client):
    owner = await create_user(client, "position-contract-owner")
    other = await create_user(client, "position-contract-other")
    account = await _account(client, owner["id"], "bank", "7777")
    await _balance(client, owner["id"], account["id"], 1000, date.today())

    denied = await client.get(f"/api/accounts/{account['id']}/position?user_id={other['id']}")
    assert denied.status_code == 404
