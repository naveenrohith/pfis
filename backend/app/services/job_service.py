"""Lightweight in-process background job orchestration for PFIS."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.email import GmailAccount
from app.models.sync import BackgroundJob, JobStatus
from app.services.gmail.sync_service import demo_sync_gmail_emails, sync_gmail_emails
from app.services.parser.pipeline import process_raw_emails, retry_parse_failures

logger = logging.getLogger(__name__)
_active_tasks: set[asyncio.Task] = set()


def serialize_job(job: BackgroundJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "job_type": job.job_type,
        "status": job.status.value,
        "payload": json.loads(job.payload_json or "{}"),
        "result": json.loads(job.result_json or "{}"),
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def get_active_task_count() -> int:
    """Return the number of in-process job tasks currently tracked."""
    return len(_active_tasks)


async def get_job_status_counts(db: AsyncSession) -> dict[str, int]:
    """Return persisted background job counts by status."""
    result = await db.execute(
        select(BackgroundJob.status, func.count(BackgroundJob.id)).group_by(BackgroundJob.status)
    )
    counts = {status.value: int(count) for status, count in result.all()}
    return {status.value: counts.get(status.value, 0) for status in JobStatus}


async def create_job(
    db: AsyncSession,
    job_type: str,
    user_id: str | None,
    payload: dict[str, Any] | None = None,
) -> BackgroundJob:
    job = BackgroundJob(
        user_id=user_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        payload_json=json.dumps(payload or {}),
        result_json="{}",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_job(db: AsyncSession, job_id: str) -> BackgroundJob | None:
    result = await db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))
    return result.scalar_one_or_none()


def schedule_job(job_id: str) -> None:
    task = asyncio.create_task(run_job(job_id))
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)


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

    sync_stats = await sync_gmail_emails(
        db=db,
        user_id=user_id,
        gmail_account_id=gmail_account.id,
        max_results=payload.get("max_results", 50),
    )
    pipeline_stats = await process_raw_emails(db, user_id, limit=payload.get("limit", 50))
    return {"sync": sync_stats, "pipeline": pipeline_stats}


async def _handle_retry_parse_failures(
    db: AsyncSession, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return await retry_parse_failures(db, user_id, limit=payload.get("limit", 20))


JOB_HANDLERS = {
    "demo_sync_pipeline": _handle_demo_sync_pipeline,
    "gmail_sync_pipeline": _handle_gmail_sync_pipeline,
    "retry_parse_failures": _handle_retry_parse_failures,
}


def classify_job_error(exc: Exception) -> str:
    """Map job exceptions to stable operational categories."""
    message = str(exc).lower()
    if isinstance(exc, ValueError) and "no gmail account connected" in message:
        return "missing_gmail_account"
    if isinstance(exc, ValueError):
        return "validation_error"
    if "credential" in message or "token" in message or "oauth" in message:
        return "credential_error"
    return "unexpected_error"


def _job_error_result(error_type: str, message: str) -> str:
    return json.dumps({"error_type": error_type, "error_message": message})


async def run_job(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await get_job(db, job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return

        payload = json.loads(job.payload_json or "{}")
        handler = JOB_HANDLERS.get(job.job_type)
        if handler is None:
            job.status = JobStatus.FAILED
            job.error_message = f"Unsupported job type: {job.job_type}"
            job.result_json = _job_error_result("unsupported_job_type", job.error_message)
            job.finished_at = datetime.now(UTC)
            await db.commit()
            return

        try:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(UTC)
            await db.commit()

            result = await handler(db, job.user_id or "", payload)
            job.status = JobStatus.COMPLETED
            job.result_json = json.dumps(result)
            job.finished_at = datetime.now(UTC)
            job.error_message = None
            await db.commit()
        except Exception as exc:
            logger.exception("Background job %s failed", job_id)
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.result_json = _job_error_result(classify_job_error(exc), str(exc))
            job.finished_at = datetime.now(UTC)
            await db.commit()
