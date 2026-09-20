"""Direct branch coverage for Gmail OAuth and connector routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.routes import gmail as routes
from app.models.email import GmailAccount
from app.security import hash_session_token
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Result:
    def __init__(self, scalar=None, rows=()):
        self.scalar_value = scalar
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalar(self):
        return self.scalar_value

    def scalars(self):
        return _Rows(self.rows)


class _Db:
    def __init__(self, *, execute_values=(), scalar_values=()):
        self.execute_values = list(execute_values)
        self.scalar_values = list(scalar_values)
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshes = 0
        self.flushes = 0
        self.fail_flush = None

    async def execute(self, _statement):
        if self.execute_values:
            value = self.execute_values.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        return _Result()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def get(self, _model, _item_id):
        return None

    def add(self, item):
        self.added.append(item)

    async def delete(self, item):
        self.deleted.append(item)

    async def flush(self):
        self.flushes += 1
        if self.fail_flush is not None:
            raise self.fail_flush
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = "generated-id"

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, _item):
        self.refreshes += 1


def _owner(**values):
    defaults = {
        "id": "user-1",
        "is_active": True,
        "deletion_started_at": None,
        "gmail_connection_generation": 0,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _oauth_state(*, user_id="user-1", token="browser-token", **values):
    defaults = {
        "user_id": user_id,
        "connection_generation": 0,
        "code_verifier_ref": "verifier",
        "nonce_ref": "nonce",
        "flow_type": "gmail_connect",
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        "browser_token_hash": hash_session_token(token),
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _request(token="browser-token"):
    return SimpleNamespace(cookies={routes.settings.OAUTH_COOKIE_NAME: token})


def _tokens(**values):
    defaults = {
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "scopes": routes.GMAIL_SCOPES,
    }
    defaults.update(values)
    return defaults


def _profile(subject="google-subject"):
    return {
        "google_account_id": subject,
        "email": "person@example.com",
        "name": "Person",
    }


@pytest.mark.asyncio
async def test_gmail_connect_persists_state_and_maps_startup_failures(monkeypatch):
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    owner = _owner()
    db = _Db(execute_values=[_Result(scalar=owner)])
    monkeypatch.setattr(
        routes,
        "get_authorization_url",
        lambda **_kwargs: ("https://accounts.google.test", "state", "verifier", "nonce"),
    )
    monkeypatch.setattr(routes, "token_urlsafe", lambda _size: "browser-token")
    monkeypatch.setattr(routes, "encrypt_secret", lambda value: value and f"enc:{value}")

    redirect = await routes.gmail_connect(user_id="user-1", current_user=None, db=db)

    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://accounts.google.test"
    assert db.commits == 1
    assert db.added[0].state == "state"
    assert db.added[0].connection_generation == 0

    inactive = _Db(execute_values=[_Result(scalar=_owner(is_active=False))])
    with pytest.raises(HTTPException, match="inactive"):
        await routes.gmail_connect(user_id="user-1", current_user=None, db=inactive)

    monkeypatch.setattr(
        routes,
        "get_authorization_url",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider")),
    )
    with pytest.raises(HTTPException, match="could not be started"):
        await routes.gmail_connect(user_id="user-1", current_user=None, db=_Db())


@pytest.mark.asyncio
async def test_gmail_callback_covers_new_link_reconnect_and_callback_boundaries(monkeypatch):
    state = _oauth_state()
    owner = _owner()
    db = _Db(
        execute_values=[
            _Result(scalar=state),
            _Result(scalar=owner),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    monkeypatch.setattr(routes, "decrypt_secret", lambda value: value)
    monkeypatch.setattr(routes, "encrypt_secret", lambda value: value and f"enc:{value}")
    monkeypatch.setattr(routes, "exchange_code_for_tokens", lambda *_args, **_kwargs: _tokens())
    monkeypatch.setattr(routes, "has_gmail_readonly_scope", lambda _tokens: True)
    monkeypatch.setattr(routes, "verify_google_identity", lambda *_args, **_kwargs: _profile())

    success = await routes.gmail_callback(_request(), code="code", state="state", error=None, db=db)

    assert success.status_code == 303
    assert success.headers["location"] == "/dashboard?gmail_auth=success"
    assert db.commits == 3
    account = next(item for item in db.added if isinstance(item, GmailAccount))
    assert account.google_account_id == "google-subject"
    assert account.access_token_ref == "enc:access-token"

    existing = SimpleNamespace(
        id="existing-account",
        user_id="user-1",
        google_account_id="google-subject",
        access_token_ref="old-access",
        refresh_token_ref="old-refresh",
        auto_sync_status="idle",
        auto_sync_enabled=False,
        auto_sync_error="old-error",
    )
    reconnect_db = _Db(
        execute_values=[
            _Result(scalar=_oauth_state()),
            _Result(scalar=owner),
            _Result(scalar=existing),
            _Result(scalar=existing),
        ]
    )
    reconnect = await routes.gmail_callback(
        _request(), code="reconnect", state="state", error=None, db=reconnect_db
    )
    assert reconnect.headers["location"] == "/dashboard?gmail_auth=success"
    assert existing.access_token_ref == "enc:access-token"
    assert existing.refresh_token_ref == "enc:refresh-token"
    assert existing.auto_sync_status == "paused"
    assert existing.auto_sync_error is None

    missing_user = _oauth_state(user_id=None)
    with pytest.raises(HTTPException, match="missing user"):
        await routes.gmail_callback(
            _request(),
            code="code",
            state="state",
            error=None,
            db=_Db(execute_values=[_Result(scalar=missing_user)]),
        )


@pytest.mark.asyncio
async def test_gmail_callback_maps_invalid_scope_ownership_race_and_provider_failures(
    monkeypatch,
):
    monkeypatch.setattr(routes, "decrypt_secret", lambda value: value)
    monkeypatch.setattr(routes, "exchange_code_for_tokens", lambda *_args, **_kwargs: _tokens())
    monkeypatch.setattr(routes, "verify_google_identity", lambda *_args, **_kwargs: _profile())

    expired = _oauth_state(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    expired_db = _Db(execute_values=[_Result(scalar=expired)])
    with pytest.raises(HTTPException, match="Invalid or expired"):
        await routes.gmail_callback(
            _request(), code="code", state="state", error=None, db=expired_db
        )
    assert expired_db.deleted == [expired]

    denial_state = _oauth_state()
    denial_db = _Db(execute_values=[_Result(scalar=denial_state)])
    denial = await routes.gmail_callback(
        _request(), code=None, state="state", error="access_denied", db=denial_db
    )
    assert denial.headers["location"] == "/dashboard?gmail_error=access_denied"

    missing_code_state = _oauth_state()
    missing_code = await routes.gmail_callback(
        _request(),
        code=None,
        state="state",
        error=None,
        db=_Db(execute_values=[_Result(scalar=missing_code_state)]),
    )
    assert missing_code.headers["location"] == "/dashboard?gmail_error=missing_code"

    monkeypatch.setattr(routes, "has_gmail_readonly_scope", lambda _tokens: False)
    scope_db = _Db(
        execute_values=[
            _Result(scalar=_oauth_state()),
        ]
    )
    scope = await routes.gmail_callback(
        _request(), code="code", state="state", error=None, db=scope_db
    )
    assert scope.headers["location"] == "/dashboard?gmail_error=gmail_scope_required"
    assert scope_db.rollbacks == 1

    monkeypatch.setattr(routes, "has_gmail_readonly_scope", lambda _tokens: True)
    revoked = []

    async def revoke_and_record(token):
        revoked.append(token)
        return True

    monkeypatch.setattr(routes, "revoke_google_token", revoke_and_record)
    invalidated_owner = _owner(gmail_connection_generation=2)
    invalidated_db = _Db(
        execute_values=[
            _Result(scalar=_oauth_state(connection_generation=1)),
            _Result(scalar=invalidated_owner),
        ]
    )
    invalidated = await routes.gmail_callback(
        _request(), code="code", state="state", error=None, db=invalidated_db
    )
    assert invalidated.headers["location"] == "/dashboard?gmail_error=gmail_connection_invalidated"
    assert revoked == ["refresh-token"]

    conflict_account = SimpleNamespace(user_id="other-user", google_account_id="google-subject")
    conflict_db = _Db(
        execute_values=[
            _Result(scalar=_oauth_state()),
            _Result(scalar=_owner()),
            _Result(scalar=None),
            _Result(scalar=conflict_account),
        ]
    )
    conflict = await routes.gmail_callback(
        _request(), code="code", state="state", error=None, db=conflict_db
    )
    assert conflict.headers["location"] == "/dashboard?gmail_error=gmail_account_conflict"

    mismatch_account = SimpleNamespace(user_id="user-1", google_account_id="other-subject")
    mismatch_db = _Db(
        execute_values=[
            _Result(scalar=_oauth_state()),
            _Result(scalar=_owner()),
            _Result(scalar=mismatch_account),
            _Result(scalar=None),
        ]
    )
    mismatch = await routes.gmail_callback(
        _request(), code="code", state="state", error=None, db=mismatch_db
    )
    assert mismatch.headers["location"] == "/dashboard?gmail_error=gmail_account_mismatch"

    monkeypatch.setattr(
        routes,
        "exchange_code_for_tokens",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider")),
    )
    failed_db = _Db(execute_values=[_Result(scalar=_oauth_state())])
    failed = await routes.gmail_callback(
        _request(), code="code", state="state", error=None, db=failed_db
    )
    assert failed.headers["location"] == "/dashboard?gmail_error=gmail_connection_failed"

    race_db = _Db(
        execute_values=[
            _Result(scalar=_oauth_state()),
            _Result(scalar=_owner()),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    race_db.fail_flush = IntegrityError("duplicate", {}, RuntimeError("constraint"))
    monkeypatch.setattr(routes, "exchange_code_for_tokens", lambda *_args, **_kwargs: _tokens())
    race = await routes.gmail_callback(
        _request(), code="code", state="state", error=None, db=race_db
    )
    assert race.headers["location"] == "/dashboard?gmail_error=gmail_account_conflict"


@pytest.mark.asyncio
async def test_gmail_operation_routes_cover_state_and_connector_branches(monkeypatch):
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    account = SimpleNamespace(
        id="gmail-1",
        auto_sync_status="idle",
        auto_sync_enabled=True,
        auto_sync_interval_seconds=300,
        auto_sync_error=None,
        last_synced_at=None,
        last_history_id=None,
        refresh_token_ref="encrypted-refresh",
        access_token_ref=None,
    )
    sync_db = _Db(execute_values=[_Result(scalar=account)])
    monkeypatch.setattr(routes, "sync_gmail_emails", _returning({"emails_fetched": 2}))
    sync = await routes.trigger_sync(
        user_id="user-1", max_results=10, current_user=None, db=sync_db
    )
    assert sync["status"] == "completed"

    monkeypatch.setattr(routes, "sync_gmail_emails", _raising(RuntimeError("sync")))
    with pytest.raises(HTTPException, match="synchronization failed"):
        await routes.trigger_sync(
            user_id="user-1", current_user=None, db=_Db(execute_values=[_Result(scalar=account)])
        )

    with pytest.raises(HTTPException, match="No Gmail account"):
        await routes.trigger_sync(
            user_id="user-1", current_user=None, db=_Db(execute_values=[_Result(scalar=None)])
        )
    disconnecting = SimpleNamespace(**{**account.__dict__, "auto_sync_status": "disconnecting"})
    with pytest.raises(HTTPException, match="disconnect"):
        await routes.trigger_sync(
            user_id="user-1",
            current_user=None,
            db=_Db(execute_values=[_Result(scalar=disconnecting)]),
        )

    run = SimpleNamespace(
        id="run-1",
        status=SimpleNamespace(value="completed"),
        start_time=datetime(2026, 9, 20, tzinfo=UTC),
        end_time=None,
        emails_fetched=2,
        emails_processed=1,
        emails_failed=0,
        coverage_complete=True,
        coverage_truncated=False,
        coverage_pages=1,
        coverage_result_size_estimate=2,
    )
    empty_status = await routes.get_sync_status(
        user_id="user-1", current_user=None, db=_Db(execute_values=[_Result(rows=[])])
    )
    assert empty_status["message"] == "No sync runs found"
    populated_status = await routes.get_sync_status(
        user_id="user-1", current_user=None, db=_Db(execute_values=[_Result(rows=[run])])
    )
    assert populated_status["latest_status"] == "completed"

    auto_db = _Db(execute_values=[_Result(scalar=account), _Result(scalar=account)])
    assert (await routes.get_auto_sync_status(user_id="user-1", current_user=None, db=auto_db))[
        "enabled"
    ] is True
    await routes.update_auto_sync_status(
        routes.AutoSyncUpdate(enabled=False, interval_seconds=600),
        user_id="user-1",
        current_user=None,
        db=auto_db,
    )
    assert account.auto_sync_status == "paused"
    account.auto_sync_error = "reauthorize"
    await routes.update_auto_sync_status(
        routes.AutoSyncUpdate(enabled=True),
        user_id="user-1",
        current_user=None,
        db=_Db(execute_values=[_Result(scalar=account)]),
    )
    assert account.auto_sync_status == "paused"
    with pytest.raises(HTTPException, match="No Gmail account"):
        await routes.get_auto_sync_status(
            user_id="user-1", current_user=None, db=_Db(execute_values=[_Result()])
        )
    with pytest.raises(HTTPException, match="disconnect"):
        await routes.update_auto_sync_status(
            routes.AutoSyncUpdate(enabled=True),
            user_id="user-1",
            current_user=None,
            db=_Db(
                execute_values=[
                    _Result(
                        scalar=SimpleNamespace(
                            **{**account.__dict__, "auto_sync_status": "disconnecting"}
                        )
                    )
                ]
            ),
        )


@pytest.mark.asyncio
async def test_gmail_disconnect_listing_demo_and_audit_paths(monkeypatch):
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    owner = _owner()
    account = SimpleNamespace(
        id="gmail-1",
        auto_sync_enabled=True,
        auto_sync_status="idle",
        auto_sync_error="old",
        refresh_token_ref="encrypted-refresh",
        access_token_ref=None,
    )
    db = _Db(
        execute_values=[_Result(scalar=owner), _Result(scalar=account), _Result()],
        scalar_values=[2],
    )
    stopped = []
    monkeypatch.setattr(
        routes, "stop_auto_sync_for_account", lambda account_id: _record(stopped, account_id)
    )
    monkeypatch.setattr(routes, "stop_user_ingestions", lambda user_id: _record(stopped, user_id))
    monkeypatch.setattr(routes, "decrypt_secret", lambda _value: "provider-token")

    async def revoke_success(_token):
        return True

    monkeypatch.setattr(routes, "revoke_google_token", revoke_success)
    result = await routes.disconnect_gmail(user_id="user-1", current_user=None, db=db)
    assert result["provider_revocation"] == "revoked"
    assert result["retained_raw_email_count"] == 2
    assert owner.gmail_connection_generation == 1
    assert account.auto_sync_status == "disconnecting"
    assert stopped == ["gmail-1", "user-1"]

    unavailable_db = _Db(
        execute_values=[
            _Result(scalar=owner),
            _Result(
                scalar=SimpleNamespace(
                    **{**account.__dict__, "id": "gmail-2", "refresh_token_ref": None}
                )
            ),
            _Result(),
        ],
        scalar_values=[0],
    )
    monkeypatch.setattr(routes, "decrypt_secret", lambda _value: None)
    unavailable = await routes.disconnect_gmail(
        user_id="user-1", current_user=None, db=unavailable_db
    )
    assert unavailable["provider_revocation"] == "token_unavailable"

    with pytest.raises(HTTPException, match="not available"):
        await routes.disconnect_gmail(
            user_id="user-1", current_user=None, db=_Db(execute_values=[_Result(scalar=None)])
        )
    with pytest.raises(HTTPException, match="No Gmail account"):
        await routes.disconnect_gmail(
            user_id="user-1",
            current_user=None,
            db=_Db(execute_values=[_Result(scalar=owner), _Result(scalar=None)]),
        )

    email = SimpleNamespace(
        id="email-1",
        gmail_message_id="message-1",
        sender="bank@example.com",
        subject="Subject",
        body="body" * 100,
        received_at=datetime(2026, 9, 20, tzinfo=UTC),
        processed_flag=True,
    )
    listing_db = _Db(
        execute_values=[
            _Result(rows=[email]),
            _Result(scalar=1),
            _Result(scalar=2),
            _Result(scalar=1),
            _Result(scalar=1),
        ]
    )
    listing = await routes.list_raw_emails(
        user_id="user-1",
        processed=True,
        limit=20,
        offset=0,
        current_user=None,
        db=listing_db,
    )
    assert listing["total"] == 1
    assert len(listing["emails"][0]["body_preview"]) == 200

    monkeypatch.setattr(
        routes,
        "demo_sync_gmail_emails",
        _returning({"emails_stored": 1, "emails_skipped_otp": 2, "emails_skipped_promo": 3}),
    )
    demo = await routes.demo_sync(user_id="user-1", current_user=None, db=_Db())
    assert demo["mode"] == "demo"

    audit_db = _Db()
    await routes._record_connector_audit(audit_db, "user-1", "gmail-1", "connect", {"ok": True})
    await routes._record_connector_audit(
        audit_db, "user-1", None, "disconnect", {"ok": True}, commit=False
    )
    assert len(audit_db.added) == 2
    assert audit_db.commits == 1


def _returning(value):
    async def return_value(*_args, **_kwargs):
        return value

    return return_value


def _raising(exc):
    async def raise_value(*_args, **_kwargs):
        raise exc

    return raise_value


async def _record(target, value):
    target.append(value)
