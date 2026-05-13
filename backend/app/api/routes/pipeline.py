"""
Pipeline Routes
Trigger and monitor the processing pipeline.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.security import get_current_user_optional, resolve_user_scope
from app.services.parser.pipeline import process_raw_emails

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.post("/process")
async def trigger_processing(
    user_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Process unprocessed raw emails through the full pipeline:
    Parse → Normalize → Categorize → Dedup → Store Transaction
    """
    user_id = resolve_user_scope(user_id, current_user)
    try:
        stats = await process_raw_emails(db, user_id, limit)
        return {"status": "completed", "stats": stats}
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
