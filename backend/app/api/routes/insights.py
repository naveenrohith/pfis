"""
Insights Routes — Phase 5
API endpoint for auto-generated financial insights.
"""

import logging
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.insights_service import InsightsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["Insights"])


@router.get("/")
async def get_insights(
    user_id: str = Query(...),
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None, ge=2020, le=2030),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate financial insights for a user's given month.
    Returns insight cards, daily spending trend, and recurring payments.
    """
    # Default to current month
    if month is None:
        month = date.today().month
    if year is None:
        year = date.today().year

    service = InsightsService(db)
    insights = await service.generate_insights(user_id, month, year)

    return insights
