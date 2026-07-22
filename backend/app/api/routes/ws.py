"""WebSocket routes for live dashboard updates."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.user import User
from app.security import decode_access_token, get_active_auth_session
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["WebSocket"])


def _origin_is_allowed(websocket: WebSocket) -> bool:
    settings = get_settings()
    origin = websocket.headers.get("origin")
    if not origin:
        return not settings.is_production
    return origin in settings.CORS_ORIGINS


async def _authorize_websocket_user(
    user_id: str,
    token: str | None,
    session_token: str | None,
) -> bool:
    settings = get_settings()
    if not token and not session_token and not settings.AUTH_REQUIRED:
        return True

    async with AsyncSessionLocal() as db:
        if session_token:
            session = await get_active_auth_session(session_token, db)
            if session is None or session.user_id != user_id:
                return False
        elif token:
            try:
                payload = decode_access_token(token)
            except Exception:
                return False
            if payload.get("sub") != user_id:
                return False
        else:
            return False
        result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        return result.scalar_one_or_none() is not None


@router.websocket("/sync")
async def sync_updates(
    websocket: WebSocket,
    user_id: str = Query(...),
    token: str | None = Query(default=None),
):
    """Stream sync progress events for one user."""
    settings = get_settings()
    if not _origin_is_allowed(websocket):
        await websocket.close(code=1008)
        return
    session_token = websocket.cookies.get(settings.SESSION_COOKIE_NAME)
    if settings.is_production and token:
        await websocket.close(code=1008)
        return
    if not await _authorize_websocket_user(user_id, token, session_token):
        await websocket.close(code=1008)
        return

    connected = await sync_event_manager.connect(
        user_id,
        websocket,
        max_connections=settings.WS_MAX_CONNECTIONS_PER_USER,
    )
    if not connected:
        return
    await sync_event_manager.broadcast(user_id, "ws_connected", {"status": "connected"})
    try:
        while True:
            # Client messages are optional heartbeats; receiving keeps the route alive.
            message = await websocket.receive_text()
            if len(message.encode("utf-8")) > settings.WS_MAX_MESSAGE_BYTES:
                await websocket.close(code=1009)
                return
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass
    except Exception as exc:
        logger.debug(
            "Sync WebSocket closed for user %s exception=%s",
            user_id[:8],
            type(exc).__name__,
        )
    finally:
        await sync_event_manager.disconnect(user_id, websocket)
