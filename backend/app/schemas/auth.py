"""Authentication schemas for registration and login."""

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserResponse


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=12, max_length=128)
    currency: str = Field(default="INR", min_length=3, max_length=3)


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
