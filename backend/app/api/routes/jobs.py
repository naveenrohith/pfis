"""Background orchestration routes for sync, pipeline, and retry jobs."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.job import JobResponse
from app.security import get_current_user_optional, resolve_user_scope
from app.services.job_service import create_job, get_job, schedule_job, serialize_job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/demo-sync-pipeline", response_model=JobResponse, status_code=202)
@limiter.limit("5/minute")
async def enqueue_demo_sync_pipeline(
    request: Request,
    user_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    authorized_user_id = resolve_user_scope(user_id, current_user)
    job = await create_job(db, "demo_sync_pipeline", authorized_user_id, {"limit": limit})
    schedule_job(job.id)
    return serialize_job(job)


@router.post("/gmail-sync-pipeline", response_model=JobResponse, status_code=202)
@limiter.limit("5/minute")
async def enqueue_gmail_sync_pipeline(
    request: Request,
    user_id: str = Query(...),
    max_results: int = Query(500, ge=1, le=5000),
    limit: int = Query(500, ge=1, le=5000),
    sync_all: bool = Query(False),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    authorized_user_id = resolve_user_scope(user_id, current_user)
    payload = {"sync_all": sync_all}
    if sync_all:
        payload.update({"max_results": None, "limit": None})
    else:
        payload.update({"max_results": max_results, "limit": limit})

    job = await create_job(
        db,
        "gmail_sync_pipeline",
        authorized_user_id,
        payload,
    )
    schedule_job(job.id)
    return serialize_job(job)


@router.post("/retry-parse-failures", response_model=JobResponse, status_code=202)
@limiter.limit("5/minute")
async def enqueue_retry_parse_failures(
    request: Request,
    user_id: str = Query(...),
    limit: int = Query(20, ge=1, le=200),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    authorized_user_id = resolve_user_scope(user_id, current_user)
    job = await create_job(db, "retry_parse_failures", authorized_user_id, {"limit": limit})
    schedule_job(job.id)
    return serialize_job(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    job = await get_job(db, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Job not found")
    resolve_user_scope(job.user_id, current_user)
    return serialize_job(job)
