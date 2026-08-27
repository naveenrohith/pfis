"""
Pydantic Schemas for Users
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.financial_time import DEFAULT_USER_TIMEZONE, validate_timezone_name


class UserCreate(BaseModel):
    """Schema for creating a new user."""

    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(..., description="User email address")
    name: str = Field(..., min_length=1, max_length=255)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    timezone: str = Field(default=DEFAULT_USER_TIMEZONE, min_length=1, max_length=64)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return validate_timezone_name(value)


class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(None, min_length=1, max_length=255)
    timezone: str | None = Field(None, min_length=1, max_length=64)
    raw_email_retention_days: int | None = Field(default=None)

    @field_validator("raw_email_retention_days")
    @classmethod
    def validate_raw_email_retention_days(cls, value: int | None) -> int | None:
        if value not in {None, 30, 90, 180, 365}:
            raise ValueError("retention must be 30, 90, 180, 365 days, or null")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return validate_timezone_name(value) if value is not None else None


class UserResponse(BaseModel):
    """User response."""

    id: str
    email: str
    name: str
    currency: str
    timezone: str
    raw_email_retention_days: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountDeletionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    confirmation: str = Field(..., min_length=8, max_length=320)


class AccountDeletionResponse(BaseModel):
    status: str
    deleted_at: datetime
    provider_revocation: str
    private_rows_deleted: int
    households_deleted: int
    household_ownership_transferred: int
    household_memberships_closed: int
