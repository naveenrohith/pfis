"""
Dashboard Routes — Financial Decision Workspace.

Exposes a single aggregate endpoint that composes the monthly snapshot,
financial timeline, insights, deterministic recommendations, review summary,
and sync summary. Existing transaction/insight/budget/gmail endpoints remain
the source of truth for their individual domains.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.dashboard import WorkspaceResponse
from app.security import get_current_user_optional, resolve_user_scope
from app.services.dashboard_service import WorkspaceService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/workspace", response_model=WorkspaceResponse)
async def get_workspace(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return the aggregate Financial Decision Workspace for a user/month."""
    user_id = resolve_user_scope(user_id, current_user)
    service = WorkspaceService(db)
    return await service.get_workspace(user_id, month, year)
