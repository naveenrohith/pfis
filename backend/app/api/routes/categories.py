"""
Category Routes
CRUD endpoints for categories.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.category import Category
from app.models.user import User
from app.schemas.intelligence import CategoryIntelligenceResponse
from app.schemas.transaction import CategoryResponse
from app.security import get_current_user_optional, resolve_user_scope
from app.services.intelligence_service import IntelligenceService

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("/intelligence", response_model=CategoryIntelligenceResponse)
async def category_intelligence(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Category intelligence: totals, budget usage, hierarchy, and top merchants."""
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).category_intelligence(user_id, month, year)


@router.get("/", response_model=list[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """List all categories."""
    result = await db.execute(select(Category).order_by(Category.name))
    return list(result.scalars().all())
