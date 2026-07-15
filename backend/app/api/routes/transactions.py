"""
Transaction Routes
CRUD + aggregation endpoints for transactions.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.transaction import (
    BulkTransactionUpdate,
    BulkTransactionUpdateResponse,
    TransactionCreate,
    TransactionResponse,
    TransactionSummary,
    TransactionUpdate,
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
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    user_id: str,
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2020, le=2030),
    category_id: str | None = None,
    q: str | None = Query(None, max_length=160),
    text: str | None = Query(None, max_length=160),
    transaction_type: Literal["debit", "credit", "refund"] | None = None,
    type_filter: Literal["debit", "credit", "refund"] | None = Query(None, alias="type"),
    payment_method: str | None = Query(None, max_length=20),
    reviewed: bool | None = None,
    review_state: Literal["reviewed", "unreviewed", "all"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    sort: Literal["transaction_date", "amount", "merchant", "created_at"] = "transaction_date",
    direction: Literal["asc", "desc"] = "desc",
    sort_field: Literal["transaction_date", "amount", "merchant", "created_at"] | None = None,
    sort_direction: Literal["asc", "desc"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List transactions with optional filters. Returns X-Total-Count header for pagination."""
    service = TransactionService(db)
    user_id = resolve_user_scope(user_id, current_user)
    effective_reviewed = reviewed
    if reviewed is None and review_state != "all":
        effective_reviewed = review_state == "reviewed" if review_state else None
    effective_q = text or q
    effective_type = type_filter or transaction_type
    effective_sort = sort_field or sort
    effective_direction = sort_direction or direction

    from fastapi.responses import JSONResponse

    txns = await service.get_transactions(
        user_id=user_id,
        month=month,
        year=year,
        category_id=category_id,
        q=effective_q,
        transaction_type=effective_type,
        payment_method=payment_method,
        reviewed=effective_reviewed,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        sort=effective_sort,
        direction=effective_direction,
        limit=limit,
        offset=offset,
    )
    total_count = await service.get_transaction_count(
        user_id=user_id,
        month=month,
        year=year,
        category_id=category_id,
        q=effective_q,
        transaction_type=effective_type,
        payment_method=payment_method,
        reviewed=effective_reviewed,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
    )

    from app.schemas.transaction import TransactionResponse as TR

    data = [TR.model_validate(t).model_dump(mode="json") for t in txns]
    response = JSONResponse(content=data)
    response.headers["X-Total-Count"] = str(total_count)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"
    return response


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
        raise HTTPException(status_code=409, detail=str(e)) from e
    return txn


@router.delete("/{txn_id}", status_code=204)
async def delete_transaction(
    txn_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Delete a transaction."""
    service = TransactionService(db)
    existing = await service.get_transaction_by_id(txn_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Transaction not found")
    ensure_user_owns_resource(existing.user_id, current_user)
    await service.delete_transaction(txn_id)
    return None
