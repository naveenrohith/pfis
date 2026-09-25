"""Production invariants for account, balance, net-worth, and transfer mutations."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from app.models.sync import PipelineEvent, UserCorrection
from app.models.transaction import Transaction, TransactionType
from app.schemas.account import TransferCreate
from app.services.account_service import AccountService
from app.services.transaction_service import TransactionService
from httpx import AsyncClient
from sqlalchemy import func, select

from tests.pytest.helpers import auth_headers, create_user, register_user, user_today


async def _create_account(
    client: AsyncClient,
    user_id: str,
    suffix: str,
    *,
    currency: str = "INR",
    account_type: str = "bank",
) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": f"Invariant Bank {suffix}",
            "account_type": account_type,
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
async def test_account_response_exposes_transaction_rolled_current_bank_and_card_positions(
    client: AsyncClient,
):
    user = await create_user(client, "account-current-positions")
    today = user_today(user)
    snapshot_date = today - timedelta(days=1)
    for suffix, account_type in (("8111", "bank"), ("8222", "credit_card")):
        account = await _create_account(
            client,
            user["id"],
            suffix,
            account_type=account_type,
        )
        balance = await client.post(
            f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
            json={"amount": 100, "as_of": snapshot_date.isoformat()},
        )
        balance.raise_for_status()
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 20,
                "currency": "INR",
                "transaction_type": "debit",
                "transaction_status": "completed",
                "transaction_date": today.isoformat(),
                "financial_account_id": account["id"],
                "merchant_raw": f"Current position fixture {account_type}",
            },
        )
        transaction.raise_for_status()
        reviewed = await client.patch(
            f"/api/transactions/{transaction.json()['id']}?user_id={user['id']}",
            json={"reviewed_flag": True},
        )
        reviewed.raise_for_status()

    response = await client.get(f"/api/accounts?user_id={user['id']}")
    response.raise_for_status()
    by_type = {row["account_type"]: row for row in response.json()}

    bank = by_type["bank"]
    assert bank["latest_balance"] == 100
    assert bank["current_balance"] == 80
    assert bank["current_balance_status"] == "estimated"
    assert bank["current_balance_as_of"] == today.isoformat()
    assert bank["current_balance_confidence"] > 0

    card = by_type["credit_card"]
    assert card["latest_balance"] == 100
    assert card["current_balance"] == 120
    assert card["current_balance_status"] == "estimated"
    assert card["current_balance_as_of"] == today.isoformat()
    assert card["current_balance_confidence"] > 0


@pytest.mark.asyncio
async def test_user_can_resolve_unknown_account_identity_without_replacing_it(client: AsyncClient):
    user = await create_user(client, "resolve-account-identity")
    today = user_today(user)
    transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 425,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_date": today.isoformat(),
            "merchant_raw": "Identity evidence",
            "account_last4": "8182",
        },
    )
    transaction.raise_for_status()
    account_id = transaction.json()["financial_account_id"]

    resolved = await client.patch(
        f"/api/accounts/{account_id}?user_id={user['id']}",
        json={
            "institution_name": "HDFC primary account",
            "account_type": "bank",
            "masked_number": "****8182",
        },
    )

    resolved.raise_for_status()
    assert resolved.json()["id"] == account_id
    assert resolved.json()["account_type"] == "bank"
    assert resolved.json()["balance_kind"] == "asset"
    assert resolved.json()["identity_status"] == "confirmed"
    assert resolved.json()["identity_confidence"] == 1.0
    assert resolved.json()["identity_evidence"][-1]["role"] == "identity_update"

    identity_history = await client.get(
        f"/api/accounts/{account_id}/identity-history?user_id={user['id']}"
    )
    identity_history.raise_for_status()
    assert len(identity_history.json()) >= 2
    assert identity_history.json()[-1]["identity_status"] == "confirmed"

    future = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 500,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_date": today.replace(day=1).isoformat(),
            "merchant_raw": "Future linked evidence",
            "account_last4": "8182",
            "reference_id": "resolved-account-future",
        },
    )
    future.raise_for_status()
    assert future.json()["financial_account_id"] == account_id

    timeline = await client.get(
        f"/api/knowledge/events?user_id={user['id']}"
        f"&range_start={today.isoformat()}&range_end={today.isoformat()}"
    )
    timeline.raise_for_status()
    account_events = [
        event for event in timeline.json()["events"] if event["kind"] == "account_identity"
    ]
    assert account_events
    assert account_events[0]["direction"] == "neutral"
    assert account_events[0]["amount"] == {"low": None, "expected": None, "high": None}


@pytest.mark.asyncio
async def test_validated_product_type_enforces_balance_kind(client: AsyncClient):
    user = await create_user(client, "validated-account-product")
    response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Incorrect Card",
            "account_type": "credit_card",
            "balance_kind": "asset",
            "masked_number": "****8190",
            "currency": "INR",
        },
    )

    assert response.status_code == 409
    assert "must be recorded as liabilities" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_explicit_product_creation_upgrades_legacy_masked_account_in_place(
    client: AsyncClient,
):
    user = await create_user(client, "account-repair")
    transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 425,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": "Account repair fixture",
            "account_last4": "8181",
        },
    )
    transaction.raise_for_status()
    legacy_account_id = transaction.json()["financial_account_id"]

    upgraded = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Explicit Card Bank",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "••••8181",
            "currency": "INR",
        },
    )
    upgraded.raise_for_status()
    assert upgraded.json()["id"] == legacy_account_id
    assert upgraded.json()["account_type"] == "credit_card"
    assert upgraded.json()["balance_kind"] == "liability"
    assert upgraded.json()["identity_status"] == "confirmed"
    assert upgraded.json()["identity_confidence"] == 1.0

    listed = await client.get(f"/api/transactions/?user_id={user['id']}&limit=20")
    listed.raise_for_status()
    repaired = next(item for item in listed.json() if item["id"] == transaction.json()["id"])
    assert repaired["financial_account_id"] == legacy_account_id


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
    user = await create_user(client, "transaction-contract", currency=" usd ")
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
async def test_transaction_currency_must_match_user_ledger(client: AsyncClient):
    user = await create_user(client, "transaction-ledger")
    response = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10,
            "currency": "USD",
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "Transaction currency USD does not match ledger currency INR"
    )


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
    assert response.json()["error"]["message"] == (
        "Transaction currency USD does not match ledger currency INR"
    )


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
    assert response.json()["error"]["message"] == (
        "Account currency USD does not match ledger currency INR"
    )


@pytest.mark.asyncio
async def test_account_currency_must_match_user_ledger(client: AsyncClient):
    user = await create_user(client, "account-ledger")
    await _create_account(client, user["id"], "1003", currency="INR")
    response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Foreign Currency Bank",
            "account_type": "bank",
            "masked_number": "****1004",
            "currency": "USD",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "Account currency USD does not match ledger currency INR"
    )


@pytest.mark.asyncio
async def test_empty_net_worth_uses_user_ledger_currency(client: AsyncClient):
    user = await create_user(client, "empty-net-worth", currency="USD")
    response = await client.get(f"/api/net-worth?user_id={user['id']}")

    response.raise_for_status()
    assert response.json()["currency"] == "USD"


@pytest.mark.asyncio
async def test_hdfc_statement_import_requires_an_inr_ledger(client: AsyncClient):
    user = await create_user(client, "usd-hdfc-statement", currency="USD")
    account = await _create_account(
        client,
        user["id"],
        "1009",
        account_type="credit_card",
        currency="USD",
    )
    response = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": account["id"],
            "document_fingerprint": "a" * 64,
            "statement_text": (
                "HDFC BANK CREDIT CARD STATEMENT\n"
                "STATEMENT DATE: 05/03/2026\n"
                "STATEMENT PERIOD: 06/02/2026 TO 05/03/2026\n"
                "TOTAL AMOUNT DUE: 900.00\n"
            ),
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "HDFC statement imports currently support INR accounts only"
    )


@pytest.mark.asyncio
async def test_legacy_currency_mismatches_are_excluded_and_reported(
    client: AsyncClient,
    test_session_factory,
):
    user = await create_user(client, "legacy-currency-integrity")
    async with test_session_factory() as db:
        db.add(
            Transaction(
                user_id=user["id"],
                amount=Decimal("99.00"),
                currency="USD",
                transaction_type=TransactionType.DEBIT,
                transaction_date=date.today(),
                fingerprint=f"legacy-currency-{user['id']}",
            )
        )
        await db.commit()
        summary = await TransactionService(db).get_monthly_summary(
            user["id"],
            date.today().month,
            date.today().year,
        )

    assert summary["total_spend"] == 0
    assert summary["transaction_count"] == 0
    health = await client.get("/api/health/ops")
    health.raise_for_status()
    assert health.json()["status"] == "needs_repair"
    assert "ledger_currency_needs_repair" in health.json()["status_reasons"]
    assert health.json()["ledger_currency"]["transaction_mismatches"] == 1
    assert health.json()["ledger_currency"]["status"] == "needs_repair"


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
async def test_atm_withdrawal_creates_bank_to_cash_transfer_without_spend(client: AsyncClient):
    user = await create_user(client, "atm-withdrawal")
    other = await create_user(client, "atm-withdrawal-other")
    bank = await _create_account(client, user["id"], "2001")
    cash = await _create_account(
        client,
        user["id"],
        "wallet",
        account_type="cash",
    )

    response = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": bank["id"],
            "to_account_id": cash["id"],
            "amount": 500,
            "currency": "INR",
            "transaction_date": date.today().isoformat(),
            "payment_rail": "atm",
        },
    )
    assert response.status_code == 201
    assert response.json()["payment_rail"] == "atm"

    listed = await client.get(f"/api/transactions/?user_id={user['id']}")
    transactions = listed.json()
    assert len(transactions) == 2
    assert {item["payment_rail"] for item in transactions} == {"atm"}
    assert all(item["is_transfer"] for item in transactions)
    assert {item["financial_account_id"] for item in transactions} == {bank["id"], cash["id"]}

    today = date.today()
    summary = await client.get(
        f"/api/transactions/summary?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert summary.status_code == 200
    assert summary.json()["total_spend"] == 0
    assert summary.json()["total_income"] == 0

    cash_spend = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "financial_account_id": cash["id"],
            "amount": 125,
            "currency": "INR",
            "transaction_type": "debit",
            "payment_method": "other",
            "transaction_date": today.isoformat(),
            "merchant_raw": "Cash tea stall",
            "merchant_normalized": "Cash tea stall",
            "reference_id": "cash-spend-1",
            "confidence_score": 1,
        },
    )
    cash_spend.raise_for_status()

    refreshed = await client.get(
        f"/api/transactions/summary?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    refreshed.raise_for_status()
    assert refreshed.json()["total_spend"] == 125
    assert refreshed.json()["total_income"] == 0
    assert refreshed.json()["transaction_count"] == 1

    pocket = await client.get(f"/api/accounts/{cash['id']}/cash-pocket?user_id={user['id']}")
    pocket.raise_for_status()
    assert pocket.json()["transfers_in"] == 500
    assert pocket.json()["cash_spend"] == 125
    assert pocket.json()["balance"] == 375

    cross_user = await client.get(f"/api/accounts/{cash['id']}/cash-pocket?user_id={other['id']}")
    assert cross_user.status_code == 404


@pytest.mark.asyncio
async def test_observed_atm_debit_links_to_cash_once_and_remains_non_spend(client: AsyncClient):
    user = await create_user(client, "observed-atm-withdrawal")
    other = await create_user(client, "observed-atm-other")
    bank = await _create_account(client, user["id"], "2011")
    cash = await _create_account(client, user["id"], "cash", account_type="cash")
    observed = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "financial_account_id": bank["id"],
            "amount": 750,
            "currency": "INR",
            "transaction_type": "debit",
            "payment_method": "debit_card",
            "payment_rail": "atm",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": "BANER",
            "merchant_normalized": "ATM cash withdrawal",
            "confidence_score": 1,
        },
    )
    observed.raise_for_status()

    denied = await client.post(
        f"/api/transactions/{observed.json()['id']}/atm-cash-link?user_id={other['id']}",
        json={"cash_account_id": cash["id"]},
    )
    assert denied.status_code == 404

    linked = await client.post(
        f"/api/transactions/{observed.json()['id']}/atm-cash-link?user_id={user['id']}",
        json={"cash_account_id": cash["id"]},
    )
    linked.raise_for_status()
    repeated = await client.post(
        f"/api/transactions/{observed.json()['id']}/atm-cash-link?user_id={user['id']}",
        json={"cash_account_id": cash["id"]},
    )
    repeated.raise_for_status()
    assert repeated.json()["transfer_group_id"] == linked.json()["transfer_group_id"]

    listed = await client.get(f"/api/transactions/?user_id={user['id']}")
    transactions = listed.json()
    assert len(transactions) == 2
    assert all(item["is_transfer"] for item in transactions)
    assert {item["financial_account_id"] for item in transactions} == {
        bank["id"],
        cash["id"],
    }
    summary = await client.get(
        f"/api/transactions/summary?user_id={user['id']}"
        f"&month={date.today().month}&year={date.today().year}"
    )
    summary.raise_for_status()
    assert summary.json()["total_spend"] == 0
    assert summary.json()["total_income"] == 0


@pytest.mark.asyncio
async def test_atm_withdrawal_rejects_non_bank_to_cash_pairs(client: AsyncClient):
    user = await create_user(client, "invalid-atm-withdrawal")
    first_bank = await _create_account(client, user["id"], "2002")
    second_bank = await _create_account(client, user["id"], "2003")

    response = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": first_bank["id"],
            "to_account_id": second_bank["id"],
            "amount": 500,
            "currency": "INR",
            "transaction_date": date.today().isoformat(),
            "payment_rail": "atm",
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["error"]["message"]
        == "ATM withdrawals must move money from a bank account to a cash account"
    )


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


@pytest.mark.asyncio
async def test_transfer_ledger_fields_cannot_be_edited_individually(client: AsyncClient):
    user = await create_user(client, "protected-transfer")
    first = await _create_account(client, user["id"], "1010")
    second = await _create_account(client, user["id"], "1011")
    transfer = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": first["id"],
            "to_account_id": second["id"],
            "amount": 25,
            "currency": "INR",
            "transaction_date": date.today().isoformat(),
        },
    )
    debit_id = transfer.json()["debit_transaction_id"]

    response = await client.patch(f"/api/transactions/{debit_id}", json={"amount": 99})
    listed = await client.get(f"/api/transactions/?user_id={user['id']}")

    assert response.status_code == 409
    assert "cannot be edited individually" in response.json()["error"]["message"]
    assert {item["amount"] for item in listed.json()} == {25}


@pytest.mark.asyncio
async def test_deleting_one_transfer_leg_deletes_the_pair(client: AsyncClient):
    user = await create_user(client, "delete-transfer")
    first = await _create_account(client, user["id"], "1012")
    second = await _create_account(client, user["id"], "1013")
    transfer = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": first["id"],
            "to_account_id": second["id"],
            "amount": 25,
            "currency": "INR",
            "transaction_date": date.today().isoformat(),
        },
    )

    response = await client.delete(f"/api/transactions/{transfer.json()['credit_transaction_id']}")
    listed = await client.get(f"/api/transactions/?user_id={user['id']}")

    assert response.status_code == 204
    assert listed.json() == []


@pytest.mark.asyncio
async def test_deleting_corrected_transaction_cleans_history_and_detaches_events(
    client: AsyncClient, test_session_factory
):
    user = await create_user(client, "delete-corrected")
    created = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 10,
            "transaction_type": "debit",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": "Original merchant",
        },
    )
    transaction_id = created.json()["id"]
    corrected = await client.patch(
        f"/api/transactions/{transaction_id}", json={"merchant_normalized": "Corrected merchant"}
    )
    assert corrected.status_code == 200

    async with test_session_factory() as session:
        session.add(
            PipelineEvent(
                user_id=user["id"],
                transaction_id=transaction_id,
                event_type="test_event",
                stage="test",
                status="completed",
            )
        )
        await session.commit()

    response = await client.delete(f"/api/transactions/{transaction_id}")
    assert response.status_code == 204

    async with test_session_factory() as session:
        transaction_count = await session.scalar(
            select(func.count(Transaction.id)).where(Transaction.id == transaction_id)
        )
        correction_count = await session.scalar(
            select(func.count(UserCorrection.id)).where(
                UserCorrection.transaction_id == transaction_id
            )
        )
        event = await session.scalar(
            select(PipelineEvent).where(PipelineEvent.event_type == "test_event")
        )

    assert transaction_count == 0
    assert correction_count == 0
    assert event is not None
    assert event.transaction_id is None


@pytest.mark.asyncio
async def test_user_approved_account_link_rule_repairs_only_uncorrected_history(
    client: AsyncClient,
):
    user = await create_user(client, "account-link-rule")
    other = await create_user(client, "account-link-rule-other")
    first = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "First Card",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****7788",
            "currency": "INR",
        },
    )
    second = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Second Card",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****7788",
            "currency": "INR",
        },
    )
    first.raise_for_status()
    second.raise_for_status()

    async def imported(amount: int, merchant: str):
        response = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": amount,
                "currency": "INR",
                "transaction_type": "debit",
                "payment_method": "credit_card",
                "payment_rail": "other",
                "card_event": "purchase",
                "transaction_date": date.today().isoformat(),
                "merchant_raw": merchant,
                "account_last4": "7788",
                "source_kind": "email",
            },
        )
        response.raise_for_status()
        return response.json()

    corrected = await imported(101, "Explicit correction")
    repairable = await imported(102, "Repairable evidence")
    assert corrected["review_outcome"] == "needs_review"
    assert repairable["review_outcome"] == "needs_review"
    explicit = await client.patch(
        f"/api/transactions/{corrected['id']}",
        json={"financial_account_id": second.json()["id"]},
    )
    explicit.raise_for_status()

    approved = await client.post(
        f"/api/account-link-rules?user_id={user['id']}",
        json={
            "financial_account_id": first.json()["id"],
            "evidence_kind": "masked_suffix",
            "evidence_value": "7788",
            "currency": "INR",
        },
    )
    approved.raise_for_status()
    assert approved.json()["repaired_transaction_count"] == 1

    repaired = await client.get(f"/api/transactions/{repairable['id']}")
    preserved = await client.get(f"/api/transactions/{corrected['id']}")
    assert repaired.json()["financial_account_id"] == first.json()["id"]
    assert repaired.json()["review_outcome"] == "matched"
    assert preserved.json()["financial_account_id"] == second.json()["id"]

    future = await imported(103, "Future explicit rule")
    assert future["financial_account_id"] == first.json()["id"]
    assert future["review_outcome"] == "newly_imported"

    denied = await client.get(f"/api/account-link-rules?user_id={other['id']}")
    denied.raise_for_status()
    assert denied.json() == []
