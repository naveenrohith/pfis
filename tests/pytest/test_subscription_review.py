"""Subscription and recurring-payment review workflow tests."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import auth_headers, register_user


async def _create_debit(
    client: AsyncClient,
    user_id: str,
    token: str,
    *,
    merchant: str,
    amount: float,
    txn_date: date,
    suffix: str,
) -> None:
    response = await client.post(
        f"/api/transactions/?user_id={user_id}",
        headers=auth_headers(token),
        json={
            "amount": amount,
            "currency": "INR",
            "transaction_type": "debit",
            "payment_method": "other",
            "merchant_raw": merchant.upper(),
            "merchant_normalized": merchant,
            "transaction_date": txn_date.isoformat(),
            "confidence_score": 0.95,
            "reference_id": f"{merchant}-{suffix}-{txn_date.isoformat()}",
        },
    )
    response.raise_for_status()


async def _seed_series(
    client: AsyncClient,
    user_id: str,
    token: str,
    merchant: str,
    dates: list[date],
    amounts: list[float] | None = None,
) -> None:
    amounts = amounts or [499.0] * len(dates)
    for index, (txn_date, amount) in enumerate(zip(dates, amounts, strict=True)):
        await _create_debit(
            client,
            user_id,
            token,
            merchant=merchant,
            amount=amount,
            txn_date=txn_date,
            suffix=str(index),
        )


@pytest.mark.asyncio
async def test_subscription_review_lifecycle_and_next_expected_rules(
    client: AsyncClient, auth_required
):
    user, token = await register_user(client, "subscription-life")
    as_of = "2026-09-25"

    await _seed_series(
        client,
        user["id"],
        token,
        "Candidate Cloud",
        [date(2026, 8, 10), date(2026, 9, 10)],
    )
    await _seed_series(
        client,
        user["id"],
        token,
        "Mature Music",
        [date(2026, 7, 15), date(2026, 8, 15), date(2026, 9, 15)],
        [100.0, 130.0, 100.0],
    )
    await _seed_series(
        client,
        user["id"],
        token,
        "Missed Backup",
        [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)],
    )
    await _seed_series(
        client,
        user["id"],
        token,
        "Inactive App",
        [date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)],
    )

    response = await client.get(
        f"/api/subscriptions/recurring-review?as_of={as_of}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    by_merchant = {item["merchant"]: item for item in body["items"]}
    assert by_merchant["Candidate Cloud"]["lifecycle_status"] == "candidate"
    assert by_merchant["Mature Music"]["lifecycle_status"] == "mature"
    assert by_merchant["Missed Backup"]["lifecycle_status"] == "missed"
    assert by_merchant["Inactive App"]["lifecycle_status"] == "inactive"

    assert by_merchant["Mature Music"]["next_expected"] == "2026-10-15"
    assert by_merchant["Mature Music"]["next_expected_null_reason"] is None
    assert by_merchant["Mature Music"]["amount_change_detected"] is True
    assert len(by_merchant["Mature Music"]["evidence_transaction_ids"]) == 3
    assert body["thresholds"]["mature_min_occurrences"] == 3

    for merchant in ("Candidate Cloud", "Missed Backup", "Inactive App"):
        assert by_merchant[merchant]["next_expected"] is None
        assert by_merchant[merchant]["next_expected_null_reason"]


@pytest.mark.asyncio
async def test_subscription_review_actions_are_persisted_scoped_and_idempotent(
    client: AsyncClient, auth_required
):
    owner, owner_token = await register_user(client, "subscription-owner")
    _, attacker_token = await register_user(client, "subscription-attacker")
    as_of = "2026-09-25"
    await _seed_series(
        client,
        owner["id"],
        owner_token,
        "Review Stream",
        [date(2026, 7, 5), date(2026, 8, 5), date(2026, 9, 5)],
    )
    listing = (
        await client.get(
            f"/api/subscriptions/recurring-review?as_of={as_of}",
            headers=auth_headers(owner_token),
        )
    ).json()
    stream_key = listing["items"][0]["stream_key"]

    forbidden_by_absence = await client.post(
        f"/api/subscriptions/recurring-review/{stream_key}/actions?as_of={as_of}",
        headers=auth_headers(attacker_token),
        json={"action": "confirm", "note": "attacker should not see owner stream"},
    )
    assert forbidden_by_absence.status_code == 404

    first = await client.post(
        f"/api/subscriptions/recurring-review/{stream_key}/actions?as_of={as_of}",
        headers=auth_headers(owner_token),
        json={"action": "confirm", "note": "still active"},
    )
    repeat = await client.post(
        f"/api/subscriptions/recurring-review/{stream_key}/actions?as_of={as_of}",
        headers=auth_headers(owner_token),
        json={"action": "confirm", "note": "still active"},
    )
    assert first.status_code == 201
    assert repeat.status_code == 201
    assert repeat.json()["id"] == first.json()["id"]

    confirmed = (
        await client.get(
            f"/api/subscriptions/recurring-review?as_of={as_of}",
            headers=auth_headers(owner_token),
        )
    ).json()
    assert confirmed["items"][0]["user_action"] == "confirm"
    assert confirmed["items"][0]["action_id"] == first.json()["id"]

    cancelled = await client.post(
        f"/api/subscriptions/recurring-review/{stream_key}/actions?as_of={as_of}",
        headers=auth_headers(owner_token),
        json={"action": "cancelled", "note": "user cancelled externally"},
    )
    assert cancelled.status_code == 201

    after_cancel = (
        await client.get(
            f"/api/subscriptions/recurring-review?as_of={as_of}",
            headers=auth_headers(owner_token),
        )
    ).json()
    assert after_cancel["items"] == []
    assert after_cancel["excluded_count"] == 1
