"""Durable cross-domain financial change capture and replay regressions."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import app.models  # noqa: F401 - ensure all ownership tables are registered.
from app.database import Base
from app.models.financial_change import FinancialChangeCursor, FinancialChangeEvent
from app.models.summary import MonthlySummary
from app.models.transaction import PaymentMethod, Transaction, TransactionType
from app.services.financial_change_capture import (
    CHANGE_CAPTURE_EXCLUDED_TABLES,
    CHANGE_DOMAINS_BY_TABLE,
    queue_financial_change,
)
from app.services.financial_change_service import (
    FINANCIAL_CHANGE_RETENTION_DAYS,
    FinancialChangeService,
    FinancialChangeTailer,
    prune_financial_change_events,
)
from sqlalchemy import func, select

from tests.pytest.helpers import auth_headers, register_user


def test_user_owned_change_tables_are_mapped_or_explicitly_excluded():
    ownership_tables = {
        name
        for name, table in Base.metadata.tables.items()
        if any(column.name.endswith("user_id") for column in table.c)
    }
    assert ownership_tables <= set(CHANGE_DOMAINS_BY_TABLE) | set(CHANGE_CAPTURE_EXCLUDED_TABLES)
    assert set(CHANGE_DOMAINS_BY_TABLE).isdisjoint(CHANGE_CAPTURE_EXCLUDED_TABLES)


def _transaction(user_id: str, marker: str) -> Transaction:
    return Transaction(
        user_id=user_id,
        amount=Decimal("123.45"),
        currency="INR",
        transaction_type=TransactionType.DEBIT,
        payment_method=PaymentMethod.OTHER,
        merchant_raw=marker,
        merchant_normalized=marker,
        transaction_date=date(2026, 9, 1),
        fingerprint=f"financial-change-{marker}",
    )


async def test_committed_transaction_is_replayed_only_to_its_authenticated_user(
    client, auth_required, test_session_factory
):
    owner, owner_token = await register_user(client, "change-owner")
    other, other_token = await register_user(client, "change-other")

    async with test_session_factory() as db:
        db.add(_transaction(owner["id"], "owner-transaction"))
        await db.commit()

    own_response = await client.get(
        "/api/sync/changes",
        params={"user_id": owner["id"], "after_sequence": 0},
        headers=auth_headers(owner_token),
    )
    own_response.raise_for_status()
    payload = own_response.json()
    assert payload["current_sequence"] == 1
    assert payload["reset_required"] is False
    assert payload["events"][0]["sequence"] == 1
    assert {"activity", "today", "accounts", "cards", "planning"}.issubset(
        payload["events"][0]["domains"]
    )

    cross_user_response = await client.get(
        "/api/sync/changes",
        params={"user_id": owner["id"], "after_sequence": 0},
        headers=auth_headers(other_token),
    )
    assert cross_user_response.status_code == 403

    other_response = await client.get(
        "/api/sync/changes",
        params={"user_id": other["id"], "after_sequence": 0},
        headers=auth_headers(other_token),
    )
    other_response.raise_for_status()
    assert other_response.json()["events"] == []
    assert other_response.json()["current_sequence"] == 0


async def test_rollback_discards_events_and_read_model_writes_do_not_emit(
    client, test_session_factory
):
    user = await register_user(client, "change-rollback")
    async with test_session_factory() as db:
        db.add(_transaction(user[0]["id"], "rolled-back-transaction"))
        await db.flush()
        await db.rollback()

        assert await db.get(FinancialChangeCursor, user[0]["id"]) is None
        assert (
            await db.scalar(
                select(func.count(FinancialChangeEvent.id)).where(
                    FinancialChangeEvent.user_id == user[0]["id"]
                )
            )
            == 0
        )

        db.add(
            MonthlySummary(
                user_id=user[0]["id"],
                month=9,
                year=2026,
                payload_json="{}",
            )
        )
        await db.commit()
        assert await db.get(FinancialChangeCursor, user[0]["id"]) is None


async def test_concurrent_commits_allocate_unique_per_user_sequences(client, test_session_factory):
    user, _ = await register_user(client, "change-concurrent")

    async def write(marker: str) -> None:
        async with test_session_factory() as db:
            db.add(_transaction(user["id"], marker))
            await db.commit()

    await asyncio.gather(write("concurrent-a"), write("concurrent-b"))

    async with test_session_factory() as db:
        sequences = list(
            (
                await db.scalars(
                    select(FinancialChangeEvent.sequence)
                    .where(FinancialChangeEvent.user_id == user["id"])
                    .order_by(FinancialChangeEvent.sequence)
                )
            ).all()
        )
        assert sequences == [1, 2]


async def test_core_change_helper_and_90_day_pruning_require_full_refresh(
    client, test_session_factory
):
    user, _ = await register_user(client, "change-retention")
    now = datetime.now(UTC)
    async with test_session_factory() as db:
        db.add(FinancialChangeCursor(user_id=user["id"], current_sequence=0))
        await db.flush()
        await queue_financial_change(db, user["id"], {"statements", "planning"})
        await db.commit()

        event_row = await db.scalar(
            select(FinancialChangeEvent).where(FinancialChangeEvent.user_id == user["id"])
        )
        assert event_row is not None
        assert event_row.domains == ["planning", "statements"]
        event_row.created_at = now - timedelta(days=FINANCIAL_CHANGE_RETENTION_DAYS + 1)
        await db.commit()

        deleted = await prune_financial_change_events(db, now=now)
        await db.commit()
        assert deleted == 1

        page = await FinancialChangeService(db).changes_after(user["id"], 0)
        assert page.current_sequence == 1
        assert page.events == []
        assert page.reset_required is True
        assert page.oldest_available_sequence is None

        future_cursor = await FinancialChangeService(db).changes_after(user["id"], 99)
        assert future_cursor.reset_required is True
        assert future_cursor.current_sequence == 1


async def test_tailer_relays_committed_journal_rows(monkeypatch, client, test_session_factory):
    user, _ = await register_user(client, "change-tailer")
    async with test_session_factory() as db:
        db.add(FinancialChangeCursor(user_id=user["id"], current_sequence=1))
        db.add(
            FinancialChangeEvent(
                user_id=user["id"],
                sequence=1,
                event_type="financial_state_updated",
                domains=["accounts", "planning"],
            )
        )
        await db.commit()

    delivered: list[tuple[str, str, dict]] = []

    async def record_broadcast(user_id: str, event_type: str, data: dict) -> None:
        delivered.append((user_id, event_type, data))

    from app.services import financial_change_service

    monkeypatch.setattr(financial_change_service.sync_event_manager, "broadcast", record_broadcast)
    tailer = FinancialChangeTailer()
    count = await tailer.poll_once()

    assert count == 1
    assert delivered[0][0:2] == (user["id"], "financial_state_updated")
    assert delivered[0][2]["domains"] == ["accounts", "planning"]
