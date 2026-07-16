"""Advanced analytics, projections, health score, and goals."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.intelligence import (
    CashFlowProjection,
    FinancialHealthScore,
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    MonthComparison,
    ScenarioRequest,
    ScenarioResponse,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.intelligence_service import IntelligenceService

router = APIRouter(prefix="/analytics", tags=["Analytics"])
goals_router = APIRouter(prefix="/goals", tags=["Goals"])


@router.get("/cash-flow", response_model=CashFlowProjection)
async def cash_flow(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).cash_flow_projection(user_id, month, year)


@router.post("/scenario", response_model=ScenarioResponse)
async def preview_scenario(
    data: ScenarioRequest,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).preview_scenario(user_id, data)


@router.get("/month-comparison", response_model=MonthComparison)
async def month_comparison(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).month_comparison(user_id, month, year)


@router.get("/financial-health", response_model=FinancialHealthScore)
async def financial_health(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).financial_health(user_id, month, year)


@goals_router.get("/", response_model=list[GoalResponse])
async def list_goals(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).list_goals(user_id, month, year)


@goals_router.post("/", response_model=GoalResponse, status_code=201)
async def create_goal(
    data: GoalCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).create_goal(user_id, data)


@goals_router.patch("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: str,
    data: GoalUpdate,
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    goal = await IntelligenceService(db).update_goal(goal_id, user_id, data, month, year)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal
