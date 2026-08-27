"""Durable database-backed background job orchestration for PFIS."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from google.auth.exceptions import RefreshError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.email import GmailAccount
from app.models.sync import BackgroundJob, JobStatus
from app.models.user import User
from app.services.balance_provider_connection_service import BalanceProviderConnectionService
from app.services.balance_sync_service import BalanceSyncService
from app.services.connectors.balance_registry import balance_connector_registry
from app.services.connectors.errors import classify_connector_exception
from app.services.gmail.sync_service import demo_sync_gmail_emails, sync_gmail_emails
from app.services.parser.pipeline import process_raw_emails, retry_parse_failures
from app.services.retention_service import redact_expired_raw_email_content
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)
_active_tasks: set[asyncio.Task] = set()
_active_user_tasks: dict[str, set[asyncio.Task]] = {}
_worker_task: asyncio.Task | None = None
_worker_wakeup: asyncio.Event | None = None
_worker_id = uuid.uuid4().hex
_worker_poll_seconds = 2
_lease_seconds = 300
_worker_concurrency = 4


def serialize_job(job: BackgroundJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "job_type": job.job_type,
        "status": job.status.value,
        "payload": json.loads(job.payload_json or "{}"),
        "result": json.loads(job.result_json or "{}"),
        "error_message": job.error_message,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def get_active_task_count() -> int:
    """Return the number of in-process job tasks currently tracked."""
    return len(_active_tasks)


async def stop_user_jobs(user_id: str) -> int:
    """Cancel in-process jobs so deletion cannot race a late write."""
    current = asyncio.current_task()
    tasks = [
        task
        for task in _active_user_tasks.get(user_id, set())
        if task is not current and not task.done()
    ]
    if not tasks:
        return 0
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    return len(tasks)


async def get_job_status_counts(db: AsyncSession) -> dict[str, int]:
    """Return persisted background job counts by status."""
    result = await db.execute(
        select(BackgroundJob.status, func.count(BackgroundJob.id)).group_by(BackgroundJob.status)
    )
    counts = {status.value: int(count) for status, count in result.all()}
    return {status.value: counts.get(status.value, 0) for status in JobStatus}


async def recover_interrupted_jobs(db: AsyncSession) -> int:
    """Requeue interrupted work while leaving already queued jobs durable."""
    result = await db.execute(
        select(BackgroundJob).where(BackgroundJob.status == JobStatus.RUNNING)
    )
    jobs = result.scalars().all()
    if not jobs:
        return 0

    now = datetime.now(UTC)
    message = "Job lease recovered after server restart"
    for job in jobs:
        job.error_message = message
        job.lease_owner = None
        job.lease_expires_at = None
        if job.attempt_count < job.max_attempts:
            job.status = JobStatus.QUEUED
            job.available_at = now
            job.started_at = None
        else:
            job.status = JobStatus.FAILED
            job.result_json = _job_error_result("attempts_exhausted", message)
            job.finished_at = now

    await db.commit()
    return len(jobs)


async def create_job(
    db: AsyncSession,
    job_type: str,
    user_id: str | None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
) -> BackgroundJob:
    scoped_key = _scoped_idempotency_key(user_id, job_type, idempotency_key)
    if scoped_key is not None:
        existing = await db.scalar(
            select(BackgroundJob).where(BackgroundJob.idempotency_key == scoped_key)
        )
        if existing is not None:
            return existing
    job = BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        payload_json=json.dumps(payload or {}),
        result_json="{}",
        available_at=datetime.now(UTC),
        idempotency_key=scoped_key,
        max_attempts=max_attempts,
    )
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if scoped_key is None:
            raise
        existing = await db.scalar(
            select(BackgroundJob).where(BackgroundJob.idempotency_key == scoped_key)
        )
        if existing is None:
            raise
        return existing
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, job_id: str) -> BackgroundJob | None:
    result = await db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))
    return result.scalar_one_or_none()


def schedule_job(job_id: str) -> None:
    task = asyncio.create_task(run_job(job_id))
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    if _worker_wakeup is not None:
        _worker_wakeup.set()


def start_job_worker() -> None:
    """Start the database-backed queue poller for durable queued work."""
    global _worker_task, _worker_wakeup
    if _worker_task and not _worker_task.done():
        return
    _worker_wakeup = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("Background job worker started")


async def stop_job_worker() -> None:
    global _worker_task, _worker_wakeup
    if _worker_task is None:
        return
    _worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await _worker_task
    if _active_tasks:
        tasks = list(_active_tasks)
        _, pending = await asyncio.wait(tasks, timeout=10)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    _worker_task = None
    _worker_wakeup = None
    logger.info("Background job worker stopped")


async def _handle_demo_sync_pipeline(
    db: AsyncSession, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    sync_stats = await demo_sync_gmail_emails(db, user_id)
    pipeline_stats = await process_raw_emails(db, user_id, limit=payload.get("limit", 50))
    return {"sync": sync_stats, "pipeline": pipeline_stats}


async def _handle_gmail_sync_pipeline(
    db: AsyncSession, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    result = await db.execute(select(GmailAccount).where(GmailAccount.user_id == user_id))
    gmail_account = result.scalar_one_or_none()
    if gmail_account is None:
        raise ValueError("No Gmail account connected for this user")
    if gmail_account.auto_sync_status == "disconnecting":
        raise ValueError("Gmail disconnect is already in progress")

    sync_stats = await sync_gmail_emails(
        db=db,
        user_id=user_id,
        gmail_account_id=gmail_account.id,
        max_results=payload.get("max_results", 50),
    )
    await sync_event_manager.broadcast(
        user_id,
        "emails_stored",
        {
            "stored": sync_stats.get("emails_stored", 0),
            "duplicates": sync_stats.get("emails_skipped_duplicate", 0),
            "failed": sync_stats.get("emails_failed", 0),
        },
    )
    await sync_event_manager.broadcast(user_id, "pipeline_started", {})
    pipeline_stats = await process_raw_emails(db, user_id, limit=payload.get("limit", 50))
    await sync_event_manager.broadcast(
        user_id,
        "transactions_updated",
        {
            "stored": pipeline_stats.get("stored", 0),
            "duplicates": pipeline_stats.get("duplicates", 0),
            "parsed_success": pipeline_stats.get("parsed_success", 0),
        },
    )
    return {"sync": sync_stats, "pipeline": pipeline_stats}


async def _handle_retry_parse_failures(
    db: AsyncSession, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return await retry_parse_failures(db, user_id, limit=payload.get("limit", 20))


async def _handle_raw_email_retention(
    db: AsyncSession, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    batch_size = min(max(int(payload.get("batch_size", 500)), 1), 2000)
    return await redact_expired_raw_email_content(
        db,
        user_id=user_id or None,
        batch_size=batch_size,
    )


async def _handle_balance_refresh(
    db: AsyncSession, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if not user_id:
        raise ValueError("A user is required for a balance refresh")
    provider_type = str(payload.get("provider_type", "")).strip().lower()
    registration = balance_connector_registry.get(provider_type)
    if registration is None:
        raise ValueError("The requested balance provider is not configured")
    connection_service = BalanceProviderConnectionService(db)
    connection = await connection_service.require_active_connection(user_id, provider_type)
    account_ids = [str(item) for item in payload.get("account_ids", [])]
    await connection_service.mark_started(user_id, provider_type)
    try:
        connector = await registration.factory(db, user_id, connection)
        result = await BalanceSyncService(db).run(
            user_id,
            connector,
            account_ids,
            provider_type=provider_type,
        )
        await connection_service.mark_completed(user_id, provider_type)
        return {
            "source_type": result.source_type,
            "financial_account_ids": result.financial_account_ids,
            "observations_ingested": result.observations_ingested,
            "card_observations_ingested": result.card_observations_ingested,
            "coverage_complete": result.coverage_complete,
            "error_types": result.error_types,
            "cursor_advanced": result.cursor_advanced,
        }
    except Exception as exc:
        await connection_service.mark_failed(
            user_id,
            provider_type,
            f"balance_refresh_{classify_connector_exception(exc).value}",
        )
        raise


JOB_HANDLERS = {
    "demo_sync_pipeline": _handle_demo_sync_pipeline,
    "gmail_sync_pipeline": _handle_gmail_sync_pipeline,
    "retry_parse_failures": _handle_retry_parse_failures,
    "raw_email_retention": _handle_raw_email_retention,
    "balance_refresh": _handle_balance_refresh,
}


def classify_job_error(exc: Exception) -> str:
    """Map job exceptions to stable operational categories."""
    message = str(exc).lower()
    if isinstance(exc, RefreshError):
        return "credential_error"
    if isinstance(exc, ValueError) and "no gmail account connected" in message:
        return "missing_gmail_account"
    if isinstance(exc, ValueError) and "balance provider is not configured" in message:
        return "missing_balance_provider"
    if isinstance(exc, ValueError) and "provider consent" in message:
        return "missing_provider_consent"
    if isinstance(exc, ValueError):
        return "validation_error"
    if "credential" in message or "token" in message or "oauth" in message:
        return "credential_error"
    return "unexpected_error"


def _job_error_result(error_type: str, message: str) -> str:
    return json.dumps({"error_type": error_type, "error_message": message})


def public_job_error_message(error_type: str) -> str:
    """Return a stable job error without exposing provider or payload details."""
    return {
        "missing_gmail_account": "No Gmail account connected for this user",
        "missing_balance_provider": "No balance provider is configured for this deployment",
        "missing_provider_consent": "Balance provider consent is missing or expired",
        "validation_error": "Background job validation failed",
        "credential_error": "Connector authorization failed",
        "unexpected_error": "Background job failed unexpectedly",
    }.get(error_type, "Background job failed")


def _scoped_idempotency_key(
    user_id: str | None, job_type: str, idempotency_key: str | None
) -> str | None:
    if idempotency_key is None or not idempotency_key.strip():
        return None
    raw = f"{user_id or 'system'}|{job_type}|{idempotency_key.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _claim_job(db: AsyncSession, job_id: str) -> BackgroundJob | None:
    """Atomically lease one due queued job across all application replicas."""
    now = datetime.now(UTC)
    result = await db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == JobStatus.QUEUED,
            or_(BackgroundJob.available_at.is_(None), BackgroundJob.available_at <= now),
        )
        .values(
            status=JobStatus.RUNNING,
            started_at=now,
            attempt_count=BackgroundJob.attempt_count + 1,
            lease_owner=_worker_id,
            lease_expires_at=now + timedelta(seconds=_lease_seconds),
        )
        .returning(BackgroundJob.id)
    )
    claimed_id = result.scalar_one_or_none()
    await db.commit()
    return await get_job(db, claimed_id) if claimed_id else None


async def _worker_loop() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(UTC)
                await _recover_expired_leases(db, now)
                capacity = max(_worker_concurrency - len(_active_tasks), 0)
                if capacity == 0:
                    job_ids = []
                else:
                    result = await db.scalars(
                        select(BackgroundJob.id)
                        .where(
                            BackgroundJob.status == JobStatus.QUEUED,
                            or_(
                                BackgroundJob.available_at.is_(None),
                                BackgroundJob.available_at <= now,
                            ),
                        )
                        .order_by(BackgroundJob.created_at, BackgroundJob.id)
                        .limit(capacity)
                    )
                    job_ids = list(result.all())
            for job_id in job_ids:
                schedule_job(job_id)
        except Exception:
            logger.exception("Background job worker poll failed")

        wakeup = _worker_wakeup
        if wakeup is None:
            return
        with suppress(TimeoutError):
            await asyncio.wait_for(wakeup.wait(), timeout=_worker_poll_seconds)
        wakeup.clear()


async def _recover_expired_leases(db: AsyncSession, now: datetime) -> int:
    result = await db.scalars(
        select(BackgroundJob).where(
            BackgroundJob.status == JobStatus.RUNNING,
            BackgroundJob.lease_expires_at.is_not(None),
            BackgroundJob.lease_expires_at <= now,
        )
    )
    jobs = list(result.all())
    for job in jobs:
        job.lease_owner = None
        job.lease_expires_at = None
        job.error_message = "Job lease expired before completion"
        if job.attempt_count < job.max_attempts:
            job.status = JobStatus.QUEUED
            job.available_at = now
            job.started_at = None
        else:
            job.status = JobStatus.FAILED
            job.result_json = _job_error_result("attempts_exhausted", job.error_message)
            job.finished_at = now
    if jobs:
        await db.commit()
    return len(jobs)


async def _renew_job_lease(job_id: str) -> None:
    while True:
        await asyncio.sleep(_lease_seconds / 3)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(BackgroundJob)
                .where(
                    BackgroundJob.id == job_id,
                    BackgroundJob.status == JobStatus.RUNNING,
                    BackgroundJob.lease_owner == _worker_id,
                )
                .values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=_lease_seconds))
            )
            await db.commit()


async def run_job(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await _claim_job(db, job_id)
        if job is None:
            return

        payload = json.loads(job.payload_json or "{}")
        handler = JOB_HANDLERS.get(job.job_type)
        if handler is None:
            job.status = JobStatus.FAILED
            job.error_message = f"Unsupported job type: {job.job_type}"
            job.result_json = _job_error_result("unsupported_job_type", job.error_message)
            job.finished_at = datetime.now(UTC)
            job.lease_owner = None
            job.lease_expires_at = None
            await db.commit()
            return

        active_task = asyncio.current_task()
        tracked_user_id = job.user_id
        if tracked_user_id and active_task is not None:
            _active_user_tasks.setdefault(tracked_user_id, set()).add(active_task)

        try:
            if tracked_user_id:
                user = await db.get(User, tracked_user_id)
                if user is None or not user.is_active or user.deletion_started_at is not None:
                    job.status = JobStatus.FAILED
                    job.error_message = "User account is unavailable"
                    job.result_json = _job_error_result("user_unavailable", job.error_message)
                    job.finished_at = datetime.now(UTC)
                    job.lease_owner = None
                    job.lease_expires_at = None
                    await db.commit()
                    return

            heartbeat = asyncio.create_task(_renew_job_lease(job_id))
            result = await handler(db, job.user_id or "", payload)
            job.status = JobStatus.COMPLETED
            job.result_json = json.dumps(result)
            job.finished_at = datetime.now(UTC)
            job.error_message = None
            job.lease_owner = None
            job.lease_expires_at = None
            await db.commit()
            if job.user_id and job.job_type in {"gmail_sync_pipeline", "demo_sync_pipeline"}:
                await sync_event_manager.broadcast(job.user_id, "sync_completed", result)
            elif job.user_id and job.job_type == "balance_refresh":
                await sync_event_manager.broadcast(job.user_id, "balance_refresh_completed", result)
        except Exception as exc:
            await db.rollback()
            job = await get_job(db, job_id)
            if job is None:
                return
            error_type = classify_job_error(exc)
            public_error = public_job_error_message(error_type)
            logger.warning(
                "Background job failed job_id=%s error_type=%s exception=%s",
                job_id,
                error_type,
                type(exc).__name__,
            )
            job.error_message = public_error
            job.result_json = _job_error_result(error_type, public_error)
            job.lease_owner = None
            job.lease_expires_at = None
            if error_type == "unexpected_error" and job.attempt_count < job.max_attempts:
                job.status = JobStatus.QUEUED
                job.available_at = datetime.now(UTC) + timedelta(
                    seconds=min(2**job.attempt_count, 60)
                )
                job.started_at = None
                job.finished_at = None
            else:
                job.status = JobStatus.FAILED
                job.finished_at = datetime.now(UTC)
            await db.commit()
            if job.user_id and job.job_type in {"gmail_sync_pipeline", "demo_sync_pipeline"}:
                await sync_event_manager.broadcast(
                    job.user_id, "sync_failed", {"error": public_error}
                )
            elif job.user_id and job.job_type == "balance_refresh":
                await sync_event_manager.broadcast(
                    job.user_id, "balance_refresh_failed", {"error": public_error}
                )
        finally:
            if tracked_user_id and active_task is not None:
                user_tasks = _active_user_tasks.get(tracked_user_id)
                if user_tasks is not None:
                    user_tasks.discard(active_task)
                    if not user_tasks:
                        _active_user_tasks.pop(tracked_user_id, None)
            if "heartbeat" in locals():
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
