"""Production invariants for account, balance, net-worth, and transfer mutations."""

from datetime import date
from unittest.mock import AsyncMock

import pytest
from app.models.transaction import Transaction
from app.schemas.account import TransferCreate
from app.services.account_service import AccountService
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.pytest.helpers import auth_headers, create_user, register_user


async def _create_account(
    client: AsyncClient,
    user_id: str,
    suffix: str,
    *,
    currency: str = "INR",
) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": f"Invariant Bank {suffix}",
            "account_type": "bank",
            "masked_number": f"****{suffix}",
            "currency": currency,
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_account_input_is_normalized(client: AsyncClient):
    user = await create_user(client, "normalized-account")
    response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "  Normalized Bank  ",
            "account_type": " bank ",
            "masked_number": "  ****9090  ",
            "currency": " inr ",
        },
    )

    assert response.status_code == 201
    assert response.json()["institution_name"] == "Normalized Bank"
    assert response.json()["account_type"] == "bank"
    assert response.json()["masked_number"] == "****9090"
    assert response.json()["currency"] == "INR"


@pytest.mark.asyncio
async def test_currency_contract_rejects_non_string_values(client: AsyncClient):
    user = await create_user(client, "invalid-currency")
    response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Invalid Currency Bank",
            "account_type": "bank",
            "masked_number": "****9091",
            "currency": 123,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_transaction_currency_is_normalized_and_bounded(client: AsyncClient):
    user = await create_user(client, "transaction-contract")
    valid = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10,
            "currency": " usd ",
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
            "reference_id": "valid-reference",
        },
    )
    oversized = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
            "reference_id": "x" * 101,
        },
    )

    assert valid.status_code == 201
    assert valid.json()["currency"] == "USD"
    assert oversized.status_code == 422


@pytest.mark.asyncio
async def test_transaction_currency_must_match_linked_account(client: AsyncClient):
    user = await create_user(client, "linked-account-currency")
    account = await _create_account(client, user["id"], "9092", currency="INR")

    response = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10,
            "currency": "USD",
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
            "financial_account_id": account["id"],
        },
    )

    assert response.status_code == 409
    assert "must match" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_balance_currency_must_match_account(client: AsyncClient):
    user = await create_user(client, "balance-currency")
    account = await _create_account(client, user["id"], "1001")

    response = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={"amount": 50, "currency": "USD", "as_of": date.today().isoformat()},
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Balance currency must match the account currency"


@pytest.mark.asyncio
async def test_account_currency_cannot_change_after_history_exists(client: AsyncClient):
    user = await create_user(client, "account-history")
    account = await _create_account(client, user["id"], "1002")
    balance = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={"amount": 50, "as_of": date.today().isoformat()},
    )
    assert balance.status_code == 201

    response = await client.patch(
        f"/api/accounts/{account['id']}?user_id={user['id']}", json={"currency": "USD"}
    )

    assert response.status_code == 409
    assert "cannot change" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_net_worth_rejects_mixed_currencies(client: AsyncClient):
    user = await create_user(client, "mixed-net-worth")
    await _create_account(client, user["id"], "1003", currency="INR")
    await _create_account(client, user["id"], "1004", currency="USD")

    response = await client.get(f"/api/net-worth?user_id={user['id']}")

    assert response.status_code == 422
    assert "without exchange rates" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_inactive_accounts_cannot_transfer(client: AsyncClient):
    user = await create_user(client, "inactive-transfer")
    first = await _create_account(client, user["id"], "1005")
    second = await _create_account(client, user["id"], "1006")
    deactivated = await client.patch(
        f"/api/accounts/{first['id']}?user_id={user['id']}", json={"is_active": False}
    )
    assert deactivated.status_code == 200

    response = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": first["id"],
            "to_account_id": second["id"],
            "amount": 25,
            "currency": "INR",
            "transaction_date": date.today().isoformat(),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Transfers require active accounts"


@pytest.mark.asyncio
async def test_account_routes_reject_cross_user_scope(client: AsyncClient, auth_required):
    owner, owner_token = await register_user(client, "account-owner")
    attacker, attacker_token = await register_user(client, "account-attacker")
    account = await client.post(
        f"/api/accounts?user_id={owner['id']}",
        headers=auth_headers(owner_token),
        json={
            "institution_name": "Owned Bank",
            "account_type": "bank",
            "masked_number": "****7001",
            "currency": "INR",
        },
    )
    assert account.status_code == 201

    response = await client.patch(
        f"/api/accounts/{account.json()['id']}?user_id={owner['id']}",
        headers=auth_headers(attacker_token),
        json={"institution_name": "Stolen Bank"},
    )

    assert attacker["id"] != owner["id"]
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_transfer_rolls_back_both_ledger_entries_on_commit_failure(
    client: AsyncClient, test_session_factory, monkeypatch: pytest.MonkeyPatch
):
    user = await create_user(client, "transfer-rollback")
    first = await _create_account(client, user["id"], "1007")
    second = await _create_account(client, user["id"], "1008")

    async with test_session_factory() as session:
        real_commit = session.commit
        rollback = AsyncMock(wraps=session.rollback)
        monkeypatch.setattr(session, "commit", AsyncMock(side_effect=RuntimeError("commit failed")))
        monkeypatch.setattr(session, "rollback", rollback)
        with pytest.raises(RuntimeError, match="commit failed"):
            await AccountService(session).create_transfer(
                user["id"],
                TransferCreate(
                    from_account_id=first["id"],
                    to_account_id=second["id"],
                    amount=25,
                    currency="INR",
                    transaction_date=date.today(),
                ),
            )
        rollback.assert_awaited_once()
        monkeypatch.setattr(session, "commit", real_commit)
        count = await session.scalar(
            select(func.count(Transaction.id)).where(Transaction.user_id == user["id"])
        )

    assert count == 0
