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
    def __init__(self, *, send_timeout_seconds: float = 5.0) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._send_timeout_seconds = send_timeout_seconds

    async def connect(
        self,
        user_id: str,
        websocket: WebSocket,
        *,
        max_connections: int | None = None,
    ) -> bool:
        rejected = False
        async with self._lock:
            sockets = self._connections.setdefault(user_id, set())
            if max_connections is not None and len(sockets) >= max_connections:
                rejected = True
            else:
                sockets.add(websocket)
        if rejected:
            await websocket.close(code=1013)
            return False
        try:
            await websocket.accept()
        except Exception:
            await self.disconnect(user_id, websocket)
            raise
        return True

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

        async def send(websocket: WebSocket) -> WebSocket | None:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await asyncio.wait_for(
                        websocket.send_json(payload),
                        timeout=self._send_timeout_seconds,
                    )
                    return None
                if websocket.client_state != WebSocketState.DISCONNECTED:
                    return None
            except Exception:
                logger.debug("Dropping stale sync WebSocket for user %s", user_id[:8])
            return websocket

        stale = [
            websocket
            for websocket in await asyncio.gather(*(send(socket) for socket in sockets))
            if websocket is not None
        ]
        await asyncio.gather(*(self.disconnect(user_id, socket) for socket in stale))

    async def connection_count(self, user_id: str) -> int:
        async with self._lock:
            return len(self._connections.get(user_id, set()))


sync_event_manager = SyncEventManager()
