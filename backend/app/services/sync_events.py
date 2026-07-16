"""User-scoped WebSocket event broadcasting for sync progress."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)


class SyncEventManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(websocket)

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(user_id)
            if not sockets:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(user_id, None)

    async def broadcast(self, user_id: str, event: str, data: dict[str, Any] | None = None) -> None:
        payload = {
            "event": event,
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data or {},
        }
        async with self._lock:
            sockets = list(self._connections.get(user_id, set()))

        stale: list[WebSocket] = []
        for websocket in sockets:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(payload)
                else:
                    stale.append(websocket)
            except Exception:
                stale.append(websocket)
                logger.debug("Dropping stale sync WebSocket for user %s", user_id[:8])

        for websocket in stale:
            await self.disconnect(user_id, websocket)

    async def connection_count(self, user_id: str) -> int:
        async with self._lock:
            return len(self._connections.get(user_id, set()))


sync_event_manager = SyncEventManager()
