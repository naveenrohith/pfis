"""Realtime channel security, isolation, and backpressure regressions."""

from __future__ import annotations

import asyncio

from app.api.routes.ws import _authorize_websocket_user, _origin_is_allowed, sync_updates
from app.config import get_settings
from app.security import create_access_token
from app.services.sync_events import SyncEventManager, sync_event_manager
from starlette.websockets import WebSocketDisconnect, WebSocketState

from tests.pytest.helpers import create_user


class FakeWebSocket:
    def __init__(
        self,
        *,
        origin: str | None = None,
        cookies: dict[str, str] | None = None,
        incoming: list[str] | None = None,
    ) -> None:
        self.headers = {"origin": origin} if origin else {}
        self.cookies = cookies or {}
        self.client_state = WebSocketState.CONNECTED
        self.incoming = list(incoming or [])
        self.accepted = False
        self.close_code: int | None = None
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.close_code = code
        self.client_state = WebSocketState.DISCONNECTED

    async def receive_text(self) -> str:
        if self.incoming:
            return self.incoming.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


class SlowWebSocket(FakeWebSocket):
    async def send_json(self, payload: dict) -> None:
        await asyncio.sleep(0.1)
        self.messages.append(payload)


def test_websocket_origin_must_match_configured_origin(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://money.example"])

    assert _origin_is_allowed(FakeWebSocket(origin="https://money.example"))  # type: ignore[arg-type]
    assert not _origin_is_allowed(FakeWebSocket(origin="https://attacker.example"))  # type: ignore[arg-type]


async def test_production_websocket_rejects_missing_origin_and_query_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://money.example"])

    missing_origin = FakeWebSocket()
    await sync_updates(missing_origin, user_id="user", token=None)  # type: ignore[arg-type]

    query_token = FakeWebSocket(origin="https://money.example")
    await sync_updates(query_token, user_id="user", token="secret-in-url")  # type: ignore[arg-type]

    assert missing_origin.close_code == 1008
    assert missing_origin.accepted is False
    assert query_token.close_code == 1008
    assert query_token.accepted is False


async def test_production_websocket_accepts_allowed_origin_and_revocable_session(
    client, monkeypatch
):
    login = await client.post(
        "/api/auth/login",
        json={"email": "demo@pfis.app", "password": "demo12345"},
    )
    login.raise_for_status()
    user_id = login.json()["user"]["id"]
    settings = get_settings()
    session_token = login.cookies.get(settings.SESSION_COOKIE_NAME)
    assert session_token
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://money.example"])
    websocket = FakeWebSocket(
        origin="https://money.example",
        cookies={settings.SESSION_COOKIE_NAME: session_token},
    )

    await sync_updates(websocket, user_id=user_id, token=None)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert [message["event"] for message in websocket.messages] == ["ws_connected"]
    assert await sync_event_manager.connection_count(user_id) == 0


async def test_websocket_bearer_token_cannot_cross_user_scope(client):
    owner = await create_user(client, "ws-owner")
    other = await create_user(client, "ws-other")
    token = create_access_token(owner["id"])

    assert await _authorize_websocket_user(owner["id"], token, None) is True
    assert await _authorize_websocket_user(other["id"], token, None) is False


async def test_oversized_websocket_heartbeat_is_closed_and_disconnected(client, monkeypatch):
    user = await create_user(client, "ws-frame-limit")
    settings = get_settings()
    monkeypatch.setattr(settings, "WS_MAX_MESSAGE_BYTES", 32)
    websocket = FakeWebSocket(incoming=["x" * 33])

    await sync_updates(websocket, user_id=user["id"], token=None)  # type: ignore[arg-type]

    assert websocket.accepted is True
    assert websocket.close_code == 1009
    assert await sync_event_manager.connection_count(user["id"]) == 0


async def test_websocket_connection_limit_rejects_excess_socket():
    manager = SyncEventManager()
    first = FakeWebSocket()
    excess = FakeWebSocket()

    assert await manager.connect("user", first, max_connections=1) is True  # type: ignore[arg-type]
    assert await manager.connect("user", excess, max_connections=1) is False  # type: ignore[arg-type]
    assert first.accepted is True
    assert excess.accepted is False
    assert excess.close_code == 1013
    assert await manager.connection_count("user") == 1


async def test_slow_websocket_does_not_block_other_clients():
    manager = SyncEventManager(send_timeout_seconds=0.01)
    slow = SlowWebSocket()
    fast = FakeWebSocket()
    await manager.connect("user", slow)  # type: ignore[arg-type]
    await manager.connect("user", fast)  # type: ignore[arg-type]

    await manager.broadcast("user", "sync_completed", {"stored": 1})

    assert [message["event"] for message in fast.messages] == ["sync_completed"]
    assert slow.messages == []
    assert await manager.connection_count("user") == 1


async def test_connecting_websocket_is_not_dropped_by_concurrent_broadcast():
    manager = SyncEventManager()
    connecting = FakeWebSocket()
    connecting.client_state = WebSocketState.CONNECTING
    await manager.connect("user", connecting)  # type: ignore[arg-type]

    await manager.broadcast("user", "sync_started", {})

    assert connecting.messages == []
    assert await manager.connection_count("user") == 1
