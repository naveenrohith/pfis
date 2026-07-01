"""In-process domain events for ingestion and sync workflows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.connectors.source_record import SourceType


@dataclass(frozen=True)
class DomainEvent:
    type: str
    user_id: str
    source_type: SourceType
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


EventHandler = Callable[[DomainEvent], Awaitable[None]]


class DomainEventDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers.get(event.type, []):
            await handler(event)


domain_event_dispatcher = DomainEventDispatcher()
