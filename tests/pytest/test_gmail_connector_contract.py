"""Offline Gmail SDK contract and token-lifecycle regressions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.models.email import GmailAccount, RawEmail
from app.models.sync import SyncRun, SyncStatus
from app.security import decrypt_secret
from app.services.classification import ClassificationType
from app.services.connectors import gmail_connector as gmail_module
from app.services.connectors.base import ConnectorErrorType
from app.services.connectors.gmail_connector import GmailConnector
from app.services.gmail import demo_data, sync_service
from app.services.gmail.oauth_service import build_credentials
from sqlalchemy import select

from tests.pytest.helpers import create_user


class FakeRequest:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.response


class FakeMessages:
    def __init__(self, *, pages=None, messages=None) -> None:
        self.pages = list(pages or [])
        self.messages = messages or {}
        self.list_calls: list[dict] = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        return FakeRequest(self.pages.pop(0))

    def get(self, **kwargs):
        response = self.messages[kwargs["id"]]
        if isinstance(response, Exception):
            return FakeRequest(error=response)
        return FakeRequest(response)


class FakeHistory:
    def __init__(self, pages=None) -> None:
        self.pages = list(pages or [])

    def list(self, **_kwargs):
        return FakeRequest(self.pages.pop(0))


class FakeUsers:
    def __init__(self, messages: FakeMessages, history: FakeHistory | None = None) -> None:
        self._messages = messages
        self._history = history or FakeHistory()

    def messages(self):
        return self._messages

    def history(self):
        return self._history


class FakeService:
    def __init__(self, messages: FakeMessages, history: FakeHistory | None = None) -> None:
        self._users = FakeUsers(messages, history)

    def users(self):
        return self._users


def _gmail_message(message_id: str, *, internal_date: object = "1784592000000") -> dict:
    return {
        "id": message_id,
        "internalDate": internal_date,
        "payload": {
            "headers": [
                {"name": "From", "value": "alerts@example.test"},
                {"name": "Subject", "value": "Payment alert"},
            ],
            "body": {"data": "SU5SIDEwMCBkZWJpdGVkIHRvIFNXSUdHWQ=="},
        },
    }


async def test_query_pagination_respects_limit_and_page_tokens():
    messages = FakeMessages(
        pages=[
            {"messages": [{"id": "1"}, {"id": "2"}], "nextPageToken": "page-2"},
            {"messages": [{"id": "3"}, {"id": "4"}]},
        ]
    )

    refs = await GmailConnector._list_message_refs_by_query(FakeService(messages), "query", 3)

    assert [ref["id"] for ref in refs] == ["1", "2", "3"]
    assert [call["maxResults"] for call in messages.list_calls] == [3, 1]
    assert messages.list_calls[1]["pageToken"] == "page-2"


async def test_query_pagination_rejects_repeated_page_token():
    messages = FakeMessages(
        pages=[
            {"messages": [], "nextPageToken": "repeat"},
            {"messages": [], "nextPageToken": "repeat"},
        ]
    )

    with pytest.raises(RuntimeError, match="repeated a page token"):
        await GmailConnector._list_message_refs_by_query(FakeService(messages), "query", None)


async def test_message_conversion_isolates_unknown_per_message_failures():
    messages = FakeMessages(
        messages={
            "good": _gmail_message("good", internal_date="invalid"),
            "bad": ValueError("malformed provider payload secret"),
        }
    )
    connector = GmailConnector(GmailAccount(user_id="user", google_account_id="google"))

    records, errors = await connector._message_refs_to_records(
        FakeService(messages),
        "user",
        [{"id": "good"}, {"id": "bad"}, {}],
    )

    assert len(records) == 1
    assert records[0].received_at is None
    assert [error.error_type for error in errors] == [
        ConnectorErrorType.UNKNOWN,
        ConnectorErrorType.UNKNOWN,
    ]
    assert "secret" not in str(errors)


async def test_message_conversion_propagates_retryable_provider_failure():
    messages = FakeMessages(messages={"timeout": TimeoutError("temporary network timeout")})
    connector = GmailConnector(GmailAccount(user_id="user", google_account_id="google"))

    with pytest.raises(TimeoutError):
        await connector._message_refs_to_records(FakeService(messages), "user", [{"id": "timeout"}])


async def test_history_pagination_deduplicates_messages_and_advances_cursor():
    history = FakeHistory(
        [
            {
                "historyId": "history-2",
                "history": [
                    {
                        "messagesAdded": [
                            {"message": {"id": "1"}},
                            {"message": {"id": "2"}},
                        ]
                    }
                ],
                "nextPageToken": "next",
            },
            {
                "historyId": "history-3",
                "history": [
                    {
                        "messagesAdded": [
                            {"message": {"id": "2"}},
                            {"message": {"id": "3"}},
                        ]
                    }
                ],
            },
        ]
    )

    refs, cursor = await GmailConnector._list_message_refs_by_history(
        FakeService(FakeMessages(), history), "history-1"
    )

    assert [ref["id"] for ref in refs] == ["1", "2", "3"]
    assert cursor == "history-3"


async def test_legacy_account_without_expiry_refreshes_and_persists_expiry(monkeypatch):
    refreshed_at = datetime(2026, 7, 21, 18, 0)

    class FakeCredentials:
        token = "old-access"
        refresh_token = "refresh-token"
        expiry = None
        expired = False
        refresh_calls = 0

        def refresh(self, _request):
            self.refresh_calls += 1
            self.token = "new-access"
            self.expiry = refreshed_at

    credentials = FakeCredentials()
    captured: dict = {}

    def fake_build_credentials(access_token, refresh_token, expiry):
        captured.update(
            access_token=access_token,
            refresh_token=refresh_token,
            expiry=expiry,
        )
        return credentials

    service = object()
    monkeypatch.setattr(gmail_module, "build_credentials", fake_build_credentials)
    monkeypatch.setattr(gmail_module, "build", lambda *_args, **_kwargs: service)
    account = GmailAccount(
        user_id="user",
        google_account_id="google",
        access_token_ref="old-access",
        refresh_token_ref="refresh-token",
    )
    connector = GmailConnector(account)

    result = await connector.refresh_credentials()

    assert result == {"refreshed": True}
    assert credentials.refresh_calls == 1
    assert captured["expiry"] is None
    assert decrypt_secret(account.access_token_ref) == "new-access"
    assert account.token_expires_at == refreshed_at.replace(tzinfo=UTC)


def test_build_credentials_normalizes_database_expiry_for_google_library():
    expiry = datetime(2026, 7, 21, 18, 0, tzinfo=UTC)

    credentials = build_credentials("access", "refresh", expiry)

    assert credentials.expiry == expiry.replace(tzinfo=None)


async def test_demo_sync_failure_rolls_back_emails_and_redacts_exception(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "demo-sync-rollback")
    secret = "provider-payload-secret"
    monkeypatch.setattr(
        demo_data,
        "SAMPLE_EMAILS",
        [
            {"sender": "bank", "subject": "first", "body": "first body"},
            {"sender": "bank", "subject": "second", "body": "second body"},
        ],
    )
    calls = 0

    def classify(_sender, _subject, _body):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError(secret)
        return ClassificationType.TRANSACTION, "Bank", 0.9

    monkeypatch.setattr(sync_service, "classify_email", classify)

    async with test_session_factory() as db:
        with pytest.raises(RuntimeError, match=secret):
            await sync_service.demo_sync_gmail_emails(db, user["id"])
        stored = list(await db.scalars(select(RawEmail).where(RawEmail.user_id == user["id"])))
        run = await db.scalar(select(SyncRun).where(SyncRun.user_id == user["id"]))

    assert stored == []
    assert run is not None
    assert run.status == SyncStatus.FAILED
    assert run.errors == '[{"error": "demo_sync_runtimeerror"}]'
    assert secret not in run.errors
