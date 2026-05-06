"""
Processing Pipeline
The core engine: Raw Email → Parse → Normalize → Categorize → Store Transaction

Processes unprocessed raw emails end-to-end.
"""

import logging
import json
from datetime import date as date_type, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import RawEmail
from app.models.transaction import Transaction
from app.models.sync import ParseFailure
from app.services.parser.registry import get_parser_registry
from app.services.parser.normalizer import normalize_merchant, get_default_category_id
from app.services.transaction_service import TransactionService
from app.schemas.transaction import TransactionCreate

logger = logging.getLogger(__name__)


async def process_raw_emails(
    db: AsyncSession,
    user_id: str,
    limit: int = 50,
) -> dict:
    """
    Process all unprocessed raw emails for a user.
    Pipeline: Parse → Normalize → Categorize → Dedup → Store
    """
    stats = {
        "total_unprocessed": 0,
        "parsed_success": 0,
        "parsed_failed": 0,
        "stored": 0,
        "duplicates": 0,
        "low_confidence": 0,
        "results": [],
    }

    # Fetch unprocessed emails
    result = await db.execute(
        select(RawEmail)
        .where(RawEmail.user_id == user_id, RawEmail.processed_flag == False)
        .order_by(RawEmail.received_at.asc())
        .limit(limit)
    )
    emails = list(result.scalars().all())
    stats["total_unprocessed"] = len(emails)

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
            # Step 1: Parse
            parse_result = registry.parse_email(
                sender=email.sender or "",
                subject=email.subject or "",
                body=email.body or "",
            )

            email_result["amount"] = parse_result.amount
            email_result["type"] = parse_result.transaction_type.value if parse_result.transaction_type else None
            email_result["merchant_raw"] = parse_result.merchant_raw
            email_result["date"] = str(parse_result.date) if parse_result.date else None
            email_result["confidence"] = parse_result.confidence_score
            email_result["bank"] = parse_result.bank

            # Check if parse result is valid
            if not parse_result.is_valid:
                stats["parsed_failed"] += 1
                email_result["status"] = "parse_failed"

                # Store in DLQ
                dlq = ParseFailure(
                    email_id=email.id,
                    error_message=f"Invalid parse: amount={parse_result.amount}, type={parse_result.transaction_type}",
                    parser_version=parse_result.parser_version,
                )
                db.add(dlq)
                email.processed_flag = True
                await db.commit()

                stats["results"].append(email_result)
                continue

            stats["parsed_success"] += 1

            # Flag low confidence
            if parse_result.confidence_score < 0.7:
                stats["low_confidence"] += 1

            # Step 2: Normalize merchant
            merchant_normalized, category_id = await normalize_merchant(
                db, parse_result.merchant_raw or ""
            )

            # Use merchant's default category, or fall back to "Others"
            if not category_id:
                category_id = default_category_id

            email_result["merchant_normalized"] = merchant_normalized
            email_result["category_id"] = category_id

            # Step 3: Create transaction (with dedup)
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
                # Duplicate
                stats["duplicates"] += 1
                email_result["status"] = "duplicate"

            # Mark email as processed
            email.processed_flag = True
            await db.commit()

        except Exception as e:
            stats["parsed_failed"] += 1
            email_result["status"] = "error"
            email_result["error"] = str(e)
            logger.error(f"Pipeline error for email {email.id}: {e}")

            # Store in DLQ
            dlq = ParseFailure(
                email_id=email.id,
                error_message=str(e),
                parser_version=1,
            )
            db.add(dlq)
            email.processed_flag = True
            await db.commit()

        stats["results"].append(email_result)

    logger.info(
        f"Pipeline complete: {stats['parsed_success']} parsed, "
        f"{stats['stored']} stored, {stats['duplicates']} dupes, "
        f"{stats['parsed_failed']} failed"
    )

    return stats
