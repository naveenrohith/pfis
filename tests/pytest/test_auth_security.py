"""Authentication and authorization regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.api.routes import auth as auth_routes
from app.api.routes import gmail as gmail_routes
from app.models.auth import AuthSession
from app.models.email import GmailAccount
from app.services.gmail import oauth_service
from sqlalchemy import select

from tests.pytest.helpers import auth_headers, register_user


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


def test_gmail_consent_can_include_existing_google_grants(monkeypatch):
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

    assert captured["include_granted_scopes"] == "true"
    assert captured["access_type"] == "offline"


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
            "email": "naveenrohith2056@gmail.com",
            "name": "Naveen Rohith",
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
    assert session_response.json()["user"]["email"] == "naveenrohith2056@gmail.com"


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

    assert callback.status_code == 500
    assert secret not in caplog.text
    assert "exception=RuntimeError" in caplog.text


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
