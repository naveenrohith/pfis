"""Deterministic guidance and recommendation-state routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.guidance import (
    GuidanceBrief,
    GuidancePeriod,
    GuidanceQueryRequest,
    GuidanceQueryResult,
    RecommendationEffectivenessReport,
    RecommendationOutcomeCreate,
    RecommendationOutcomeResponse,
    RecommendationStateResponse,
    RecommendationStateUpdate,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.financial_clock import user_financial_today
from app.services.guidance_service import GuidanceService
from app.services.ledger_currency import get_ledger_currency
from app.services.recommendation_evaluation_service import RecommendationEvaluationService

router = APIRouter(prefix="/guidance", tags=["Guidance"])


@router.get("/brief", response_model=GuidanceBrief)
async def get_guidance_brief(
    user_id: str,
    period: GuidancePeriod = Query("daily"),
    as_of: date | None = Query(None),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    effective_as_of = as_of or await user_financial_today(db, user_id)
    return await GuidanceService(db).brief(user_id, period, effective_as_of)


@router.post("/query", response_model=GuidanceQueryResult)
async def query_guidance(
    data: GuidanceQueryRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    today = await user_financial_today(db, user_id)
    return await GuidanceService(db).query(
        user_id,
        data.query,
        data.month or today.month,
        data.year or today.year,
        current_user.currency if current_user else await get_ledger_currency(db, user_id),
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
    try:
        return await GuidanceService(db).set_state(user_id, recommendation_id, data)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/decisions", response_model=list[RecommendationStateResponse])
async def list_recommendation_decisions(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await GuidanceService(db).list_decisions(resolve_user_scope(user_id, current_user))


@router.post(
    "/decisions/{decision_id}/outcome",
    response_model=RecommendationOutcomeResponse,
)
async def record_recommendation_outcome(
    decision_id: str,
    data: RecommendationOutcomeCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await GuidanceService(db).record_outcome(
            resolve_user_scope(user_id, current_user), decision_id, data
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/outcomes", response_model=list[RecommendationOutcomeResponse])
async def list_recommendation_outcomes(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await GuidanceService(db).list_outcomes(resolve_user_scope(user_id, current_user))


@router.get("/effectiveness", response_model=RecommendationEffectivenessReport)
async def get_recommendation_effectiveness(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    # Authorize the viewer, but never return another user's decisions or outcomes.
    resolve_user_scope(user_id, current_user)
    return await RecommendationEvaluationService(db).effectiveness_report()
