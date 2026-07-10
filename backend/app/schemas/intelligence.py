"""Schemas for merchant, category, analytics, goals, and explanations."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "success", "warning", "danger"]
GoalType = Literal["savings", "category_reduction", "recurring_reduction"]


class TransactionPreview(BaseModel):
    id: str
    merchant: str
    category: str | None = None
    amount: float
    transaction_type: str
    transaction_date: date
    confidence_score: float
    reviewed_flag: bool


class MerchantSummary(BaseModel):
    merchant_key: str
    name: str
    total_spend: float = 0.0
    transaction_count: int = 0
    avg_spend: float = 0.0
    month_change_pct: float | None = None
    category: str | None = None
    category_id: str | None = None
    recurrence_likelihood: float = 0.0
    latest_transaction_date: date | None = None


class MerchantDetail(MerchantSummary):
    aliases: list[str] = Field(default_factory=list)
    default_category_id: str | None = None
    latest_transactions: list[TransactionPreview] = Field(default_factory=list)


class MerchantUpdate(BaseModel):
    normalized_name: str | None = Field(None, min_length=1, max_length=255)
    default_category_id: str | None = None
    aliases: list[str] | None = None
    apply_existing: bool = True


class CategoryTopMerchant(BaseModel):
    name: str
    total: float
    count: int


class CategoryIntelligenceItem(BaseModel):
    category_id: str | None
    name: str
    parent_category_id: str | None = None
    parent_name: str | None = None
    icon: str | None = None
    total_spend: float = 0.0
    transaction_count: int = 0
    month_change_pct: float | None = None
    budget_limit: float | None = None
    budget_usage_pct: float | None = None
    top_merchants: list[CategoryTopMerchant] = Field(default_factory=list)


class CategoryIntelligenceResponse(BaseModel):
    month: int
    year: int
    categories: list[CategoryIntelligenceItem] = Field(default_factory=list)


class CashFlowProjection(BaseModel):
    month: int
    year: int
    income: float = 0.0
    spend_to_date: float = 0.0
    net_to_date: float = 0.0
    projected_spend: float = 0.0
    projected_net: float = 0.0
    daily_spend_rate: float = 0.0
    days_elapsed: int = 0
    days_in_month: int = 0


class MonthComparison(BaseModel):
    month: int
    year: int
    previous_month: int
    previous_year: int
    income: float = 0.0
    previous_income: float = 0.0
    spend: float = 0.0
    previous_spend: float = 0.0
    savings: float = 0.0
    previous_savings: float = 0.0
    spend_change_pct: float | None = None
    income_change_pct: float | None = None
    category_deltas: list[dict] = Field(default_factory=list)


class FinancialHealthScore(BaseModel):
    score: int
    savings_rate: float = 0.0
    budget_adherence: float = 100.0
    recurring_burden: float = 0.0
    review_cleanliness: float = 100.0
    signals: list[dict] = Field(default_factory=list)


class GoalCreate(BaseModel):
    goal_type: GoalType
    label: str = Field(..., min_length=1, max_length=160)
    target_amount: float = Field(..., gt=0)
    target_key: str | None = Field(None, max_length=160)
    target_month: int | None = Field(None, ge=1, le=12)
    target_year: int | None = Field(None, ge=2020, le=2030)


class GoalUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=160)
    target_amount: float | None = Field(None, gt=0)
    target_key: str | None = Field(None, max_length=160)
    target_month: int | None = Field(None, ge=1, le=12)
    target_year: int | None = Field(None, ge=2020, le=2030)
    is_active: bool | None = None


class GoalResponse(BaseModel):
    id: str
    user_id: str
    goal_type: GoalType
    label: str
    target_amount: float
    target_key: str | None = None
    target_month: int | None = None
    target_year: int | None = None
    is_active: bool = True
    current_amount: float = 0.0
    progress_pct: float = 0.0
    status: str = "tracking"
    created_at: datetime


class ExplainRequest(BaseModel):
    surface: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    metrics: dict = Field(default_factory=dict)


class ExplainResponse(BaseModel):
    surface: str
    summary: str
    drivers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    safety_note: str
