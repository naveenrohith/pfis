"""Automatic sync and live-event regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.email import GmailAccount
from app.services import auto_sync_service
from app.services.sync_events import SyncEventManager
from sqlalchemy import select
from starlette.websockets import WebSocketState

from tests.pytest.helpers import create_user


class FakeWebSocket:
    def __init__(self) -> None:
        self.client_state = WebSocketState.CONNECTED
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


async def test_auto_sync_status_can_be_read_and_updated(client, test_session_factory):
    user = await create_user(client, "autosync")
    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="gmail-test",
                access_token_ref="token",
                refresh_token_ref="refresh",
            )
        )
        await db.commit()

    status_response = await client.get(f"/api/gmail/auto-sync?user_id={user['id']}")
    status_response.raise_for_status()
    payload = status_response.json()
    assert payload["enabled"] is True
    assert payload["interval_seconds"] == 300
    assert payload["status"] == "idle"

    update_response = await client.patch(
        f"/api/gmail/auto-sync?user_id={user['id']}",
        json={"enabled": False, "interval_seconds": 600},
    )
    update_response.raise_for_status()
    updated = update_response.json()
    assert updated["enabled"] is False
    assert updated["interval_seconds"] == 600
    assert updated["status"] == "paused"


async def test_sync_event_manager_broadcasts_only_to_target_user():
    manager = SyncEventManager()
    target = FakeWebSocket()
    other = FakeWebSocket()

    await manager.connect("user-a", target)  # type: ignore[arg-type]
    await manager.connect("user-b", other)  # type: ignore[arg-type]
    await manager.broadcast("user-a", "sync_started", {"mode": "test"})

    assert target.accepted is True
    assert other.accepted is True
    assert [message["event"] for message in target.messages] == ["sync_started"]
    assert other.messages == []


async def test_auto_sync_scheduler_does_not_overlap_running_account(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "autosync-overlap")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-test",
            access_token_ref="token",
            refresh_token_ref="refresh",
            last_synced_at=datetime.now(UTC) - timedelta(hours=1),
            auto_sync_interval_seconds=60,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    scheduled: list[str] = []

    def fake_schedule(account_id: str):
        scheduled.append(account_id)
        return None

    monkeypatch.setattr(auto_sync_service, "_schedule_account_sync", fake_schedule)
    auto_sync_service._running_account_ids.add(account_id)
    try:
        due = await auto_sync_service.run_due_auto_syncs_once()
    finally:
        auto_sync_service._running_account_ids.discard(account_id)

    assert due == 1
    assert scheduled == []


async def test_auto_sync_scheduler_respects_error_cooldown(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "autosync-cooldown")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-test",
            access_token_ref="token",
            refresh_token_ref="refresh",
            last_sync_started_at=datetime.now(UTC),
            auto_sync_interval_seconds=60,
            auto_sync_status="error",
        )
        db.add(account)
        await db.commit()

    scheduled: list[str] = []

    def fake_schedule(account_id: str):
        scheduled.append(account_id)
        return None

    monkeypatch.setattr(auto_sync_service, "_schedule_account_sync", fake_schedule)
    due = await auto_sync_service.run_due_auto_syncs_once()

    assert due == 0
    assert scheduled == []


async def test_auto_sync_failure_persists_and_broadcasts_only_safe_error(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "autosync-private-error")
    secret = "invalid_grant refresh-token-must-not-leak"
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-private-error",
            access_token_ref="token",
            refresh_token_ref="refresh",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async def fail_sync(_db, _user_id, _account_id):
        raise RuntimeError(secret)

    broadcasts: list[tuple[str, str, dict]] = []

    async def capture_broadcast(user_id: str, event: str, payload: dict):
        broadcasts.append((user_id, event, payload))

    monkeypatch.setattr(auto_sync_service, "sync_gmail_emails_incremental", fail_sync)
    monkeypatch.setattr(auto_sync_service.sync_event_manager, "broadcast", capture_broadcast)

    await auto_sync_service._run_account_sync(account_id)

    async with test_session_factory() as db:
        stored = await db.scalar(select(GmailAccount).where(GmailAccount.id == account_id))

    assert stored is not None
    assert stored.auto_sync_status == "paused"
    assert stored.auto_sync_error == "Gmail authorization is invalid or revoked"
    assert secret not in stored.auto_sync_error
    assert broadcasts == [
        (
            user["id"],
            "sync_failed",
            {
                "error": "Gmail authorization is invalid or revoked",
                "error_type": "permanent",
            },
        )
    ]
