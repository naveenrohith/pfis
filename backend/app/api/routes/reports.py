"""Reports and export routes."""

import logging
from collections.abc import Iterator
from typing import IO

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.rate_limit import limiter
from app.security import get_current_user_optional, resolve_user_scope
from app.services.portable_export_service import build_portable_export
from app.services.report_service import (
    build_monthly_report_html,
    build_transactions_csv,
    fetch_monthly_transaction_rows,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Reports"])


def _stream_file(stream: IO[bytes]) -> Iterator[bytes]:
    try:
        while chunk := stream.read(64 * 1024):
            yield chunk
    finally:
        stream.close()


@router.post("/export/portable")
@limiter.limit("2/minute")
async def export_portable_data(
    request: Request,
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Download a versioned portable copy without credentials or session secrets."""
    user_id = resolve_user_scope(user_id, current_user)
    try:
        artifact = await build_portable_export(db, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info(
        "Portable export generated entity_count=%s size_bytes=%s",
        artifact.manifest["archive"]["entity_count"],
        artifact.size_bytes,
    )
    return StreamingResponse(
        _stream_file(artifact.stream),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Content-Length": str(artifact.size_bytes),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
