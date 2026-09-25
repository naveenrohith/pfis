"""Budget schemas — Pydantic models for budget CRUD and tracking."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class BudgetCreate(BaseModel):
    category_id: str
    monthly_limit: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)


class BudgetUpdate(BaseModel):
    monthly_limit: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)


class BudgetResponse(BaseModel):
    id: str
    user_id: str
    category_id: str
    category_name: str | None = None
    category_icon: str | None = None
    monthly_limit: float

    model_config = {"from_attributes": True}


class BudgetTracker(BaseModel):
    """Budget with actual spend for the given month."""

    id: str
    category_id: str
    category_name: str
    category_icon: str | None
    monthly_limit: float
    actual_spend: float
    remaining: float
    usage_pct: float
    status: str  # under, warning, over


class BudgetDrilldownTransaction(BaseModel):
    """One ledger row contributing to a budget's monthly actual spend."""

    id: str
    transaction_date: date
    merchant: str | None
    transaction_type: str
    amount: float
    spend_effect: float
    currency: str


class BudgetDrilldown(BaseModel):
    """Budget tracker for one month plus the transactions behind its actual spend."""

    budget: BudgetTracker
    month: int
    year: int
    transaction_count: int
    transactions: list[BudgetDrilldownTransaction]
    has_more: bool
