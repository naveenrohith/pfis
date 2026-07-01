"""Persistence helpers for connector-neutral source records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import RawEmail
from app.services.classification import ClassificationType, classify_source_record
from app.services.connectors.source_record import SourceRecord, SourceType
from app.services.domain_events import DomainEvent, domain_event_dispatcher

SKIP_STORAGE_TYPES = {
    ClassificationType.OTP,
    ClassificationType.PROMOTION,
    ClassificationType.IGNORE,
}


async def persist_source_records(
    db: AsyncSession,
    user_id: str,
    source_type: SourceType,
    records: list[SourceRecord],
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "emails_fetched": len(records),
        "emails_processed": 0,
        "emails_stored": 0,
        "emails_skipped_otp": 0,
        "emails_skipped_promo": 0,
        "emails_skipped_ignore": 0,
        "emails_skipped_duplicate": 0,
        "emails_failed": 0,
        "classification_counts": {},
        "errors": [],
    }

    for record in records:
        scoped_message_id = _scoped_message_id(user_id, record.source_message_id)
        try:
            if scoped_message_id:
                existing = await db.execute(
                    select(RawEmail).where(RawEmail.gmail_message_id == scoped_message_id)
                )
                if existing.scalar_one_or_none():
                    stats["emails_skipped_duplicate"] += 1
                    continue

            classification = classify_source_record(record.sender, record.subject, record.body)
            _increment(stats["classification_counts"], classification.classification.value)
            if classification.classification in SKIP_STORAGE_TYPES:
                if classification.classification == ClassificationType.OTP:
                    stats["emails_skipped_otp"] += 1
                elif classification.classification == ClassificationType.PROMOTION:
                    stats["emails_skipped_promo"] += 1
                else:
                    stats["emails_skipped_ignore"] += 1
                continue

            db.add(
                RawEmail(
                    user_id=user_id,
                    gmail_message_id=scoped_message_id,
                    subject=record.subject,
                    body=record.body,
                    sender=record.sender,
                    received_at=record.received_at or datetime.now(UTC),
                    processed_flag=False,
                )
            )
            stats["emails_processed"] += 1
            stats["emails_stored"] += 1
            await domain_event_dispatcher.publish(
                DomainEvent(
                    "RawEmailStored",
                    user_id,
                    source_type,
                    {
                        "source_message_id": scoped_message_id,
                        "classification": classification.classification.value,
                        "confidence": classification.confidence,
                    },
                )
            )
        except Exception as exc:
            stats["emails_failed"] += 1
            stats["errors"].append({"source_message_id": scoped_message_id, "error": str(exc)})

    return stats


def _scoped_message_id(user_id: str, message_id: str | None) -> str | None:
    if not message_id:
        return None
    return message_id if message_id.startswith(f"{user_id}:") else f"{user_id}:{message_id}"


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1
