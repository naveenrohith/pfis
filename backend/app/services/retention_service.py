"""Evidence-safe personal-data retention and redaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import RawEmail
from app.models.sync import ParseFailure, PipelineEvent
from app.models.user import User

RAW_EMAIL_RETENTION_POLICY_VERSION = 1
RAW_EMAIL_RETENTION_OPTIONS = frozenset({30, 90, 180, 365})
RAW_EMAIL_REDACTED_FIELDS = ("sender", "subject", "body")


async def redact_expired_raw_email_content(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    now: datetime | None = None,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Redact expired processed content while retaining lineage and audit evidence."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")

    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)

    users_statement = select(User.id, User.raw_email_retention_days).where(
        User.raw_email_retention_days.is_not(None)
    )
    if user_id is not None:
        users_statement = users_statement.where(User.id == user_id)
    policies = list((await db.execute(users_statement)).all())

    redacted_count = 0
    deferred_unresolved_count = 0
    for scoped_user_id, retention_days in policies:
        if retention_days not in RAW_EMAIL_RETENTION_OPTIONS:
            continue
        cutoff = instant - timedelta(days=retention_days)
        unresolved_failure = exists(
            select(ParseFailure.id).where(
                ParseFailure.email_id == RawEmail.id,
                ParseFailure.resolved.is_(False),
            )
        )
        expired = (
            RawEmail.user_id == scoped_user_id,
            RawEmail.content_redacted_at.is_(None),
            RawEmail.processed_flag.is_(True),
            func.coalesce(RawEmail.received_at, RawEmail.created_at) < cutoff,
        )

        deferred_unresolved_count += int(
            await db.scalar(select(func.count(RawEmail.id)).where(*expired, unresolved_failure))
            or 0
        )
        candidate_ids = list(
            await db.scalars(
                select(RawEmail.id)
                .where(*expired, ~unresolved_failure)
                .order_by(
                    func.coalesce(RawEmail.received_at, RawEmail.created_at),
                    RawEmail.id,
                )
                .limit(batch_size)
            )
        )
        if not candidate_ids:
            continue

        redacted_ids = list(
            await db.scalars(
                update(RawEmail)
                .where(
                    RawEmail.id.in_(candidate_ids),
                    RawEmail.content_redacted_at.is_(None),
                )
                .values(
                    sender=None,
                    subject=None,
                    body=None,
                    content_redacted_at=instant,
                )
                .returning(RawEmail.id)
            )
        )
        for email_id in redacted_ids:
            db.add(
                PipelineEvent(
                    user_id=scoped_user_id,
                    email_id=email_id,
                    event_type="raw_email_content_redacted",
                    stage="retention",
                    status="completed",
                    payload_json=json.dumps(
                        {
                            "policy_version": RAW_EMAIL_RETENTION_POLICY_VERSION,
                            "retention_days": retention_days,
                            "redacted_fields": RAW_EMAIL_REDACTED_FIELDS,
                        },
                        sort_keys=True,
                    ),
                    created_at=instant,
                )
            )
        redacted_count += len(redacted_ids)

    await db.commit()
    return {
        "policy_version": RAW_EMAIL_RETENTION_POLICY_VERSION,
        "users_evaluated": len(policies),
        "redacted": redacted_count,
        "deferred_unresolved": deferred_unresolved_count,
        "as_of": instant.isoformat().replace("+00:00", "Z"),
    }
