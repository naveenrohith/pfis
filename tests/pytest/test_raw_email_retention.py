"""Owned raw-email retention, lineage, and idempotency tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.models.category import Category
from app.models.email import RawEmail
from app.models.sync import BackgroundJob, ParseFailure, PipelineEvent
from app.models.transaction import PaymentMethod, Transaction, TransactionType
from app.models.user import User
from app.services import retention_scheduler
from app.services.retention_service import redact_expired_raw_email_content
from sqlalchemy import func, select

from tests.pytest.helpers import auth_headers, create_user, register_user


async def test_retention_redacts_only_eligible_owned_content_and_preserves_lineage(
    client,
    test_session_factory,
):
    user = await create_user(client, "retention-owner")
    other = await create_user(client, "retention-other")
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    old = now - timedelta(days=31)
    recent = now - timedelta(days=5)

    async with test_session_factory() as db:
        owner = await db.get(User, user["id"])
        assert owner is not None
        owner.raw_email_retention_days = 30
        other_user = await db.get(User, other["id"])
        assert other_user is not None
        other_user.raw_email_retention_days = 30
        category = await db.scalar(select(Category).order_by(Category.name))
        assert category is not None

        eligible = RawEmail(
            user_id=user["id"],
            gmail_message_id="retention-eligible",
            sender="alerts@bank.test",
            subject="Sensitive eligible subject",
            body="Sensitive eligible body",
            received_at=old,
            processed_flag=True,
        )
        unresolved = RawEmail(
            user_id=user["id"],
            gmail_message_id="retention-unresolved",
            sender="alerts@bank.test",
            subject="Must remain for retry",
            body="Unresolved parser evidence",
            received_at=old,
            processed_flag=True,
        )
        recent_email = RawEmail(
            user_id=user["id"],
            gmail_message_id="retention-recent",
            sender="alerts@bank.test",
            subject="Recent evidence",
            body="Recent body",
            received_at=recent,
            processed_flag=True,
        )
        other_email = RawEmail(
            user_id=other["id"],
            gmail_message_id="retention-other-user",
            sender="other@bank.test",
            subject="Other user subject",
            body="Other user body",
            received_at=old,
            processed_flag=True,
        )
        db.add_all([eligible, unresolved, recent_email, other_email])
        await db.flush()
        transaction = Transaction(
            user_id=user["id"],
            amount=Decimal("42.00"),
            currency="INR",
            transaction_type=TransactionType.DEBIT,
            payment_method=PaymentMethod.UPI,
            merchant_raw="RETENTION STORE",
            merchant_normalized="Retention Store",
            category_id=category.id,
            transaction_date=date(2026, 6, 1),
            source_email_id=eligible.id,
            fingerprint="retention-lineage-fingerprint",
        )
        db.add(transaction)
        db.add(
            ParseFailure(
                email_id=unresolved.id,
                error_message="Safe parser failure",
                failure_stage="parse",
                failure_code="no_match",
                parser_name="generic",
                parser_version=3,
                resolved=False,
            )
        )
        await db.commit()

        result = await redact_expired_raw_email_content(
            db,
            user_id=user["id"],
            now=now,
        )

        await db.refresh(eligible)
        await db.refresh(unresolved)
        await db.refresh(recent_email)
        await db.refresh(other_email)
        await db.refresh(transaction)
        assert result["redacted"] == 1
        assert result["deferred_unresolved"] == 1
        assert eligible.sender is None
        assert eligible.subject is None
        assert eligible.body is None
        assert eligible.content_redacted_at == now
        assert eligible.gmail_message_id == "retention-eligible"
        assert eligible.received_at == old
        assert transaction.source_email_id == eligible.id
        assert unresolved.body == "Unresolved parser evidence"
        assert recent_email.body == "Recent body"
        assert other_email.body == "Other user body"

        events = list(
            await db.scalars(
                select(PipelineEvent).where(
                    PipelineEvent.event_type == "raw_email_content_redacted"
                )
            )
        )
        assert len(events) == 1
        assert events[0].email_id == eligible.id
        assert json.loads(events[0].payload_json) == {
            "policy_version": 1,
            "redacted_fields": ["sender", "subject", "body"],
            "retention_days": 30,
        }
        assert "Sensitive" not in events[0].payload_json

        repeated = await redact_expired_raw_email_content(
            db,
            user_id=user["id"],
            now=now,
        )
        event_count = await db.scalar(
            select(func.count(PipelineEvent.id)).where(
                PipelineEvent.event_type == "raw_email_content_redacted"
            )
        )
        assert repeated["redacted"] == 0
        assert event_count == 1


async def test_retention_policy_update_is_owned_validated_and_enqueued(
    client,
    auth_required,
    test_session_factory,
):
    user, token = await register_user(client, "retention-policy-owner")
    other, _ = await register_user(client, "retention-policy-other")

    response = await client.patch(
        f"/api/users/{user['id']}",
        headers=auth_headers(token),
        json={"raw_email_retention_days": 90},
    )

    assert response.status_code == 200
    assert response.json()["raw_email_retention_days"] == 90
    invalid = await client.patch(
        f"/api/users/{user['id']}",
        headers=auth_headers(token),
        json={"raw_email_retention_days": 45},
    )
    assert invalid.status_code == 422
    cross_user = await client.patch(
        f"/api/users/{other['id']}",
        headers=auth_headers(token),
        json={"raw_email_retention_days": None},
    )
    assert cross_user.status_code == 403

    async with test_session_factory() as db:
        job = await db.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.user_id == user["id"],
                BackgroundJob.job_type == "raw_email_retention",
            )
            .order_by(BackgroundJob.created_at.desc())
        )
        assert job is not None
        assert json.loads(job.payload_json) == {"batch_size": 500}


async def test_system_retention_sweep_is_durable_and_daily_idempotent(
    test_session_factory,
    monkeypatch,
):
    scheduled = []
    monkeypatch.setattr(retention_scheduler, "AsyncSessionLocal", test_session_factory)
    monkeypatch.setattr(
        retention_scheduler,
        "schedule_job",
        lambda job_id: scheduled.append(job_id),
    )

    first_id = await retention_scheduler.enqueue_retention_sweep()
    second_id = await retention_scheduler.enqueue_retention_sweep()

    assert second_id == first_id
    assert scheduled == [first_id, first_id]
    async with test_session_factory() as db:
        job = await db.get(BackgroundJob, first_id)
        assert job is not None
        assert job.user_id is None
        assert job.job_type == "raw_email_retention"
        assert job.idempotency_key is not None
