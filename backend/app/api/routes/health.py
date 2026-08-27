"""Health, readiness, and lightweight operational visibility routes."""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.financial_position import StatementImport
from app.models.sync import (
    ConnectorAuditEvent,
    ParseFailure,
    PipelineEvent,
    SyncRun,
    SyncStatus,
)
from app.models.transaction import Transaction
from app.observability import request_metrics
from app.schemas.operational import (
    ProductCapabilitiesResponse,
    ProductCapabilitySource,
    ProductRecoveryPath,
)
from app.services.job_service import get_active_task_count, get_job_status_counts
from app.services.ledger_currency import ledger_currency_health

router = APIRouter(tags=["Health"])
settings = get_settings()
logger = logging.getLogger(__name__)
QUALITY_WINDOW_DAYS = 30
DRIFT_WINDOW_DAYS = 7
DRIFT_MIN_SAMPLES = 20
DRIFT_FAILURE_RATE_DELTA = 0.10
DRIFT_FALLBACK_RATE_DELTA = 0.20
STATEMENT_DRIFT_MIN_ATTEMPTS = 20
STATEMENT_LAYOUT_REJECTION_RATE = 0.25
STATEMENT_LAYOUT_REJECTION_CODES = frozenset(
    {"unsupported_layout", "missing_billing_period", "validation_failed"}
)


@router.get("/health")
async def health_check():
    """Process liveness check; intentionally does not depend on downstream services."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Report whether the application can execute database-backed requests."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database is not ready") from exc
    return {"status": "ready", "database": "reachable"}


@router.get("/health/metrics")
async def operational_metrics():
    """Return bounded, privacy-safe process metrics for deployment monitoring."""

    return {
        "status": "available",
        "metrics_scope": "process",
        "privacy": "No query strings, user identifiers, source content, or request bodies are retained.",
        "metrics": request_metrics.snapshot(),
    }


@router.get("/health/capabilities", response_model=ProductCapabilitiesResponse)
async def product_capabilities() -> ProductCapabilitiesResponse:
    """Publish the supported-source boundary and user recovery paths.

    This contract is intentionally static and non-secret. It prevents the UI
    from implying broad bank or operational support that has not been proved by
    a release cohort or hosted incident system.
    """

    return ProductCapabilitiesResponse(
        incident_message=(
            "No hosted incident feed is configured for this deployment. Check Data & settings "
            "for source and parser recovery actions."
        ),
        sources=[
            ProductCapabilitySource(
                key="gmail_transaction_alerts",
                label="Gmail transaction alerts",
                status="beta",
                scope="Read-only Gmail ingestion for supported transaction-alert layouts.",
                freshness="Current after the latest completed sync and pipeline run.",
                limitations=[
                    "Gmail is the only live connector in this release.",
                    "Institution and card-specific layouts remain cohort-limited.",
                ],
            ),
            ProductCapabilitySource(
                key="hdfc_digital_statement",
                label="HDFC digital statement",
                status="beta",
                scope=(
                    "Reviewed HDFC credit-card and exact-profile deposit-account digital "
                    "statement layouts."
                ),
                freshness="Imported rows are visible after statement reconciliation or review.",
                limitations=[
                    "Encrypted, scanned, and unsupported layouts are rejected without retention.",
                    "Deposit support is limited to one reviewed, arithmetically reconciled profile.",
                    "Other statement institutions are not represented as supported formats.",
                ],
            ),
            ProductCapabilitySource(
                key="generic_email_fallback",
                label="Other financial emails",
                status="best_effort",
                scope="Deterministic generic parsing with review when evidence is incomplete.",
                freshness="Only parsed and reviewed rows contribute to financial read models.",
                limitations=[
                    "Fallback parsing is not proof of institution-wide accuracy.",
                    "Unknown merchants and uncertain fields stay visible for correction.",
                ],
            ),
            ProductCapabilitySource(
                key="connected_bank_card_balances",
                label="Connected bank and card balances",
                status="deferred",
                scope="Provider-neutral balance observation and freshness contracts are ready; no institution provider is configured in this release.",
                freshness="Unknown until a consented provider refresh returns an observed balance.",
                limitations=[
                    "Transaction roll-forward and statement imports remain estimated or observed source facts, never live institution balances.",
                    "A regulated Account Aggregator or equivalent provider decision, consent flow, account mapping, and refresh operations are still required.",
                    "Available credit is not inferred from credit limit minus estimated outstanding.",
                ],
            ),
        ],
        recovery_paths=[
            ProductRecoveryPath(
                code="connector_expired",
                label="Reconnect Gmail",
                target="inbox",
                description="Renew read-only access when a connector is paused or revoked.",
            ),
            ProductRecoveryPath(
                code="parse_failure",
                label="Retry or replay safely",
                target="pipeline",
                description="Retry one failed item or run a dry-run replay before changing rows.",
            ),
            ProductRecoveryPath(
                code="stale_data",
                label="Sync and inspect freshness",
                target="inbox",
                description="Run a sync, then confirm the last completed run before acting on totals.",
            ),
            ProductRecoveryPath(
                code="conflicting_evidence",
                label="Resolve evidence",
                target="review",
                description="Review uncertain or conflicting records before accepting a plan.",
            ),
            ProductRecoveryPath(
                code="portable_copy",
                label="Export a portable copy",
                target="settings",
                description="Download the versioned evidence archive before destructive changes.",
            ),
        ],
    )


@router.get("/health/ops")
async def operational_health(db: AsyncSession = Depends(get_db)):
    """Return non-secret operational state for local and deployment checks."""
    sync_metrics = await _sync_metrics(db)
    quality_metrics = await _quality_metrics(db)
    sync_metrics["duplicate_rate"] = quality_metrics["duplicate_rate"]
    job_statuses = await get_job_status_counts(db)
    ledger_health = await ledger_currency_health(db)
    status, status_reasons, data_warnings = _operational_status(
        sync_metrics=sync_metrics,
        quality_metrics=quality_metrics,
        job_statuses=job_statuses,
        ledger_health=ledger_health,
    )
    return {
        "status": status,
        "status_reasons": status_reasons,
        "data_warnings": data_warnings,
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "auth_required": settings.AUTH_REQUIRED,
        "database_profile": "postgresql",
        "jobs": {
            "active_in_process": get_active_task_count(),
            "persisted_by_status": job_statuses,
        },
        "ledger_currency": ledger_health,
        "sync": sync_metrics,
        "data_quality": quality_metrics,
    }


def _operational_status(
    *,
    sync_metrics: dict,
    quality_metrics: dict,
    job_statuses: dict[str, int],
    ledger_health: dict,
) -> tuple[str, list[str], list[str]]:
    """Derive a safe service status without hiding data-quality warnings.

    Historical failed syncs and intentionally capped provider queries are useful
    evidence, but they should not make a live process look unavailable. Only
    unresolved integrity/parser/job conditions affect the service status; source
    completeness is reported separately as a data warning.
    """

    status_reasons: list[str] = []
    data_warnings: list[str] = []
    if ledger_health.get("status") != "healthy":
        status_reasons.append("ledger_currency_needs_repair")
    if int(quality_metrics.get("parse_failures_open", 0)) > 0:
        status_reasons.append("unresolved_parse_failures")
    if quality_metrics.get("source_drift", {}).get("alert_sources"):
        status_reasons.append("parser_source_drift")
    if quality_metrics.get("statement_quality", {}).get("status") == "alert":
        status_reasons.append("statement_layout_drift")
    if int(job_statuses.get("failed", 0)) > 0:
        status_reasons.append("failed_background_jobs")

    coverage = sync_metrics.get("coverage", {})
    if int(coverage.get("incomplete_runs", 0)) > 0:
        data_warnings.append("provider_query_coverage_is_partial")
    if coverage.get("latest_truncated") is True:
        data_warnings.append("latest_provider_query_was_capped")
    if int(sync_metrics.get("failed_runs", 0)) > 0:
        data_warnings.append("historical_sync_runs_failed")

    if ledger_health.get("status") == "needs_repair":
        status = "needs_repair"
    elif status_reasons:
        status = "degraded"
    else:
        status = "healthy"
    return status, status_reasons, data_warnings


async def _sync_metrics(db: AsyncSession) -> dict:
    totals = await db.execute(
        select(
            func.count(SyncRun.id),
            func.coalesce(func.sum(SyncRun.emails_fetched), 0),
            func.coalesce(func.sum(SyncRun.emails_processed), 0),
            func.coalesce(func.sum(SyncRun.emails_failed), 0),
        )
    )
    run_count, fetched, processed, failed = totals.one()

    failed_runs = await db.execute(
        select(func.count(SyncRun.id)).where(SyncRun.status == SyncStatus.FAILED)
    )
    parse_failures = await db.execute(
        select(func.count(ParseFailure.id)).where(ParseFailure.resolved.is_(False))
    )
    audit_counts = await db.execute(
        select(ConnectorAuditEvent.event_type, func.count(ConnectorAuditEvent.id)).group_by(
            ConnectorAuditEvent.event_type
        )
    )
    events = {event_type: int(count) for event_type, count in audit_counts.all()}
    incomplete_coverage_runs = await db.scalar(
        select(func.count(SyncRun.id)).where(
            SyncRun.status == SyncStatus.COMPLETED,
            SyncRun.coverage_complete.is_(False),
        )
    )
    latest_completed = await db.scalar(
        select(SyncRun)
        .where(SyncRun.status == SyncStatus.COMPLETED)
        .order_by(SyncRun.end_time.desc())
        .limit(1)
    )
    return {
        "runs": int(run_count or 0),
        "failed_runs": int(failed_runs.scalar() or 0),
        "emails_fetched": int(fetched or 0),
        "emails_stored": int(processed or 0),
        "emails_failed": int(failed or 0),
        "duplicate_rate": 0.0,
        "parse_failures_open": int(parse_failures.scalar() or 0),
        "oauth_failures": events.get("token_refresh_failed", 0),
        "gmail_api_failures": events.get("sync_failed", 0),
        "audit_events": events,
        "coverage": {
            "incomplete_runs": int(incomplete_coverage_runs or 0),
            "latest_complete": (
                latest_completed.coverage_complete if latest_completed is not None else None
            ),
            "latest_truncated": (
                latest_completed.coverage_truncated if latest_completed is not None else None
            ),
            "latest_result_size_estimate": (
                latest_completed.coverage_result_size_estimate
                if latest_completed is not None
                else 0
            ),
        },
    }


async def _quality_metrics(db: AsyncSession) -> dict:
    """Aggregate privacy-safe parser and review signals for drift monitoring."""
    instant = datetime.now(UTC)
    window_started_at = instant - timedelta(days=QUALITY_WINDOW_DAYS)
    audit_rows = list(
        await db.scalars(
            select(ConnectorAuditEvent).where(
                ConnectorAuditEvent.event_type == "sync_completed",
                ConnectorAuditEvent.created_at >= window_started_at,
            )
        )
    )
    fetched = 0
    duplicates = 0
    for audit_event in audit_rows:
        payload = _safe_payload(audit_event.payload_json)
        fetched += _non_negative_int(payload.get("emails_fetched"))
        duplicates += _non_negative_int(payload.get("emails_skipped_duplicate"))

    event_counts_result = await db.execute(
        select(PipelineEvent.event_type, func.count(PipelineEvent.id))
        .where(
            PipelineEvent.created_at >= window_started_at,
            PipelineEvent.event_type.in_({"Parsed", "ParseFailed", "DuplicateDetected"}),
        )
        .group_by(PipelineEvent.event_type)
    )
    event_counts = {event_type: int(count) for event_type, count in event_counts_result.all()}
    parsed_count = event_counts.get("Parsed", 0)
    failed_count = event_counts.get("ParseFailed", 0)
    fallback_count = int(
        await db.scalar(
            select(func.count(PipelineEvent.id)).where(
                PipelineEvent.created_at >= window_started_at,
                PipelineEvent.event_type == "Parsed",
                PipelineEvent.payload_json.like('%"fallback": true%'),
            )
        )
        or 0
    )
    parser_version_rows = await db.execute(
        select(
            PipelineEvent.parser_name,
            PipelineEvent.parser_version,
            func.count(PipelineEvent.id),
        )
        .where(
            PipelineEvent.created_at >= window_started_at,
            PipelineEvent.event_type == "Parsed",
        )
        .group_by(PipelineEvent.parser_name, PipelineEvent.parser_version)
    )
    parser_versions = {
        f"{parser_name or 'unknown'}:v{parser_version or 0}": int(count)
        for parser_name, parser_version, count in parser_version_rows.all()
    }

    transaction_counts = await db.execute(
        select(
            func.count(Transaction.id),
            func.coalesce(
                func.sum(case((Transaction.reviewed_flag.is_(False), 1), else_=0)),
                0,
            ),
        ).where(
            Transaction.source_kind != "manual",
            Transaction.created_at >= window_started_at,
        )
    )
    imported_transactions, pending_review = transaction_counts.one()
    imported_count = int(imported_transactions or 0)
    pending_count = int(pending_review or 0)
    parse_attempts = max(parsed_count, failed_count)
    source_drift = await _source_drift_metrics(db, instant)
    statement_quality = await _statement_quality_metrics(db, window_started_at)

    return {
        "window_days": QUALITY_WINDOW_DAYS,
        "sync_runs_observed": len(audit_rows),
        "ingestion_records_observed": fetched,
        "duplicate_count": duplicates,
        "duplicate_rate": _ratio(duplicates, fetched),
        "parse_attempts": parse_attempts,
        "parse_failure_count": failed_count,
        "parse_failure_rate": _ratio(failed_count, parse_attempts),
        "fallback_count": fallback_count,
        "fallback_rate": _ratio(fallback_count, parsed_count),
        "imported_transactions": imported_count,
        "pending_review_count": pending_count,
        "pending_review_rate": _ratio(pending_count, imported_count),
        "parser_versions": dict(sorted(parser_versions.items())),
        "source_drift": source_drift,
        "statement_quality": statement_quality,
    }


async def _statement_quality_metrics(db: AsyncSession, started_at: datetime) -> dict:
    """Aggregate statement-layout outcomes without retaining uploaded content."""

    imports = await db.execute(
        select(
            StatementImport.issuer,
            StatementImport.extractor_version,
            func.count(StatementImport.id),
        )
        .where(StatementImport.created_at >= started_at)
        .group_by(StatementImport.issuer, StatementImport.extractor_version)
    )
    imported_count = 0
    issuers: dict[str, dict[str, object]] = {}
    for issuer, extractor_version, count in imports.all():
        issuer_key = str(issuer)
        issuer_metrics = issuers.setdefault(
            issuer_key,
            {"imported": 0, "extractor_versions": {}},
        )
        imported = int(count or 0)
        imported_count += imported
        previous_imported = issuer_metrics.get("imported", 0)
        issuer_metrics["imported"] = (
            previous_imported + imported if isinstance(previous_imported, int) else imported
        )
        versions = cast(dict[str, int], issuer_metrics["extractor_versions"])
        version_key = str(extractor_version or "unknown")
        versions[version_key] = versions.get(version_key, 0) + imported

    rejection_rows = await db.scalars(
        select(ConnectorAuditEvent.payload_json).where(
            ConnectorAuditEvent.connector_type == "statement",
            ConnectorAuditEvent.event_type == "statement_import_rejected",
            ConnectorAuditEvent.created_at >= started_at,
        )
    )
    rejected_count = 0
    layout_rejected_count = 0
    rejection_reasons: dict[str, int] = {}
    for payload_json in rejection_rows.all():
        rejected_count += 1
        reason = _safe_payload(payload_json).get("reason_code", "unknown")
        reason_key = reason if isinstance(reason, str) and reason else "unknown"
        rejection_reasons[reason_key] = rejection_reasons.get(reason_key, 0) + 1
        if reason_key in STATEMENT_LAYOUT_REJECTION_CODES:
            layout_rejected_count += 1

    attempts = imported_count + rejected_count
    layout_rejection_rate = _ratio(layout_rejected_count, attempts)
    status = (
        "insufficient_history"
        if attempts < STATEMENT_DRIFT_MIN_ATTEMPTS
        else ("alert" if layout_rejection_rate >= STATEMENT_LAYOUT_REJECTION_RATE else "stable")
    )
    return {
        "window_days": QUALITY_WINDOW_DAYS,
        "attempts": attempts,
        "imported": imported_count,
        "rejected": rejected_count,
        "rejection_rate": _ratio(rejected_count, attempts),
        "layout_rejected": layout_rejected_count,
        "layout_rejection_rate": layout_rejection_rate,
        "status": status,
        "minimum_attempts": STATEMENT_DRIFT_MIN_ATTEMPTS,
        "layout_rejection_rate_threshold": STATEMENT_LAYOUT_REJECTION_RATE,
        "issuers": dict(sorted(issuers.items())),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
    }


async def _source_drift_metrics(db: AsyncSession, instant: datetime) -> dict:
    current_start = instant - timedelta(days=DRIFT_WINDOW_DAYS)
    previous_start = current_start - timedelta(days=DRIFT_WINDOW_DAYS)
    current = await _source_window_metrics(db, current_start, instant)
    previous = await _source_window_metrics(db, previous_start, current_start)

    sources = {}
    alerts = []
    for institution in sorted(set(current) | set(previous)):
        current_counts = current.get(institution, _empty_source_counts())
        previous_counts = previous.get(institution, _empty_source_counts())
        current_samples = max(current_counts["parsed"], current_counts["failed"])
        previous_samples = max(previous_counts["parsed"], previous_counts["failed"])
        current_failure_rate = _ratio(current_counts["failed"], current_samples)
        previous_failure_rate = _ratio(previous_counts["failed"], previous_samples)
        current_fallback_rate = _ratio(current_counts["fallback"], current_counts["parsed"])
        previous_fallback_rate = _ratio(previous_counts["fallback"], previous_counts["parsed"])
        failure_delta = round(current_failure_rate - previous_failure_rate, 4)
        fallback_delta = round(current_fallback_rate - previous_fallback_rate, 4)
        signals = []
        if current_samples >= DRIFT_MIN_SAMPLES and previous_samples >= DRIFT_MIN_SAMPLES:
            if failure_delta >= DRIFT_FAILURE_RATE_DELTA:
                signals.append("parse_failure_rate_increased")
            if fallback_delta >= DRIFT_FALLBACK_RATE_DELTA:
                signals.append("fallback_rate_increased")
            status = "alert" if signals else "stable"
        else:
            status = "insufficient_history"
        if status == "alert":
            alerts.append(institution)
        sources[institution] = {
            "status": status,
            "signals": signals,
            "current_samples": current_samples,
            "previous_samples": previous_samples,
            "current_failure_rate": current_failure_rate,
            "previous_failure_rate": previous_failure_rate,
            "failure_rate_delta": failure_delta,
            "current_fallback_rate": current_fallback_rate,
            "previous_fallback_rate": previous_fallback_rate,
            "fallback_rate_delta": fallback_delta,
            "parser_versions": dict(sorted(current_counts["parser_versions"].items())),
        }
    return {
        "window_days": DRIFT_WINDOW_DAYS,
        "minimum_samples_per_window": DRIFT_MIN_SAMPLES,
        "failure_rate_delta_threshold": DRIFT_FAILURE_RATE_DELTA,
        "fallback_rate_delta_threshold": DRIFT_FALLBACK_RATE_DELTA,
        "alert_sources": alerts,
        "sources": sources,
    }


async def _source_window_metrics(
    db: AsyncSession,
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, dict]:
    rows = await db.execute(
        select(
            PipelineEvent.source_institution,
            PipelineEvent.event_type,
            PipelineEvent.parser_name,
            PipelineEvent.parser_version,
            func.count(PipelineEvent.id),
        )
        .where(
            PipelineEvent.created_at >= started_at,
            PipelineEvent.created_at < ended_at,
            PipelineEvent.source_institution.is_not(None),
            PipelineEvent.event_type.in_({"Parsed", "ParseFailed"}),
        )
        .group_by(
            PipelineEvent.source_institution,
            PipelineEvent.event_type,
            PipelineEvent.parser_name,
            PipelineEvent.parser_version,
        )
    )
    metrics: dict[str, dict] = {}
    for institution, event_type, parser_name, parser_version, count in rows.all():
        source = metrics.setdefault(str(institution), _empty_source_counts())
        event_count = int(count)
        if event_type == "Parsed":
            source["parsed"] += event_count
            if parser_name == "GenericParser":
                source["fallback"] += event_count
            parser_key = f"{parser_name or 'unknown'}:v{parser_version or 0}"
            source["parser_versions"][parser_key] = (
                source["parser_versions"].get(parser_key, 0) + event_count
            )
        elif event_type == "ParseFailed":
            source["failed"] += event_count
    return metrics


def _empty_source_counts() -> dict:
    return {"parsed": 0, "failed": 0, "fallback": 0, "parser_versions": {}}


def _safe_payload(payload_json: str) -> dict:
    try:
        payload = json.loads(payload_json or "{}")
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _non_negative_int(value: object) -> int:
    if not isinstance(value, str | int | float):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
