"""Versioned temporal financial knowledge APIs."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.temporal import (
    TemporalEventDecisionUpsert,
    TemporalEventSummary,
    TemporalFinancialEvent,
    TemporalHistoryBackfillRequest,
    TemporalHistoryBackfillResponse,
    TemporalRecomputationAudit,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.temporal_event_service import TemporalEventService
from app.services.temporal_source_history import backfill_temporal_source_history

router = APIRouter(prefix="/knowledge", tags=["Financial knowledge"])


@router.get("/events", response_model=TemporalEventSummary)
async def temporal_events(
    user_id: str,
    range_start: date | None = Query(None),
    range_end: date | None = Query(None),
    as_of: date | None = Query(
        None,
        description="Financial day at which to evaluate the read model; future dates are rejected.",
    ),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await TemporalEventService(db).timeline(
            resolve_user_scope(user_id, current_user),
            range_start=range_start,
            range_end=range_end,
            as_of=as_of,
            historical_safe=as_of is not None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/events/audit", response_model=TemporalRecomputationAudit)
async def audit_temporal_event_recomputation(
    user_id: str,
    range_start: date | None = Query(None),
    range_end: date | None = Query(None),
    as_of: date | None = Query(None),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await TemporalEventService(db).recomputation_audit(
            resolve_user_scope(user_id, current_user),
            range_start=range_start,
            range_end=range_end,
            as_of=as_of,
            historical_safe=as_of is not None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/history/backfill",
    response_model=TemporalHistoryBackfillResponse,
)
async def backfill_temporal_history(
    data: TemporalHistoryBackfillRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Preview or capture a forward-only baseline for legacy source rows."""

    try:
        return await backfill_temporal_source_history(
            db,
            user_id=resolve_user_scope(user_id, current_user),
            source_types=data.source_types,
            dry_run=data.dry_run,
            max_rows_per_source=data.max_rows_per_source,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/events/{event_id}/decision", response_model=TemporalFinancialEvent)
async def upsert_temporal_event_decision(
    event_id: str,
    data: TemporalEventDecisionUpsert,
    user_id: str,
    range_start: date | None = Query(None),
    range_end: date | None = Query(None),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await TemporalEventService(db).upsert_decision(
            resolve_user_scope(user_id, current_user),
            event_id,
            data,
            range_start=range_start,
            range_end=range_end,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/events/{event_id}/decision", status_code=204)
async def delete_temporal_event_decision(
    event_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    deleted = await TemporalEventService(db).delete_decision(
        resolve_user_scope(user_id, current_user), event_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Temporal event decision not found")
