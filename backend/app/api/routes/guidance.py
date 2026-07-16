"""Deterministic guidance and recommendation-state routes."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.guidance import (
    GuidanceBrief,
    GuidancePeriod,
    GuidanceQueryRequest,
    GuidanceQueryResult,
    RecommendationStateResponse,
    RecommendationStateUpdate,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.guidance_service import GuidanceService

router = APIRouter(prefix="/guidance", tags=["Guidance"])


@router.get("/brief", response_model=GuidanceBrief)
async def get_guidance_brief(
    user_id: str,
    period: GuidancePeriod = Query("daily"),
    as_of: date = Query(default_factory=date.today),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await GuidanceService(db).brief(user_id, period, as_of)


@router.post("/query", response_model=GuidanceQueryResult)
async def query_guidance(
    data: GuidanceQueryRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    today = date.today()
    return await GuidanceService(db).query(
        user_id,
        data.query,
        data.month or today.month,
        data.year or today.year,
        current_user.currency if current_user else "INR",
    )


@router.patch("/{recommendation_id}/state", response_model=RecommendationStateResponse)
async def update_recommendation_state(
    recommendation_id: str,
    data: RecommendationStateUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await GuidanceService(db).set_state(user_id, recommendation_id, data)
