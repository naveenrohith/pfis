"""
Pydantic Schemas for Transactions
Request/response validation and serialization.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionTypeEnum(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    REFUND = "refund"


class PaymentMethodEnum(str, Enum):
    UPI = "upi"
    DEBIT_CARD = "debit_card"
    CREDIT_CARD = "credit_card"
    EMI = "emi"
    PAY_LATER = "pay_later"
    WALLET = "wallet"
    BANK_TRANSFER = "bank_transfer"
    OTHER = "other"


# --- Request Schemas ---


class TransactionCreate(BaseModel):
    """Schema for creating a new transaction (manual or parsed)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal = Field(
        ..., gt=0, max_digits=18, decimal_places=2, description="Transaction amount"
    )
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    transaction_type: TransactionTypeEnum
    payment_method: PaymentMethodEnum = PaymentMethodEnum.OTHER
    transaction_status: str = Field(default="completed", min_length=1, max_length=24)
    transaction_timestamp: datetime | None = None
    merchant_raw: str | None = Field(None, max_length=255)
    merchant_normalized: str | None = Field(None, max_length=255)
    category_id: str | None = Field(None, max_length=36)
    transaction_date: date
    account_last4: str | None = Field(None, max_length=4)
    reference_id: str | None = Field(None, max_length=100)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    parser_version: int = Field(default=1, ge=1)
    merchant_resolution_source: str = Field(default="manual", max_length=32)
    merchant_resolution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    merchant_rule_id: str | None = Field(default=None, max_length=36)
    merchant_resolver_version: int = Field(default=1, ge=1)
    source_email_id: str | None = Field(None, max_length=36)
    financial_account_id: str | None = Field(None, max_length=36)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class TransactionUpdate(BaseModel):
    """Schema for updating transaction fields (user corrections)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    merchant_normalized: str | None = Field(None, max_length=255)
    category_id: str | None = Field(None, max_length=36)
    transaction_type: TransactionTypeEnum | None = None
    payment_method: PaymentMethodEnum | None = None
    transaction_status: str | None = Field(None, min_length=1, max_length=24)
    amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    reviewed_flag: bool | None = None


class BulkTransactionUpdate(BaseModel):
    """Schema for updating multiple transactions at once."""

    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_ids: list[str] = Field(..., min_length=1)
    category_id: str | None = Field(None, max_length=36)
    transaction_type: TransactionTypeEnum | None = None
    payment_method: PaymentMethodEnum | None = None
    reviewed_flag: bool | None = None


class BulkTransactionUpdateResponse(BaseModel):
    requested_count: int
    updated_count: int
    failed: list[dict] = Field(default_factory=list)


# --- Response Schemas ---


class TransactionResponse(BaseModel):
    """Full transaction response."""

    id: str
    user_id: str
    amount: float
    currency: str
    transaction_type: TransactionTypeEnum
    payment_method: PaymentMethodEnum
    transaction_status: str
    transaction_timestamp: datetime | None = None
    merchant_raw: str | None
    merchant_normalized: str | None
    category_id: str | None
    category_name: str | None = None
    transaction_date: date
    account_last4: str | None
    reference_id: str | None
    confidence_score: float
    reviewed_flag: bool = False
    reviewed_at: datetime | None = None
    parser_version: int
    merchant_resolution_source: str = "legacy"
    merchant_resolution_confidence: float | None = None
    merchant_rule_id: str | None = None
    merchant_resolver_version: int = 1
    created_at: datetime
    source_received_at: datetime | None = None
    financial_account_id: str | None = None
    transfer_group_id: str | None = None
    is_transfer: bool = False

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
    icon: str | None

    model_config = {"from_attributes": True}
