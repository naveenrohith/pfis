"""
Insights Routes — Phase 5
API endpoint for auto-generated financial insights.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.intelligence import (
    AnomalyAdjudicationRequest,
    AnomalyAdjudicationResponse,
    InsightsResponse,
    SpendingAnomaly,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.anomaly_adjudication_service import AnomalyAdjudicationService
from app.services.financial_clock import user_financial_today
from app.services.insights_service import InsightsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/", response_model=InsightsResponse)
async def get_insights(
    user_id: str = Query(...),
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None, ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate financial insights for a user's given month.
    Returns insight cards, daily spending trend, recurring payments, and
    evidence-backed category/merchant baseline departures.
    """
    user_id = resolve_user_scope(user_id, current_user)
    # Default to current month
    today = await user_financial_today(db, user_id)
    if month is None:
        month = today.month
    if year is None:
        year = today.year

    service = InsightsService(db)
    insights = await service.generate_insights(user_id, month, year)

    return insights


@router.post(
    "/anomalies/{anomaly_id}/adjudication",
    response_model=AnomalyAdjudicationResponse,
    status_code=201,
)
async def adjudicate_anomaly(
    anomaly_id: str,
    data: AnomalyAdjudicationRequest,
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Persist an explicit decision for a current server-derived anomaly."""

    user_id = resolve_user_scope(user_id, current_user)
    anomaly = next(
        (
            item
            for item in await InsightsService(db).anomalies_for_period(user_id, month, year)
            if item.id == anomaly_id
        ),
        None,
    )
    if anomaly is None:
        raise HTTPException(status_code=404, detail="Anomaly is no longer present for this period")
    return await AnomalyAdjudicationService(db).record(
        user_id,
        anomaly,
        month=month,
        year=year,
        decision=data.decision,
        note=data.note,
    )


@router.get("/anomaly-samples", response_model=list[SpendingAnomaly])
async def get_anomaly_samples(
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    limit: int = Query(4, ge=1, le=8),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return bounded non-alert samples for balanced anomaly adjudication."""

    user_id = resolve_user_scope(user_id, current_user)
    return await InsightsService(db).anomaly_samples_for_period(user_id, month, year, limit=limit)


@router.post(
    "/anomaly-samples/{sample_id}/adjudication",
    response_model=AnomalyAdjudicationResponse,
    status_code=201,
)
async def adjudicate_anomaly_sample(
    sample_id: str,
    data: AnomalyAdjudicationRequest,
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Persist an explicit decision for a server-sampled non-alert case."""

    user_id = resolve_user_scope(user_id, current_user)
    sample = next(
        (
            item
            for item in await InsightsService(db).anomaly_samples_for_period(
                user_id, month, year, limit=8
            )
            if item.id == sample_id
        ),
        None,
    )
    if sample is None:
        raise HTTPException(status_code=404, detail="Anomaly sample is no longer available")
    return await AnomalyAdjudicationService(db).record(
        user_id,
        sample,
        month=month,
        year=year,
        decision=data.decision,
        note=data.note,
        predicted_alert=False,
    )


@router.get(
    "/anomaly-adjudications",
    response_model=list[AnomalyAdjudicationResponse],
)
async def list_anomaly_adjudications(
    user_id: str = Query(...),
    limit: int = Query(100, ge=1, le=250),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List owned anomaly feedback without source transaction details."""

    return await AnomalyAdjudicationService(db).list_for_user(
        resolve_user_scope(user_id, current_user), limit
    )
