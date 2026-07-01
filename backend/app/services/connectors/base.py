"""Base connector contracts for source ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from app.services.connectors.source_record import SourceRecord


class ConnectorErrorType(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConnectorCursor:
    history_id: str | None = None
    fallback_used: bool = False


@dataclass(frozen=True)
class ConnectorError:
    error_type: ConnectorErrorType
    message: str
    retryable: bool


@dataclass(frozen=True)
class ConnectorBatch:
    records: list[SourceRecord]
    cursor: ConnectorCursor
    metrics: dict[str, int | float | bool] = field(default_factory=dict)
    errors: list[ConnectorError] = field(default_factory=list)


@dataclass(frozen=True)
class BackfillOptions:
    max_results: int | None = 500


class BaseConnector(Protocol):
    source_type: str

    async def fetch_incremental(self, user_id: str, cursor: ConnectorCursor) -> ConnectorBatch:
        ...

    async def fetch_backfill(self, user_id: str, options: BackfillOptions) -> ConnectorBatch:
        ...

    async def refresh_credentials(self) -> dict[str, Any]:
        ...
