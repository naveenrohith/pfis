"""
Transaction Routes
CRUD + aggregation endpoints for transactions.
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.transaction import (
    BulkTransactionUpdate,
    BulkTransactionUpdateResponse,
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionSummary,
)
from app.security import ensure_user_owns_resource, get_current_user_optional, resolve_user_scope
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post("/", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    user_id: str,
    data: TransactionCreate,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Create a new transaction with automatic dedup."""
    service = TransactionService(db)
    user_id = resolve_user_scope(user_id, current_user)
    try:
        txn = await service.create_transaction(user_id, data)
        return txn
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    user_id: str,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2020, le=2030),
    category_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List transactions with optional filters."""
    service = TransactionService(db)
    user_id = resolve_user_scope(user_id, current_user)
    txns = await service.get_transactions(
        user_id=user_id,
        month=month,
        year=year,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    return txns


@router.get("/summary", response_model=TransactionSummary)
async def get_monthly_summary(
    user_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Get monthly spending summary with category breakdown and top merchants."""
    service = TransactionService(db)
    user_id = resolve_user_scope(user_id, current_user)
    summary = await service.get_monthly_summary(user_id, month, year)
    return summary


@router.patch("/bulk-update", response_model=BulkTransactionUpdateResponse)
async def bulk_update_transactions(
    data: BulkTransactionUpdate,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Apply shared review updates across multiple transactions."""
    service = TransactionService(db)
    user_id = resolve_user_scope(user_id, current_user)
    result = await service.bulk_update_transactions(user_id, data)
    return result


@router.get("/{txn_id}", response_model=TransactionResponse)
async def get_transaction(
    txn_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Get a single transaction by ID."""
    service = TransactionService(db)
    txn = await service.get_transaction_by_id(txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    ensure_user_owns_resource(txn.user_id, current_user)
    return txn


@router.patch("/{txn_id}", response_model=TransactionResponse)
async def update_transaction(
    txn_id: str,
    data: TransactionUpdate,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Update a transaction (user correction)."""
    service = TransactionService(db)
    existing = await service.get_transaction_by_id(txn_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Transaction not found")
    ensure_user_owns_resource(existing.user_id, current_user)
    try:
        txn = await service.update_transaction(txn_id, data)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return txn
