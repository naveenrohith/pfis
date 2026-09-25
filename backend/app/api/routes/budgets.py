"""
Budget Routes — Phase 6
CRUD endpoints for category budgets and budget-vs-actual tracking.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import extract, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.category import Category
from app.models.sync import Budget
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.budget import (
    BudgetCreate,
    BudgetDrilldown,
    BudgetDrilldownTransaction,
    BudgetResponse,
    BudgetTracker,
    BudgetUpdate,
)
from app.security import ensure_user_owns_resource, get_current_user_optional, resolve_user_scope
from app.services.transaction_aggregates import (
    spend_effect_expression,
    spend_event_predicate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/budgets", tags=["Budgets"])


# ─── CRUD ───


@router.post("/", status_code=201)
async def create_budget(
    data: BudgetCreate = Body(...),
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Create a monthly budget for a category."""
    user_id = resolve_user_scope(user_id, current_user)
    category = await db.scalar(select(Category.id).where(Category.id == data.category_id))
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
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
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Budget already exists for this category"
        ) from exc
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
            id=b.id,
            user_id=b.user_id,
            category_id=b.category_id,
            category_name=name,
            category_icon=icon,
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
            func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
        )
        .where(
            Transaction.user_id == user_id,
            spend_event_predicate(),
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        )
        .group_by(Transaction.category_id)
        .having(func.sum(spend_effect_expression()) > 0)
    )
    spend_map = {row.category_id: float(row.total) for row in spend_result.all()}

    trackers = [
        _build_tracker(budget, cat_name, cat_icon, spend_map.get(budget.category_id, 0))
        for budget, cat_name, cat_icon in budgets
    ]

    # Sort: over first, then warning, then under
    priority = {"over": 0, "warning": 1, "under": 2}
    trackers.sort(key=lambda t: (priority.get(t.status, 3), -t.usage_pct))

    return trackers


@router.get("/{budget_id}/drilldown", response_model=BudgetDrilldown)
async def budget_drilldown(
    budget_id: str,
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    limit: int = Query(100, ge=1, le=500),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return one budget's monthly tracker and the transactions behind its actual spend.

    Uses the same spend semantics as ``/track`` so the listed rows reconcile
    with ``actual_spend``: debits add, refunds subtract, and transfers,
    accounting adjustments, ignored, pending, and foreign-currency rows are
    excluded.
    """
    result = await db.execute(
        select(Budget, Category.name, Category.icon)
        .join(Category, Budget.category_id == Category.id)
        .where(Budget.id == budget_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    budget, cat_name, cat_icon = row
    ensure_user_owns_resource(budget.user_id, current_user)

    scope = (
        Transaction.user_id == budget.user_id,
        Transaction.category_id == budget.category_id,
        spend_event_predicate(),
        extract("month", Transaction.transaction_date) == month,
        extract("year", Transaction.transaction_date) == year,
    )
    totals = (
        await db.execute(
            select(
                func.count(Transaction.id).label("count"),
                func.coalesce(func.sum(spend_effect_expression()), 0).label("total"),
            ).where(*scope)
        )
    ).one()
    # /track only reports positive net spend per category; mirror that clamp.
    actual = max(float(totals.total), 0.0)

    txn_rows = (
        await db.execute(
            select(
                Transaction.id,
                Transaction.transaction_date,
                Transaction.merchant_normalized,
                Transaction.merchant_raw,
                Transaction.transaction_type,
                Transaction.amount,
                Transaction.currency,
                spend_effect_expression().label("spend_effect"),
            )
            .where(*scope)
            .order_by(
                Transaction.transaction_date.desc(),
                Transaction.amount.desc(),
                Transaction.id,
            )
            .limit(limit)
        )
    ).all()

    return BudgetDrilldown(
        budget=_build_tracker(budget, cat_name, cat_icon, actual),
        month=month,
        year=year,
        transaction_count=int(totals._mapping["count"]),
        has_more=int(totals._mapping["count"]) > len(txn_rows),
        transactions=[
            BudgetDrilldownTransaction(
                id=txn.id,
                transaction_date=txn.transaction_date,
                merchant=txn.merchant_normalized or txn.merchant_raw,
                transaction_type=str(
                    getattr(txn.transaction_type, "value", txn.transaction_type)
                ).lower(),
                amount=float(txn.amount),
                spend_effect=float(txn.spend_effect),
                currency=txn.currency,
            )
            for txn in txn_rows
        ],
    )


def _build_tracker(
    budget: Budget, cat_name: str, cat_icon: str | None, actual: float
) -> BudgetTracker:
    limit = float(budget.monthly_limit)
    pct = (actual / limit * 100) if limit > 0 else 0

    if pct >= 100:
        status = "over"
    elif pct >= 80:
        status = "warning"
    else:
        status = "under"

    return BudgetTracker(
        id=budget.id,
        category_id=budget.category_id,
        category_name=cat_name,
        category_icon=cat_icon,
        monthly_limit=limit,
        actual_spend=actual,
        remaining=limit - actual,
        usage_pct=round(pct, 1),
        status=status,
    )
