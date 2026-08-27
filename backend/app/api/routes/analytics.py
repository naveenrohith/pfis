"""Advanced analytics, projections, health score, and goals."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.intelligence import (
    CashFlowBacktestReport,
    CashFlowForecastOutcomeResponse,
    CashFlowForecastSnapshotCreate,
    CashFlowForecastSnapshotResponse,
    CashFlowOutcomeEvaluationResponse,
    CashFlowProjection,
    FinancialHealthScore,
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    MonthComparison,
    ScenarioRequest,
    ScenarioResponse,
    SourceCoverageResponse,
)
from app.schemas.operational import IntelligenceReadinessResponse, ReconciliationQualityResponse
from app.security import get_current_user_optional, resolve_user_scope
from app.services.forecast_accountability_service import ForecastAccountabilityService
from app.services.intelligence_readiness_service import IntelligenceReadinessService
from app.services.intelligence_service import IntelligenceService
from app.services.reconciliation_quality_service import ReconciliationQualityService

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


@router.get("/cash-flow/backtest", response_model=CashFlowBacktestReport)
async def cash_flow_backtest(
    user_id: str,
    months: int = Query(6, ge=3, le=12),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).cash_flow_backtest(user_id, months=months)


@router.post("/cash-flow/snapshots", response_model=CashFlowForecastSnapshotResponse)
async def create_cash_flow_forecast_snapshot(
    data: CashFlowForecastSnapshotCreate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await ForecastAccountabilityService(db).create_snapshot(
            resolve_user_scope(user_id, current_user), data
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cash-flow/snapshots", response_model=list[CashFlowForecastSnapshotResponse])
async def list_cash_flow_forecast_snapshots(
    user_id: str,
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await ForecastAccountabilityService(db).list_snapshots(
        resolve_user_scope(user_id, current_user), month=month, year=year
    )


@router.post(
    "/cash-flow/outcomes/evaluate",
    response_model=CashFlowOutcomeEvaluationResponse,
)
async def evaluate_cash_flow_forecast_outcomes(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await ForecastAccountabilityService(db).evaluate_completed(
        resolve_user_scope(user_id, current_user)
    )


@router.get(
    "/cash-flow/outcomes",
    response_model=list[CashFlowForecastOutcomeResponse],
)
async def list_cash_flow_forecast_outcomes(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    return await ForecastAccountabilityService(db).list_outcomes(
        resolve_user_scope(user_id, current_user)
    )


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


@router.get("/source-coverage", response_model=SourceCoverageResponse)
async def source_coverage(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return explicit observed-source coverage and freshness evidence."""

    try:
        return await IntelligenceService(db).source_coverage(
            resolve_user_scope(user_id, current_user)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/intelligence-readiness", response_model=IntelligenceReadinessResponse)
async def intelligence_readiness(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return the evidence gates behind this workspace's intelligence claims."""

    try:
        return await IntelligenceReadinessService(db).report(
            resolve_user_scope(user_id, current_user)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reconciliation-quality", response_model=ReconciliationQualityResponse)
async def reconciliation_quality(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return explicit ledger, statement, and balance reconciliation evidence."""

    return await ReconciliationQualityService(db).report(resolve_user_scope(user_id, current_user))


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
