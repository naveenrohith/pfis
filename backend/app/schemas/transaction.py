"""
Pydantic Schemas for Transactions
Request/response validation and serialization.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

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


class PaymentRailEnum(str, Enum):
    UPI = "upi"
    DEBIT_CARD = "debit_card"
    ATM = "atm"
    TRANSFER = "transfer"
    WALLET = "wallet"
    OTHER = "other"


class CardEventEnum(str, Enum):
    NONE = "none"
    PURCHASE = "purchase"
    PAYMENT = "payment"
    REFUND = "refund"
    CASHBACK = "cashback"
    FEE = "fee"
    TAX = "tax"
    INTEREST = "interest"
    REVERSAL = "reversal"


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
    payment_rail: PaymentRailEnum = PaymentRailEnum.OTHER
    card_event: CardEventEnum = CardEventEnum.NONE
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
    source_kind: str = Field(default="manual", max_length=24)
    source_identifier: str | None = Field(None, max_length=128)

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
    payment_rail: PaymentRailEnum | None = None
    card_event: CardEventEnum | None = None
    transaction_status: str | None = Field(None, min_length=1, max_length=24)
    amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    financial_account_id: str | None = Field(None, max_length=36)
    reviewed_flag: bool | None = None
    note: str | None = Field(None, max_length=1000)
    tags: list[str] | None = Field(None, max_length=20)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_tag in value:
            tag = raw_tag.strip()
            if not tag:
                continue
            if len(tag) > 32:
                raise ValueError("Tags must be 32 characters or fewer")
            key = tag.casefold()
            if key not in seen:
                normalized.append(tag)
                seen.add(key)
        return normalized


class BulkTransactionUpdate(BaseModel):
    """Schema for updating multiple transactions at once."""

    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_ids: list[str] = Field(..., min_length=1)
    category_id: str | None = Field(None, max_length=36)
    transaction_type: TransactionTypeEnum | None = None
    payment_method: PaymentMethodEnum | None = None
    payment_rail: PaymentRailEnum | None = None
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
    payment_rail: PaymentRailEnum = PaymentRailEnum.OTHER
    card_event: CardEventEnum = CardEventEnum.NONE
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
    is_accounting_adjustment: bool = False
    ledger_subtype: str | None = None
    source_kind: str = "manual"
    source_identifier: str | None = None
    review_outcome: str = "newly_imported"
    note: str | None = None
    tags: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TransactionSplitCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(..., min_length=1, max_length=120)
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    category_id: str | None = Field(None, max_length=36)


class TransactionSplitReplace(BaseModel):
    splits: list[TransactionSplitCreate] = Field(..., min_length=2, max_length=20)


class TransactionSplitResponse(BaseModel):
    id: str
    transaction_id: str
    user_id: str
    label: str
    amount: float
    category_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AtmCashLinkRequest(BaseModel):
    cash_account_id: str = Field(..., min_length=1, max_length=36)


class TransferMatchLinkRequest(BaseModel):
    """Confirm a proposed pair of imported account ledger legs."""

    counterparty_transaction_id: str = Field(..., min_length=1, max_length=36)
    kind: Literal["card_payment", "account_transfer"]


class TransferMatchCandidate(BaseModel):
    """Deterministic, reviewable candidate for two imported ledger legs."""

    candidate_id: str
    debit_transaction_id: str
    credit_transaction_id: str
    debit_account_id: str
    debit_account_label: str
    credit_account_id: str
    credit_account_label: str
    amount: float
    currency: str
    debit_date: date
    credit_date: date
    date_difference_days: int
    kind: Literal["card_payment", "account_transfer"]
    confidence: float = Field(..., ge=0, le=1)
    ambiguous: bool = False
    reason_codes: list[str] = Field(default_factory=list)


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
