"""
Transaction Routes
CRUD + aggregation endpoints for transactions.
"""

from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.transaction import (
    TransactionCreate,
    TransactionUpdate,
    TransactionResponse,
    TransactionSummary,
)
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.post("/", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    user_id: str,
    data: TransactionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new transaction with automatic dedup."""
    service = TransactionService(db)
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
    db: AsyncSession = Depends(get_db),
):
    """List transactions with optional filters."""
    service = TransactionService(db)
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
    db: AsyncSession = Depends(get_db),
):
    """Get monthly spending summary with category breakdown and top merchants."""
    service = TransactionService(db)
    summary = await service.get_monthly_summary(user_id, month, year)
    return summary


@router.get("/{txn_id}", response_model=TransactionResponse)
async def get_transaction(
    txn_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single transaction by ID."""
    service = TransactionService(db)
    txn = await service.get_transaction_by_id(txn_id)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.patch("/{txn_id}", response_model=TransactionResponse)
async def update_transaction(
    txn_id: str,
    data: TransactionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a transaction (user correction)."""
    service = TransactionService(db)
    txn = await service.update_transaction(txn_id, data)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn
