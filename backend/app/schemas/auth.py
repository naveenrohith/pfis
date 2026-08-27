"""Authentication schemas for registration and login."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.user import UserResponse
from app.utils.financial_time import DEFAULT_USER_TIMEZONE, validate_timezone_name


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=12, max_length=128)
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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class AuthSessionResponse(BaseModel):
    """Browser-safe authentication response; the session remains in an HttpOnly cookie."""

    expires_in: int
    mode: str = "auth"
    csrf_cookie_name: str
    user: UserResponse


class LogoutResponse(BaseModel):
    status: str = "signed_out"


class AuthMeResponse(UserResponse):
    is_active: bool
