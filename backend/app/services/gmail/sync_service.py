"""Gmail sync compatibility service.

Real Gmail ingestion is coordinated through the connector-driven
``IngestionCoordinator``. This module keeps the public service functions stable
for existing routes and jobs while the Gmail-specific API work lives in
``services.connectors.gmail_connector``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import RawEmail
from app.models.sync import SyncRun, SyncStatus
from app.services.gmail.email_filter import EmailType, classify_email
from app.services.ingestion import IngestionCoordinator, IngestionMode

logger = logging.getLogger(__name__)


class DemoSyncStats(TypedDict):
    emails_fetched: int
    emails_stored: int
    emails_skipped_otp: int
    emails_skipped_promo: int
    emails_skipped_duplicate: int
    classifications: list[dict[str, object]]


async def demo_sync_gmail_emails(
    db: AsyncSession,
    user_id: str,
) -> DemoSyncStats:
    """Simulate Gmail sync using deterministic sample emails for demo/testing."""
    from app.services.gmail.demo_data import SAMPLE_EMAILS

    stats: DemoSyncStats = {
        "emails_fetched": len(SAMPLE_EMAILS),
        "emails_stored": 0,
        "emails_skipped_otp": 0,
        "emails_skipped_promo": 0,
        "emails_skipped_duplicate": 0,
        "classifications": [],
    }

    sync_run = SyncRun(user_id=user_id, status=SyncStatus.RUNNING)
    db.add(sync_run)
    await db.commit()
    await db.refresh(sync_run)
    sync_run_id = sync_run.id

    try:
        for email_data in SAMPLE_EMAILS:
            fake_gmail_id = f"demo_{uuid.uuid5(uuid.NAMESPACE_DNS, email_data['body'][:50])}"
            scoped_gmail_id = f"{user_id}:{fake_gmail_id}"

            existing = await db.execute(
                select(RawEmail).where(RawEmail.gmail_message_id == scoped_gmail_id)
            )
            if existing.scalar_one_or_none():
                stats["emails_skipped_duplicate"] += 1
                stats["classifications"].append(
                    {
                        "subject": email_data["subject"][:60],
                        "type": "DUPLICATE",
                    }
                )
                continue

            email_type, bank_name, confidence = classify_email(
                email_data["sender"],
                email_data["subject"],
                email_data["body"],
            )

            stats["classifications"].append(
                {
                    "subject": email_data["subject"][:60],
                    "sender": email_data["sender"],
                    "type": email_type.value,
                    "bank": bank_name,
                    "confidence": confidence,
                }
            )

            if email_type == EmailType.OTP:
                stats["emails_skipped_otp"] += 1
                continue
            if email_type == EmailType.PROMOTION:
                stats["emails_skipped_promo"] += 1
                continue
            if email_type == EmailType.IGNORE:
                continue

            db.add(
                RawEmail(
                    user_id=user_id,
                    gmail_message_id=scoped_gmail_id,
                    subject=email_data["subject"],
                    body=email_data["body"],
                    sender=email_data["sender"],
                    received_at=datetime.now(UTC),
                    processed_flag=False,
                )
            )
            stats["emails_stored"] += 1

        sync_run.status = SyncStatus.COMPLETED
        sync_run.end_time = datetime.now(UTC)
        sync_run.emails_fetched = stats["emails_fetched"]
        sync_run.emails_processed = stats["emails_stored"]
        await db.commit()
        return stats
    except Exception as exc:
        await db.rollback()
        failed_run = await db.scalar(
            select(SyncRun).where(SyncRun.id == sync_run_id, SyncRun.user_id == user_id)
        )
        if failed_run is not None:
            failed_run.status = SyncStatus.FAILED
            failed_run.end_time = datetime.now(UTC)
            failed_run.errors = json.dumps([{"error": f"demo_sync_{type(exc).__name__.lower()}"}])
        await db.commit()
        logger.warning(
            "Demo Gmail sync failed user=%s exception=%s",
            user_id[:8],
            type(exc).__name__,
        )
        raise


async def sync_gmail_emails(
    db: AsyncSession,
    user_id: str,
    gmail_account_id: str,
    max_results: int | None = 50,
) -> dict:
    """Compatibility wrapper for Gmail backfill sync."""
    coordinator = IngestionCoordinator(db)
    return await coordinator.run_gmail(
        user_id=user_id,
        gmail_account_id=gmail_account_id,
        mode=IngestionMode.BACKFILL,
        max_results=max_results,
    )


async def sync_gmail_emails_incremental(
    db: AsyncSession,
    user_id: str,
    gmail_account_id: str,
) -> dict:
    """Compatibility wrapper for Gmail incremental sync."""
    coordinator = IngestionCoordinator(db)
    return await coordinator.run_gmail(
        user_id=user_id,
        gmail_account_id=gmail_account_id,
        mode=IngestionMode.INCREMENTAL,
        max_results=500,
    )
