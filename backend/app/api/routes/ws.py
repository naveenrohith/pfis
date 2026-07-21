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
    session_token = websocket.cookies.get(settings.SESSION_COOKIE_NAME)
    if not await _authorize_websocket_user(user_id, token, session_token):
        await websocket.close(code=1008)
        return

    await sync_event_manager.connect(user_id, websocket)
    await sync_event_manager.broadcast(user_id, "ws_connected", {"status": "connected"})
    try:
        while True:
            # Client messages are optional heartbeats; receiving keeps the route alive.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except RuntimeError:
        pass
    except Exception as exc:
        logger.debug("Sync WebSocket closed for user %s: %s", user_id[:8], exc)
    finally:
        await sync_event_manager.disconnect(user_id, websocket)
