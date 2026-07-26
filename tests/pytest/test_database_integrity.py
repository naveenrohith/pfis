"""Database behavior that must be consistent in local and production runtimes."""

from __future__ import annotations

import pytest
from app.models.email import GmailAccount, RawEmail
from app.models.sync import Budget
from sqlalchemy.exc import IntegrityError

from tests.pytest.helpers import create_user


@pytest.mark.asyncio
async def test_postgres_runtime_enforces_foreign_keys(test_session_factory):
    async with test_session_factory() as session:
        session.add(
            Budget(
                user_id="missing-user",
                category_id="missing-category",
                monthly_limit=100,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_database_rejects_duplicate_budget_and_gmail_identity(client, test_session_factory):
    user = await create_user(client, "integrity-unique")
    categories = (await client.get("/api/categories/")).json()
    category_id = categories[0]["id"]

    async with test_session_factory() as session:
        session.add_all(
            [
                Budget(user_id=user["id"], category_id=category_id, monthly_limit=100),
                Budget(user_id=user["id"], category_id=category_id, monthly_limit=200),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        session.add_all(
            [
                GmailAccount(user_id=user["id"], google_account_id="google-1"),
                GmailAccount(user_id=user["id"], google_account_id="google-2"),
            ]
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_transaction_relations_are_validated_with_user_scope(client, test_session_factory):
    owner = await create_user(client, "source-owner")
    attacker = await create_user(client, "source-attacker")
    async with test_session_factory() as session:
        source = RawEmail(
            user_id=owner["id"],
            gmail_message_id="owned-source-email",
            subject="Transaction alert",
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        source_id = source.id

    payload = {
        "amount": 10.25,
        "transaction_type": "debit",
        "transaction_date": "2026-07-21",
        "source_email_id": source_id,
    }
    cross_user = await client.post(f"/api/transactions/?user_id={attacker['id']}", json=payload)
    assert cross_user.status_code == 409
    assert cross_user.json()["error"]["message"] == "Source email not found"

    payload["source_email_id"] = None
    payload["category_id"] = "missing-category"
    missing_category = await client.post(
        f"/api/transactions/?user_id={attacker['id']}", json=payload
    )
    assert missing_category.status_code == 409
    assert missing_category.json()["error"]["message"] == "Category not found"


@pytest.mark.asyncio
async def test_money_inputs_require_two_decimal_fixed_scale(client):
    user = await create_user(client, "money-scale")
    invalid = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10.001,
            "transaction_type": "debit",
            "transaction_date": "2026-07-21",
        },
    )
    assert invalid.status_code == 422

    valid = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10.25,
            "transaction_type": "debit",
            "transaction_date": "2026-07-21",
        },
    )
    assert valid.status_code == 201
    assert valid.json()["amount"] == 10.25


@pytest.mark.asyncio
async def test_account_identity_includes_institution_and_type(client):
    user = await create_user(client, "account-identity")
    base = {
        "institution_name": "Bank A",
        "account_type": "bank",
        "masked_number": "****1234",
        "currency": "INR",
    }
    first = await client.post(f"/api/accounts?user_id={user['id']}", json=base)
    second = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={**base, "institution_name": "Bank B"},
    )
    duplicate = await client.post(f"/api/accounts?user_id={user['id']}", json=base)

    assert first.status_code == second.status_code == 201
    assert duplicate.status_code == 409
