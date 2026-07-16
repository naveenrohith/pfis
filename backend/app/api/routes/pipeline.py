"""
Pipeline Routes
Trigger and monitor the processing pipeline.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.security import get_current_user_optional, resolve_user_scope
from app.services.parser.pipeline import (
    get_pipeline_metrics,
    list_parse_failures,
    process_raw_emails,
    reprocess_raw_emails,
    retry_parse_failure_by_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


class ReprocessRequest(BaseModel):
    email_ids: list[str] | None = Field(default=None, max_length=200)
    from_date: date | None = None
    to_date: date | None = None
    dry_run: bool = True
    limit: int = Field(default=100, ge=1, le=500)


@router.post("/process")
async def trigger_processing(
    user_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Process unprocessed raw emails through the full pipeline:
    Parse → Normalize → Categorize → Dedup → Store Transaction
    """
    user_id = resolve_user_scope(user_id, current_user)
    try:
        stats = await process_raw_emails(db, user_id, limit)
        return {"status": "completed", "stats": stats}
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/metrics")
async def pipeline_metrics(
    user_id: str = Query(...),
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return parser and transaction pipeline health metrics."""
    user_id = resolve_user_scope(user_id, current_user)
    return await get_pipeline_metrics(db, user_id, month, year)


@router.get("/failures")
async def pipeline_failures(
    user_id: str = Query(...),
    resolved: bool | None = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List parser DLQ items without exposing raw email bodies."""
    user_id = resolve_user_scope(user_id, current_user)
    return await list_parse_failures(db, user_id, resolved, limit, offset)


@router.post("/failures/{failure_id}/retry")
async def retry_pipeline_failure(
    failure_id: str,
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Retry one DLQ item."""
    user_id = resolve_user_scope(user_id, current_user)
    stats = await retry_parse_failure_by_id(db, user_id, failure_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Parse failure not found")
    return {"status": "completed", "stats": stats}


@router.post("/reprocess")
async def reprocess_pipeline_emails(
    payload: ReprocessRequest,
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Replay retained raw emails; dry_run compares parser output without mutating transactions."""
    user_id = resolve_user_scope(user_id, current_user)
    if payload.from_date and payload.to_date and payload.from_date > payload.to_date:
        raise HTTPException(status_code=400, detail="from_date must be before to_date")
    return await reprocess_raw_emails(
        db,
        user_id,
        email_ids=payload.email_ids,
        from_date=payload.from_date,
        to_date=payload.to_date,
        dry_run=payload.dry_run,
        limit=payload.limit,
    )
