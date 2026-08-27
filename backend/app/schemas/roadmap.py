"""Contracts for roadmap extensions that depend on the trusted ledger."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal["manual", "email", "statement", "connector"]


class BillCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    financial_account_id: str | None = None
    label: str = Field(..., min_length=1, max_length=160)
    bill_type: Literal["bill", "subscription", "insurance", "utility", "rent"] = "bill"
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    due_date: date
    cadence: Literal["weekly", "monthly", "quarterly", "annual"] | None = None
    source_kind: SourceKind = "manual"
    source_identifier: str | None = Field(None, max_length=128)
    confirmed: bool = False


class BillUpdate(BaseModel):
    status: Literal["due", "due_soon", "paid", "skipped"] | None = None
    due_date: date | None = None
    amount: Decimal | None = Field(None, gt=0, max_digits=18, decimal_places=2)
    confirmed: bool | None = None


class BillResponse(BillCreate):
    id: str
    user_id: str
    status: str
    paid_at: datetime | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HealthChecklistUpsert(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    item_type: Literal[
        "emergency_fund",
        "health_insurance",
        "life_insurance",
        "nominee",
        "will",
        "other",
    ]
    label: str = Field(..., min_length=1, max_length=160)
    status: Literal["not_started", "in_progress", "complete", "not_applicable"]
    note: str | None = Field(None, max_length=500)


class HealthChecklistResponse(HealthChecklistUpsert):
    id: str
    user_id: str
    reviewed_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CardDisputeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    statement_line_id: str | None = None
    label: str = Field(..., min_length=1, max_length=160)
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    complaint_date: date
    reference_number: str | None = Field(None, max_length=100)
    note: str | None = Field(None, max_length=500)


class CardDisputeUpdate(BaseModel):
    status: Literal["open", "issuer_review", "resolved", "rejected"]
    reference_number: str | None = Field(None, max_length=100)
    note: str | None = Field(None, max_length=500)


class CardDisputeResponse(CardDisputeCreate):
    id: str
    user_id: str
    financial_account_id: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HouseholdCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)


class HouseholdMemberCreate(BaseModel):
    user_id: str
    role: Literal["member", "viewer"] = "member"
    visibility: Literal["annotations_only"] = "annotations_only"


class HouseholdMemberResponse(BaseModel):
    id: str
    household_id: str
    user_id: str
    role: Literal["owner", "member", "viewer"]
    visibility: Literal["annotations_only"]
    joined_at: datetime
    left_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class HouseholdMemberUpdate(BaseModel):
    role: Literal["member", "viewer"]
    visibility: Literal["annotations_only"] = "annotations_only"


class HouseholdSummary(BaseModel):
    id: str
    owner_user_id: str
    name: str
    member_count: int
    expense_count: int
    open_settlement_count: int
    created_at: datetime


class HouseholdExpenseCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    payer_user_id: str
    label: str = Field(..., min_length=1, max_length=160)
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    currency: str = Field("INR", pattern=r"^[A-Z]{3}$")
    expense_date: date
    splits: dict[str, Decimal] = Field(..., min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_splits(self) -> "HouseholdExpenseCreate":
        if any(value <= 0 for value in self.splits.values()):
            raise ValueError("Every household split must be positive")
        if sum(self.splits.values(), Decimal()) != self.amount:
            raise ValueError("Household splits must equal the expense amount")
        return self


class HouseholdExpenseResponse(HouseholdExpenseCreate):
    id: str
    household_id: str
    created_by_user_id: str
    created_at: datetime


class HouseholdSettlementCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    from_user_id: str
    to_user_id: str
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    currency: str = Field("INR", pattern=r"^[A-Z]{3}$")
    settlement_date: date
    status: Literal["planned", "recorded", "cancelled"] = "planned"
    note: str | None = Field(None, max_length=240)

    @model_validator(mode="after")
    def validate_parties(self) -> "HouseholdSettlementCreate":
        if self.from_user_id == self.to_user_id:
            raise ValueError("A household settlement needs two different members")
        return self


class HouseholdSettlementResponse(HouseholdSettlementCreate):
    id: str
    household_id: str
    created_by_user_id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HouseholdSettlementUpdate(BaseModel):
    status: Literal["planned", "recorded", "cancelled"]
    note: str | None = Field(None, max_length=240)


class PayoffDebt(BaseModel):
    liability_id: str
    label: str
    starting_balance: float
    annual_interest_rate: float
    minimum_payment: float


class PayoffScenario(BaseModel):
    method: Literal["highest_interest_first", "smallest_balance_first"]
    payoff_order: list[str]
    estimated_months: int | None
    estimated_interest: float | None


class PayoffComparisonResponse(BaseModel):
    readiness: Literal["ready", "needs_complete_liabilities", "insufficient_budget"]
    monthly_budget: float
    debts: list[PayoffDebt]
    excluded_liability_ids: list[str]
    scenarios: list[PayoffScenario]
    assumptions: list[str]
