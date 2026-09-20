"""Direct branch coverage for browser sessions and Google identity flows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.routes import auth as routes
from app.models.user import User
from app.security import hash_session_token
from fastapi import HTTPException, Response


class _Result:
    def __init__(self, scalar=None):
        self.scalar_value = scalar

    def scalar_one_or_none(self):
        return self.scalar_value


class _Db:
    def __init__(self, *, execute_values=(), user=None):
        self.execute_values = list(execute_values)
        self.user = user
        self.deleted = []
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _statement):
        return self.execute_values.pop(0) if self.execute_values else _Result()

    async def get(self, _model, _user_id):
        return self.user

    async def delete(self, item):
        self.deleted.append(item)

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        if self.added:
            for item in self.added:
                if getattr(item, "id", None) is None:
                    item.id = "generated-user"

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _user(**overrides):
    values = {
        "id": "user-1",
        "email": "person@example.com",
        "name": "Person",
        "currency": "INR",
        "timezone": "UTC",
        "password_hash": None,
        "is_active": True,
        "deletion_started_at": None,
        "created_at": datetime(2026, 9, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return User(**values)


def test_cookie_and_timestamp_helpers_cover_set_and_clear_paths():
    naive = datetime(2026, 9, 20)
    assert routes._as_utc(naive).tzinfo == UTC
    aware = datetime(2026, 9, 20, tzinfo=UTC)
    assert routes._as_utc(aware) is aware

    response = Response()
    routes._set_session_cookies(response, "session", "csrf")
    routes._set_oauth_cookie(response, "oauth")
    routes._clear_session_cookies(response)
    routes._clear_oauth_cookie(response)
    assert "pfis_session" in str(response.raw_headers).lower()


@pytest.mark.asyncio
async def test_oauth_state_consumption_rejects_mismatch_and_accepts_valid_cookie():
    token = "browser-token"
    valid = SimpleNamespace(
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        flow_type="google_login",
        browser_token_hash=hash_session_token(token),
    )
    request = SimpleNamespace(cookies={routes.settings.OAUTH_COOKIE_NAME: token})
    db = _Db(execute_values=[_Result(valid)])
    assert await routes._consume_oauth_state(request, db, "state", "google_login") is valid
    assert db.deleted == [valid]
    assert db.commits == 1

    for state, expected_flow, cookies in [
        (None, "google_login", {}),
        (
            SimpleNamespace(
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
                flow_type="google_login",
                browser_token_hash=hash_session_token(token),
            ),
            "google_login",
            {routes.settings.OAUTH_COOKIE_NAME: token},
        ),
        (
            SimpleNamespace(
                expires_at=datetime.now(UTC) + timedelta(minutes=1),
                flow_type="gmail_connect",
                browser_token_hash=hash_session_token(token),
            ),
            "google_login",
            {routes.settings.OAUTH_COOKIE_NAME: token},
        ),
    ]:
        mismatch_db = _Db(execute_values=[_Result(state)])
        with pytest.raises(HTTPException) as caught:
            await routes._consume_oauth_state(
                SimpleNamespace(cookies=cookies), mismatch_db, "state", expected_flow
            )
        assert caught.value.status_code == 400
        assert mismatch_db.commits == (1 if state is not None else 0)


@pytest.mark.asyncio
async def test_google_user_resolution_covers_existing_identity_legacy_link_and_new_user():
    existing = _user()
    identity = SimpleNamespace(user_id=existing.id)
    assert (
        await routes._resolve_google_user(
            _Db(execute_values=[_Result(identity)], user=existing),
            {"google_account_id": "subject", "email": existing.email, "name": "New"},
        )
        is existing
    )

    inactive = _user(is_active=False)
    with pytest.raises(HTTPException) as caught:
        await routes._resolve_google_user(
            _Db(execute_values=[_Result(identity)], user=inactive),
            {"google_account_id": "subject", "email": inactive.email, "name": "New"},
        )
    assert caught.value.status_code == 403

    with pytest.raises(HTTPException) as caught:
        await routes._resolve_google_user(
            _Db(), {"google_account_id": "", "email": "x@example.com", "name": "X"}
        )
    assert caught.value.status_code == 401

    legacy = _user(password_hash=None)
    legacy_db = _Db(
        execute_values=[_Result(None), _Result(legacy), _Result(SimpleNamespace(id="gmail"))]
    )
    resolved = await routes._resolve_google_user(
        legacy_db,
        {"google_account_id": "legacy-subject", "email": legacy.email, "name": "Renamed"},
    )
    assert resolved is legacy
    assert legacy.name == "Renamed"
    assert len(legacy_db.added) == 1

    password_user = _user(password_hash="hash")
    password_db = _Db(
        execute_values=[_Result(None), _Result(password_user), _Result(SimpleNamespace(id="gmail"))]
    )
    with pytest.raises(HTTPException) as caught:
        await routes._resolve_google_user(
            password_db,
            {"google_account_id": "subject-2", "email": password_user.email, "name": "X"},
        )
    assert caught.value.status_code == 409

    new_db = _Db(execute_values=[_Result(None), _Result(None)])
    new_user = await routes._resolve_google_user(
        new_db,
        {"google_account_id": "new-subject", "email": "new@example.com", "name": "New User"},
    )
    assert new_user.email == "new@example.com"
    assert len(new_db.added) == 2


@pytest.mark.asyncio
async def test_google_login_callback_and_browser_session_cover_redirect_outcomes(monkeypatch):
    monkeypatch.setattr(
        routes.oauth_service,
        "get_authorization_url",
        lambda **_kwargs: ("https://accounts.google.test", "state", "verifier", "nonce"),
    )
    db = _Db()
    redirect = await routes.google_login(db)
    assert redirect.status_code == 307
    assert db.commits == 1

    monkeypatch.setattr(
        routes.oauth_service,
        "get_authorization_url",
        lambda **_kwargs: (_ for _ in ()).throw(HTTPException(status_code=500)),
    )
    assert (await routes.google_login(_Db())).status_code == 303
    monkeypatch.setattr(
        routes.oauth_service,
        "get_authorization_url",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    assert (await routes.google_login(_Db())).status_code == 303

    state = SimpleNamespace(code_verifier_ref="verifier", nonce_ref="nonce")
    user = _user()
    monkeypatch.setattr(routes.settings, "GOOGLE_ALLOWED_EMAILS", [], raising=False)
    monkeypatch.setattr(routes, "_consume_oauth_state", _return(state))
    monkeypatch.setattr(routes, "decrypt_secret", lambda value: value)
    monkeypatch.setattr(
        routes.oauth_service, "exchange_code_for_tokens", lambda *_args, **_kwargs: {"id": "token"}
    )
    monkeypatch.setattr(
        routes.oauth_service,
        "verify_google_identity",
        lambda *_args, **_kwargs: {
            "google_account_id": "subject",
            "email": user.email,
            "name": user.name,
        },
    )
    monkeypatch.setattr(routes, "_resolve_google_user", _return(user))
    monkeypatch.setattr(routes, "create_auth_session", _session)
    success = await routes.google_callback(SimpleNamespace(cookies={}), "code", "state", _Db())
    assert success.status_code == 303
    assert "google_auth=success" in success.headers["location"]

    monkeypatch.setattr(
        routes.oauth_service,
        "exchange_code_for_tokens",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(HTTPException(status_code=403)),
    )
    denied_db = _Db()
    denied = await routes.google_callback(SimpleNamespace(cookies={}), "code", "state", denied_db)
    assert "google_account_not_allowed" in denied.headers["location"]
    assert denied_db.rollbacks == 1

    monkeypatch.setattr(
        routes.oauth_service,
        "exchange_code_for_tokens",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider")),
    )
    failed = await routes.google_callback(SimpleNamespace(cookies={}), "code", "state", _Db())
    assert "google_signin_failed" in failed.headers["location"]

    session = SimpleNamespace(mode="demo", expires_at=datetime.now(UTC) + timedelta(minutes=10))
    monkeypatch.setattr(routes, "get_active_auth_session", _return(session))
    monkeypatch.setattr(routes, "revoke_auth_session", _return(None))
    browser = await routes.browser_session(
        SimpleNamespace(cookies={routes.settings.SESSION_COOKIE_NAME: "session"}), user, _Db()
    )
    assert browser.mode == "demo"
    logout = await routes.logout(SimpleNamespace(cookies={}), Response(), _Db())
    assert logout.status == "signed_out"
    assert await routes.me(user) is user


def _return(value):
    async def returning(*_args, **_kwargs):
        return value

    return returning


async def _session(_db, _user_id, *, mode="auth"):
    return (
        "session-token",
        "csrf-token",
        SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(hours=1)),
    )
