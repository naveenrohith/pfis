"""API schemas for durable financial change replay."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FinancialChangeEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    sequence: int
    event_type: str
    domains: list[str]
    created_at: datetime


class FinancialChangePageResponse(BaseModel):
    events: list[FinancialChangeEventResponse]
    current_sequence: int = Field(ge=0)
    oldest_available_sequence: int | None = Field(default=None, ge=1)
    has_more: bool
    reset_required: bool
