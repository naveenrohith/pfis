"""Authenticated API for user-scoped durable financial change replay."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.financial_change import FinancialChangePageResponse
from app.security import get_current_user_optional, resolve_user_scope
from app.services.financial_change_service import FinancialChangeService

router = APIRouter(prefix="/sync", tags=["Synchronization"])


@router.get("/changes", response_model=FinancialChangePageResponse)
async def financial_changes(
    user_id: str = Query(...),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(250, ge=1, le=500),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Replay committed invalidation hints after the authenticated user's cursor."""
    scoped_user_id = resolve_user_scope(user_id, current_user)
    try:
        return await FinancialChangeService(db).changes_after(scoped_user_id, after_sequence, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
