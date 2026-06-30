"""Reports and export routes."""

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.security import get_current_user_optional, resolve_user_scope
from app.services.report_service import (
    build_monthly_report_html,
    build_transactions_csv,
    fetch_monthly_transaction_rows,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/export/csv")
async def export_csv(
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Export transactions as CSV for the given month."""
    user_id = resolve_user_scope(user_id, current_user)
    rows = await fetch_monthly_transaction_rows(db, user_id, month, year)
    output = build_transactions_csv(rows)
    filename = f"pfis_transactions_{year}-{month:02d}.csv"
    logger.info("CSV export: %s transactions for %s-%02d", len(rows), year, month)

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/monthly", response_class=HTMLResponse)
async def monthly_report(
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Generate a printable monthly financial report as HTML."""
    user_id = resolve_user_scope(user_id, current_user)
    html = await build_monthly_report_html(db, user_id, month, year)
    return HTMLResponse(content=html)
