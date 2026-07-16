"""
Processing Pipeline
The core engine: Raw Email → Parse → Normalize → Categorize → Store Transaction

Processes unprocessed raw emails end-to-end.
"""

import json
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Any

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.email import RawEmail
from app.models.sync import ParseFailure, PipelineEvent
from app.schemas.transaction import PaymentMethodEnum, TransactionCreate
from app.schemas.transaction import TransactionTypeEnum as TransactionSchemaType
from app.services.connectors.source_record import SourceType
from app.services.domain_events import DomainEvent, domain_event_dispatcher
from app.services.gmail.email_filter import EmailType, classify_email
from app.services.parser.base_parser import BaseParser, ParseResult
from app.services.parser.confidence import score_parse_result
from app.services.parser.identity import build_identity
from app.services.parser.normalizer import (
    MerchantResolution,
    get_default_category_id,
    infer_merchant_from_text,
    resolve_merchant,
)
from app.services.parser.registry import get_parser_registry
from app.services.parser.validation import (
    ValidationIssue,
    validate_parse_result,
    validation_summary,
)
from app.services.transaction_service import DuplicateTransactionError, TransactionService

logger = logging.getLogger(__name__)
_TEXT_NORMALIZER = BaseParser()
SKIPPABLE_EMAIL_TYPES = {
    EmailType.IGNORE,
    EmailType.OTP,
    EmailType.PROMOTION,
    EmailType.STATEMENT,
}
PIPELINE_EVENT_TYPES = {
    "SourcePrepared",
    "EmailClassified",
    "Parsed",
    "ValidationFailed",
    "Normalized",
    "DuplicateDetected",
    "TransactionCreated",
    "ParseFailed",
    "RetryScheduled",
    "ReplayCompleted",
}


def _safe_json(payload: dict[str, Any] | None) -> str:
    """Serialize non-secret diagnostic payloads consistently."""
    return json.dumps(payload or {}, default=str, sort_keys=True)


def _public_parse_diagnostics(parse_result: ParseResult | None) -> dict[str, Any]:
    if parse_result is None:
        return {}
    return {
        "amount_present": parse_result.amount is not None,
        "type": parse_result.transaction_type.value if parse_result.transaction_type else None,
        "payment_method": parse_result.payment_method,
        "transaction_status": parse_result.transaction_status,
        "transaction_timestamp": (
            parse_result.transaction_timestamp.isoformat()
            if parse_result.transaction_timestamp
            else None
        ),
        "merchant_source": parse_result.merchant_source,
        "date_present": parse_result.date is not None,
        "account_present": parse_result.account_last4 is not None,
        "reference_present": parse_result.reference_id is not None,
        "field_confidence": parse_result.field_confidence,
        "validation_errors": parse_result.validation_errors,
        "fallback": parse_result.used_fallback,
    }


def _record_pipeline_event(
    db: AsyncSession,
    *,
    user_id: str,
    event_type: str,
    stage: str,
    status: str,
    email_id: str | None = None,
    transaction_id: str | None = None,
    parse_result: ParseResult | None = None,
    duration_ms: float | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if event_type not in PIPELINE_EVENT_TYPES:
        logger.warning("Unknown pipeline event type: %s", event_type)
    db.add(
        PipelineEvent(
            user_id=user_id,
            email_id=email_id,
            transaction_id=transaction_id,
            event_type=event_type,
            stage=stage,
            status=status,
            parser_name=parse_result.parser_name if parse_result else None,
            parser_version=parse_result.parser_version if parse_result else None,
            confidence_score=parse_result.confidence_score if parse_result else None,
            duration_ms=duration_ms,
            payload_json=_safe_json(payload),
        )
    )


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
    email_result["payment_method"] = parse_result.payment_method
    email_result["transaction_status"] = parse_result.transaction_status
    email_result["transaction_timestamp"] = (
        parse_result.transaction_timestamp.isoformat()
        if parse_result.transaction_timestamp
        else None
    )
    email_result["merchant_raw"] = parse_result.merchant_raw
    email_result["merchant_source"] = parse_result.merchant_source
    email_result["date"] = str(parse_result.date) if parse_result.date else None
    email_result["confidence"] = parse_result.confidence_score
    email_result["bank"] = parse_result.bank
    email_result["parser_name"] = parse_result.parser_name
    email_result["parser_version"] = parse_result.parser_version
    email_result["pattern_version"] = parse_result.pattern_version
    email_result["confidence_version"] = parse_result.confidence_version
    email_result["normalization_version"] = parse_result.normalization_version
    email_result["parser_fallback"] = parse_result.used_fallback
    email_result["field_confidence"] = parse_result.field_confidence
    email_result["validation_errors"] = parse_result.validation_errors


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
        score_parse_result(parse_result)
        email_result["merchant_raw"] = inferred_merchant
        email_result["merchant_source"] = "inferred"
        email_result["merchant_inferred"] = True
        email_result["confidence"] = parse_result.confidence_score
    return inferred_category_id


def _validate_pipeline_parse(parse_result: ParseResult) -> list[ValidationIssue]:
    """Run validation and keep ParseResult validation metadata aligned."""
    return validate_parse_result(parse_result)


def _legacy_validation_error_message(
    parse_result: ParseResult, validation_issues: list[ValidationIssue]
) -> str:
    issue_codes = {issue.code for issue in validation_issues}
    if issue_codes == {"missing_date"}:
        return "Invalid parse: missing transaction date"
    if {"missing_amount", "invalid_amount", "missing_type"} & issue_codes:
        return f"Invalid parse: amount={parse_result.amount}, type={parse_result.transaction_type}"
    return validation_summary(validation_issues)


async def _resolve_transaction_category(
    db: AsyncSession,
    user_id: str,
    parse_result: ParseResult,
    inferred_category_id: str | None,
    default_category_id: str | None,
) -> MerchantResolution:
    """Resolve normalized merchant and category for a parsed transaction."""
    resolution = await resolve_merchant(db, parse_result.merchant_raw or "", user_id=user_id)
    category_id = resolution.category_id
    if not category_id and inferred_category_id:
        category_id = inferred_category_id
    if not category_id:
        category_id = default_category_id
    return MerchantResolution(
        normalized_name=resolution.normalized_name,
        category_id=category_id,
        source=resolution.source,
        confidence=resolution.confidence,
        rule_id=resolution.rule_id,
        resolver_version=resolution.resolver_version,
    )


def _build_transaction_create(
    email: RawEmail,
    parse_result: ParseResult,
    resolution: MerchantResolution,
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
        payment_method=PaymentMethodEnum(parse_result.payment_method),
        transaction_status=parse_result.transaction_status,
        transaction_timestamp=parse_result.transaction_timestamp,
        merchant_raw=parse_result.merchant_raw,
        merchant_normalized=resolution.normalized_name,
        category_id=resolution.category_id,
        transaction_date=parse_result.date,
        account_last4=parse_result.account_last4,
        reference_id=parse_result.reference_id,
        confidence_score=parse_result.confidence_score,
        parser_version=parse_result.parser_version,
        merchant_resolution_source=resolution.source,
        merchant_resolution_confidence=resolution.confidence,
        merchant_rule_id=resolution.rule_id,
        merchant_resolver_version=resolution.resolver_version,
        source_email_id=email.id,
    )


async def _record_parse_failure(
    db: AsyncSession,
    email: RawEmail,
    error_message: str,
    parser_version: int = 1,
    *,
    failure_stage: str = "parse",
    failure_code: str = "parse_failed",
    parse_result: ParseResult | None = None,
    diagnostic: dict[str, Any] | None = None,
) -> None:
    result = await db.execute(select(ParseFailure).where(ParseFailure.email_id == email.id))
    failure = result.scalar_one_or_none()
    parser_name = parse_result.parser_name if parse_result else None
    pattern_version = parse_result.pattern_version if parse_result else 1
    confidence_version = parse_result.confidence_version if parse_result else 1
    normalization_version = parse_result.normalization_version if parse_result else 1
    diagnostic_payload = {
        **_public_parse_diagnostics(parse_result),
        **(diagnostic or {}),
    }
    if failure is None:
        failure = ParseFailure(
            email_id=email.id,
            error_message=error_message,
            failure_stage=failure_stage,
            failure_code=failure_code,
            parser_name=parser_name,
            parser_version=parser_version,
            pattern_version=pattern_version,
            confidence_version=confidence_version,
            normalization_version=normalization_version,
            diagnostic_json=_safe_json(diagnostic_payload),
            resolved=False,
        )
        db.add(failure)
    else:
        failure.error_message = error_message
        failure.failure_stage = failure_stage
        failure.failure_code = failure_code
        failure.parser_name = parser_name
        failure.parser_version = parser_version
        failure.pattern_version = pattern_version
        failure.confidence_version = confidence_version
        failure.normalization_version = normalization_version
        failure.diagnostic_json = _safe_json(diagnostic_payload)
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
            started_at = perf_counter()
            parser_body = _prepare_parser_body(email)
            _record_pipeline_event(
                db,
                user_id=user_id,
                email_id=email.id,
                event_type="SourcePrepared",
                stage="prepare",
                status="completed",
                payload={
                    "subject_present": bool(email.subject),
                    "sender_present": bool(email.sender),
                    "body_present": bool(parser_body),
                },
            )
            email_type = _classify_pipeline_email(email, parser_body)
            email_result["classification"] = email_type.value
            _record_pipeline_event(
                db,
                user_id=user_id,
                email_id=email.id,
                event_type="EmailClassified",
                stage="classify",
                status="completed",
                payload={"classification": email_type.value},
            )

            if email_type in SKIPPABLE_EMAIL_TYPES:
                stats["skipped_non_transaction"] += 1
                email_result["status"] = "skipped_non_transaction"
                await _resolve_parse_failure(db, email.id)
                email.processed_flag = True
                await db.commit()
                stats["results"].append(email_result)
                continue

            parse_started_at = perf_counter()
            parse_result = registry.parse_email(
                sender=email.sender or "",
                subject=email.subject or "",
                body=parser_body,
            )
            score_parse_result(parse_result)
            parse_duration_ms = round((perf_counter() - parse_started_at) * 1000, 3)

            _attach_parse_result(email_result, parse_result)
            _record_pipeline_event(
                db,
                user_id=user_id,
                email_id=email.id,
                event_type="Parsed",
                stage="parse",
                status="completed",
                parse_result=parse_result,
                duration_ms=parse_duration_ms,
                payload=_public_parse_diagnostics(parse_result),
            )

            validation_issues = _validate_pipeline_parse(parse_result)
            _attach_parse_result(email_result, parse_result)
            if validation_issues:
                stats["parsed_failed"] += 1
                email_result["status"] = "parse_failed"
                email_result["failure_code"] = validation_issues[0].code
                await _record_parse_failure(
                    db,
                    email,
                    _legacy_validation_error_message(parse_result, validation_issues),
                    parse_result.parser_version,
                    failure_stage="validate",
                    failure_code=validation_issues[0].code,
                    parse_result=parse_result,
                    diagnostic={"issue_codes": [issue.code for issue in validation_issues]},
                )
                _record_pipeline_event(
                    db,
                    user_id=user_id,
                    email_id=email.id,
                    event_type="ValidationFailed",
                    stage="validate",
                    status="failed",
                    parse_result=parse_result,
                    payload={"issue_codes": [issue.code for issue in validation_issues]},
                )
                _record_pipeline_event(
                    db,
                    user_id=user_id,
                    email_id=email.id,
                    event_type="ParseFailed",
                    stage="validate",
                    status="failed",
                    parse_result=parse_result,
                    payload={"failure_code": validation_issues[0].code},
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

            resolution = await _resolve_transaction_category(
                db,
                user_id,
                parse_result,
                inferred_category_id,
                default_category_id,
            )
            merchant_normalized = resolution.normalized_name
            category_id = resolution.category_id

            email_result["merchant_normalized"] = merchant_normalized
            email_result["category_id"] = category_id
            email_result["merchant_resolution_source"] = resolution.source
            email_result["merchant_resolution_confidence"] = resolution.confidence
            email_result["confidence"] = parse_result.confidence_score
            identity = build_identity(
                user_id=user_id,
                amount=parse_result.amount or 0,
                transaction_date=parse_result.date,
                merchant=merchant_normalized or parse_result.merchant_raw,
                reference_id=parse_result.reference_id,
                account_last4=parse_result.account_last4,
            )
            email_result["identity_level"] = identity.level
            _record_pipeline_event(
                db,
                user_id=user_id,
                email_id=email.id,
                event_type="Normalized",
                stage="normalize",
                status="completed",
                parse_result=parse_result,
                payload={
                    "merchant_present": bool(merchant_normalized),
                    "category_present": bool(category_id),
                    "identity_level": identity.level,
                    "reference_present": bool(identity.reference_key),
                    "fuzzy_ready": bool(identity.fuzzy_key),
                    "merchant_resolution_source": resolution.source,
                    "merchant_resolution_confidence": resolution.confidence,
                    "merchant_resolver_version": resolution.resolver_version,
                },
            )

            txn_data = _build_transaction_create(
                email,
                parse_result,
                resolution,
            )

            try:
                txn = await txn_service.create_transaction(user_id, txn_data)
                stats["stored"] += 1
                email_result["status"] = "stored"
                email_result["transaction_id"] = txn.id
                _record_pipeline_event(
                    db,
                    user_id=user_id,
                    email_id=email.id,
                    transaction_id=txn.id,
                    event_type="TransactionCreated",
                    stage="persist",
                    status="completed",
                    parse_result=parse_result,
                    duration_ms=round((perf_counter() - started_at) * 1000, 3),
                    payload={"identity_level": identity.level},
                )
                await domain_event_dispatcher.publish(
                    DomainEvent(
                        "TransactionCreated",
                        user_id,
                        SourceType.GMAIL,
                        {"transaction_id": txn.id, "source_email_id": email.id},
                    )
                )
            except DuplicateTransactionError:
                stats["duplicates"] += 1
                email_result["status"] = "duplicate"
                _record_pipeline_event(
                    db,
                    user_id=user_id,
                    email_id=email.id,
                    event_type="DuplicateDetected",
                    stage="identity",
                    status="duplicate",
                    parse_result=parse_result,
                    payload={"identity_level": identity.level},
                )

            await _resolve_parse_failure(db, email.id)
            email.processed_flag = True
            await db.commit()

        except Exception as e:
            stats["parsed_failed"] += 1
            email_result["status"] = "error"
            email_result["error"] = str(e)
            logger.error(f"Pipeline error for email {email.id}: {e}")

            await _record_parse_failure(
                db,
                email,
                str(e),
                parser_version=1,
                failure_stage="pipeline",
                failure_code="unexpected_error",
                diagnostic={"error_type": type(e).__name__},
            )
            _record_pipeline_event(
                db,
                user_id=user_id,
                email_id=email.id,
                event_type="ParseFailed",
                stage="pipeline",
                status="error",
                payload={"error_type": type(e).__name__},
            )
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


async def get_pipeline_metrics(
    db: AsyncSession,
    user_id: str,
    month: int | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """Return non-secret operational metrics for parser pipeline health."""
    query = select(PipelineEvent).where(PipelineEvent.user_id == user_id)
    if month and year:
        query = query.where(
            extract("month", PipelineEvent.created_at) == month,
            extract("year", PipelineEvent.created_at) == year,
        )
    result = await db.execute(query)
    events = list(result.scalars().all())

    parsed_events = [event for event in events if event.event_type == "Parsed"]
    created_events = [event for event in events if event.event_type == "TransactionCreated"]
    failed_events = [
        event for event in events if event.event_type in {"ParseFailed", "ValidationFailed"}
    ]
    duplicate_events = [event for event in events if event.event_type == "DuplicateDetected"]
    fallback_events = [
        event
        for event in parsed_events
        if _loads_payload(event.payload_json).get("fallback") is True
    ]
    unknown_merchant_events = [
        event
        for event in parsed_events
        if _loads_payload(event.payload_json).get("merchant_source") in {None, "missing", "generic"}
    ]

    failure_query = (
        select(func.count(ParseFailure.id))
        .join(RawEmail, ParseFailure.email_id == RawEmail.id)
        .where(RawEmail.user_id == user_id, ParseFailure.resolved.is_(False))
    )
    dlq_size = int((await db.execute(failure_query)).scalar() or 0)

    retry_query = (
        select(func.coalesce(func.sum(ParseFailure.retry_count), 0))
        .join(RawEmail, ParseFailure.email_id == RawEmail.id)
        .where(RawEmail.user_id == user_id)
    )
    retry_count = int((await db.execute(retry_query)).scalar() or 0)

    attempted_email_ids = {
        event.email_id for event in [*parsed_events, *failed_events] if event.email_id is not None
    }
    parse_attempts = len(attempted_email_ids) or len(parsed_events) + len(failed_events)
    confidence_values = [
        event.confidence_score for event in parsed_events if event.confidence_score is not None
    ]
    duration_values = [
        event.duration_ms for event in parsed_events if event.duration_ms is not None
    ]

    return {
        "user_id": user_id,
        "month": month,
        "year": year,
        "parse_attempts": parse_attempts,
        "parsed_count": len(parsed_events),
        "transaction_created_count": len(created_events),
        "parse_success_rate": _pct(len(created_events), max(parse_attempts, 1)),
        "average_confidence": (
            round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else 0.0
        ),
        "fallback_rate": _pct(len(fallback_events), max(len(parsed_events), 1)),
        "unknown_merchant_rate": _pct(len(unknown_merchant_events), max(len(parsed_events), 1)),
        "duplicate_rate": _pct(len(duplicate_events), max(parse_attempts, 1)),
        "retry_count": retry_count,
        "dlq_size": dlq_size,
        "average_parse_time_ms": (
            round(sum(duration_values) / len(duration_values), 3) if duration_values else 0.0
        ),
    }


async def list_parse_failures(
    db: AsyncSession,
    user_id: str,
    resolved: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    query = (
        select(ParseFailure)
        .options(selectinload(ParseFailure.email).selectinload(RawEmail.transaction))
        .join(RawEmail, ParseFailure.email_id == RawEmail.id)
        .where(RawEmail.user_id == user_id)
        .order_by(
            ParseFailure.resolved.asc(),
            ParseFailure.last_retry_at.desc().nullslast(),
            ParseFailure.id.asc(),
        )
    )
    count_query = (
        select(func.count(ParseFailure.id))
        .join(RawEmail, ParseFailure.email_id == RawEmail.id)
        .where(RawEmail.user_id == user_id)
    )
    if resolved is not None:
        query = query.where(ParseFailure.resolved.is_(resolved))
        count_query = count_query.where(ParseFailure.resolved.is_(resolved))

    total = int((await db.execute(count_query)).scalar() or 0)
    result = await db.execute(query.limit(limit).offset(offset))
    failures = list(result.scalars().all())
    return {
        "total": total,
        "failures": [_serialize_parse_failure(failure) for failure in failures],
    }


async def retry_parse_failure_by_id(
    db: AsyncSession,
    user_id: str,
    failure_id: str,
) -> dict[str, Any] | None:
    result = await db.execute(
        select(ParseFailure)
        .options(selectinload(ParseFailure.email))
        .join(RawEmail, ParseFailure.email_id == RawEmail.id)
        .where(ParseFailure.id == failure_id, RawEmail.user_id == user_id)
    )
    failure = result.scalar_one_or_none()
    if failure is None:
        return None

    failure.retry_count += 1
    failure.last_retry_at = datetime.now(UTC)
    if failure.email:
        failure.email.processed_flag = False
    _record_pipeline_event(
        db,
        user_id=user_id,
        email_id=failure.email_id,
        event_type="RetryScheduled",
        stage="retry",
        status="queued",
        payload={"failure_id": failure.id, "retry_count": failure.retry_count},
    )
    await db.commit()
    stats = await _process_email_batch(db, user_id, [failure.email] if failure.email else [])
    stats["failure_id"] = failure_id
    return stats


async def reprocess_raw_emails(
    db: AsyncSession,
    user_id: str,
    *,
    email_ids: list[str] | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    dry_run: bool = True,
    limit: int = 100,
) -> dict[str, Any]:
    """Replay retained raw emails and optionally compare without mutation."""
    query = (
        select(RawEmail)
        .options(selectinload(RawEmail.transaction))
        .where(RawEmail.user_id == user_id)
        .order_by(RawEmail.received_at.desc().nullslast(), RawEmail.created_at.desc())
        .limit(limit)
    )
    if email_ids:
        query = query.where(RawEmail.id.in_(email_ids))
    if from_date:
        query = query.where(func.date(RawEmail.received_at) >= from_date)
    if to_date:
        query = query.where(func.date(RawEmail.received_at) <= to_date)

    result = await db.execute(query)
    emails = list(result.scalars().all())

    if dry_run:
        registry = get_parser_registry()
        comparisons = []
        for email in emails:
            parser_body = _normalize_email_body(email.body or "") or (email.body or "")
            parse_started_at = perf_counter()
            parse_result = registry.parse_email(
                email.sender or "", email.subject or "", parser_body
            )
            score_parse_result(parse_result)
            issues = validate_parse_result(parse_result)
            comparisons.append(
                {
                    "email_id": email.id,
                    "subject": (email.subject or "")[:80],
                    "existing_transaction_id": email.transaction.id if email.transaction else None,
                    "new_result": {
                        "amount": parse_result.amount,
                        "type": (
                            parse_result.transaction_type.value
                            if parse_result.transaction_type
                            else None
                        ),
                        "merchant_raw": parse_result.merchant_raw,
                        "date": str(parse_result.date) if parse_result.date else None,
                        "confidence": parse_result.confidence_score,
                        "field_confidence": parse_result.field_confidence,
                        "validation_errors": [issue.code for issue in issues],
                        "parser_name": parse_result.parser_name,
                        "parser_version": parse_result.parser_version,
                    },
                    "duration_ms": round((perf_counter() - parse_started_at) * 1000, 3),
                }
            )
        _record_pipeline_event(
            db,
            user_id=user_id,
            event_type="ReplayCompleted",
            stage="replay",
            status="dry_run",
            payload={"email_count": len(emails), "dry_run": True},
        )
        await db.commit()
        return {"dry_run": True, "email_count": len(emails), "comparisons": comparisons}

    for email in emails:
        email.processed_flag = False
    await db.commit()
    stats = await _process_email_batch(db, user_id, emails)
    _record_pipeline_event(
        db,
        user_id=user_id,
        event_type="ReplayCompleted",
        stage="replay",
        status="completed",
        payload={"email_count": len(emails), "dry_run": False},
    )
    await db.commit()
    return {"dry_run": False, "email_count": len(emails), "stats": stats}


def _serialize_parse_failure(failure: ParseFailure) -> dict[str, Any]:
    email = failure.email
    transaction = email.transaction if email else None
    return {
        "id": failure.id,
        "email_id": failure.email_id,
        "subject": (email.subject or "")[:120] if email else None,
        "sender": email.sender if email else None,
        "received_at": email.received_at if email else None,
        "transaction_id": transaction.id if transaction else None,
        "error_message": failure.error_message,
        "failure_stage": failure.failure_stage,
        "failure_code": failure.failure_code,
        "parser_name": failure.parser_name,
        "parser_version": failure.parser_version,
        "pattern_version": failure.pattern_version,
        "confidence_version": failure.confidence_version,
        "normalization_version": failure.normalization_version,
        "diagnostic": _loads_payload(failure.diagnostic_json),
        "retry_count": failure.retry_count,
        "last_retry_at": failure.last_retry_at,
        "resolved": failure.resolved,
    }


def _loads_payload(payload_json: str | None) -> dict[str, Any]:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0
