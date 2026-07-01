"""
Processing Pipeline
The core engine: Raw Email → Parse → Normalize → Categorize → Store Transaction

Processes unprocessed raw emails end-to-end.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.email import RawEmail
from app.models.sync import ParseFailure
from app.schemas.transaction import TransactionCreate
from app.schemas.transaction import TransactionTypeEnum as TransactionSchemaType
from app.services.gmail.email_filter import EmailType, classify_email
from app.services.parser.base_parser import BaseParser, ParseResult
from app.services.parser.normalizer import (
    get_default_category_id,
    infer_merchant_from_text,
    normalize_merchant,
)
from app.services.parser.registry import get_parser_registry
from app.services.transaction_service import DuplicateTransactionError, TransactionService

logger = logging.getLogger(__name__)
_TEXT_NORMALIZER = BaseParser()
SKIPPABLE_EMAIL_TYPES = {
    EmailType.IGNORE,
    EmailType.OTP,
    EmailType.PROMOTION,
    EmailType.STATEMENT,
}


def _normalize_email_body(body: str) -> str:
    """Normalize stored email bodies before parser rules are applied."""
    return _TEXT_NORMALIZER._clean_text(body or "")


def _prepare_parser_body(email: RawEmail) -> str:
    """Normalize the email body once and keep the stored body aligned."""
    raw_body = email.body or ""
    cleaned_body = _normalize_email_body(raw_body)
    parser_body = cleaned_body or raw_body
    if cleaned_body and cleaned_body != raw_body:
        email.body = cleaned_body
    return parser_body


def _classify_pipeline_email(email: RawEmail, parser_body: str) -> EmailType:
    """Classify an email for pipeline routing."""
    email_type, _, _ = classify_email(
        email.sender or "",
        email.subject or "",
        parser_body,
    )
    return email_type


def _attach_parse_result(email_result: dict[str, Any], parse_result: ParseResult) -> None:
    """Add parse metadata to a per-email pipeline result."""
    email_result["amount"] = parse_result.amount
    email_result["type"] = (
        parse_result.transaction_type.value if parse_result.transaction_type else None
    )
    email_result["merchant_raw"] = parse_result.merchant_raw
    email_result["merchant_source"] = parse_result.merchant_source
    email_result["date"] = str(parse_result.date) if parse_result.date else None
    email_result["confidence"] = parse_result.confidence_score
    email_result["bank"] = parse_result.bank
    email_result["parser_version"] = parse_result.parser_version
    email_result["parser_fallback"] = parse_result.used_fallback


async def _infer_missing_merchant(
    db: AsyncSession,
    email: RawEmail,
    parser_body: str,
    parse_result: ParseResult,
    email_result: dict[str, Any],
) -> str | None:
    """Infer merchant/category when exact parser extraction is missing."""
    if parse_result.merchant_raw and parse_result.merchant_source == "exact":
        return None

    inferred_merchant, inferred_category_id = await infer_merchant_from_text(
        db,
        f"{email.subject or ''} {parser_body}",
    )
    if inferred_merchant:
        parse_result.merchant_raw = inferred_merchant
        parse_result.merchant_source = "inferred"
        parse_result.compute_confidence()
        email_result["merchant_raw"] = inferred_merchant
        email_result["merchant_source"] = "inferred"
        email_result["merchant_inferred"] = True
        email_result["confidence"] = parse_result.confidence_score
    return inferred_category_id


async def _resolve_transaction_category(
    db: AsyncSession,
    parse_result: ParseResult,
    inferred_category_id: str | None,
    default_category_id: str | None,
) -> tuple[str, str | None]:
    """Resolve normalized merchant and category for a parsed transaction."""
    merchant_normalized, category_id = await normalize_merchant(db, parse_result.merchant_raw or "")
    if not category_id and inferred_category_id:
        category_id = inferred_category_id
    if not category_id:
        category_id = default_category_id
    return merchant_normalized, category_id


def _build_transaction_create(
    email: RawEmail,
    parse_result: ParseResult,
    merchant_normalized: str,
    category_id: str | None,
) -> TransactionCreate:
    """Build the transaction create schema from a valid parse result."""
    if parse_result.amount is None or parse_result.transaction_type is None:
        raise ValueError("Cannot build transaction from invalid parse result")
    if parse_result.date is None:
        raise ValueError("Cannot build transaction without a transaction date")

    return TransactionCreate(
        amount=parse_result.amount,
        currency=parse_result.currency,
        transaction_type=TransactionSchemaType(parse_result.transaction_type.value),
        merchant_raw=parse_result.merchant_raw,
        merchant_normalized=merchant_normalized,
        category_id=category_id,
        transaction_date=parse_result.date,
        account_last4=parse_result.account_last4,
        reference_id=parse_result.reference_id,
        confidence_score=parse_result.confidence_score,
        source_email_id=email.id,
    )


async def _record_parse_failure(
    db: AsyncSession,
    email: RawEmail,
    error_message: str,
    parser_version: int,
) -> None:
    result = await db.execute(select(ParseFailure).where(ParseFailure.email_id == email.id))
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
    result = await db.execute(select(ParseFailure).where(ParseFailure.email_id == email_id))
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
    stats: dict[str, Any] = {
        "total_unprocessed": len(emails),
        "parsed_success": 0,
        "parsed_failed": 0,
        "stored": 0,
        "duplicates": 0,
        "low_confidence": 0,
        "fallback_parsed": 0,
        "skipped_non_transaction": 0,
        "results": [],
    }

    if not emails:
        logger.info("No unprocessed emails found")
        return stats

    registry = get_parser_registry()
    txn_service = TransactionService(db)
    default_category_id = await get_default_category_id(db)

    for email in emails:
        email_result: dict[str, Any] = {
            "email_id": email.id,
            "subject": (email.subject or "")[:60],
            "sender": email.sender,
        }

        try:
            parser_body = _prepare_parser_body(email)
            email_type = _classify_pipeline_email(email, parser_body)
            email_result["classification"] = email_type.value

            if email_type in SKIPPABLE_EMAIL_TYPES:
                stats["skipped_non_transaction"] += 1
                email_result["status"] = "skipped_non_transaction"
                await _resolve_parse_failure(db, email.id)
                email.processed_flag = True
                await db.commit()
                stats["results"].append(email_result)
                continue

            parse_result = registry.parse_email(
                sender=email.sender or "",
                subject=email.subject or "",
                body=parser_body,
            )

            _attach_parse_result(email_result, parse_result)

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

            if parse_result.date is None:
                # Genuine bank/wallet alerts always carry a transaction date. An
                # amount without a date is almost always a promo/marketing email
                # misclassified as a transaction. Route it to the parse-failure
                # queue instead of fabricating today() (which surfaces junk as
                # "today's spending").
                stats["parsed_failed"] += 1
                email_result["status"] = "parse_failed"
                await _record_parse_failure(
                    db,
                    email,
                    "Invalid parse: missing transaction date",
                    parse_result.parser_version,
                )
                email.processed_flag = True
                await db.commit()
                stats["results"].append(email_result)
                continue

            inferred_category_id = await _infer_missing_merchant(
                db,
                email,
                parser_body,
                parse_result,
                email_result,
            )

            stats["parsed_success"] += 1
            if parse_result.confidence_score < 0.7:
                stats["low_confidence"] += 1
            if email_result.get("parser_fallback"):
                stats["fallback_parsed"] += 1

            merchant_normalized, category_id = await _resolve_transaction_category(
                db,
                parse_result,
                inferred_category_id,
                default_category_id,
            )

            email_result["merchant_normalized"] = merchant_normalized
            email_result["category_id"] = category_id
            email_result["confidence"] = parse_result.confidence_score

            txn_data = _build_transaction_create(
                email,
                parse_result,
                merchant_normalized,
                category_id,
            )

            try:
                txn = await txn_service.create_transaction(user_id, txn_data)
                stats["stored"] += 1
                email_result["status"] = "stored"
                email_result["transaction_id"] = txn.id
            except DuplicateTransactionError:
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
        f"{stats['fallback_parsed']} fallback, "
        f"{stats['skipped_non_transaction']} skipped, "
        f"{stats['parsed_failed']} failed"
    )
    return stats


async def process_raw_emails(
    db: AsyncSession,
    user_id: str,
    limit: int | None = 50,
) -> dict:
    """
    Process all unprocessed raw emails for a user.
    Pipeline: Parse → Normalize → Categorize → Dedup → Store
    """
    # Fetch unprocessed emails
    query = (
        select(RawEmail)
        .where(RawEmail.user_id == user_id, RawEmail.processed_flag.is_(False))
        .order_by(RawEmail.received_at.asc())
    )
    if limit is not None:
        query = query.limit(limit)

    result = await db.execute(query)
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
        failure.last_retry_at = datetime.now(UTC)
        if failure.email:
            failure.email.processed_flag = False
    await db.commit()

    emails = [failure.email for failure in failures if failure.email is not None]
    stats = await _process_email_batch(db, user_id, emails)
    stats["retried_failures"] = len(failures)
    return stats
