"""Subscription and recurring-payment review workflow tests."""

from __future__ import annotations

from datetime import date

import pytest
from app.services.knowledge.recurring_knowledge import RecurringPattern, RecurringPatternService
from app.services.subscription_review_service import SubscriptionReviewService
from fastapi import HTTPException
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


def _pattern(
    stream_key: str,
    merchant: str,
    *,
    occurrences: int = 3,
    cadence_confidence: float = 0.9,
    amount_low: float = 499.0,
    amount_high: float = 499.0,
) -> RecurringPattern:
    return RecurringPattern(
        merchant=merchant,
        occurrences=occurrences,
        avg_amount=(amount_low + amount_high) / 2,
        amount_low=amount_low,
        amount_high=amount_high,
        monthly_equivalent=(amount_low + amount_high) / 2,
        cadence="monthly",
        median_interval_days=30.0,
        cadence_confidence=cadence_confidence,
        amount_confidence=0.9,
        confidence=0.88,
        status="mature",
        last_seen=date(2026, 9, 1),
        next_expected_date=date(2026, 10, 1),
        next_expected_date_low=date(2026, 9, 29),
        next_expected_date_high=date(2026, 10, 3),
        data_sufficiency="high",
        financial_account_id="acct-sub",
        stream_key=stream_key,
        source_transaction_ids=(f"txn-{stream_key}-1", f"txn-{stream_key}-2"),
    )


@pytest.mark.asyncio
async def test_subscription_review_service_existing_action_paths_and_exclusions(
    client: AsyncClient, test_session_factory, monkeypatch
):
    user, _ = await register_user(client, "subscription-direct")
    active_pattern = _pattern("stream-active", "Direct Music", amount_low=400.0, amount_high=560.0)
    excluded_pattern = _pattern("stream-excluded", "Cancelled Video")
    current_patterns = [active_pattern, excluded_pattern]

    async def fake_analyze(_service, user_id: str, *, as_of=None):
        assert user_id == user["id"]
        return current_patterns

    monkeypatch.setattr(RecurringPatternService, "analyze", fake_analyze)

    async with test_session_factory() as session:
        service = SubscriptionReviewService(session)

        first = await service.record_action(
            user["id"],
            active_pattern.stream_key,
            action="confirm",
            note="keep it",
            as_of=date(2026, 9, 25),
        )
        assert first["merchant"] == "Direct Music"
        assert first["action"] == "confirm"

        await service.record_action(
            user["id"],
            excluded_pattern.stream_key,
            action="mark_not_recurring",
            note="one-off",
            as_of=date(2026, 9, 25),
        )
        listed = await service.list_items(user["id"], as_of=date(2026, 9, 25))
        assert listed["excluded_count"] == 1
        assert [item["merchant"] for item in listed["items"]] == ["Direct Music"]
        item = listed["items"][0]
        assert item["user_action"] == "confirm"
        assert item["action_note"] == "keep it"
        assert item["amount_change_detected"] is True
        assert item["evidence_transaction_ids"] == ["txn-stream-active-1", "txn-stream-active-2"]

        current_patterns = []
        repeat = await service.record_action(
            user["id"],
            active_pattern.stream_key,
            action="confirm",
            note="still keep it",
            as_of=date(2026, 9, 25),
        )
        assert repeat["id"] == first["id"]
        assert repeat["note"] == "still keep it"

        with pytest.raises(HTTPException) as changed_missing:
            await service.record_action(
                user["id"],
                active_pattern.stream_key,
                action="cancelled",
                as_of=date(2026, 9, 25),
            )
        assert changed_missing.value.status_code == 404

        with pytest.raises(HTTPException) as unknown:
            await service.record_action(
                user["id"],
                "stream-never-seen",
                action="confirm",
                as_of=date(2026, 9, 25),
            )
        assert unknown.value.status_code == 404

        with pytest.raises(HTTPException) as unsupported:
            await service.record_action(user["id"], active_pattern.stream_key, action="pause")
        assert unsupported.value.status_code == 422
