"""Subscriptions and recurring-payment review routes."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.subscription_review import (
    SubscriptionReviewActionRequest,
    SubscriptionReviewActionResponse,
    SubscriptionReviewListResponse,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.subscription_review_service import SubscriptionReviewService

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


@router.get("/recurring-review", response_model=SubscriptionReviewListResponse)
async def list_recurring_review_items(
    user_id: str | None = Query(None),
    as_of: date | None = Query(None),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List deterministic recurring merchant streams requiring or carrying review."""

    scoped_user_id = resolve_user_scope(user_id, current_user)
    return await SubscriptionReviewService(db).list_items(scoped_user_id, as_of=as_of)


@router.post(
    "/recurring-review/{stream_key}/actions",
    response_model=SubscriptionReviewActionResponse,
    status_code=201,
)
async def record_recurring_review_action(
    stream_key: str,
    data: SubscriptionReviewActionRequest,
    user_id: str | None = Query(None),
    as_of: date | None = Query(None),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Upsert an explicit user decision for one recurring merchant stream."""

    scoped_user_id = resolve_user_scope(user_id, current_user)
    return await SubscriptionReviewService(db).record_action(
        scoped_user_id,
        stream_key,
        action=data.action,
        note=data.note,
        as_of=as_of,
    )
