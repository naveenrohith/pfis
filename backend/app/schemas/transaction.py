"""
Pydantic Schemas for Transactions
Request/response validation and serialization.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import date, datetime
from enum import Enum


class TransactionTypeEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    REFUND = "refund"


# --- Request Schemas ---

class TransactionCreate(BaseModel):
    """Schema for creating a new transaction (manual or parsed)."""
    amount: float = Field(..., gt=0, description="Transaction amount")
    currency: str = Field(default="INR", max_length=3)
    transaction_type: TransactionTypeEnum
    merchant_raw: Optional[str] = None
    merchant_normalized: Optional[str] = None
    category_id: Optional[str] = None
    transaction_date: date
    account_last4: Optional[str] = Field(None, max_length=4)
    reference_id: Optional[str] = None
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source_email_id: Optional[str] = None


class TransactionUpdate(BaseModel):
    """Schema for updating transaction fields (user corrections)."""
    merchant_normalized: Optional[str] = None
    category_id: Optional[str] = None
    transaction_type: Optional[TransactionTypeEnum] = None
    amount: Optional[float] = Field(None, gt=0)
    reviewed_flag: Optional[bool] = None


class BulkTransactionUpdate(BaseModel):
    """Schema for updating multiple transactions at once."""
    transaction_ids: list[str] = Field(..., min_length=1)
    category_id: Optional[str] = None
    transaction_type: Optional[TransactionTypeEnum] = None
    reviewed_flag: Optional[bool] = None


class BulkTransactionUpdateResponse(BaseModel):
    requested_count: int
    updated_count: int
    failed: list[dict] = []


# --- Response Schemas ---

class TransactionResponse(BaseModel):
    """Full transaction response."""
    id: str
    user_id: str
    amount: float
    currency: str
    transaction_type: TransactionTypeEnum
    merchant_raw: Optional[str]
    merchant_normalized: Optional[str]
    category_id: Optional[str]
    category_name: Optional[str] = None
    transaction_date: date
    account_last4: Optional[str]
    reference_id: Optional[str]
    confidence_score: float
    reviewed_flag: bool = False
    reviewed_at: Optional[datetime] = None
    parser_version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionSummary(BaseModel):
    """Monthly summary response."""
    total_spend: float
    total_income: float
    net: float
    transaction_count: int
    month: str
    category_breakdown: list[dict] = []
    top_merchants: list[dict] = []


class CategoryResponse(BaseModel):
    """Category response."""
    id: str
    name: str
    icon: Optional[str]

    model_config = {"from_attributes": True}
