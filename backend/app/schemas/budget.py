"""Budget schemas — Pydantic models for budget CRUD and tracking."""

from pydantic import BaseModel, Field


class BudgetCreate(BaseModel):
    category_id: str
    monthly_limit: float = Field(..., gt=0)


class BudgetUpdate(BaseModel):
    monthly_limit: float = Field(..., gt=0)


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
