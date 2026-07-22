"""Schemas for background job orchestration APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: str
    user_id: str | None = None
    job_type: str
    status: str
    payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    error_message: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
