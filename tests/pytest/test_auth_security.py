"""Authentication and authorization regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

from app.api.routes import auth as auth_routes

from tests.pytest.helpers import auth_headers, create_user, register_user


async def test_demo_seed_user_can_login_with_configured_password(client):
    response = await client.post(
        "/api/auth/login",
        json={"email": "demo@pfis.app", "password": "demo12345"},
    )
    response.raise_for_status()

    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["email"] == "demo@pfis.app"


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

    def fake_authorization_url(redirect_uri=None):
        return "https://accounts.google.test/oauth", state

    def fake_exchange(code, redirect_uri=None):
        assert code == "oauth-code"
        return {
            "access_token": "google-access",
            "refresh_token": "google-refresh",
            "id_token": "google-id",
        }

    def fake_identity(token_data):
        assert token_data["id_token"] == "google-id"
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
        f"/api/auth/google/callback?code=oauth-code&state={state}"
    )
    callback_response.raise_for_status()
    assert "localStorage.setItem('pfis.session.v3'" in callback_response.text
    assert "naveenrohith2056@gmail.com" in callback_response.text


async def test_protected_route_requires_auth_when_enabled(client, auth_required):
    user = await create_user(client, "needsauth")

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
