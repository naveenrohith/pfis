"""Integration coverage for historical and current-cycle card utilization."""

from datetime import date, timedelta

from app.models.financial_position import CreditCardStatement, StatementImport
from sqlalchemy import select

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Utilization Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def _add_statement(
    test_session_factory,
    *,
    user_id: str,
    account_id: str,
    statement_date: date,
    total_due: int,
    fingerprint: str,
) -> None:
    async with test_session_factory() as db:
        statement_import = StatementImport(
            user_id=user_id,
            financial_account_id=account_id,
            issuer="TEST",
            document_fingerprint=fingerprint,
            extractor_version="utilization-history-test",
        )
        db.add(statement_import)
        await db.flush()
        db.add(
            CreditCardStatement(
                user_id=user_id,
                statement_import_id=statement_import.id,
                financial_account_id=account_id,
                statement_date=statement_date,
                period_start=statement_date - timedelta(days=30),
                period_end=statement_date,
                due_date=statement_date + timedelta(days=20),
                total_due=total_due,
                minimum_due=total_due // 10,
                credit_limit=100_000,
                available_credit_limit=100_000 - total_due,
                currency="INR",
            )
        )
        await db.commit()


async def test_card_utilization_history_combines_statement_trend_and_daily_rollforward(
    client, test_session_factory
):
    user = await create_user(client, "utilization-history")
    other = await create_user(client, "utilization-history-other")
    card = await _account(client, user["id"], "credit_card", "7711")
    today = date.today()

    for index, (days_ago, total_due) in enumerate(((73, 20_000), (42, 40_000), (11, 60_000))):
        await _add_statement(
            test_session_factory,
            user_id=user["id"],
            account_id=card["id"],
            statement_date=today - timedelta(days=days_ago),
            total_due=total_due,
            fingerprint=f"{index + 1}" * 64,
        )

    preference = await client.put(
        f"/api/cards/{card['id']}/preferences?user_id={user['id']}",
        json={"utilization_target_pct": 30},
    )
    preference.raise_for_status()
    purchase = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 5_000,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "card_event": "purchase",
            "transaction_date": (today - timedelta(days=7)).isoformat(),
            "merchant_raw": "CURRENT CYCLE PURCHASE",
            "confidence_score": 1.0,
            "financial_account_id": card["id"],
        },
    )
    purchase.raise_for_status()
    payment = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 1_000,
            "transaction_type": "credit",
            "transaction_status": "settled",
            "card_event": "payment",
            "transaction_date": (today - timedelta(days=5)).isoformat(),
            "merchant_raw": "CURRENT CYCLE PAYMENT",
            "confidence_score": 1.0,
            "financial_account_id": card["id"],
        },
    )
    payment.raise_for_status()

    response = await client.get(
        f"/api/cards/{card['id']}/utilization-history?user_id={user['id']}"
        "&statement_limit=12&daily_limit=10"
    )
    response.raise_for_status()
    body = response.json()

    assert [point["utilization_pct"] for point in body["statement_points"]] == [20.0, 40.0, 60.0]
    assert len(body["daily_points"]) == 10
    assert body["daily_points"][-1]["balance"] == 64_000
    assert body["daily_points"][-1]["utilization_pct"] == 64.0
    assert body["daily_points"][-1]["status"] == "over_target"
    assert body["trend"] == "worsening"
    assert body["trend_basis"] == "issuer_to_current_estimate"
    assert body["trend_delta_pct"] == 44.0
    assert body["peak_statement_utilization_pct"] == 60.0
    assert body["peak_daily_utilization_pct"] == 65.0
    assert body["credit_limit_breach_count"] == 0
    assert "current_cycle_ledger_estimate_available" in body["reason_codes"]

    denied = await client.get(
        f"/api/cards/{card['id']}/utilization-history?user_id={other['id']}"
    )
    assert denied.status_code == 404

    bank = await _account(client, user["id"], "bank", "7722")
    wrong_type = await client.get(
        f"/api/cards/{bank['id']}/utilization-history?user_id={user['id']}"
    )
    assert wrong_type.status_code == 422

    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(CreditCardStatement).where(
                    CreditCardStatement.financial_account_id == card["id"]
                )
            )
            is not None
        )


async def test_card_utilization_history_fails_closed_without_statement_evidence(client):
    user = await create_user(client, "utilization-history-empty")
    card = await _account(client, user["id"], "credit_card", "7733")

    response = await client.get(
        f"/api/cards/{card['id']}/utilization-history?user_id={user['id']}"
    )
    response.raise_for_status()
    body = response.json()

    assert body["statement_points"] == []
    assert body["daily_points"] == []
    assert body["trend"] == "unavailable"
    assert body["trend_basis"] == "unavailable"
    assert "no_statement_utilization_evidence" in body["reason_codes"]
