"""Expected-versus-observed temporal knowledge regression tests."""

from datetime import date, timedelta

import pytest
from app.models.roadmap import RoadmapBill
from app.services.temporal_event_service import TemporalEventService
from httpx import AsyncClient

from tests.pytest.helpers import create_user, user_today


async def _seed_transaction(
    client: AsyncClient,
    user_id: str,
    category_id: str,
    *,
    transaction_type: str,
    merchant: str,
    amount: float,
    transaction_date: date,
    reference: str,
    card_event: str = "none",
    transaction_status: str = "completed",
) -> dict:
    response = await client.post(
        f"/api/transactions/?user_id={user_id}",
        json={
            "amount": amount,
            "currency": "INR",
            "transaction_type": transaction_type,
            "card_event": card_event,
            "transaction_status": transaction_status,
            "merchant_raw": merchant.upper(),
            "merchant_normalized": merchant,
            "category_id": category_id,
            "transaction_date": transaction_date.isoformat(),
            "confidence_score": 0.95,
            "reference_id": reference,
        },
    )
    response.raise_for_status()
    return response.json()


async def _seed_bill_event(
    client: AsyncClient,
    user_id: str,
    *,
    label: str,
    amount: float,
    due_date: date,
) -> dict:
    created = await client.post(
        f"/api/bills?user_id={user_id}",
        json={
            "label": label,
            "bill_type": "utility",
            "amount": amount,
            "due_date": due_date.isoformat(),
            "source_kind": "manual",
            "confirmed": True,
        },
    )
    created.raise_for_status()
    timeline = await client.get(
        f"/api/knowledge/events?user_id={user_id}"
        f"&range_start={due_date.isoformat()}&range_end={due_date.isoformat()}"
    )
    timeline.raise_for_status()
    return next(event for event in timeline.json()["events"] if event["label"] == label)


@pytest.mark.asyncio
async def test_empty_temporal_timeline_has_stable_versioned_shape(client: AsyncClient):
    user = await create_user(client, "temporal-empty")
    response = await client.get(f"/api/knowledge/events?user_id={user['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["ruleset_version"] == "pfis-temporal-events-1"
    assert body["events"] == []
    assert body["counts"] == {
        "conflict": 0,
        "overdue": 0,
        "missed": 0,
        "expected": 0,
        "observed": 0,
        "cancelled": 0,
    }
    assert "similar merchant" in " ".join(body["assumptions"]).lower()


@pytest.mark.asyncio
async def test_temporal_timeline_unifies_explicit_and_pattern_evidence(client: AsyncClient):
    user = await create_user(client, "temporal-unified")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = user_today(user)

    overdue_bill = await client.post(
        f"/api/bills?user_id={user['id']}",
        json={
            "label": "Electricity",
            "bill_type": "utility",
            "amount": 1800,
            "due_date": (today - timedelta(days=3)).isoformat(),
            "source_kind": "manual",
            "confirmed": True,
        },
    )
    overdue_bill.raise_for_status()

    income_ids: list[str] = []
    expense_ids: list[str] = []
    for index, days_ago in enumerate((60, 30, 0)):
        income = await _seed_transaction(
            client,
            user["id"],
            category_id,
            transaction_type="credit",
            merchant="Employer payroll",
            amount=50000,
            transaction_date=today - timedelta(days=days_ago),
            reference=f"temporal-income-{index}",
        )
        expense = await _seed_transaction(
            client,
            user["id"],
            category_id,
            transaction_type="debit",
            merchant="Home internet",
            amount=999,
            transaction_date=today - timedelta(days=days_ago),
            reference=f"temporal-expense-{index}",
        )
        income_ids.append(income["id"])
        expense_ids.append(expense["id"])

    response = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={(today - timedelta(days=7)).isoformat()}"
        f"&range_end={(today + timedelta(days=45)).isoformat()}"
    )
    assert response.status_code == 200
    events = response.json()["events"]

    bill = next(event for event in events if event["label"] == "Electricity")
    assert bill["state"] == "overdue"
    assert bill["observation"] is None
    assert bill["evidence"] == [
        {
            "source_type": "bill",
            "source_id": overdue_bill.json()["id"],
            "role": "definition",
        }
    ]

    income = next(event for event in events if event["kind"] == "income")
    assert income["direction"] == "inflow"
    assert income["window_start"] < income["expected_date"] < income["window_end"]
    assert {
        item["source_id"] for item in income["evidence"] if item["source_type"] == "transaction"
    } == set(income_ids)

    recurring = next(event for event in events if event["kind"] == "recurring_expense")
    assert recurring["direction"] == "outflow"
    assert recurring["amount"]["low"] <= 999 <= recurring["amount"]["high"]
    assert {
        item["source_id"] for item in recurring["evidence"] if item["source_type"] == "transaction"
    } == set(expense_ids)


@pytest.mark.asyncio
async def test_transaction_lifecycle_events_preserve_status_and_ledger_neutrality(
    client: AsyncClient,
):
    user = await create_user(client, "temporal-transaction-lifecycle")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = user_today(user)

    pending = await _seed_transaction(
        client,
        user["id"],
        category_id,
        transaction_type="debit",
        merchant="Pending authorization",
        amount=1200,
        transaction_date=today,
        reference="lifecycle-pending",
        transaction_status="pending",
    )
    failed = await _seed_transaction(
        client,
        user["id"],
        category_id,
        transaction_type="debit",
        merchant="Failed authorization",
        amount=800,
        transaction_date=today,
        reference="lifecycle-failed",
        transaction_status="failed",
    )
    refund = await _seed_transaction(
        client,
        user["id"],
        category_id,
        transaction_type="refund",
        merchant="Returned purchase",
        amount=450,
        transaction_date=today,
        reference="lifecycle-refund",
        card_event="refund",
    )
    reversal = await _seed_transaction(
        client,
        user["id"],
        category_id,
        transaction_type="debit",
        merchant="Reversed purchase",
        amount=975,
        transaction_date=today,
        reference="lifecycle-reversal",
        card_event="reversal",
    )

    response = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
    )
    response.raise_for_status()
    lifecycle = {
        event["evidence"][0]["source_id"]: event
        for event in response.json()["events"]
        if event["kind"] == "transaction_lifecycle"
    }

    assert set(lifecycle) == {pending["id"], failed["id"], refund["id"], reversal["id"]}
    assert lifecycle[pending["id"]]["state"] == "expected"
    assert lifecycle[pending["id"]]["direction"] == "outflow"
    assert lifecycle[failed["id"]]["state"] == "cancelled"
    assert lifecycle[failed["id"]]["direction"] == "outflow"
    assert lifecycle[refund["id"]]["state"] == "observed"
    assert lifecycle[refund["id"]]["direction"] == "inflow"
    assert lifecycle[refund["id"]]["amount"] == {"low": 450.0, "expected": 450.0, "high": 450.0}
    assert lifecycle[refund["id"]]["observation"] == {
        "observed_date": today.isoformat(),
        "amount": 450.0,
        "transaction_id": refund["id"],
        "confirmation": "user_status",
    }
    assert lifecycle[reversal["id"]]["label"].startswith("Reversal")
    assert lifecycle[reversal["id"]]["direction"] == "inflow"
    decision = await client.put(
        f"/api/knowledge/events/{lifecycle[pending['id']]['id']}/decision?user_id={user['id']}",
        json={"decision": "confirmed"},
    )
    assert decision.status_code == 422
    historical = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
        f"&as_of={today.isoformat()}"
    )
    historical.raise_for_status()
    historical_ids = {
        event["evidence"][0]["source_id"]
        for event in historical.json()["events"]
        if event["kind"] == "transaction_lifecycle"
    }
    assert historical_ids == set(lifecycle)
    assert all(
        "does not create a second ledger row" in assumption
        for event in lifecycle.values()
        for assumption in event["assumptions"]
        if "ledger row" in assumption
    )


@pytest.mark.asyncio
async def test_paid_bill_is_explicit_observation_without_false_ledger_match(client: AsyncClient):
    user = await create_user(client, "temporal-paid")
    today = user_today(user)
    created = await client.post(
        f"/api/bills?user_id={user['id']}",
        json={
            "label": "Insurance renewal",
            "bill_type": "insurance",
            "amount": 4200,
            "due_date": today.isoformat(),
            "source_kind": "manual",
            "confirmed": True,
        },
    )
    created.raise_for_status()
    paid = await client.patch(
        f"/api/bills/{created.json()['id']}?user_id={user['id']}", json={"status": "paid"}
    )
    paid.raise_for_status()

    response = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
    )
    event = response.json()["events"][0]
    assert event["state"] == "observed"
    assert event["observation"] == {
        "observed_date": today.isoformat(),
        "amount": 4200.0,
        "transaction_id": None,
        "confirmation": "user_status",
    }
    assert "no ledger transaction" in " ".join(event["assumptions"]).lower()


@pytest.mark.asyncio
async def test_temporal_timeline_rejects_unbounded_or_reversed_ranges(client: AsyncClient):
    user = await create_user(client, "temporal-range")
    today = user_today(user)
    reversed_range = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={(today - timedelta(days=1)).isoformat()}"
    )
    assert reversed_range.status_code == 422

    oversized = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={(today + timedelta(days=367)).isoformat()}"
    )
    assert oversized.status_code == 422


@pytest.mark.asyncio
async def test_temporal_decisions_persist_update_and_can_be_removed(client: AsyncClient):
    user = await create_user(client, "temporal-decision")
    today = user_today(user)
    event = await _seed_bill_event(
        client,
        user["id"],
        label="Decision lifecycle bill",
        amount=1250,
        due_date=today,
    )
    endpoint = f"/api/knowledge/events/{event['id']}/decision?user_id={user['id']}"

    invalid_observed = await client.put(endpoint, json={"decision": "observed"})
    invalid_conflict = await client.put(endpoint, json={"decision": "conflict"})
    assert invalid_observed.status_code == 422
    assert invalid_conflict.status_code == 422

    confirmed = await client.put(endpoint, json={"decision": "confirmed"})
    assert confirmed.status_code == 200
    assert confirmed.json()["decision"]["decision"] == "confirmed"
    assert confirmed.json()["confidence"] == 1.0
    assert confirmed.json()["evidence"][-1]["source_type"] == "user_confirmation"

    persisted = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
    )
    persisted_event = next(item for item in persisted.json()["events"] if item["id"] == event["id"])
    assert persisted_event["decision"]["decision"] == "confirmed"

    cancelled = await client.put(
        endpoint,
        json={"decision": "cancelled", "note": "Provider cancelled this occurrence"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["observation"] is None

    removed = await client.delete(endpoint)
    assert removed.status_code == 204
    reset = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
    )
    reset_event = next(item for item in reset.json()["events"] if item["id"] == event["id"])
    assert reset_event["decision"] is None
    assert reset_event["state"] == "expected"
    assert (await client.delete(endpoint)).status_code == 404


@pytest.mark.asyncio
async def test_exact_transaction_links_are_owned_validated_and_explain_conflicts(
    client: AsyncClient,
):
    user = await create_user(client, "temporal-link-owner")
    other = await create_user(client, "temporal-link-other")
    category_id = (await client.get("/api/categories/")).json()[0]["id"]
    today = user_today(user)
    event = await _seed_bill_event(
        client,
        user["id"],
        label="Linked electricity bill",
        amount=1800,
        due_date=today,
    )
    endpoint = f"/api/knowledge/events/{event['id']}/decision?user_id={user['id']}"
    exact = await _seed_transaction(
        client,
        user["id"],
        category_id,
        transaction_type="debit",
        merchant="Electricity provider",
        amount=1800,
        transaction_date=today,
        reference="temporal-exact-link",
    )

    linked = await client.put(
        endpoint,
        json={"decision": "linked", "transaction_id": exact["id"]},
    )
    assert linked.status_code == 200
    linked_event = linked.json()
    assert linked_event["state"] == "observed"
    assert linked_event["observation"] == {
        "observed_date": today.isoformat(),
        "amount": 1800.0,
        "transaction_id": exact["id"],
        "confirmation": "ledger_match",
    }
    assert linked_event["evidence"][-1] == {
        "source_type": "transaction",
        "source_id": exact["id"],
        "role": "match",
    }

    other_transaction = await _seed_transaction(
        client,
        other["id"],
        category_id,
        transaction_type="debit",
        merchant="Private other-user activity",
        amount=1800,
        transaction_date=today,
        reference="temporal-cross-user-link",
    )
    cross_user = await client.put(
        endpoint,
        json={"decision": "linked", "transaction_id": other_transaction["id"]},
    )
    assert cross_user.status_code == 404

    wrong_direction = await _seed_transaction(
        client,
        user["id"],
        category_id,
        transaction_type="credit",
        merchant="Refund",
        amount=1800,
        transaction_date=today,
        reference="temporal-wrong-direction",
    )
    rejected = await client.put(
        endpoint,
        json={"decision": "linked", "transaction_id": wrong_direction["id"]},
    )
    assert rejected.status_code == 422

    mismatched = await _seed_transaction(
        client,
        user["id"],
        category_id,
        transaction_type="debit",
        merchant="Electricity provider adjustment",
        amount=3000,
        transaction_date=today,
        reference="temporal-amount-conflict",
    )
    conflict = await client.put(
        endpoint,
        json={"decision": "linked", "transaction_id": mismatched["id"]},
    )
    assert conflict.status_code == 200
    assert conflict.json()["state"] == "conflict"
    assert "amount differs" in conflict.json()["conflict_reason"]


@pytest.mark.asyncio
async def test_recomputation_audit_is_non_mutating_and_finds_orphaned_decisions(
    client: AsyncClient,
    test_session_factory,
):
    user = await create_user(client, "temporal-recomputation-audit")
    today = user_today(user)
    event = await _seed_bill_event(
        client,
        user["id"],
        label="Audited source bill",
        amount=2400,
        due_date=today,
    )
    decision = await client.put(
        f"/api/knowledge/events/{event['id']}/decision?user_id={user['id']}",
        json={"decision": "confirmed"},
    )
    decision.raise_for_status()
    audit_url = (
        f"/api/knowledge/events/audit?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
    )

    clean = await client.get(audit_url)
    clean.raise_for_status()
    clean_body = clean.json()
    assert clean_body["source_event_count"] == 1
    assert clean_body["decision_count"] == 1
    assert clean_body["applicable_decision_count"] == 1
    assert clean_body["orphaned_decision_count"] == 0
    assert clean_body["events_by_kind"] == {"bill": 1}
    assert clean_body["would_mutate"] is False

    async with test_session_factory() as db:
        source = await db.get(RoadmapBill, event["evidence"][0]["source_id"])
        assert source is not None
        await db.delete(source)
        await db.commit()

    orphaned = await client.get(audit_url)
    orphaned.raise_for_status()
    orphaned_body = orphaned.json()
    assert orphaned_body["source_event_count"] == 0
    assert orphaned_body["decision_count"] == 1
    assert orphaned_body["applicable_decision_count"] == 0
    assert orphaned_body["orphaned_decision_count"] == 1
    assert orphaned_body["issues"][0]["issue"] == "orphaned_event"
    assert orphaned_body["would_mutate"] is False

    repeated = await client.get(audit_url)
    assert repeated.json() == orphaned_body


def test_temporal_recurrence_fast_forwards_without_losing_month_end_anchor():
    assert TemporalEventService._occurrences(
        date(2010, 1, 31),
        "monthly",
        date(2026, 1, 1),
        date(2026, 3, 31),
    ) == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]
