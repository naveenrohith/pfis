"""
Budget Routes — Phase 6
CRUD endpoints for category budgets and budget-vs-actual tracking.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.sync import Budget
from app.models.transaction import Transaction, TransactionType
from app.models.category import Category
from app.models.user import User
from app.security import ensure_user_owns_resource, get_current_user_optional, resolve_user_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/budgets", tags=["Budgets"])


# ─── Schemas ───

class BudgetCreate(BaseModel):
    category_id: str
    monthly_limit: float = Field(..., gt=0)

class BudgetUpdate(BaseModel):
    monthly_limit: float = Field(..., gt=0)

class BudgetResponse(BaseModel):
    id: str
    user_id: str
    category_id: str
    category_name: Optional[str] = None
    category_icon: Optional[str] = None
    monthly_limit: float

    model_config = {"from_attributes": True}

class BudgetTracker(BaseModel):
    """Budget with actual spend for the given month."""
    id: str
    category_id: str
    category_name: str
    category_icon: Optional[str]
    monthly_limit: float
    actual_spend: float
    remaining: float
    usage_pct: float
    status: str  # under, warning, over


# ─── CRUD ───

@router.post("/", status_code=201)
async def create_budget(
    user_id: str = Query(...),
    data: BudgetCreate = ...,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Create a monthly budget for a category."""
    user_id = resolve_user_scope(user_id, current_user)
    # Check if budget already exists for this user+category
    existing = await db.execute(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.category_id == data.category_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Budget already exists for this category")

    budget = Budget(
        user_id=user_id,
        category_id=data.category_id,
        monthly_limit=data.monthly_limit,
    )
    db.add(budget)
    await db.commit()
    await db.refresh(budget)

    logger.info(f"Budget created: category={data.category_id} limit=₹{data.monthly_limit}")
    return {"id": budget.id, "status": "created"}


@router.get("/", response_model=list[BudgetResponse])
async def list_budgets(
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List all budgets for a user."""
    user_id = resolve_user_scope(user_id, current_user)
    result = await db.execute(
        select(Budget, Category.name, Category.icon)
        .join(Category, Budget.category_id == Category.id, isouter=True)
        .where(Budget.user_id == user_id)
        .order_by(Category.name)
    )
    rows = result.all()
    return [
        BudgetResponse(
            id=b.id, user_id=b.user_id, category_id=b.category_id,
            category_name=name, category_icon=icon,
            monthly_limit=b.monthly_limit,
        )
        for b, name, icon in rows
    ]


@router.patch("/{budget_id}")
async def update_budget(
    budget_id: str,
    data: BudgetUpdate,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Update a budget's monthly limit."""
    result = await db.execute(select(Budget).where(Budget.id == budget_id))
    budget = result.scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    ensure_user_owns_resource(budget.user_id, current_user)

    budget.monthly_limit = data.monthly_limit
    await db.commit()
    return {"id": budget_id, "monthly_limit": data.monthly_limit, "status": "updated"}


@router.delete("/{budget_id}")
async def delete_budget(
    budget_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Delete a budget."""
    result = await db.execute(select(Budget).where(Budget.id == budget_id))
    budget = result.scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    ensure_user_owns_resource(budget.user_id, current_user)

    await db.delete(budget)
    await db.commit()
    return {"status": "deleted"}


# ─── Budget Tracking ───

@router.get("/track", response_model=list[BudgetTracker])
async def track_budgets(
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Get budget vs actual spending for all budgeted categories.
    Returns usage percentage and status (under/warning/over).
    """
    user_id = resolve_user_scope(user_id, current_user)
    # Get all budgets
    budget_result = await db.execute(
        select(Budget, Category.name, Category.icon)
        .join(Category, Budget.category_id == Category.id)
        .where(Budget.user_id == user_id)
    )
    budgets = budget_result.all()

    if not budgets:
        return []

    # Get actual spend per category for the month
    spend_result = await db.execute(
        select(
            Transaction.category_id,
            func.coalesce(func.sum(Transaction.amount), 0).label("total"),
        )
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.DEBIT,
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        )
        .group_by(Transaction.category_id)
    )
    spend_map = {row.category_id: float(row.total) for row in spend_result.all()}

    trackers = []
    for budget, cat_name, cat_icon in budgets:
        actual = spend_map.get(budget.category_id, 0)
        remaining = budget.monthly_limit - actual
        pct = (actual / budget.monthly_limit * 100) if budget.monthly_limit > 0 else 0

        if pct >= 100:
            status = "over"
        elif pct >= 80:
            status = "warning"
        else:
            status = "under"

        trackers.append(BudgetTracker(
            id=budget.id,
            category_id=budget.category_id,
            category_name=cat_name,
            category_icon=cat_icon,
            monthly_limit=budget.monthly_limit,
            actual_spend=actual,
            remaining=remaining,
            usage_pct=round(pct, 1),
            status=status,
        ))

    # Sort: over first, then warning, then under
    priority = {"over": 0, "warning": 1, "under": 2}
    trackers.sort(key=lambda t: (priority.get(t.status, 3), -t.usage_pct))

    return trackers
