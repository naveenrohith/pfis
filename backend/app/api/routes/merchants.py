"""Merchant intelligence and correction routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.intelligence import MerchantDetail, MerchantSummary, MerchantUpdate
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
