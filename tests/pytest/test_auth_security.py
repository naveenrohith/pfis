"""Authentication and authorization regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

from tests.pytest.helpers import auth_headers, create_user, register_user


async def test_register_login_and_me(client, auth_required):
    user, token = await register_user(client, "authme")

    me_response = await client.get("/api/auth/me", headers=auth_headers(token))
    me_response.raise_for_status()

    payload = me_response.json()
    assert payload["id"] == user["id"]
    assert payload["email"] == user["email"]
    assert payload["is_active"] is True


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