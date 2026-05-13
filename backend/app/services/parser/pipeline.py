"""
Processing Pipeline
The core engine: Raw Email → Parse → Normalize → Categorize → Store Transaction

Processes unprocessed raw emails end-to-end.
"""

import logging
from datetime import date as date_type, datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import RawEmail
from app.models.sync import ParseFailure
from app.services.parser.registry import get_parser_registry
from app.services.parser.normalizer import (
    normalize_merchant,
    get_default_category_id,
    infer_merchant_from_text,
)
from app.services.transaction_service import TransactionService
from app.schemas.transaction import TransactionCreate

logger = logging.getLogger(__name__)


async def _record_parse_failure(
    db: AsyncSession,
    email: RawEmail,
    error_message: str,
    parser_version: int,
) -> None:
    result = await db.execute(
        select(ParseFailure).where(ParseFailure.email_id == email.id)
    )
    failure = result.scalar_one_or_none()
    if failure is None:
        failure = ParseFailure(
            email_id=email.id,
            error_message=error_message,
            parser_version=parser_version,
            resolved=False,
        )
        db.add(failure)
    else:
        failure.error_message = error_message
        failure.parser_version = parser_version
        failure.resolved = False


async def _resolve_parse_failure(db: AsyncSession, email_id: str) -> None:
    result = await db.execute(
        select(ParseFailure).where(ParseFailure.email_id == email_id)
    )
    failure = result.scalar_one_or_none()
    if failure:
        failure.resolved = True
        failure.error_message = None


async def _process_email_batch(
    db: AsyncSession,
    user_id: str,
    emails: Iterable[RawEmail],
) -> dict:
    emails = list(emails)
    stats = {
        "total_unprocessed": len(emails),
        "parsed_success": 0,
        "parsed_failed": 0,
        "stored": 0,
        "duplicates": 0,
        "low_confidence": 0,
        "results": [],
    }

    if not emails:
        logger.info("No unprocessed emails found")
        return stats

    registry = get_parser_registry()
    txn_service = TransactionService(db)
    default_category_id = await get_default_category_id(db)

    for email in emails:
        email_result = {
            "email_id": email.id,
            "subject": (email.subject or "")[:60],
            "sender": email.sender,
        }

        try:
            parse_result = registry.parse_email(
                sender=email.sender or "",
                subject=email.subject or "",
                body=email.body or "",
            )

            email_result["amount"] = parse_result.amount
            email_result["type"] = parse_result.transaction_type.value if parse_result.transaction_type else None
            email_result["merchant_raw"] = parse_result.merchant_raw
            email_result["merchant_source"] = parse_result.merchant_source
            email_result["date"] = str(parse_result.date) if parse_result.date else None
            email_result["confidence"] = parse_result.confidence_score
            email_result["bank"] = parse_result.bank

            if not parse_result.is_valid:
                stats["parsed_failed"] += 1
                email_result["status"] = "parse_failed"
                await _record_parse_failure(
                    db,
                    email,
                    f"Invalid parse: amount={parse_result.amount}, type={parse_result.transaction_type}",
                    parse_result.parser_version,
                )
                email.processed_flag = True
                await db.commit()
                stats["results"].append(email_result)
                continue

            inferred_category_id = None
            if not parse_result.merchant_raw or parse_result.merchant_source != "exact":
                inferred_merchant, inferred_category_id = await infer_merchant_from_text(
                    db,
                    f"{email.subject or ''} {email.body or ''}",
                )
                if inferred_merchant:
                    parse_result.merchant_raw = inferred_merchant
                    parse_result.merchant_source = "inferred"
                    parse_result.compute_confidence()
                    email_result["merchant_raw"] = inferred_merchant
                    email_result["merchant_source"] = "inferred"
                    email_result["merchant_inferred"] = True

            stats["parsed_success"] += 1
            if parse_result.confidence_score < 0.7:
                stats["low_confidence"] += 1

            merchant_normalized, category_id = await normalize_merchant(
                db, parse_result.merchant_raw or ""
            )
            if not category_id and inferred_category_id:
                category_id = inferred_category_id
            if not category_id:
                category_id = default_category_id

            email_result["merchant_normalized"] = merchant_normalized
            email_result["category_id"] = category_id
            email_result["confidence"] = parse_result.confidence_score

            txn_date = parse_result.date or date_type.today()
            txn_data = TransactionCreate(
                amount=parse_result.amount,
                currency=parse_result.currency,
                transaction_type=parse_result.transaction_type.value,
                merchant_raw=parse_result.merchant_raw,
                merchant_normalized=merchant_normalized,
                category_id=category_id,
                transaction_date=txn_date,
                account_last4=parse_result.account_last4,
                reference_id=parse_result.reference_id,
                confidence_score=parse_result.confidence_score,
                source_email_id=email.id,
            )

            try:
                txn = await txn_service.create_transaction(user_id, txn_data)
                stats["stored"] += 1
                email_result["status"] = "stored"
                email_result["transaction_id"] = txn.id
            except ValueError:
                stats["duplicates"] += 1
                email_result["status"] = "duplicate"

            await _resolve_parse_failure(db, email.id)
            email.processed_flag = True
            await db.commit()

        except Exception as e:
            stats["parsed_failed"] += 1
            email_result["status"] = "error"
            email_result["error"] = str(e)
            logger.error(f"Pipeline error for email {email.id}: {e}")

            await _record_parse_failure(db, email, str(e), parser_version=1)
            email.processed_flag = True
            await db.commit()

        stats["results"].append(email_result)

    logger.info(
        f"Pipeline complete: {stats['parsed_success']} parsed, "
        f"{stats['stored']} stored, {stats['duplicates']} dupes, "
        f"{stats['parsed_failed']} failed"
    )
    return stats


async def process_raw_emails(
    db: AsyncSession,
    user_id: str,
    limit: int = 50,
) -> dict:
    """
    Process all unprocessed raw emails for a user.
    Pipeline: Parse → Normalize → Categorize → Dedup → Store
    """
    # Fetch unprocessed emails
    result = await db.execute(
        select(RawEmail)
        .where(RawEmail.user_id == user_id, RawEmail.processed_flag.is_(False))
        .order_by(RawEmail.received_at.asc())
        .limit(limit)
    )
    emails = list(result.scalars().all())
    return await _process_email_batch(db, user_id, emails)


async def retry_parse_failures(
    db: AsyncSession,
    user_id: str,
    limit: int = 20,
) -> dict:
    """Retry unresolved parse failures for a user as a reprocessing batch."""
    result = await db.execute(
        select(ParseFailure)
        .options(selectinload(ParseFailure.email))
        .join(RawEmail, ParseFailure.email_id == RawEmail.id)
        .where(
            ParseFailure.resolved.is_(False),
            RawEmail.user_id == user_id,
        )
        .order_by(ParseFailure.last_retry_at.asc().nullsfirst(), ParseFailure.id.asc())
        .limit(limit)
    )
    failures = list(result.scalars().all())

    for failure in failures:
        failure.retry_count += 1
        failure.last_retry_at = datetime.now(timezone.utc)
        if failure.email:
            failure.email.processed_flag = False
    await db.commit()

    emails = [failure.email for failure in failures if failure.email is not None]
    stats = await _process_email_batch(db, user_id, emails)
    stats["retried_failures"] = len(failures)
    return stats
