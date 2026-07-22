"""Account, balance, net-worth, and transfer API contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BalanceKind = Literal["asset", "liability"]


class FinancialAccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    institution_name: str = Field(..., min_length=1, max_length=160)
    account_type: str = Field(default="cash", min_length=1, max_length=40)
    balance_kind: BalanceKind = "asset"
    masked_number: str = Field(..., min_length=2, max_length=32)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FinancialAccountUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    institution_name: str | None = Field(None, min_length=1, max_length=160)
    account_type: str | None = Field(None, min_length=1, max_length=40)
    balance_kind: BalanceKind | None = None
    masked_number: str | None = Field(None, min_length=2, max_length=32)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    is_active: bool | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FinancialAccountResponse(BaseModel):
    id: str
    user_id: str
    institution_name: str
    account_type: str
    balance_kind: BalanceKind
    masked_number: str
    currency: str
    is_active: bool
    latest_balance: float | None = None
    balance_as_of: date | None = None
    created_at: datetime


class BalanceSnapshotCreate(BaseModel):
    amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    as_of: date

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class BalanceSnapshotResponse(BaseModel):
    id: str
    financial_account_id: str
    amount: float
    currency: str
    as_of: date
    source: str
    created_at: datetime


class NetWorthPoint(BaseModel):
    date: date
    assets: float
    liabilities: float
    net_worth: float


class NetWorthSeries(BaseModel):
    currency: str
    as_of: date | None = None
    assets: float = 0.0
    liabilities: float = 0.0
    net_worth: float = 0.0
    points: list[NetWorthPoint] = Field(default_factory=list)


class TransferCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    from_account_id: str
    to_account_id: str
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    transaction_date: date
    description: str | None = Field(None, max_length=160)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def different_accounts(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("Transfer accounts must be different")
        return self


class TransferResponse(BaseModel):
    transfer_group_id: str
    debit_transaction_id: str
    credit_transaction_id: str
    amount: float
    currency: str
    transaction_date: date
