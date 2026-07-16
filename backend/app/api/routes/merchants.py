"""Merchant intelligence and correction routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.intelligence import (
    LearnedMerchantRule,
    MerchantDetail,
    MerchantSummary,
    MerchantUpdate,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.intelligence_service import IntelligenceService

router = APIRouter(prefix="/merchants", tags=["Merchants"])


@router.get("/", response_model=list[MerchantSummary])
async def list_merchants(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).list_merchants(user_id, month, year)


@router.get("/learned-rules", response_model=list[LearnedMerchantRule])
async def list_learned_rules(
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List exact merchant mappings learned from this user's corrections."""
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).list_learned_merchant_rules(user_id)


@router.delete("/learned-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_learned_rule(
    rule_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Forget one user-owned learned merchant mapping."""
    user_id = resolve_user_scope(user_id, current_user)
    deleted = await IntelligenceService(db).delete_learned_merchant_rule(user_id, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Learned merchant rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{merchant_key}", response_model=MerchantDetail)
async def get_merchant(
    merchant_key: str,
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    return await IntelligenceService(db).get_merchant_detail(user_id, merchant_key, month, year)


@router.patch("/{merchant_key}", response_model=MerchantDetail)
async def update_merchant(
    merchant_key: str,
    data: MerchantUpdate,
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    user_id = resolve_user_scope(user_id, current_user)
    try:
        return await IntelligenceService(db).update_merchant(
            user_id, merchant_key, data, month, year
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
