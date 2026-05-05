"""
Pydantic Schemas for Users
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    """Schema for creating a new user."""
    email: str = Field(..., description="User email address")
    name: str = Field(..., min_length=1, max_length=255)
    currency: str = Field(default="INR", max_length=3)


class UserResponse(BaseModel):
    """User response."""
    id: str
    email: str
    name: str
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}
