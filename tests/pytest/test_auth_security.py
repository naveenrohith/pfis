"""Authentication and authorization regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from app.api.routes import auth as auth_routes
from app.api.routes import gmail as gmail_routes
from app.models.auth import AuthSession
from app.models.email import GmailAccount, RawEmail
from app.models.sync import ConnectorAuditEvent, OAuthState
from app.models.user import User
from app.security import decrypt_secret, encrypt_secret, hash_session_token
from app.services.gmail import oauth_service
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.pytest.helpers import auth_headers, create_user, register_user


def test_google_identity_signin_does_not_include_prior_gmail_grants(monkeypatch):
    captured: dict = {}

    class FakeFlow:
        def authorization_url(self, **kwargs):
            captured.update(kwargs)
            return "https://accounts.google.test/identity", "identity-state"

    monkeypatch.setattr(oauth_service, "validate_google_oauth_settings", lambda: None)
    monkeypatch.setattr(oauth_service, "create_oauth_flow", lambda **kwargs: FakeFlow())

    oauth_service.get_authorization_url(
        scopes=oauth_service.IDENTITY_SCOPES,
        offline=False,
    )

    assert captured["include_granted_scopes"] == "false"
    assert captured["access_type"] == "online"


def test_gmail_consent_does_not_include_existing_google_grants(monkeypatch):
    captured: dict = {}

    class FakeFlow:
        def authorization_url(self, **kwargs):
            captured.update(kwargs)
            return "https://accounts.google.test/gmail", "gmail-state"

    monkeypatch.setattr(oauth_service, "validate_google_oauth_settings", lambda: None)
    monkeypatch.setattr(oauth_service, "create_oauth_flow", lambda **kwargs: FakeFlow())

    oauth_service.get_authorization_url(
        scopes=oauth_service.GMAIL_SCOPES,
        offline=True,
    )

    assert captured["include_granted_scopes"] == "false"
    assert captured["access_type"] == "offline"


def test_gmail_scope_checker_requires_provider_returned_readonly_scope():
    assert oauth_service.has_gmail_readonly_scope({"scopes": [oauth_service.GMAIL_READONLY_SCOPE]})
    assert oauth_service.has_gmail_readonly_scope(
        {"scopes": f"openid {oauth_service.GMAIL_READONLY_SCOPE}"}
    )
    assert not oauth_service.has_gmail_readonly_scope({"scopes": oauth_service.IDENTITY_SCOPES})
    assert not oauth_service.has_gmail_readonly_scope(
        {
            "scopes": [
                oauth_service.GMAIL_READONLY_SCOPE,
                "https://www.googleapis.com/auth/drive.readonly",
            ]
        }
    )
    assert not oauth_service.has_gmail_readonly_scope({})


def test_token_exchange_uses_provider_granted_scopes(monkeypatch):
    granted_scopes = [oauth_service.GMAIL_READONLY_SCOPE]

    class FakeCredentials:
        token = "access-token"
        refresh_token = "refresh-token"
        id_token = "id-token"
        expiry = None

    FakeCredentials.granted_scopes = granted_scopes

    class FakeFlow:
        credentials = FakeCredentials()

        def fetch_token(self, **kwargs):
            assert kwargs["code"] == "oauth-code"

    monkeypatch.setattr(oauth_service, "create_oauth_flow", lambda **kwargs: FakeFlow())

    token_data = oauth_service.exchange_code_for_tokens(
        "oauth-code", scopes=oauth_service.GMAIL_SCOPES
    )

    assert token_data["scopes"] == granted_scopes


async def test_google_token_revocation_uses_provider_endpoint(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, data, headers):
            captured.update({"url": url, "data": data, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(
        oauth_service.httpx,
        "AsyncClient",
        lambda *, timeout: FakeClient(),
    )

    assert await oauth_service.revoke_google_token("provider-token") is True
    assert captured == {
        "url": oauth_service.GOOGLE_TOKEN_REVOCATION_URL,
        "data": {"token": "provider-token"},
        "headers": {"Content-Type": "application/x-www-form-urlencoded"},
    }


async def test_demo_seed_user_can_login_with_configured_password(client):
    response = await client.post(
        "/api/auth/login",
        json={"email": "demo@pfis.app", "password": "demo12345"},
    )
    response.raise_for_status()

    payload = response.json()
    assert payload["mode"] == "auth"
    assert payload["csrf_cookie_name"] == "pfis_csrf"
    assert payload["user"]["email"] == "demo@pfis.app"
    assert response.cookies.get("pfis_session")


async def test_register_login_and_me(client, auth_required):
    user, token = await register_user(client, "authme")

    me_response = await client.get("/api/auth/me", headers=auth_headers(token))
    me_response.raise_for_status()

    payload = me_response.json()
    assert payload["id"] == user["id"]
    assert payload["email"] == user["email"]
    assert payload["is_active"] is True


async def test_register_rejects_short_password_and_duplicate_email(client):
    email = "duplicate-auth@example.com"
    short = await client.post(
        "/api/auth/register",
        json={"email": email, "name": "Short", "password": "short"},
    )
    assert short.status_code == 422

    first = await client.post(
        "/api/auth/register",
        json={"email": email, "name": "First", "password": "Sup3rSecure!"},
    )
    first.raise_for_status()
    duplicate = await client.post(
        "/api/auth/register",
        json={"email": email.upper(), "name": "Duplicate", "password": "Sup3rSecure!"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == "An account with this email already exists"


@pytest.mark.parametrize("field", ["is_active", "deletion_started_at"])
async def test_login_rejects_unavailable_accounts(client, test_session_factory, field):
    user, _ = await register_user(client, f"unavailable-{field}")
    async with test_session_factory() as db:
        owner = await db.get(User, user["id"])
        assert owner is not None
        if field == "is_active":
            owner.is_active = False
        else:
            owner.deletion_started_at = datetime.now(UTC)
        await db.commit()

    response = await client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": "Sup3rSecure!"},
    )
    assert response.status_code == 403
    assert "account" in response.json()["error"]["message"].lower()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("not_configured", "/dashboard?auth_error=google_not_configured"),
        ("startup", "/dashboard?auth_error=google_start_failed"),
    ],
)
async def test_google_login_hides_startup_failures(client, monkeypatch, failure, expected):
    def fail(**_kwargs):
        if failure == "not_configured":
            raise HTTPException(status_code=500, detail="client secret leaked")
        raise RuntimeError("provider secret leaked")

    monkeypatch.setattr(auth_routes.oauth_service, "get_authorization_url", fail)
    response = await client.get("/api/auth/google/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == expected
    assert "secret" not in response.text.lower()


async def test_google_callback_creates_session_and_user(client, monkeypatch):
    state = "state-google"

    def fake_authorization_url(redirect_uri=None, *, scopes=None, offline=True):
        assert "https://www.googleapis.com/auth/gmail.readonly" not in scopes
        assert offline is False
        return "https://accounts.google.test/oauth", state, "verifier", "nonce"

    def fake_exchange(code, redirect_uri=None, *, scopes=None, code_verifier=None):
        assert code == "oauth-code"
        assert code_verifier == "verifier"
        return {
            "access_token": "google-access",
            "refresh_token": "google-refresh",
            "id_token": "google-id",
        }

    def fake_identity(token_data, *, expected_nonce=None):
        assert token_data["id_token"] == "google-id"
        assert expected_nonce == "nonce"
        return {
            "google_account_id": "google-sub-1",
            "email": "first-real-user@example.com",
            "name": "First Real User",
        }

    monkeypatch.setattr(auth_routes.oauth_service, "get_authorization_url", fake_authorization_url)
    monkeypatch.setattr(auth_routes.oauth_service, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(auth_routes.oauth_service, "verify_google_identity", fake_identity)

    login_response = await client.get("/api/auth/google/login", follow_redirects=False)
    assert login_response.status_code == 307
    assert login_response.headers["location"] == "https://accounts.google.test/oauth"

    callback_response = await client.get(
        f"/api/auth/google/callback?code=oauth-code&state={state}",
        follow_redirects=False,
    )
    assert callback_response.status_code == 303
    assert callback_response.headers["location"] == "/dashboard?google_auth=success"
    assert callback_response.cookies.get("pfis_session")
    assert "localStorage" not in callback_response.text

    session_response = await client.get("/api/auth/session")
    session_response.raise_for_status()
    assert session_response.json()["user"]["email"] == "first-real-user@example.com"


async def test_cookie_session_requires_csrf_and_logout_revokes_it(client, test_session_factory):
    response = await client.post(
        "/api/auth/login",
        json={"email": "demo@pfis.app", "password": "demo12345"},
    )
    response.raise_for_status()
    csrf = response.cookies.get("pfis_csrf")
    assert csrf
    assert "HttpOnly" in response.headers.get_list("set-cookie")[0]

    rejected = await client.post("/api/auth/logout")
    assert rejected.status_code == 403

    accepted = await client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    accepted.raise_for_status()
    assert accepted.json()["status"] == "signed_out"

    async with test_session_factory() as db:
        result = await db.execute(select(AuthSession))
        session = result.scalar_one()
        assert session.revoked_at is not None

    current = await client.get("/api/auth/session")
    assert current.status_code == 401


async def test_auth_mutation_rejects_cross_site_origin(client):
    response = await client.post(
        "/api/auth/login",
        headers={"Origin": "https://attacker.example"},
        json={"email": "demo@pfis.app", "password": "demo12345"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_site_request_blocked"


async def test_auth_responses_are_not_browser_cached(client):
    response = await client.post(
        "/api/auth/login",
        json={"email": "demo@pfis.app", "password": "demo12345"},
    )

    response.raise_for_status()
    assert response.headers["cache-control"] == "no-store"


async def test_google_callback_rejects_browser_transaction_mismatch(client, monkeypatch):
    state = "browser-bound-state"

    monkeypatch.setattr(
        auth_routes.oauth_service,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/oauth",
            state,
            "verifier",
            "nonce",
        ),
    )
    await client.get("/api/auth/google/login", follow_redirects=False)
    client.cookies.delete("pfis_oauth")

    response = await client.get(
        f"/api/auth/google/callback?code=oauth-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 400


async def test_gmail_callback_rejects_browser_transaction_mismatch(client, monkeypatch):
    state = "gmail-browser-bound-state"
    user = await create_user(client, "gmail-browser-bound")
    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda **_kwargs: (
            "https://accounts.google.test/gmail",
            state,
            "verifier",
            "nonce",
        ),
    )
    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}", follow_redirects=False
    )
    assert connect.status_code == 307
    client.cookies.delete(gmail_routes.settings.OAUTH_COOKIE_NAME)

    response = await client.get(
        f"/api/auth/gmail/callback?code=gmail-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 400


async def test_gmail_consent_is_separate_and_stores_verified_encrypted_tokens(
    client,
    monkeypatch,
    test_session_factory,
):
    demo = await client.post("/api/auth/demo")
    demo.raise_for_status()
    user = demo.json()["user"]
    state = "gmail-consent-state"

    def fake_authorization_url(redirect_uri=None, *, scopes=None, offline=True):
        assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
        assert offline is True
        return "https://accounts.google.test/gmail", state, "gmail-verifier", "gmail-nonce"

    def fake_exchange(code, redirect_uri=None, *, scopes=None, code_verifier=None):
        assert code == "gmail-code"
        assert code_verifier == "gmail-verifier"
        return {
            "access_token": "raw-access-token",
            "refresh_token": "raw-refresh-token",
            "id_token": "gmail-id-token",
            "expiry": "2026-07-21T18:00:00+00:00",
            "scopes": gmail_routes.GMAIL_SCOPES,
        }

    def fake_identity(token_data, *, expected_nonce=None):
        assert token_data["id_token"] == "gmail-id-token"
        assert expected_nonce == "gmail-nonce"
        return {
            "google_account_id": "gmail-subject-1",
            "email": "gmailconsent@example.com",
            "name": "Gmail Consent",
        }

    monkeypatch.setattr(gmail_routes, "get_authorization_url", fake_authorization_url)
    monkeypatch.setattr(gmail_routes, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(gmail_routes, "verify_google_identity", fake_identity)

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307
    assert connect.headers["location"] == "https://accounts.google.test/gmail"
    assert connect.cookies.get("pfis_oauth")

    callback = await client.get(
        f"/api/auth/gmail/callback?code=gmail-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard?gmail_auth=success"

    async with test_session_factory() as db:
        result = await db.execute(select(GmailAccount).where(GmailAccount.user_id == user["id"]))
        account = result.scalar_one()
        assert account.google_account_id == "gmail-subject-1"
        assert account.access_token_ref.startswith("enc:")
        assert account.refresh_token_ref.startswith("enc:")
        assert account.token_expires_at is not None
        assert account.token_expires_at.replace(tzinfo=UTC) == datetime(
            2026, 7, 21, 18, 0, tzinfo=UTC
        )
        assert "raw-access-token" not in account.access_token_ref
        assert "raw-refresh-token" not in account.refresh_token_ref


async def test_gmail_reconnect_replaces_grant_and_resumes_auto_sync(
    client,
    monkeypatch,
    test_session_factory,
):
    demo = await client.post("/api/auth/demo")
    demo.raise_for_status()
    user = demo.json()["user"]
    state = "gmail-reconnect-state"

    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="gmail-subject-1",
                access_token_ref="old-access",
                refresh_token_ref="old-refresh",
                auto_sync_enabled=True,
                auto_sync_status="paused",
                auto_sync_error="Gmail authorization is invalid or revoked",
            )
        )
        await db.commit()

    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            state,
            "gmail-verifier",
            "gmail-nonce",
        ),
    )
    monkeypatch.setattr(
        gmail_routes,
        "exchange_code_for_tokens",
        lambda code, redirect_uri=None, scopes=None, code_verifier=None: {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "id_token": "gmail-id-token",
            "expiry": "2026-07-28T18:00:00+00:00",
            "scopes": gmail_routes.GMAIL_SCOPES,
        },
    )
    monkeypatch.setattr(
        gmail_routes,
        "verify_google_identity",
        lambda token_data, expected_nonce=None: {
            "google_account_id": "gmail-subject-1",
            "email": "gmailreconnect@example.com",
            "name": "Gmail Reconnect",
        },
    )

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307

    callback = await client.get(
        f"/api/auth/gmail/callback?code=gmail-code&state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard?gmail_auth=success"

    async with test_session_factory() as db:
        account = await db.scalar(select(GmailAccount).where(GmailAccount.user_id == user["id"]))

    assert account is not None
    assert account.auto_sync_enabled is True
    assert account.auto_sync_status == "idle"
    assert account.auto_sync_error is None
    assert account.access_token_ref.startswith("enc:")
    assert account.refresh_token_ref.startswith("enc:")
    assert "new-access-token" not in account.access_token_ref
    assert "new-refresh-token" not in account.refresh_token_ref


async def test_gmail_disconnect_revokes_grant_and_retains_imported_evidence(
    client,
    monkeypatch,
    test_session_factory,
):
    demo = await client.post("/api/auth/demo")
    demo.raise_for_status()
    user = demo.json()["user"]
    captured: dict[str, str] = {}

    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="gmail-disconnect-subject",
                access_token_ref=encrypt_secret("disconnect-access-token"),
                refresh_token_ref=encrypt_secret("disconnect-refresh-token"),
            )
        )
        db.add(
            RawEmail(
                user_id=user["id"],
                gmail_message_id="disconnect-retained-email",
                subject="Retained evidence",
                body="Imported content remains after connector removal",
            )
        )
        db.add(
            OAuthState(
                state="pending-disconnect-state",
                user_id=user["id"],
                flow_type="gmail_connect",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()

    async def fake_revoke(token: str) -> bool:
        captured["token"] = token
        async with test_session_factory() as db:
            disconnecting = await db.scalar(
                select(GmailAccount).where(GmailAccount.user_id == user["id"])
            )
        assert disconnecting is not None
        assert disconnecting.auto_sync_enabled is False
        assert disconnecting.auto_sync_status == "disconnecting"
        csrf_headers = {"X-CSRF-Token": client.cookies.get("pfis_csrf")}
        settings_response = await client.patch(
            f"/api/gmail/auto-sync?user_id={user['id']}",
            headers=csrf_headers,
            json={"enabled": True},
        )
        sync_response = await client.post(
            f"/api/gmail/sync?user_id={user['id']}",
            headers=csrf_headers,
        )
        assert settings_response.status_code == 409
        assert sync_response.status_code == 409
        return True

    monkeypatch.setattr(gmail_routes, "revoke_google_token", fake_revoke)
    response = await client.delete(
        f"/api/gmail/connection?user_id={user['id']}",
        headers={"X-CSRF-Token": client.cookies.get("pfis_csrf")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "disconnected",
        "provider_revocation": "revoked",
        "retained_raw_email_count": 1,
        "derived_records_retained": True,
    }
    assert captured == {"token": "disconnect-refresh-token"}

    async with test_session_factory() as db:
        account = await db.scalar(select(GmailAccount).where(GmailAccount.user_id == user["id"]))
        owner = await db.get(User, user["id"])
        pending_state = await db.get(OAuthState, "pending-disconnect-state")
        retained_email = await db.scalar(select(RawEmail).where(RawEmail.user_id == user["id"]))
        audit = await db.scalar(
            select(ConnectorAuditEvent)
            .where(
                ConnectorAuditEvent.user_id == user["id"],
                ConnectorAuditEvent.event_type == "disconnect",
            )
            .order_by(ConnectorAuditEvent.created_at.desc())
        )

    assert account is None
    assert owner is not None
    assert owner.gmail_connection_generation == 1
    assert pending_state is None
    assert retained_email is not None
    assert audit is not None
    assert json.loads(audit.payload_json) == {
        "provider_revocation": "revoked",
        "retained_raw_email_count": 1,
        "derived_records_retained": True,
    }


async def test_gmail_callback_rejects_an_oauth_state_invalidated_by_disconnect(
    client,
    monkeypatch,
    test_session_factory,
):
    demo = await client.post("/api/auth/demo")
    demo.raise_for_status()
    user = demo.json()["user"]
    state = "invalidated-gmail-state"
    browser_token = "invalidated-browser-token"

    async with test_session_factory() as db:
        owner = await db.get(User, user["id"])
        assert owner is not None
        owner.gmail_connection_generation = 1
        db.add(
            OAuthState(
                state=state,
                user_id=user["id"],
                flow_type="gmail_connect",
                browser_token_hash=hash_session_token(browser_token),
                code_verifier_ref=encrypt_secret("invalidated-verifier"),
                nonce_ref=encrypt_secret("invalidated-nonce"),
                connection_generation=0,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()

    monkeypatch.setattr(
        gmail_routes,
        "exchange_code_for_tokens",
        lambda *args, **kwargs: {
            "access_token": "unclaimed-access-token",
            "refresh_token": "unclaimed-refresh-token",
            "id_token": "invalidated-id-token",
            "scopes": gmail_routes.GMAIL_SCOPES,
        },
    )
    monkeypatch.setattr(
        gmail_routes,
        "verify_google_identity",
        lambda *args, **kwargs: {
            "google_account_id": "invalidated-subject",
            "email": "invalidated@example.com",
            "name": "Invalidated",
        },
    )
    revoked: list[str] = []

    async def fake_revoke(token: str) -> bool:
        revoked.append(token)
        return True

    monkeypatch.setattr(gmail_routes, "revoke_google_token", fake_revoke)
    client.cookies.set(gmail_routes.settings.OAUTH_COOKIE_NAME, browser_token)

    response = await client.get(
        f"/api/auth/gmail/callback?code=invalidated-code&state={state}",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard?gmail_error=gmail_connection_invalidated"
    assert revoked == ["unclaimed-refresh-token"]
    async with test_session_factory() as db:
        assert (
            await db.scalar(select(GmailAccount).where(GmailAccount.user_id == user["id"])) is None
        )


async def test_gmail_disconnect_removes_local_grant_when_provider_is_unavailable(
    client,
    monkeypatch,
    test_session_factory,
    caplog,
):
    demo = await client.post("/api/auth/demo")
    demo.raise_for_status()
    user = demo.json()["user"]
    secret = "provider failure containing private-token-material"

    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="gmail-failed-revocation-subject",
                access_token_ref=encrypt_secret("failed-revocation-access"),
                refresh_token_ref=encrypt_secret("failed-revocation-refresh"),
            )
        )
        await db.commit()

    async def fail_revoke(_token: str) -> bool:
        raise RuntimeError(secret)

    monkeypatch.setattr(gmail_routes, "revoke_google_token", fail_revoke)
    with caplog.at_level(logging.WARNING, logger="app.api.routes.gmail"):
        response = await client.delete(
            f"/api/gmail/connection?user_id={user['id']}",
            headers={"X-CSRF-Token": client.cookies.get("pfis_csrf")},
        )

    assert response.status_code == 200
    assert response.json()["provider_revocation"] == "unconfirmed"
    assert secret not in caplog.text
    assert "exception=RuntimeError" in caplog.text
    async with test_session_factory() as db:
        account = await db.scalar(select(GmailAccount).where(GmailAccount.user_id == user["id"]))
    assert account is None


async def test_gmail_callback_failure_does_not_log_provider_secret(client, monkeypatch, caplog):
    demo = await client.post("/api/auth/demo")
    demo.raise_for_status()
    user = demo.json()["user"]
    state = "gmail-private-failure-state"
    secret = "invalid_grant provider-secret-must-not-be-logged"

    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            state,
            "verifier",
            "nonce",
        ),
    )
    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307

    def fail_exchange(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(gmail_routes, "exchange_code_for_tokens", fail_exchange)

    with caplog.at_level(logging.ERROR, logger="app.api.routes.gmail"):
        callback = await client.get(
            f"/api/auth/gmail/callback?code=gmail-code&state={state}",
            follow_redirects=False,
        )

    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard?gmail_error=gmail_connection_failed"
    assert secret not in caplog.text
    assert "exception=RuntimeError" in caplog.text


async def test_gmail_callback_redirects_denied_consent_and_consumes_state(client, monkeypatch):
    state = "gmail-denied-state"
    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            state,
            "verifier",
            "nonce",
        ),
    )

    user = await create_user(client, "gmaildenied")
    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307

    denied = await client.get(
        f"/api/auth/gmail/callback?state={state}&error=access_denied",
        follow_redirects=False,
    )
    assert denied.status_code == 303
    assert denied.headers["location"] == "/dashboard?gmail_error=access_denied"

    replay = await client.get(
        f"/api/auth/gmail/callback?state={state}&code=late-code",
        follow_redirects=False,
    )
    assert replay.status_code == 400


async def test_gmail_callback_redirects_when_provider_omits_code(client, monkeypatch):
    state = "gmail-missing-code-state"
    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            state,
            "verifier",
            "nonce",
        ),
    )

    user = await create_user(client, "gmailmissing")
    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307

    callback = await client.get(
        f"/api/auth/gmail/callback?state={state}",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard?gmail_error=missing_code"


async def test_gmail_callback_requires_readonly_scope_before_persisting(
    client, monkeypatch, test_session_factory
):
    state = "gmail-missing-scope-state"
    user = await create_user(client, "gmailscope")

    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            state,
            "verifier",
            "nonce",
        ),
    )
    monkeypatch.setattr(
        gmail_routes,
        "exchange_code_for_tokens",
        lambda *args, **kwargs: {
            "access_token": "scope-access",
            "refresh_token": "scope-refresh",
            "id_token": "scope-id",
            "scopes": oauth_service.IDENTITY_SCOPES,
        },
    )

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307

    callback = await client.get(
        f"/api/auth/gmail/callback?state={state}&code=scope-code",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard?gmail_error=gmail_scope_required"

    async with test_session_factory() as db:
        result = await db.execute(select(GmailAccount).where(GmailAccount.user_id == user["id"]))
        assert result.scalar_one_or_none() is None


async def test_gmail_callback_rejects_cross_user_mailbox_takeover(
    client, monkeypatch, test_session_factory
):
    first_user = await create_user(client, "gmailowner")
    second_user = await create_user(client, "gmailintruder")
    states = iter(("gmail-owner-state", "gmail-takeover-state"))

    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            next(states),
            "verifier",
            "nonce",
        ),
    )
    monkeypatch.setattr(
        gmail_routes,
        "exchange_code_for_tokens",
        lambda code, *args, **kwargs: {
            "access_token": f"access-{code}",
            "refresh_token": f"refresh-{code}",
            "id_token": "shared-id",
            "scopes": gmail_routes.GMAIL_SCOPES,
        },
    )
    monkeypatch.setattr(
        gmail_routes,
        "verify_google_identity",
        lambda token_data, *, expected_nonce=None: {
            "google_account_id": "shared-google-subject",
            "email": "shared-mailbox@example.com",
            "name": "Shared Mailbox",
        },
    )

    first_connect = await client.get(
        f"/api/auth/gmail/connect?user_id={first_user['id']}",
        follow_redirects=False,
    )
    assert first_connect.status_code == 307
    first_callback = await client.get(
        "/api/auth/gmail/callback?state=gmail-owner-state&code=owner-code",
        follow_redirects=False,
    )
    assert first_callback.headers["location"] == "/dashboard?gmail_auth=success"

    second_connect = await client.get(
        f"/api/auth/gmail/connect?user_id={second_user['id']}",
        follow_redirects=False,
    )
    assert second_connect.status_code == 307
    second_callback = await client.get(
        "/api/auth/gmail/callback?state=gmail-takeover-state&code=takeover-code",
        follow_redirects=False,
    )
    assert second_callback.status_code == 303
    assert second_callback.headers["location"] == "/dashboard?gmail_error=gmail_account_conflict"

    async with test_session_factory() as db:
        accounts = (await db.execute(select(GmailAccount))).scalars().all()
        assert len(accounts) == 1
        assert accounts[0].user_id == first_user["id"]

    first_status = await client.get(f"/api/gmail/auto-sync?user_id={first_user['id']}")
    second_status = await client.get(f"/api/gmail/auto-sync?user_id={second_user['id']}")
    assert first_status.status_code == 200
    assert first_status.json()["connection_status"] == "connected"
    assert second_status.status_code == 404


async def test_gmail_reconnect_preserves_cursor_and_rejects_mailbox_replacement(
    client,
    monkeypatch,
    test_session_factory,
):
    user = await create_user(client, "gmailreconnect")
    states = iter(("gmail-initial-state", "gmail-reconnect-state", "gmail-replace-state"))

    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            next(states),
            "verifier",
            "nonce",
        ),
    )
    monkeypatch.setattr(
        gmail_routes,
        "exchange_code_for_tokens",
        lambda code, *args, **kwargs: {
            "access_token": f"access-{code}",
            "refresh_token": f"refresh-{code}",
            "id_token": "reconnect-id",
            "scopes": gmail_routes.GMAIL_SCOPES,
        },
    )

    def fake_identity(token_data, *, expected_nonce=None):
        subject = (
            "subject-two" if token_data["access_token"] == "access-replace-code" else "subject-one"
        )
        return {
            "google_account_id": subject,
            "email": f"{subject}@example.com",
            "name": subject,
        }

    monkeypatch.setattr(gmail_routes, "verify_google_identity", fake_identity)

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307
    initial = await client.get(
        "/api/auth/gmail/callback?state=gmail-initial-state&code=initial-code",
        follow_redirects=False,
    )
    assert initial.headers["location"] == "/dashboard?gmail_auth=success"

    async with test_session_factory() as db:
        account = (await db.execute(select(GmailAccount))).scalar_one()
        account.last_history_id = "cursor-before-reconnect"
        account.auto_sync_status = "paused"
        account.auto_sync_error = "Gmail authorization is invalid or revoked"
        await db.commit()

    reauth_status = await client.get(f"/api/gmail/auto-sync?user_id={user['id']}")
    assert reauth_status.status_code == 200
    assert reauth_status.json()["connection_status"] == "reauthorization_required"

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307
    reconnect = await client.get(
        "/api/auth/gmail/callback?state=gmail-reconnect-state&code=reconnect-code",
        follow_redirects=False,
    )
    assert reconnect.headers["location"] == "/dashboard?gmail_auth=success"

    async with test_session_factory() as db:
        account = (await db.execute(select(GmailAccount))).scalar_one()
        assert account.google_account_id == "subject-one"
        assert account.last_history_id == "cursor-before-reconnect"
        assert decrypt_secret(account.access_token_ref) == "access-reconnect-code"
        assert decrypt_secret(account.refresh_token_ref) == "refresh-reconnect-code"
        assert account.auto_sync_status == "idle"
        assert account.auto_sync_error is None

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307
    replacement = await client.get(
        "/api/auth/gmail/callback?state=gmail-replace-state&code=replace-code",
        follow_redirects=False,
    )
    assert replacement.status_code == 303
    assert replacement.headers["location"] == "/dashboard?gmail_error=gmail_account_mismatch"

    async with test_session_factory() as db:
        account = (await db.execute(select(GmailAccount))).scalar_one()
        assert account.google_account_id == "subject-one"
        assert decrypt_secret(account.access_token_ref) == "access-reconnect-code"


async def test_gmail_reconnect_requires_a_new_refresh_token_after_auth_error(
    client, monkeypatch, test_session_factory
):
    user = await create_user(client, "gmail-refresh-required")
    state = "gmail-refresh-required-state"
    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="refresh-required-subject",
                access_token_ref=encrypt_secret("old-access"),
                refresh_token_ref=encrypt_secret("old-refresh"),
                auto_sync_status="paused",
                auto_sync_error="Gmail authorization is invalid or revoked",
            )
        )
        await db.commit()

    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda **_kwargs: ("https://accounts.google.test/gmail", state, "v", "n"),
    )
    monkeypatch.setattr(
        gmail_routes,
        "exchange_code_for_tokens",
        lambda *_args, **_kwargs: {
            "access_token": "new-access",
            "id_token": "new-id",
            "scopes": gmail_routes.GMAIL_SCOPES,
        },
    )
    monkeypatch.setattr(
        gmail_routes,
        "verify_google_identity",
        lambda *_args, **_kwargs: {
            "google_account_id": "refresh-required-subject",
            "email": "refresh-required@example.com",
            "name": "Refresh Required",
        },
    )

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}", follow_redirects=False
    )
    assert connect.status_code == 307
    callback = await client.get(
        f"/api/auth/gmail/callback?state={state}&code=reauth-code",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard?gmail_error=gmail_transaction_invalid"

    async with test_session_factory() as db:
        account = await db.scalar(select(GmailAccount).where(GmailAccount.user_id == user["id"]))
    assert account is not None
    assert decrypt_secret(account.access_token_ref) == "old-access"


async def test_gmail_callback_converts_ownership_race_to_safe_redirect(
    client,
    monkeypatch,
    test_session_factory,
):
    state = "gmail-race-state"
    user = await create_user(client, "gmailrace")
    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda redirect_uri=None, scopes=None, offline=True: (
            "https://accounts.google.test/gmail",
            state,
            "verifier",
            "nonce",
        ),
    )
    monkeypatch.setattr(
        gmail_routes,
        "exchange_code_for_tokens",
        lambda *args, **kwargs: {
            "access_token": "race-access",
            "refresh_token": "race-refresh",
            "id_token": "race-id",
            "scopes": gmail_routes.GMAIL_SCOPES,
        },
    )
    monkeypatch.setattr(
        gmail_routes,
        "verify_google_identity",
        lambda token_data, *, expected_nonce=None: {
            "google_account_id": "race-google-subject",
            "email": "race@example.com",
            "name": "Race User",
        },
    )

    connect = await client.get(
        f"/api/auth/gmail/connect?user_id={user['id']}",
        follow_redirects=False,
    )
    assert connect.status_code == 307

    original_flush = AsyncSession.flush

    async def fail_for_new_gmail_account(self, *args, **kwargs):
        if any(isinstance(item, GmailAccount) for item in self.new):
            raise IntegrityError("duplicate Gmail ownership", {}, RuntimeError("constraint"))
        return await original_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", fail_for_new_gmail_account)
    callback = await client.get(
        f"/api/auth/gmail/callback?state={state}&code=race-code",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/dashboard?gmail_error=gmail_account_conflict"

    async with test_session_factory() as db:
        assert (await db.execute(select(GmailAccount))).scalar_one_or_none() is None


async def test_protected_route_requires_auth_when_enabled(client, auth_required):
    user, _ = await register_user(client, "needsauth")
    client.cookies.delete("pfis_session")
    client.cookies.delete("pfis_csrf")

    response = await client.get(f"/api/gmail/emails?user_id={user['id']}")
    assert response.status_code == 401


async def test_user_scope_mismatch_is_forbidden(client, auth_required):
    user_one, token_one = await register_user(client, "scopeone")
    user_two, _ = await register_user(client, "scopetwo")

    response = await client.get(
        f"/api/gmail/emails?user_id={user_two['id']}",
        headers=auth_headers(token_one),
    )
    assert response.status_code == 403


async def test_authenticated_user_can_access_own_transactions(client, auth_required):
    user, token = await register_user(client, "ownscope")
    categories_response = await client.get("/api/categories/", headers=auth_headers(token))
    categories_response.raise_for_status()
    food = next(category for category in categories_response.json() if category["name"] == "Food")

    create_response = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        headers=auth_headers(token),
        json={
            "amount": 321.0,
            "transaction_type": "debit",
            "merchant_raw": "SWIGGY",
            "merchant_normalized": "Swiggy",
            "category_id": food["id"],
            "transaction_date": "2026-05-05",
            "account_last4": "1111",
            "reference_id": "auth-own-1",
            "confidence_score": 0.9,
        },
    )
    create_response.raise_for_status()

    list_response = await client.get(
        f"/api/transactions/?user_id={user['id']}&month=5&year=2026",
        headers=auth_headers(token),
    )
    list_response.raise_for_status()
    assert len(list_response.json()) == 1
