"""Financial Horizon route."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.financial_horizon import FinancialHorizonResponse
from app.security import get_current_user_optional, resolve_user_scope
from app.services.financial_horizon_service import FinancialHorizonService

router = APIRouter(prefix="/horizon", tags=["Financial Horizon"])


@router.get("", response_model=FinancialHorizonResponse)
async def financial_horizon(
    user_id: str | None = None,
    days: int = Query(30, ge=7, le=90),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return a deterministic, server-owned financial horizon read model."""

    scoped_user_id = resolve_user_scope(user_id, current_user)
    return await FinancialHorizonService(db).horizon(scoped_user_id, days=days)
