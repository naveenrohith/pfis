"""Health and lightweight operational visibility routes."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.sync import ConnectorAuditEvent, ParseFailure, SyncRun, SyncStatus
from app.services.job_service import get_active_task_count, get_job_status_counts

router = APIRouter(tags=["Health"])
settings = get_settings()


@router.get("/health")
async def health_check():
    """System health check."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/health/ops")
async def operational_health(db: AsyncSession = Depends(get_db)):
    """Return non-secret operational state for local and deployment checks."""
    database_profile = "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "server"
    sync_metrics = await _sync_metrics(db)
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "auth_required": settings.AUTH_REQUIRED,
        "database_profile": database_profile,
        "jobs": {
            "active_in_process": get_active_task_count(),
            "persisted_by_status": await get_job_status_counts(db),
        },
        "sync": sync_metrics,
    }


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
    return {
        "runs": int(run_count or 0),
        "failed_runs": int(failed_runs.scalar() or 0),
        "emails_fetched": int(fetched or 0),
        "emails_stored": int(processed or 0),
        "emails_failed": int(failed or 0),
        "duplicate_rate": None,
        "parse_failures_open": int(parse_failures.scalar() or 0),
        "oauth_failures": events.get("token_refresh_failed", 0),
        "gmail_api_failures": events.get("sync_failed", 0),
        "audit_events": events,
    }
