"""Ownership, atomicity, and privacy regression tests for source ingestion."""

from datetime import UTC, datetime

from app.models.email import RawEmail
from app.services.connectors.source_record import SourceRecord, SourceType
from app.services.domain_events import domain_event_dispatcher
from app.services.ingestion.persistence import persist_source_records
from sqlalchemy import select

from tests.pytest.helpers import create_user


def _record(user_id: str, message_id: str | None, *, source_type=SourceType.GMAIL):
    return SourceRecord(
        user_id=user_id,
        source_type=source_type,
        source_message_id=message_id,
        sender="HDFC Bank <alerts@hdfcbank.net>",
        subject="Payment alert",
        body="INR 750.00 was debited via UPI to BOOKMYSHOW",
        received_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


async def test_source_record_ownership_mismatch_is_rejected(client, test_session_factory):
    owner = await create_user(client, "source-owner")
    other = await create_user(client, "source-other")

    async with test_session_factory() as db:
        stats = await persist_source_records(
            db,
            owner["id"],
            SourceType.GMAIL,
            [
                _record(other["id"], "cross-user"),
                _record(owner["id"], "wrong-source", source_type=SourceType.DEMO),
            ],
        )
        await db.commit()
        stored = await db.scalars(select(RawEmail).where(RawEmail.user_id == owner["id"]))

    assert stats["emails_failed"] == 2
    assert stats["emails_stored"] == 0
    assert all(error["error"] == "source_ownership_mismatch" for error in stats["errors"])
    assert list(stored) == []


async def test_source_persistence_rolls_back_when_event_publication_fails(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "source-atomic")
    secret = "raw-email-secret-must-not-leak"

    async def fail_publish(_event):
        raise RuntimeError(secret)

    monkeypatch.setattr(domain_event_dispatcher, "publish", fail_publish)

    async with test_session_factory() as db:
        stats = await persist_source_records(
            db,
            user["id"],
            SourceType.GMAIL,
            [_record(user["id"], "event-failure")],
        )
        await db.commit()
        stored = await db.scalar(
            select(RawEmail).where(RawEmail.gmail_message_id == f"{user['id']}:event-failure")
        )

    assert stats["emails_failed"] == 1
    assert stats["emails_stored"] == 0
    assert secret not in str(stats)
    assert stats["errors"][0]["error"] == "source_processing_runtimeerror"
    assert stored is None


async def test_duplicate_source_records_are_counted_without_double_storage(
    client, test_session_factory
):
    user = await create_user(client, "source-duplicate")
    record = _record(user["id"], "same-message")

    async with test_session_factory() as db:
        stats = await persist_source_records(
            db,
            user["id"],
            SourceType.GMAIL,
            [record, record],
        )
        await db.commit()
        stored = await db.scalars(select(RawEmail).where(RawEmail.user_id == user["id"]))

    assert stats["emails_stored"] == 1
    assert stats["emails_skipped_duplicate"] == 1
    assert len(list(stored)) == 1
