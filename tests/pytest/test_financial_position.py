"""Integration coverage for verified financial-position workflows."""

import hashlib
import sys
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.models.account import AccountBalanceSnapshot
from app.models.email import RawEmail
from app.models.financial_position import (
    CreditCardStatement,
    DepositAccountStatement,
    DepositStatementLine,
    DepositStatementLineReviewDecision,
    StatementAnalysisReview,
    StatementImport,
    StatementLine,
    StatementLineMatch,
    StatementLineReviewDecision,
)
from app.models.knowledge import TemporalEventDecision
from app.models.sync import ConnectorAuditEvent, SyncRun, SyncStatus, UserCorrection
from app.models.transaction import CardEvent, Transaction, TransactionType
from app.schemas.financial_position import StatementTextImport
from app.schemas.transaction import (
    CardEventEnum,
    PaymentMethodEnum,
    PaymentRailEnum,
    TransactionCreate,
    TransactionTypeEnum,
)
from app.services.balance_observation_service import BalanceObservationService
from app.services.connectors.base import (
    BalanceObservationBatch,
    ConnectorError,
    ConnectorErrorType,
)
from app.services.financial_position_service import FinancialPositionService
from app.services.transaction_service import (
    DuplicateTransactionError,
    TransactionService,
)
from sqlalchemy import func, select

from tests.pytest.helpers import create_user, user_today

HDFC_DEPOSIT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "hdfc_deposit_statement_reviewed.txt"
).read_text(encoding="utf-8")


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Position Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_failed_balance_batch_marks_source_coverage_incomplete(client, test_session_factory):
    user = await create_user(client, "balance-batch-error")
    account = await _account(client, user["id"], "bank", "6622")

    async with test_session_factory() as db:
        responses = await BalanceObservationService(db).ingest_batch(
            user["id"],
            BalanceObservationBatch(
                source="connector",
                affected_account_ids=[account["id"]],
                errors=[
                    ConnectorError(
                        error_type=ConnectorErrorType.TRANSIENT,
                        message="provider unavailable",
                        retryable=True,
                    )
                ],
            ),
        )

        assert responses == []
        coverage = await BalanceObservationService(db).list_coverage(user["id"], account["id"])

    assert coverage is not None
    assert coverage[0].coverage_complete is False
    assert coverage[0].freshness_status == "unknown"
    assert coverage[0].last_error_code == "connector_batch_transient"
    assert "connector_batch_transient" in coverage[0].reason_codes


async def test_card_calendar_events_are_user_scoped_editable_and_reversible(client):
    owner = await create_user(client, "calendar-owner")
    other = await create_user(client, "calendar-other")
    card = await _account(client, owner["id"], "credit_card", "7041")

    created = await client.post(
        f"/api/cards/{card['id']}/calendar?user_id={owner['id']}",
        json={
            "event_type": "annual_fee",
            "label": "Annual fee review",
            "event_date": "2026-10-05",
        },
    )
    created.raise_for_status()
    event = created.json()
    assert event["source_kind"] == "manual"

    hidden = await client.patch(
        f"/api/cards/{card['id']}/calendar/{event['id']}?user_id={other['id']}",
        json={"label": "Must remain private"},
    )
    assert hidden.status_code == 404

    updated = await client.patch(
        f"/api/cards/{card['id']}/calendar/{event['id']}?user_id={owner['id']}",
        json={
            "event_type": "fee_reversal",
            "label": "Fee reversal follow-up",
            "event_date": "2026-10-12",
        },
    )
    updated.raise_for_status()
    assert updated.json()["event_type"] == "fee_reversal"
    assert updated.json()["label"] == "Fee reversal follow-up"

    deleted = await client.delete(
        f"/api/cards/{card['id']}/calendar/{event['id']}?user_id={owner['id']}"
    )
    assert deleted.status_code == 204
    missing = await client.delete(
        f"/api/cards/{card['id']}/calendar/{event['id']}?user_id={owner['id']}"
    )
    assert missing.status_code == 404


async def test_cash_plan_requires_verified_balance_then_uses_confirmed_inputs(client):
    user = await create_user(client, "cash-position")
    account = await _account(client, user["id"], "bank", "4455")
    income_day = date.today() + timedelta(days=10)
    configured = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": income_day.isoformat(),
        },
    )
    configured.raise_for_status()
    assert configured.json()["readiness"] == "needs_verified_balance"

    balance = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": date.today().isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    balance.raise_for_status()
    commitment = await client.post(
        f"/api/commitments?user_id={user['id']}",
        json={
            "label": "Rent",
            "commitment_type": "rent",
            "amount": 3000,
            "due_date": (date.today() + timedelta(days=2)).isoformat(),
            "confirmed": True,
        },
    )
    commitment.raise_for_status()
    reserve = await client.post(
        f"/api/reserves?user_id={user['id']}",
        json={
            "financial_account_id": account["id"],
            "label": "Insurance",
            "target_amount": 24000,
            "due_date": (date.today() + timedelta(days=300)).isoformat(),
            "monthly_allocation": 2000,
            "approved": True,
        },
    )
    reserve.raise_for_status()
    plan = await client.get(f"/api/cash-plan?user_id={user['id']}")
    plan.raise_for_status()
    assert plan.json()["readiness"] == "ready"
    assert plan.json()["flexible_money"] == 5000.0


async def test_cash_plan_rejects_non_bank_funding_account(client):
    user = await create_user(client, "cash-plan-product-gate")
    card = await _account(client, user["id"], "credit_card", "4457")

    response = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": card["id"],
            "next_income_date": (date.today() + timedelta(days=5)).isoformat(),
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == "Cash Plan requires one active bank account"


async def test_commitment_and_reserve_approval_lifecycle_is_explicit_and_user_scoped(client):
    user = await create_user(client, "planning-lifecycle")
    other = await create_user(client, "planning-lifecycle-other")
    account = await _account(client, user["id"], "bank", "4456")
    income_day = date.today() + timedelta(days=10)
    configured = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": income_day.isoformat(),
        },
    )
    configured.raise_for_status()
    balance = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={"amount": 10000, "as_of": date.today().isoformat()},
    )
    balance.raise_for_status()
    commitment = await client.post(
        f"/api/commitments?user_id={user['id']}",
        json={
            "label": "Draft insurance",
            "commitment_type": "insurance",
            "amount": 1000,
            "due_date": income_day.isoformat(),
            "financial_account_id": account["id"],
            "source_kind": "manual",
            "confirmed": False,
        },
    )
    commitment.raise_for_status()
    reserve = await client.post(
        f"/api/reserves?user_id={user['id']}",
        json={
            "financial_account_id": account["id"],
            "label": "Annual premium",
            "target_amount": 12000,
            "due_date": (date.today() + timedelta(days=120)).isoformat(),
            "monthly_allocation": 1000,
            "approved": False,
        },
    )
    reserve.raise_for_status()
    draft_plan = await client.get(f"/api/cash-plan?user_id={user['id']}")
    draft_plan.raise_for_status()
    assert draft_plan.json()["flexible_money"] == 10000

    confirmed = await client.patch(
        f"/api/commitments/{commitment.json()['id']}?user_id={user['id']}",
        json={"confirmed": True},
    )
    approved = await client.patch(
        f"/api/reserves/{reserve.json()['id']}?user_id={user['id']}",
        json={"approved": True},
    )
    confirmed.raise_for_status()
    approved.raise_for_status()
    active_plan = await client.get(f"/api/cash-plan?user_id={user['id']}")
    active_plan.raise_for_status()
    assert active_plan.json()["commitment_total"] == 1000
    assert active_plan.json()["approved_reserve_total"] == 1000
    assert active_plan.json()["flexible_money"] == 8000

    forbidden = await client.patch(
        f"/api/reserves/{reserve.json()['id']}?user_id={other['id']}",
        json={"approved": False},
    )
    assert forbidden.status_code == 404


async def test_commitment_rejects_a_liability_owned_by_another_user(client):
    user = await create_user(client, "commitment-owner")
    other = await create_user(client, "commitment-liability-owner")
    liability = await client.post(
        f"/api/liabilities?user_id={other['id']}",
        json={
            "label": "Other user's loan",
            "liability_type": "loan",
            "complete_schedule": False,
        },
    )
    liability.raise_for_status()

    response = await client.post(
        f"/api/commitments?user_id={user['id']}",
        json={
            "label": "Spoofed liability payment",
            "commitment_type": "loan",
            "amount": 1000,
            "due_date": (date.today() + timedelta(days=5)).isoformat(),
            "liability_id": liability.json()["id"],
        },
    )

    assert response.status_code == 404


async def test_cash_plan_rejects_stale_verified_balance(client):
    user = await create_user(client, "cash-stale")
    account = await _account(client, user["id"], "bank", "4458")
    configured = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (date.today() + timedelta(days=5)).isoformat(),
        },
    )
    configured.raise_for_status()
    balance = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": (date.today() - timedelta(days=8)).isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    balance.raise_for_status()

    plan = await client.get(f"/api/cash-plan?user_id={user['id']}")
    plan.raise_for_status()
    assert plan.json()["readiness"] == "needs_fresh_balance"
    assert plan.json()["flexible_money"] is None
    assert "seven days" in plan.json()["assumptions"][0]


async def test_cash_plan_rolls_forward_settled_activity_and_exposes_position_basis(client):
    user = await create_user(client, "cash-position-roll-forward")
    account = await _account(client, user["id"], "bank", "4459")
    anchor_date = date.today() - timedelta(days=2)
    balance = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": anchor_date.isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    balance.raise_for_status()
    transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 1250,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": (date.today() - timedelta(days=1)).isoformat(),
            "merchant_raw": "Settled rent transfer",
            "confidence_score": 0.99,
            "financial_account_id": account["id"],
        },
    )
    transaction.raise_for_status()
    configured = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (date.today() + timedelta(days=5)).isoformat(),
        },
    )
    configured.raise_for_status()
    body = configured.json()
    assert body["readiness"] == "ready"
    assert body["estimated_balance"] == 8750
    assert body["planning_balance"] == 8750
    assert body["balance_basis"] == "estimated"
    assert body["flexible_money"] == 8750


async def test_cash_plan_fails_closed_when_pending_activity_changes_position(client):
    user = await create_user(client, "cash-position-pending")
    account = await _account(client, user["id"], "bank", "4461")
    anchor_date = date.today() - timedelta(days=2)
    balance = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": anchor_date.isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    balance.raise_for_status()
    transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 400,
            "transaction_type": "debit",
            "transaction_status": "pending",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": "Pending card authorization",
            "confidence_score": 0.99,
            "financial_account_id": account["id"],
        },
    )
    transaction.raise_for_status()
    configured = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (date.today() + timedelta(days=5)).isoformat(),
        },
    )
    configured.raise_for_status()
    body = configured.json()
    assert body["readiness"] == "needs_position_review"
    assert body["flexible_money"] is None
    assert body["estimated_balance"] == 10000
    assert body["pending_decrease"] == 400
    assert "pending_activity_excluded" in body["position_reason_codes"]


async def test_connector_balance_observation_retries_are_idempotent(client):
    user = await create_user(client, "balance-source-identity")
    account = await _account(client, user["id"], "bank", "4462")
    payload = {
        "amount": 12000,
        "as_of": (date.today() - timedelta(days=1)).isoformat(),
        "source": "connector",
        "source_record_id": "provider-balance-2026-08-01T12:00:00Z",
        "verified": True,
    }
    first = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json=payload,
    )
    first.raise_for_status()
    retry = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={**payload, "amount": 9999},
    )
    retry.raise_for_status()
    assert retry.json()["id"] == first.json()["id"]
    assert retry.json()["amount"] == 12000
    assert retry.json()["source_record_id"] == payload["source_record_id"]
    same_day = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            **payload,
            "amount": 12100,
            "source_record_id": "provider-balance-2026-08-01T13:00:00Z",
            "effective_at": "2026-08-01T13:00:00Z",
        },
    )
    same_day.raise_for_status()
    assert same_day.json()["id"] != first.json()["id"]
    assert same_day.json()["amount"] == 12100
    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    assert position.json()["observed_balance"] == 12100


async def test_provider_balance_observation_persists_coverage_and_freshness(client):
    user = await create_user(client, "balance-coverage-contract")
    account = await _account(client, user["id"], "bank", "4464")
    observed_at = datetime.now(UTC)
    response = await client.post(
        f"/api/accounts/{account['id']}/balance-observations?user_id={user['id']}",
        json={
            "amount": 15000,
            "currency": "INR",
            "as_of": date.today().isoformat(),
            "source_record_id": "aa-balance-2026-08-03T10:00:00Z",
            "source_account_id": "aa-account-4464",
            "observed_at": observed_at.isoformat(),
            "effective_at": (observed_at - timedelta(minutes=2)).isoformat(),
            "expected_cadence_minutes": 60,
            "coverage_start": (observed_at - timedelta(days=90)).isoformat(),
            "coverage_end": observed_at.isoformat(),
            "coverage_complete": True,
        },
    )
    response.raise_for_status()
    body = response.json()
    assert body["snapshot"]["source"] == "connector"
    assert body["coverage"]["freshness_status"] == "fresh"
    assert body["coverage"]["coverage_complete"] is True
    assert body["coverage"]["last_source_record_id"] == "aa-balance-2026-08-03T10:00:00Z"

    coverage = await client.get(
        f"/api/accounts/{account['id']}/balance-coverage?user_id={user['id']}"
    )
    coverage.raise_for_status()
    assert coverage.json()[0]["source_account_id"] == "aa-account-4464"

    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    position_body = position.json()
    assert position_body["coverage_status"] == "fresh"
    assert position_body["coverage_complete"] is True


async def test_overdue_or_incomplete_provider_balance_blocks_position(client):
    user = await create_user(client, "balance-coverage-overdue")
    account = await _account(client, user["id"], "credit_card", "4465")
    observed_at = datetime.now(UTC) - timedelta(hours=4)
    response = await client.post(
        f"/api/accounts/{account['id']}/balance-observations?user_id={user['id']}",
        json={
            "amount": 4000,
            "currency": "INR",
            "as_of": (date.today() - timedelta(days=1)).isoformat(),
            "source_record_id": "aa-balance-2026-08-03T06:00:00Z",
            "observed_at": observed_at.isoformat(),
            "effective_at": observed_at.isoformat(),
            "expected_cadence_minutes": 60,
            "coverage_complete": False,
        },
    )
    response.raise_for_status()

    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    body = position.json()
    assert body["position_status"] == "needs_review"
    assert body["coverage_status"] == "overdue"
    assert body["coverage_complete"] is False
    assert {
        "source_coverage_incomplete",
        "balance_observation_overdue",
    } <= set(body["position_reason_codes"])

    overview = await client.get(f"/api/cards/{account['id']}?user_id={user['id']}")
    overview.raise_for_status()
    assert overview.json()["observed_source"] == "connector"
    assert overview.json()["coverage_status"] == "overdue"


async def test_cash_position_blocks_unlinked_card_payment_activity(client):
    user = await create_user(client, "cash-unlinked-card-payment")
    account = await _account(client, user["id"], "bank", "4463")
    anchor = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": (date.today() - timedelta(days=2)).isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    anchor.raise_for_status()
    payment = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 500,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "payment_rail": "transfer",
            "card_event": "payment",
            "transaction_date": (date.today() - timedelta(days=1)).isoformat(),
            "merchant_raw": "Card bill payment",
            "confidence_score": 0.99,
            "financial_account_id": account["id"],
        },
    )
    payment.raise_for_status()
    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    body = position.json()
    assert body["position_status"] == "needs_review"
    assert "unlinked_card_payment" in body["position_reason_codes"]


async def test_liability_schedule_requires_explicit_rows_and_projects_confirmed_emi(
    client,
):
    user = await create_user(client, "liability-schedule")
    other = await create_user(client, "liability-schedule-other")
    bank = await _account(client, user["id"], "bank", "4460")
    configured = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": bank["id"],
            "next_income_date": (date.today() + timedelta(days=20)).isoformat(),
        },
    )
    configured.raise_for_status()
    balance = await client.post(
        f"/api/accounts/{bank['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": date.today().isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    balance.raise_for_status()

    spoofed = await client.post(
        f"/api/liabilities?user_id={user['id']}",
        json={
            "label": "Unproven loan",
            "liability_type": "loan",
            "monthly_due": 900,
            "complete_schedule": True,
        },
    )
    assert spoofed.status_code == 422

    created = await client.post(
        f"/api/liabilities?user_id={user['id']}",
        json={
            "label": "Education loan",
            "liability_type": "loan",
            "outstanding_principal": 8000,
            "monthly_due": 1000,
            "complete_schedule": False,
        },
    )
    created.raise_for_status()
    liability_id = created.json()["id"]
    schedule = await client.post(
        f"/api/liabilities/{liability_id}/schedule/confirm?user_id={user['id']}",
        json={
            "source_kind": "manual",
            "items": [
                {
                    "due_date": (date.today() + timedelta(days=5)).isoformat(),
                    "installment_amount": 1000,
                },
                {
                    "due_date": (date.today() + timedelta(days=35)).isoformat(),
                    "installment_amount": 1000,
                },
            ],
        },
    )
    schedule.raise_for_status()
    assert len(schedule.json()) == 2

    denied = await client.get(f"/api/liabilities/{liability_id}/schedule?user_id={other['id']}")
    assert denied.status_code == 404
    repeat = await client.post(
        f"/api/liabilities/{liability_id}/schedule/confirm?user_id={user['id']}",
        json={
            "source_kind": "manual",
            "items": [
                {
                    "due_date": (date.today() + timedelta(days=5)).isoformat(),
                    "installment_amount": 1000,
                }
            ],
        },
    )
    assert repeat.status_code == 422

    liabilities = await client.get(f"/api/liabilities?user_id={user['id']}")
    liabilities.raise_for_status()
    assert liabilities.json()[0]["complete_schedule"] is True
    assert liabilities.json()[0]["remaining_installments"] == 2
    plan = await client.get(f"/api/cash-plan?user_id={user['id']}")
    plan.raise_for_status()
    assert plan.json()["commitment_total"] == 1000
    assert plan.json()["flexible_money"] == 9000
    assert plan.json()["confirmed_commitments"][0]["liability_id"] == liability_id

    first_item = schedule.json()[0]
    paid = await client.patch(
        f"/api/liabilities/{liability_id}/schedule/{first_item['id']}?user_id={user['id']}",
        json={"status": "paid"},
    )
    paid.raise_for_status()
    assert paid.json()["status"] == "paid"
    denied_update = await client.patch(
        f"/api/liabilities/{liability_id}/schedule/{schedule.json()[1]['id']}"
        f"?user_id={other['id']}",
        json={"status": "paid"},
    )
    assert denied_update.status_code == 404
    updated_liabilities = await client.get(f"/api/liabilities?user_id={user['id']}")
    updated_liabilities.raise_for_status()
    assert updated_liabilities.json()[0]["remaining_installments"] == 1
    updated_plan = await client.get(f"/api/cash-plan?user_id={user['id']}")
    updated_plan.raise_for_status()
    assert updated_plan.json()["commitment_total"] == 0
    assert updated_plan.json()["flexible_money"] == 10000


async def test_account_position_reconciles_both_transfer_legs_from_verified_snapshots(
    client,
):
    user = await create_user(client, "position-transfer")
    source = await _account(client, user["id"], "bank", "4401")
    target = await _account(client, user["id"], "bank", "4402")
    opening_date = date.today() - timedelta(days=2)
    closing_date = date.today()
    for account, amount, as_of, verified in (
        (source, 1000, opening_date, True),
        (source, 9999, date.today() - timedelta(days=1), False),
    ):
        response = await client.post(
            f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
            json={
                "amount": amount,
                "as_of": as_of.isoformat(),
                "source": "manual",
                "verified": verified,
            },
        )
        response.raise_for_status()
    transfer = await client.post(
        f"/api/transfers?user_id={user['id']}",
        json={
            "from_account_id": source["id"],
            "to_account_id": target["id"],
            "amount": 200,
            "currency": "INR",
            "transaction_date": closing_date.isoformat(),
            "payment_rail": "transfer",
        },
    )
    transfer.raise_for_status()
    closing = await client.post(
        f"/api/accounts/{source['id']}/balances?user_id={user['id']}",
        json={
            "amount": 800,
            "as_of": closing_date.isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    closing.raise_for_status()

    source_position = await client.get(
        f"/api/accounts/{source['id']}/position?user_id={user['id']}"
    )
    source_position.raise_for_status()
    payload = source_position.json()
    assert payload["verified_balance"] == 800
    assert payload["outflows"] == 200
    assert payload["rail_breakdown"]["transfer"] == 200
    assert payload["reconciliation_status"] == "reconciled"
    assert payload["unexplained_amount"] == 0

    target_position = await client.get(
        f"/api/accounts/{target['id']}/position?user_id={user['id']}"
    )
    target_position.raise_for_status()
    assert target_position.json()["inflows"] == 200


async def test_account_position_uses_liability_signs_and_separates_pending_activity(client):
    user = await create_user(client, "position-liability-signs")
    card = await _account(client, user["id"], "credit_card", "4404")
    anchor_date = date.today() - timedelta(days=3)
    anchor = await client.post(
        f"/api/accounts/{card['id']}/balances?user_id={user['id']}",
        json={
            "amount": 1000,
            "as_of": anchor_date.isoformat(),
            "source": "statement",
            "verified": True,
        },
    )
    anchor.raise_for_status()

    for payload in (
        {
            "amount": 200,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": (date.today() - timedelta(days=2)).isoformat(),
            "merchant_raw": "Card purchase",
            "card_event": "purchase",
            "payment_method": "credit_card",
            "financial_account_id": card["id"],
        },
        {
            "amount": 100,
            "transaction_type": "credit",
            "transaction_status": "posted",
            "transaction_date": (date.today() - timedelta(days=1)).isoformat(),
            "merchant_raw": "Card payment",
            "card_event": "payment",
            "payment_method": "bank_transfer",
            "payment_rail": "transfer",
            "financial_account_id": card["id"],
        },
        {
            "amount": 50,
            "transaction_type": "debit",
            "transaction_status": "pending",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": "Pending purchase",
            "card_event": "purchase",
            "payment_method": "credit_card",
            "financial_account_id": card["id"],
        },
    ):
        transaction = await client.post(f"/api/transactions/?user_id={user['id']}", json=payload)
        transaction.raise_for_status()

    position = await client.get(f"/api/accounts/{card['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    body = position.json()
    assert body["balance_kind"] == "liability"
    assert body["observed_balance"] == 1000
    assert body["settled_movement_since_observation"] == 100
    assert body["estimated_balance"] == 1100
    assert body["pending_increase"] == 50
    assert body["pending_decrease"] == 0
    assert body["position_status"] == "needs_review"
    assert "pending_activity_excluded" in body["position_reason_codes"]


async def test_account_position_exposes_deterministic_focused_reconciliation_items(client):
    user = await create_user(client, "position-focused-review")
    account = await _account(client, user["id"], "bank", "4403")
    opening_date = date.today() - timedelta(days=2)
    activity_date = date.today() - timedelta(days=1)
    for amount, as_of in ((1000, opening_date), (700, date.today())):
        snapshot = await client.post(
            f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
            json={"amount": amount, "as_of": as_of.isoformat(), "verified": True},
        )
        snapshot.raise_for_status()
    for reference in ("duplicate-a", "duplicate-b"):
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 100,
                "currency": "INR",
                "transaction_type": "debit",
                "transaction_date": activity_date.isoformat(),
                "merchant_raw": "Same merchant",
                "merchant_normalized": "Same merchant",
                "financial_account_id": account["id"],
                "reference_id": reference,
            },
        )
        transaction.raise_for_status()

    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    payload = position.json()
    assert payload["opening_balance"] == 1000
    assert payload["known_movement"] == -200
    assert payload["verified_balance"] == 700
    assert payload["unexplained_amount"] == -100
    assert payload["reconciliation_status"] == "needs_review"
    assert {item["kind"] for item in payload["reconciliation_items"]} == {
        "transaction_review",
        "duplicate_candidate",
        "unexplained_movement",
    }
    assert payload["review_count"] == 4


async def test_reconciliation_excludes_unsettled_activity_from_known_movement(client):
    user = await create_user(client, "position-reconciliation-settlement")
    account = await _account(client, user["id"], "bank", "4407")
    opening_date = date.today() - timedelta(days=2)
    activity_date = date.today() - timedelta(days=1)
    for amount, as_of in ((1000, opening_date), (900, date.today())):
        snapshot = await client.post(
            f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
            json={"amount": amount, "as_of": as_of.isoformat(), "verified": True},
        )
        snapshot.raise_for_status()
    settled = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 100,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": activity_date.isoformat(),
            "merchant_raw": "Settled movement",
            "reviewed_flag": True,
            "financial_account_id": account["id"],
        },
    )
    settled.raise_for_status()
    pending = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 50,
            "transaction_type": "debit",
            "transaction_status": "pending",
            "transaction_date": activity_date.isoformat(),
            "merchant_raw": "Pending authorization",
            "financial_account_id": account["id"],
        },
    )
    pending.raise_for_status()

    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    payload = position.json()
    assert payload["known_movement"] == -100
    assert payload["unexplained_amount"] == 0
    assert payload["reconciliation_delta"] == 0
    assert payload["last_reconciled_at"] is not None
    assert payload["reconciliation_status"] == "needs_review"
    assert {item["kind"] for item in payload["reconciliation_items"]} == {"transaction_review"}


async def test_unexplained_balance_residual_blocks_safe_to_spend(client):
    user = await create_user(client, "position-unexplained-residual")
    account = await _account(client, user["id"], "bank", "4407")
    for amount, as_of in (
        (1000, date.today() - timedelta(days=2)),
        (650, date.today()),
    ):
        snapshot = await client.post(
            f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
            json={"amount": amount, "as_of": as_of.isoformat(), "verified": True},
        )
        snapshot.raise_for_status()

    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    body = position.json()
    assert body["reconciliation_status"] == "needs_review"
    assert body["reconciliation_delta"] == -350
    assert body["position_status"] == "needs_review"
    assert "unexplained_balance_movement" in body["position_reason_codes"]

    configured = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (date.today() + timedelta(days=5)).isoformat(),
        },
    )
    configured.raise_for_status()
    assert configured.json()["readiness"] == "needs_position_review"
    assert configured.json()["flexible_money"] is None


async def test_connector_coverage_gap_blocks_current_position(client, test_session_factory):
    user = await create_user(client, "position-coverage-gap")
    account = await _account(client, user["id"], "bank", "4408")
    anchor = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": (date.today() - timedelta(days=2)).isoformat(),
            "verified": True,
        },
    )
    anchor.raise_for_status()
    activity = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 100,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": (date.today() - timedelta(days=1)).isoformat(),
            "merchant_raw": "Connector activity",
            "source_kind": "email",
            "source_identifier": "email-coverage-gap",
            "confidence_score": 0.99,
            "financial_account_id": account["id"],
        },
    )
    activity.raise_for_status()
    async with test_session_factory() as session:
        session.add(
            SyncRun(
                user_id=user["id"],
                status=SyncStatus.COMPLETED,
                coverage_complete=False,
                coverage_truncated=True,
                coverage_pages=1,
                coverage_result_size_estimate=100,
            )
        )
        await session.commit()
        saved_sync = await session.scalar(select(SyncRun).where(SyncRun.user_id == user["id"]))
        assert saved_sync is not None
        assert saved_sync.coverage_complete is False
        saved_activity = await session.scalar(
            select(Transaction).where(Transaction.id == activity.json()["id"])
        )
        assert saved_activity is not None
        saved_activity.source_kind = "email"
        await session.commit()

    position = await client.get(f"/api/accounts/{account['id']}/position?user_id={user['id']}")
    position.raise_for_status()
    payload = position.json()
    assert payload["position_status"] == "needs_review"
    assert "source_coverage_incomplete" in payload["position_reason_codes"]


async def test_net_worth_uses_eligible_current_positions_after_settled_activity(client):
    user = await create_user(client, "net-worth-current-position")
    today = user_today(user)
    bank = await _account(client, user["id"], "bank", "4405")
    card = await _account(client, user["id"], "credit_card", "4406")
    anchor_date = today - timedelta(days=2)
    for account, amount in ((bank, 10000), (card, 2000)):
        snapshot = await client.post(
            f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
            json={
                "amount": amount,
                "as_of": anchor_date.isoformat(),
                "source": "manual",
                "verified": True,
            },
        )
        snapshot.raise_for_status()
    for account, amount, transaction_type, merchant in (
        (bank, 1000, "debit", "Settled bank spend"),
        (card, 300, "debit", "Settled card purchase"),
    ):
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": amount,
                "transaction_type": transaction_type,
                "transaction_status": "settled",
                "transaction_date": (today - timedelta(days=1)).isoformat(),
                "merchant_raw": merchant,
                "confidence_score": 0.99,
                "financial_account_id": account["id"],
            },
        )
        transaction.raise_for_status()

    response = await client.get(f"/api/net-worth?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()
    assert body["current_position_status"] == "estimated"
    assert body["current_position_as_of"] == today.isoformat()
    assert body["assets"] == 9000
    assert body["liabilities"] == 2300
    assert body["net_worth"] == 6700


async def test_hdfc_text_statement_import_is_idempotent_and_keeps_card_payment_for_review(client):
    user = await create_user(client, "hdfc-position")
    card = await _account(client, user["id"], "credit_card", "9911")
    statement_text = """
    HDFC BANK CREDIT CARD STATEMENT
    STATEMENT DATE: 05/01/2026
    STATEMENT PERIOD: 06/12/2025 TO 05/01/2026
    TOTAL AMOUNT DUE: 1,250.00
    MINIMUM AMOUNT DUE: 125.00
    PAYMENT DUE DATE: 25/01/2026
    TOTAL CREDIT LIMIT: 100,000.00
    AVAILABLE CREDIT LIMIT: 86,000.00
    22/12/2025 GROCER MARKET 1,000.00
    03/01/2026 CARD PAYMENT RECEIVED 250.00 CR
    """
    payload = {
        "financial_account_id": card["id"],
        "document_fingerprint": "a" * 64,
        "statement_text": statement_text,
    }
    imported = await client.post(f"/api/statements/hdfc/text?user_id={user['id']}", json=payload)
    imported.raise_for_status()
    lines = imported.json()["lines"]
    assert {line["review_outcome"] for line in lines} == {"newly_imported", "needs_review"}
    repeated = await client.post(f"/api/statements/hdfc/text?user_id={user['id']}", json=payload)
    repeated.raise_for_status()
    assert repeated.json()["id"] == imported.json()["id"]
    post_statement_purchase = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 300,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "card_event": "purchase",
            "transaction_date": "2026-01-10",
            "merchant_raw": "POST-STATEMENT PURCHASE",
            "financial_account_id": card["id"],
        },
    )
    post_statement_purchase.raise_for_status()
    post_statement_payment = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 100,
            "transaction_type": "credit",
            "transaction_status": "settled",
            "card_event": "payment",
            "transaction_date": "2026-01-11",
            "merchant_raw": "POST-STATEMENT PAYMENT",
            "financial_account_id": card["id"],
        },
    )
    post_statement_payment.raise_for_status()
    overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    overview.raise_for_status()
    body = overview.json()
    assert body["observed_balance"] == 1250
    assert body["estimated_current_balance"] == 1450
    assert body["balance_status"] == "needs_review"
    assert body["billed_total_due"] == 1250
    assert body["billed_total_due_as_of"] == "2026-01-05"
    assert body["paid_since_statement"] == 100
    assert body["unbilled_activity"] == 300
    assert body["unbilled_activity_increase"] == 300
    assert body["unbilled_activity_decrease"] == 0
    assert body["refund_tracker"]["status"] == "clear"
    assert body["refund_tracker"]["pending_count"] == 0


async def test_hdfc_text_import_rejects_marker_only_legacy_documents(client):
    user = await create_user(client, "hdfc-marker-only")
    card = await _account(client, user["id"], "credit_card", "9911")

    response = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "b" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            CREDIT CARD NO XX9911
            TOTAL AMOUNT DUE 500.00
            MINIMUM AMOUNT DUE 50.00
            TOTAL CREDIT LIMIT 100000.00
            PAYMENT DUE DATE 10/09/2026
            """,
        },
    )

    assert response.status_code == 409
    assert "supported HDFC digital statement layout" in response.json()["error"]["message"]


async def test_hdfc_pdf_route_extracts_without_retaining_document_bytes(
    client,
    monkeypatch,
    test_session_factory,
):
    user = await create_user(client, "hdfc-pdf-route")
    card = await _account(client, user["id"], "credit_card", "9911")
    statement_text = """
    HDFC BANK CREDIT CARD STATEMENT
    STATEMENT DATE: 05/01/2026
    STATEMENT PERIOD: 06/12/2025 TO 05/01/2026
    TOTAL AMOUNT DUE: 1,000.00
    MINIMUM AMOUNT DUE: 100.00
    PAYMENT DUE DATE: 25/01/2026
    TOTAL CREDIT LIMIT: 100,000.00
    AVAILABLE CREDIT LIMIT: 99,000.00
    22/12/2025 GROCER MARKET 1,000.00
    """
    payload = b"%PDF-1.7\nPFIS de-identified digital statement fixture"
    opened_payloads: list[bytes] = []

    def fake_open(stream, password=None):
        assert password is None
        opened_payloads.append(stream.getvalue())
        return nullcontext(
            SimpleNamespace(
                doc=SimpleNamespace(is_encrypted=False),
                pages=[SimpleNamespace(extract_text=lambda **_: statement_text)],
            )
        )

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=fake_open))

    response = await client.post(
        "/api/statements/hdfc/upload",
        params={"user_id": user["id"], "financial_account_id": card["id"]},
        content=payload,
        headers={"Content-Type": "application/pdf"},
    )
    response.raise_for_status()

    assert opened_payloads == [payload]
    assert response.json()["financial_account_id"] == card["id"]
    async with test_session_factory() as db:
        imported = await db.scalar(
            select(StatementImport).where(StatementImport.user_id == user["id"])
        )
        assert imported is not None
        assert imported.document_fingerprint == hashlib.sha256(payload).hexdigest()
        assert "statement_text" not in StatementImport.__table__.columns
        assert "document_bytes" not in StatementImport.__table__.columns


async def test_statement_detection_is_read_only_and_identifies_deposit_activity(
    client,
    test_session_factory,
):
    user = await create_user(client, "statement-detection")
    response = await client.post(
        f"/api/statements/detect?user_id={user['id']}",
        json={
            "statement_text": """
            HDFC BANK LTD ACCOUNT STATEMENT
            ACCOUNT NO: XX0011
            DATE NARRATION CHQ./REF.NO. VALUE DT WITHDRAWAL AMT. DEPOSIT AMT. CLOSING BALANCE
            01/08/2026 UPI-MERCHANT-ONE 01/08/2026 500.00 0.00 9500.00
            """,
        },
    )

    response.raise_for_status()
    body = response.json()
    assert body["institution"] == "hdfc"
    assert body["product_type"] == "deposit_account"
    assert body["support_status"] == "recognized_not_supported"
    assert body["activity_types"] == ["upi"]
    assert body["analysis"]["status"] == "partial"
    assert body["analysis"]["row_count"] == 1
    assert body["analysis"]["debit_total"] == 500.0
    assert body["analysis"]["lines"][0]["payment_rail"] == "upi"
    assert "statement_text" not in body
    assert "XX0011" not in response.text

    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 0
        )


async def test_statement_analysis_review_persists_redacted_generic_evidence_without_import(
    client,
    test_session_factory,
):
    user = await create_user(client, "statement-analysis-review")
    other = await create_user(client, "statement-analysis-review-other")
    statement_text = """
    HDFC BANK LTD ACCOUNT STATEMENT
    ACCOUNT NO: XX0011
    DATE NARRATION CHQ./REF.NO. VALUE DT WITHDRAWAL AMT. DEPOSIT AMT. CLOSING BALANCE
    01/08/2026 UPI-MERCHANT-ONE 01/08/2026 500.00 0.00 9500.00
    """
    payload = {
        "document_fingerprint": "r" * 64,
        "statement_text": statement_text,
    }

    response = await client.post(f"/api/statements/review/text?user_id={user['id']}", json=payload)
    response.raise_for_status()
    body = response.json()
    assert body["status"] == "pending_review"
    assert body["support_status"] == "recognized_not_supported"
    assert body["analysis"]["status"] == "partial"
    assert body["analysis"]["row_count"] == 1
    assert "XX0011" not in response.text
    assert "statement_text" not in response.text

    repeated = await client.post(f"/api/statements/review/text?user_id={user['id']}", json=payload)
    repeated.raise_for_status()
    assert repeated.json()["id"] == body["id"]

    listed = await client.get(f"/api/statements/review?user_id={user['id']}&status=pending_review")
    listed.raise_for_status()
    assert [item["id"] for item in listed.json()] == [body["id"]]

    detail = await client.get(f"/api/statements/review/{body['id']}?user_id={user['id']}")
    detail.raise_for_status()
    assert detail.json()["document_fingerprint"] == "r" * 64

    forbidden = await client.get(f"/api/statements/review/{body['id']}?user_id={other['id']}")
    assert forbidden.status_code == 404

    async with test_session_factory() as db:
        review = await db.scalar(
            select(StatementAnalysisReview).where(StatementAnalysisReview.id == body["id"])
        )
        assert review is not None
        assert "XX0011" not in str(review.analysis_payload)
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 0
        )


async def test_statement_detection_classifies_generic_bank_shape_without_enabling_import(
    client,
    test_session_factory,
):
    user = await create_user(client, "generic-bank-detection")
    response = await client.post(
        f"/api/statements/detect?user_id={user['id']}",
        json={
            "statement_text": """
            ICICI BANK ACCOUNT STATEMENT
            ACCOUNT NUMBER XX7788
            DATE DESCRIPTION DEBIT CREDIT BALANCE
            01/08/2026 UPI-MERCHANT-ONE 500.00 0.00 9500.00
            02/08/2026 NEFT-SALARY 0.00 50000.00 59500.00
            """,
        },
    )

    response.raise_for_status()
    body = response.json()
    assert body["institution"] is None
    assert body["product_type"] == "deposit_account"
    assert body["format_id"] == "generic-deposit-account-candidate"
    assert body["support_status"] == "recognized_not_supported"
    assert body["activity_types"] == ["upi", "bank_transfer"]
    assert body["analysis"]["status"] == "partial"
    assert body["analysis"]["row_count"] == 2
    assert body["analysis"]["debit_total"] == 500.0
    assert body["analysis"]["credit_total"] == 50000.0
    assert "XX7788" not in response.text

    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 0
        )


async def test_statement_pdf_detection_identifies_product_before_account_selection(
    client,
    monkeypatch,
    test_session_factory,
):
    user = await create_user(client, "statement-pdf-detection")
    statement_text = """
    HDFC BANK LTD ACCOUNT STATEMENT
    ACCOUNT NO: XX0011
    DATE NARRATION CHQ./REF.NO. VALUE DT WITHDRAWAL AMT. DEPOSIT AMT. CLOSING BALANCE
    01/08/2026 UPI-MERCHANT-ONE 01/08/2026 500.00 0.00 9500.00
    """
    payload = b"%PDF-1.7\nPFIS deposit statement detection fixture"

    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(
            open=lambda *_args, **_kwargs: nullcontext(
                SimpleNamespace(
                    doc=SimpleNamespace(is_encrypted=False),
                    pages=[SimpleNamespace(extract_text=lambda **_: statement_text)],
                )
            )
        ),
    )

    response = await client.post(
        f"/api/statements/detect/upload?user_id={user['id']}",
        content=payload,
        headers={"Content-Type": "application/pdf"},
    )
    response.raise_for_status()

    assert response.json()["product_type"] == "deposit_account"
    assert response.json()["support_status"] == "recognized_not_supported"

    review = await client.post(
        f"/api/statements/review/upload?user_id={user['id']}",
        content=payload,
        headers={"Content-Type": "application/pdf"},
    )
    review.raise_for_status()
    assert review.json()["status"] == "pending_review"
    assert review.json()["analysis"]["row_count"] == 1
    assert "XX0011" not in review.text
    async with test_session_factory() as db:
        assert await db.scalar(select(func.count(StatementImport.id))) == 0
        assert await db.scalar(select(func.count(StatementAnalysisReview.id))) == 1
        assert await db.scalar(select(func.count(ConnectorAuditEvent.id))) == 0
        assert (
            await db.scalar(
                select(func.count(ConnectorAuditEvent.id)).where(
                    ConnectorAuditEvent.user_id == user["id"]
                )
            )
            == 0
        )


async def test_hdfc_document_detection_pdf_returns_redacted_import_contract_without_persistence(
    client,
    monkeypatch,
    test_session_factory,
):
    user = await create_user(client, "hdfc-document-detection")
    statement_text = """
    HDFC BANK
    DUPLICATE CREDIT CARD STATEMENT
    CREDIT CARD NO XX9911
    TOTAL AMOUNT DUE 1,000.00
    BILLING PERIOD 01/07/2026 TO 31/07/2026
    DOMESTIC TRANSACTIONS
    DATE & TIME TRANSACTION DESCRIPTION AMOUNT PI
    """
    payload = b"%PDF-1.7\nPFIS HDFC document detection fixture"
    opened_payloads: list[bytes] = []

    def fake_open(stream, password=None):
        assert password is None
        opened_payloads.append(stream.getvalue())
        return nullcontext(
            SimpleNamespace(
                doc=SimpleNamespace(is_encrypted=False),
                pages=[SimpleNamespace(extract_text=lambda **_: statement_text)],
            )
        )

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=fake_open))

    response = await client.post(
        f"/api/statements/hdfc/detect?user_id={user['id']}",
        content=payload,
        headers={"Content-Type": "application/pdf"},
    )
    response.raise_for_status()
    body = response.json()

    assert opened_payloads == [payload]
    assert body["status"] == "recognized"
    assert body["issuer"] == "hdfc"
    assert body["document_kind"] == "credit_card_statement"
    assert body["format_id"] == "hdfc-credit-card-digital"
    assert body["import_supported"] is True
    assert body["import_endpoint"] == "/api/statements/hdfc/upload"
    assert body["reason_code"] == "recognized_hdfc_credit_card"
    assert "XX9911" not in response.text
    assert "statement_text" not in response.text

    async with test_session_factory() as db:
        assert await db.scalar(select(func.count(StatementImport.id))) == 0
        assert await db.scalar(select(func.count(CreditCardStatement.id))) == 0
        assert await db.scalar(select(func.count(DepositAccountStatement.id))) == 0
        assert await db.scalar(select(func.count(ConnectorAuditEvent.id))) == 0


async def test_hdfc_document_detection_pdf_rejects_transport_and_content_failures(
    client,
    monkeypatch,
):
    user = await create_user(client, "hdfc-document-detection-gates")
    endpoint = f"/api/statements/hdfc/detect?user_id={user['id']}"

    oversized = await client.post(endpoint, content=b"%PDF" + b"x" * (10 * 1024 * 1024))
    assert oversized.status_code == 413

    not_pdf = await client.post(endpoint, content=b"not a pdf")
    assert not_pdf.status_code == 422

    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(
            open=lambda *_args, **_kwargs: nullcontext(
                SimpleNamespace(
                    doc=SimpleNamespace(is_encrypted=True),
                    pages=[],
                )
            )
        ),
    )
    encrypted = await client.post(endpoint, content=b"%PDF-1.7\nencrypted")
    assert encrypted.status_code == 422

    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(
            open=lambda *_args, **_kwargs: nullcontext(
                SimpleNamespace(
                    doc=SimpleNamespace(is_encrypted=False),
                    pages=[SimpleNamespace(extract_text=lambda **_: "")],
                )
            )
        ),
    )
    scanned = await client.post(endpoint, content=b"%PDF-1.7\nscanned")
    assert scanned.status_code == 422


async def test_hdfc_statement_mid_import_failure_rolls_back_all_financial_rows(
    client,
    monkeypatch,
    test_session_factory,
):
    user = await create_user(client, "hdfc-import-atomicity")
    card = await _account(client, user["id"], "credit_card", "9911")
    calls = 0

    async def fail_on_second_line(self, user_id, account_id, line_record):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("induced mid-import failure")
        return None, False, None

    monkeypatch.setattr(
        FinancialPositionService,
        "_match_statement_line",
        fail_on_second_line,
    )

    response = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "9" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 05/01/2026
            STATEMENT PERIOD: 06/12/2025 TO 05/01/2026
            TOTAL AMOUNT DUE: 1,500.00
            MINIMUM AMOUNT DUE: 150.00
            PAYMENT DUE DATE: 25/01/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 98,500.00
            22/12/2025 FIRST MERCHANT 1,000.00
            23/12/2025 SECOND MERCHANT 500.00
            """,
        },
    )

    assert response.status_code == 409
    assert calls == 2
    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(CreditCardStatement.id)).where(
                    CreditCardStatement.user_id == user["id"]
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(StatementLine.id)).where(StatementLine.user_id == user["id"])
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.user_id == user["id"],
                    Transaction.source_kind == "statement",
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(ConnectorAuditEvent.id)).where(
                    ConnectorAuditEvent.user_id == user["id"],
                    ConnectorAuditEvent.event_type == "statement_import_rejected",
                )
            )
            == 1
        )


async def test_statement_matching_does_not_exceed_three_calendar_day_tolerance(client):
    user = await create_user(client, "statement-date-tolerance")
    card = await _account(client, user["id"], "credit_card", "9912")
    earlier = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 500,
            "currency": "INR",
            "transaction_type": "debit",
            "transaction_date": "2026-01-01",
            "merchant_raw": "CONTROLLED MERCHANT",
            "merchant_normalized": "Controlled Merchant",
            "financial_account_id": card["id"],
            "reference_id": "outside-three-day-window",
        },
    )
    earlier.raise_for_status()
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "d" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 10/01/2026
            STATEMENT PERIOD: 11/12/2025 TO 10/01/2026
            TOTAL AMOUNT DUE: 500.00
            MINIMUM AMOUNT DUE: 50.00
            PAYMENT DUE DATE: 30/01/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 99,500.00
            05/01/2026 CONTROLLED MERCHANT 500.00
            """,
        },
    )
    imported.raise_for_status()
    assert imported.json()["lines"][0]["review_outcome"] == "newly_imported"
    assert imported.json()["lines"][0]["created_transaction_id"] != earlier.json()["id"]


async def test_card_overview_groups_observed_emi_principal_interest_tax_and_fee(
    client,
    test_session_factory,
):
    user = await create_user(client, "hdfc-emi-anatomy")
    card = await _account(client, user["id"], "credit_card", "9912")
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "b" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 05/06/2026
            STATEMENT PERIOD: 06/05/2026 TO 05/06/2026
            TOTAL AMOUNT DUE: 1,500.00
            MINIMUM AMOUNT DUE: 150.00
            PAYMENT DUE DATE: 25/06/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 98,500.00
            01/05/2026 EMI FLIPKART PAYMENTSBANGALORE 23,838.00
            04/05/2026 AGGREGATOR EMI - OFFUS CREDIT 23,838.00 CR
            05/05/2026 OFFUS EMI,PROCNG FEE,00000000001397 199.00
            01/06/2026 OFFUS EMI,PRIN NB:01,00000139775674 (Ref# 09999999980601001234567) 1,800.00
            01/06/2026 OFFUS EMI,INT NBR:01,00000139775674 (Ref# 09999999980601007654321) 220.00
            01/06/2026 IGST-VPS2717-RATE 18.0 39.60
            """,
        },
    )
    imported.raise_for_status()

    async with test_session_factory() as db:
        ledger_rows = list(
            (
                await db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.user_id == user["id"],
                        Transaction.source_kind == "statement",
                    )
                    .order_by(Transaction.transaction_date, Transaction.amount)
                )
            ).all()
        )
    assert len(ledger_rows) == 6
    assert {row.merchant_normalized for row in ledger_rows} == {"Flipkart"}
    assert {row.ledger_subtype for row in ledger_rows if row.is_accounting_adjustment} == {
        "emi_conversion_purchase",
        "emi_conversion_credit",
    }
    assert (
        next(row for row in ledger_rows if row.ledger_subtype == "emi_interest").card_event
        == CardEvent.INTEREST
    )
    assert (
        next(row for row in ledger_rows if row.ledger_subtype == "emi_tax").card_event
        == CardEvent.TAX
    )

    summary = await client.get(f"/api/transactions/summary?user_id={user['id']}&month=6&year=2026")
    summary.raise_for_status()
    assert summary.json()["total_spend"] == 2059.6
    may_summary = await client.get(
        f"/api/transactions/summary?user_id={user['id']}&month=5&year=2026"
    )
    may_summary.raise_for_status()
    assert may_summary.json()["total_spend"] == 199

    repaired = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": False},
    )
    repaired.raise_for_status()
    overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    overview.raise_for_status()

    plan = overview.json()["emi_plans"][0]
    assert plan["issuer_plan_reference"] == "1397"
    assert plan["merchant"] == "Flipkart"
    assert plan["original_amount"] == 23838
    assert plan["latest_installment_number"] == 1
    assert plan["observed_principal"] == 1800
    assert plan["observed_interest"] == 220
    assert plan["observed_tax"] == 39.6
    assert plan["observed_fees"] == 199
    assert plan["latest_principal"] == 1800
    assert plan["latest_interest"] == 220
    assert plan["latest_tax"] == 39.6
    assert plan["latest_fees"] == 199
    assert plan["latest_installment_amount"] == 2059.6
    assert plan["evidence_line_count"] == 6
    assert "annual_rate" in plan["missing_fields"]
    assert plan["schedule_completeness"] == "partial"

    liabilities = await client.get(f"/api/liabilities/overview?user_id={user['id']}")
    liabilities.raise_for_status()
    liability_overview = liabilities.json()
    assert liability_overview["known_monthly_debt"] == 2059.6
    assert liability_overview["confirmed_monthly_debt"] == 0
    assert liability_overview["observed_card_emi_monthly"] == 2059.6
    assert liability_overview["partial_evidence_count"] == 1
    observed_liability = liability_overview["liabilities"][0]
    assert observed_liability["schedule_status"] == "observed_partial"
    assert observed_liability["issuer_plan_reference"] == "1397"
    assert observed_liability["observed_principal_component"] == 1800
    assert observed_liability["observed_interest_component"] == 220
    assert observed_liability["observed_tax_component"] == 39.6
    assert observed_liability["observed_fee_component"] == 199
    assert observed_liability["outstanding_principal"] is None
    assert observed_liability["interest_rate"] is None
    assert observed_liability["remaining_installments"] is None


async def test_intelligence_repair_merges_only_unique_cross_source_duplicate(
    client, test_session_factory
):
    user = await create_user(client, "historical-cross-source")
    card = await _account(client, user["id"], "credit_card", "9916")
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "d" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 20/05/2026
            STATEMENT PERIOD: 21/04/2026 TO 20/05/2026
            TOTAL AMOUNT DUE: 3,994.00
            MINIMUM AMOUNT DUE: 399.40
            PAYMENT DUE DATE: 10/06/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 96,006.00
            11/05/2026 EMI FLIPKART PAYMENTSBANGALORE 3,994.00
            """,
        },
    )
    imported.raise_for_status()
    line_id = imported.json()["lines"][0]["id"]

    async with test_session_factory() as db:
        email = RawEmail(
            user_id=user["id"],
            gmail_message_id="legacy-flipkart-alert",
            subject="Card transaction alert",
            body="Rs. 3994 spent at FLIPKART on HDFC card ending 9916 on 14-05-2026",
            sender="alerts@hdfcbank.net",
        )
        db.add(email)
        await db.commit()
        await db.refresh(email)
        legacy = await TransactionService(db).create_transaction(
            user["id"],
            TransactionCreate(
                amount=3994,
                currency="INR",
                transaction_type=TransactionTypeEnum.DEBIT,
                payment_method=PaymentMethodEnum.CREDIT_CARD,
                payment_rail=PaymentRailEnum.OTHER,
                card_event=CardEventEnum.PURCHASE,
                transaction_date=date(2026, 5, 14),
                merchant_raw="FLIPKART",
                merchant_normalized="Flipkart",
                financial_account_id=card["id"],
                source_email_id=email.id,
                source_kind="manual",
                source_identifier=email.gmail_message_id,
                confidence_score=0.99,
            ),
        )
        non_financial_email = RawEmail(
            user_id=user["id"],
            gmail_message_id="legacy-research-study",
            subject="Preference for Purchase-II",
            body="A new research study is available. Open the study link to participate.",
            sender="Prolific Team <no-reply@prolific.com>",
        )
        db.add(non_financial_email)
        await db.commit()
        await db.refresh(non_financial_email)
        false_positive = await TransactionService(db).create_transaction(
            user["id"],
            TransactionCreate(
                amount=50,
                currency="INR",
                transaction_type=TransactionTypeEnum.DEBIT,
                payment_method=PaymentMethodEnum.UPI,
                payment_rail=PaymentRailEnum.UPI,
                card_event=CardEventEnum.NONE,
                transaction_date=date(2026, 5, 20),
                merchant_raw="UPI TRANSFER",
                merchant_normalized="Unknown",
                source_email_id=non_financial_email.id,
                source_kind="email",
                source_identifier=non_financial_email.gmail_message_id,
                confidence_score=0.2,
            ),
        )

    preview = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": True},
    )
    preview.raise_for_status()
    assert preview.json()["duplicates_merged"] == 1
    assert preview.json()["false_positive_transactions_removed"] == 1

    repair = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": False},
    )
    repair.raise_for_status()
    assert repair.json()["duplicates_merged"] == 1
    assert repair.json()["false_positive_transactions_removed"] == 1
    repeat_preview = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": True},
    )
    repeat_preview.raise_for_status()
    assert {key: value for key, value in repeat_preview.json().items() if key != "dry_run"} == {
        "email_merchants_repaired": 0,
        "statement_merchants_repaired": 0,
        "source_provenance_repaired": 0,
        "transaction_semantics_repaired": 0,
        "emi_components_classified": 0,
        "emi_ledger_events_projected": 0,
        "accounting_adjustments_marked": 0,
        "non_spend_payments_classified": 0,
        "duplicates_merged": 0,
        "fuel_surcharge_duplicates_merged": 0,
        "amounts_reconciled_to_statement": 0,
        "liabilities_synced": 0,
        "false_positive_transactions_removed": 0,
        "conflicts_held_for_review": 0,
    }

    async with test_session_factory() as db:
        count = await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user["id"],
                Transaction.amount == 3994,
            )
        )
        line = await db.get(StatementLine, line_id)
        match = await db.scalar(
            select(StatementLineMatch).where(StatementLineMatch.statement_line_id == line_id)
        )
        transaction = await db.get(Transaction, legacy.id)
        removed_false_positive = await db.get(Transaction, false_positive.id)
        assert count == 1
        assert line is not None and line.created_transaction_id == legacy.id
        assert line.review_outcome == "matched"
        assert match is not None and match.transaction_id == legacy.id
        assert transaction is not None and transaction.source_kind == "email"
        assert removed_false_positive is not None
        assert removed_false_positive.review_outcome == "ignored_by_rule"


async def test_intelligence_repair_removes_auto_reviewed_newsletter_false_positive(
    client,
    test_session_factory,
):
    user = await create_user(client, "newsletter-repair")
    async with test_session_factory() as db:
        email = RawEmail(
            user_id=user["id"],
            gmail_message_id="groww-digest-false-positive",
            subject="Market holiday and factory output - Daily Digest",
            body=(
                "Your daily Groww digest. Markets were closed today. "
                "A sample investment of Rs. 3500 was discussed. Unsubscribe."
            ),
            sender="Groww Digest <noreply@digest.groww.in>",
        )
        db.add(email)
        await db.commit()
        await db.refresh(email)
        transaction = await TransactionService(db).create_transaction(
            user["id"],
            TransactionCreate(
                amount=3500,
                currency="INR",
                transaction_type=TransactionTypeEnum.DEBIT,
                payment_method=PaymentMethodEnum.OTHER,
                payment_rail=PaymentRailEnum.OTHER,
                card_event=CardEventEnum.NONE,
                transaction_date=date(2023, 4, 4),
                merchant_raw="YOUR DAILY GROWW DIGEST MARKETS WERE CLOSED TODAY",
                merchant_normalized="Your Daily Groww Digest Markets Were Closed Today",
                source_email_id=email.id,
                source_kind="email",
                source_identifier=email.gmail_message_id,
                confidence_score=1.0,
                merchant_resolution_source="legacy",
            ),
        )
        assert transaction.reviewed_flag is True
        transaction_id = transaction.id

    repaired = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": False},
    )
    repaired.raise_for_status()
    assert repaired.json()["false_positive_transactions_removed"] == 1
    async with test_session_factory() as db:
        ignored = await db.get(Transaction, transaction_id)
        assert ignored is not None
        assert ignored.review_outcome == "ignored_by_rule"
        correction = await db.scalar(
            select(UserCorrection).where(
                UserCorrection.transaction_id == transaction_id,
                UserCorrection.field_corrected == "review_outcome",
            )
        )
        assert correction is not None

    visible = await client.get(f"/api/transactions/?user_id={user['id']}")
    visible.raise_for_status()
    assert all(item["id"] != transaction_id for item in visible.json())
    audit = await client.get(f"/api/transactions/?user_id={user['id']}&include_ignored=true")
    audit.raise_for_status()
    assert any(item["id"] == transaction_id for item in audit.json())


async def test_intelligence_repair_quarantines_service_notice_and_holds_atm_for_cash_link(
    client,
    test_session_factory,
):
    user = await create_user(client, "service-and-atm-repair")
    bank = await _account(client, user["id"], "bank", "4017")
    async with test_session_factory() as db:
        notice_email = RawEmail(
            user_id=user["id"],
            gmail_message_id="planned-maintenance-false-positive",
            subject="Planned System Maintenance: Service Impact Details",
            body=(
                "UPI transactions can be carried out up to applicable limits. "
                "Rs 5,000 will be kept aside for debit card usage while services are unavailable."
            ),
            sender="HDFC Bank <alerts@hdfcbank.net>",
        )
        atm_email = RawEmail(
            user_id=user["id"],
            gmail_message_id="observed-atm-4017",
            subject="View: Account update for your HDFC Bank A/c",
            body=(
                "Thank you for using your HDFC Bank Debit Card ending 4017 for ATM withdrawal "
                "for Rs 20,000.00 in PUNE at BANER on 09-06-2026 19:16:57. "
                "For more details on Service charges and Fees, click here."
            ),
            sender="HDFC Bank InstaAlerts <alerts@hdfcbank.net>",
        )
        db.add_all([notice_email, atm_email])
        await db.commit()
        await db.refresh(notice_email)
        await db.refresh(atm_email)
        notice = await TransactionService(db).create_transaction(
            user["id"],
            TransactionCreate(
                amount=5000,
                currency="INR",
                transaction_type=TransactionTypeEnum.DEBIT,
                payment_method=PaymentMethodEnum.UPI,
                payment_rail=PaymentRailEnum.UPI,
                card_event=CardEventEnum.PURCHASE,
                transaction_date=date(2026, 4, 11),
                merchant_raw="THE APPLICABLE",
                merchant_normalized="The Applicable",
                source_email_id=notice_email.id,
                source_kind="email",
                source_identifier=notice_email.gmail_message_id,
                confidence_score=1.0,
                merchant_resolution_source="legacy",
            ),
        )
        atm = await TransactionService(db).create_transaction(
            user["id"],
            TransactionCreate(
                amount=20000,
                currency="INR",
                transaction_type=TransactionTypeEnum.DEBIT,
                payment_method=PaymentMethodEnum.DEBIT_CARD,
                payment_rail=PaymentRailEnum.OTHER,
                card_event=CardEventEnum.FEE,
                transaction_date=date(2026, 6, 9),
                merchant_raw="BANER",
                merchant_normalized="Baner",
                source_email_id=atm_email.id,
                source_kind="email",
                source_identifier=atm_email.gmail_message_id,
                financial_account_id=bank["id"],
                confidence_score=1.0,
                merchant_resolution_source="legacy",
            ),
        )
        notice_id = notice.id
        atm_id = atm.id

    repaired = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": False},
    )
    repaired.raise_for_status()
    assert repaired.json()["false_positive_transactions_removed"] == 1
    assert repaired.json()["transaction_semantics_repaired"] == 1

    async with test_session_factory() as db:
        notice = await db.get(Transaction, notice_id)
        atm = await db.get(Transaction, atm_id)
        assert notice is not None and notice.review_outcome == "ignored_by_rule"
        assert atm is not None
        assert atm.payment_rail.value == "atm"
        assert atm.card_event == CardEvent.NONE
        assert atm.is_accounting_adjustment is True
        assert atm.ledger_subtype == "unlinked_atm_withdrawal"
        assert atm.review_outcome == "needs_review"
        assert atm.reviewed_flag is False
        assert atm.merchant_normalized == "Atm Cash Withdrawal"

    summary = await client.get(f"/api/transactions/summary?user_id={user['id']}&month=6&year=2026")
    summary.raise_for_status()
    assert summary.json()["total_spend"] == 0

    repeat = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": True},
    )
    repeat.raise_for_status()
    assert all(value == 0 for key, value in repeat.json().items() if key != "dry_run")


async def test_explicit_card_bill_payment_is_visible_but_excluded_from_spend(client):
    user = await create_user(client, "card-payment-effect")
    created = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 8220,
            "currency": "INR",
            "transaction_type": "debit",
            "payment_method": "bank_transfer",
            "payment_rail": "other",
            "card_event": "none",
            "transaction_date": "2026-07-10",
            "merchant_raw": "PZ HDFC CC BILLPAY",
            "merchant_normalized": "Pz Hdfc Cc Billpay",
            "confidence_score": 1.0,
        },
    )
    created.raise_for_status()

    repaired = await client.post(
        f"/api/financial-intelligence/repair?user_id={user['id']}",
        json={"dry_run": False},
    )
    repaired.raise_for_status()
    assert repaired.json()["non_spend_payments_classified"] == 1

    visible = await client.get(f"/api/transactions/?user_id={user['id']}&month=7&year=2026")
    visible.raise_for_status()
    assert visible.json()[0]["card_event"] == "payment"
    assert visible.json()[0]["payment_rail"] == "transfer"
    summary = await client.get(f"/api/transactions/summary?user_id={user['id']}&month=7&year=2026")
    summary.raise_for_status()
    assert summary.json()["total_spend"] == 0


async def test_fuel_alert_reconciles_to_posted_statement_amount_and_preserves_user_label(
    client, test_session_factory
):
    user = await create_user(client, "fuel-surcharge-reconciliation")
    card = await _account(client, user["id"], "credit_card", "9917")

    async with test_session_factory() as db:
        email = RawEmail(
            user_id=user["id"],
            gmail_message_id="fuel-alert-9917",
            subject="HDFC Bank credit card transaction alert",
            body=(
                "Rs.500.00 spent at LAKSHMI FILLING STATIO on HDFC Bank "
                "Credit Card ending 9917 on 09-07-2026."
            ),
            sender="alerts@hdfcbank.net",
        )
        db.add(email)
        await db.commit()
        await db.refresh(email)
        alert_transaction = await TransactionService(db).create_transaction(
            user["id"],
            TransactionCreate(
                amount=500,
                currency="INR",
                transaction_type=TransactionTypeEnum.DEBIT,
                payment_method=PaymentMethodEnum.CREDIT_CARD,
                payment_rail=PaymentRailEnum.OTHER,
                card_event=CardEventEnum.PURCHASE,
                transaction_date=date(2026, 7, 9),
                merchant_raw="LAKSHMI FILLING STATIO",
                merchant_normalized="Lakshmi Filling Station",
                financial_account_id=card["id"],
                source_email_id=email.id,
                source_kind="email",
                source_identifier=email.gmail_message_id,
                confidence_score=0.99,
            ),
        )

    corrected = await client.patch(
        f"/api/transactions/{alert_transaction.id}",
        json={"merchant_normalized": "Petrol Pulsar"},
    )
    corrected.raise_for_status()

    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "f" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 20/07/2026
            STATEMENT PERIOD: 21/06/2026 TO 20/07/2026
            TOTAL AMOUNT DUE: 506.73
            MINIMUM AMOUNT DUE: 50.67
            PAYMENT DUE DATE: 10/08/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 99,493.27
            09/07/2026 LAKSHMI FILLING STATION Amalapuram 511.80
            09/07/2026 PETRO SURCHARGE WAIVER 5.07 CR
            """,
        },
    )
    imported.raise_for_status()
    purchase_line = next(
        line for line in imported.json()["lines"] if line["transaction_type"] == "debit"
    )
    assert purchase_line["review_outcome"] == "matched"

    async with test_session_factory() as db:
        retained = await db.get(Transaction, alert_transaction.id)
        gross_purchase_count = await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user["id"],
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.transaction_date == date(2026, 7, 9),
            )
        )
        match = await db.scalar(
            select(StatementLineMatch).where(
                StatementLineMatch.statement_line_id == purchase_line["id"]
            )
        )
        assert retained is not None
        assert float(retained.amount) == 511.80
        assert retained.merchant_normalized == "Petrol Pulsar"
        assert gross_purchase_count == 1
        assert match is not None
        assert match.transaction_id == alert_transaction.id
        assert match.match_method == "fuel_surcharge_reconciliation"


async def test_hdfc_import_routes_amount_date_merchant_conflicts_to_review(client):
    user = await create_user(client, "hdfc-conflict")
    card = await _account(client, user["id"], "credit_card", "9914")
    existing = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 500,
            "currency": "INR",
            "transaction_type": "debit",
            "payment_method": "credit_card",
            "payment_rail": "other",
            "card_event": "purchase",
            "transaction_date": "2026-01-02",
            "merchant_raw": "FIRST MERCHANT",
            "financial_account_id": card["id"],
        },
    )
    existing.raise_for_status()
    statement_text = """
    HDFC BANK CREDIT CARD STATEMENT
    STATEMENT DATE: 05/01/2026
    STATEMENT PERIOD: 06/12/2025 TO 05/01/2026
    TOTAL AMOUNT DUE: 500.00
    MINIMUM AMOUNT DUE: 50.00
    PAYMENT DUE DATE: 25/01/2026
    TOTAL CREDIT LIMIT: 100,000.00
    AVAILABLE CREDIT LIMIT: 99,500.00
    02/01/2026 SECOND MERCHANT 500.00
    """
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "c" * 64,
            "statement_text": statement_text,
        },
    )
    imported.raise_for_status()

    line = imported.json()["lines"][0]
    assert line["review_outcome"] == "needs_review"
    assert line["created_transaction_id"] is None


async def test_auto_import_dispatches_reviewed_hdfc_deposit_statement_atomically(
    client, test_session_factory
):
    user = await create_user(client, "hdfc-deposit-auto-import")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********1234",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account = account_response.json()
    payload = {
        "financial_account_id": account["id"],
        "document_fingerprint": "d" * 64,
        "statement_text": HDFC_DEPOSIT_FIXTURE,
    }

    imported = await client.post(f"/api/statements/import/text?user_id={user['id']}", json=payload)
    imported.raise_for_status()
    body = imported.json()

    assert body["product_type"] == "deposit_account"
    assert body["detection"]["support_status"] == "supported"
    assert body["detection"]["format_id"] == "hdfc-deposit-pipe-v1"
    assert body["credit_card_statement"] is None
    statement = body["deposit_account_statement"]
    assert statement["opening_balance"] == 10_000
    assert statement["closing_balance"] == 31_510
    assert statement["imported_transaction_count"] == 4
    assert statement["review_count"] == 1
    assert len(statement["lines"]) == 5
    assert statement["lines"][-1]["review_outcome"] == "needs_review"

    repeated = await client.post(f"/api/statements/import/text?user_id={user['id']}", json=payload)
    repeated.raise_for_status()
    assert repeated.json()["deposit_account_statement"]["id"] == statement["id"]

    async with test_session_factory() as db:
        transaction_count = await db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user["id"],
                Transaction.financial_account_id == account["id"],
                Transaction.source_kind == "statement",
            )
        )
        line_count = await db.scalar(
            select(func.count(DepositStatementLine.id)).where(
                DepositStatementLine.user_id == user["id"]
            )
        )
        snapshot = await db.scalar(
            select(AccountBalanceSnapshot).where(
                AccountBalanceSnapshot.user_id == user["id"],
                AccountBalanceSnapshot.financial_account_id == account["id"],
                AccountBalanceSnapshot.source == "statement",
            )
        )
        assert transaction_count == 4
        assert line_count == 5
        assert snapshot is not None
        assert float(snapshot.amount) == 31_510
        assert snapshot.verified is True


async def test_auto_upload_detects_and_imports_reviewed_hdfc_deposit_pdf(client, monkeypatch):
    user = await create_user(client, "hdfc-deposit-auto-upload")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********1234",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    payload = b"%PDF-1.7\nPFIS reviewed HDFC deposit statement fixture"
    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(
            open=lambda *_args, **_kwargs: nullcontext(
                SimpleNamespace(
                    doc=SimpleNamespace(is_encrypted=False),
                    pages=[SimpleNamespace(extract_text=lambda **_: HDFC_DEPOSIT_FIXTURE)],
                )
            )
        ),
    )

    response = await client.post(
        "/api/statements/import/upload",
        params={
            "user_id": user["id"],
            "financial_account_id": account_response.json()["id"],
        },
        content=payload,
        headers={"Content-Type": "application/pdf"},
    )

    response.raise_for_status()
    assert response.json()["product_type"] == "deposit_account"
    assert response.json()["deposit_account_statement"]["imported_transaction_count"] == 4


async def test_deposit_import_rejects_account_mismatch_before_writes(client, test_session_factory):
    user = await create_user(client, "hdfc-deposit-account-mismatch")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********5678",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()

    response = await client.post(
        f"/api/statements/import/text?user_id={user['id']}",
        json={
            "financial_account_id": account_response.json()["id"],
            "document_fingerprint": "e" * 64,
            "statement_text": HDFC_DEPOSIT_FIXTURE,
        },
    )

    assert response.status_code == 409
    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(DepositAccountStatement.id)).where(
                    DepositAccountStatement.user_id == user["id"]
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 0
        )


async def test_deposit_import_rejects_a_fingerprint_reused_by_another_account(
    client,
    test_session_factory,
):
    user = await create_user(client, "hdfc-deposit-fingerprint-account")
    first_account = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********1234",
            "currency": "INR",
        },
    )
    second_account = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "XXXX1234",
            "currency": "INR",
        },
    )
    first_account.raise_for_status()
    second_account.raise_for_status()
    payload = {
        "document_fingerprint": "1" * 64,
        "statement_text": HDFC_DEPOSIT_FIXTURE,
    }

    imported = await client.post(
        f"/api/statements/import/text?user_id={user['id']}",
        json={**payload, "financial_account_id": first_account.json()["id"]},
    )
    imported.raise_for_status()
    repeated_for_other_account = await client.post(
        f"/api/statements/import/text?user_id={user['id']}",
        json={**payload, "financial_account_id": second_account.json()["id"]},
    )

    assert repeated_for_other_account.status_code == 409
    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(DepositAccountStatement.id)).where(
                    DepositAccountStatement.user_id == user["id"]
                )
            )
            == 1
        )


async def test_deposit_import_runtime_failure_rolls_back_source_and_ledger_rows(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "hdfc-deposit-atomicity")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********1234",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    original_create = TransactionService.create_transaction
    calls = 0

    async def fail_on_second_create(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("induced deposit import failure")
        return await original_create(self, *args, **kwargs)

    monkeypatch.setattr(TransactionService, "create_transaction", fail_on_second_create)
    async with test_session_factory() as db:
        with pytest.raises(RuntimeError, match="induced deposit import failure"):
            await FinancialPositionService(db).import_hdfc_deposit_statement_text(
                user["id"],
                StatementTextImport(
                    financial_account_id=account_response.json()["id"],
                    document_fingerprint="f" * 64,
                    statement_text=HDFC_DEPOSIT_FIXTURE,
                ),
            )

        for model in (
            StatementImport,
            DepositAccountStatement,
            DepositStatementLine,
            Transaction,
            AccountBalanceSnapshot,
        ):
            count = await db.scalar(
                select(func.count()).select_from(model).where(model.user_id == user["id"])
            )
            assert count == 0


async def test_transaction_delete_clears_statement_and_review_references(
    client,
    test_session_factory,
):
    user = await create_user(client, "transaction-delete-statement-references")
    card = await _account(client, user["id"], "credit_card", "9971")
    bank = await _account(client, user["id"], "bank", "9972")
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "2" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 05/01/2026
            STATEMENT PERIOD: 06/12/2025 TO 05/01/2026
            TOTAL AMOUNT DUE: 1,000.00
            MINIMUM AMOUNT DUE: 100.00
            PAYMENT DUE DATE: 25/01/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 99,000.00
            22/12/2025 DELETE ME 1,000.00
            """,
        },
    )
    imported.raise_for_status()

    async with test_session_factory() as db:
        statement = await db.scalar(
            select(CreditCardStatement).where(CreditCardStatement.user_id == user["id"])
        )
        assert statement is not None
        card_line = await db.scalar(
            select(StatementLine).where(StatementLine.credit_card_statement_id == statement.id)
        )
        assert card_line is not None
        transaction = await db.get(Transaction, card_line.created_transaction_id)
        assert transaction is not None
        deposit_import = StatementImport(
            user_id=user["id"],
            financial_account_id=bank["id"],
            issuer="HDFC",
            document_fingerprint="3" * 64,
            extractor_version="test",
        )
        db.add(deposit_import)
        await db.flush()
        deposit_statement = DepositAccountStatement(
            user_id=user["id"],
            statement_import_id=deposit_import.id,
            financial_account_id=bank["id"],
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 2),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1000.00"),
            currency="INR",
        )
        db.add(deposit_statement)
        await db.flush()
        deposit_line = DepositStatementLine(
            user_id=user["id"],
            deposit_account_statement_id=deposit_statement.id,
            line_number=1,
            transaction_date=date(2026, 1, 1),
            value_date=date(2026, 1, 1),
            description="DELETE ME EVIDENCE",
            amount=Decimal("1000.00"),
            transaction_type="debit",
            payment_rail="other",
            balance_after=Decimal("0.00"),
            review_outcome="matched",
            created_transaction_id=transaction.id,
        )
        db.add(deposit_line)
        await db.flush()
        db.add_all(
            [
                StatementLineMatch(
                    user_id=user["id"],
                    statement_line_id=card_line.id,
                    transaction_id=transaction.id,
                    match_method="test",
                    confidence=Decimal("1.000"),
                ),
                StatementLineReviewDecision(
                    user_id=user["id"],
                    statement_line_id=card_line.id,
                    decision="matched",
                    previous_outcome="needs_review",
                    new_outcome="matched",
                    matched_transaction_id=transaction.id,
                ),
                DepositStatementLineReviewDecision(
                    user_id=user["id"],
                    deposit_statement_line_id=deposit_line.id,
                    decision="matched",
                    previous_outcome="needs_review",
                    new_outcome="matched",
                    created_transaction_id=transaction.id,
                ),
                TemporalEventDecision(
                    user_id=user["id"],
                    event_id="delete-me-event",
                    event_kind="bill",
                    source_type="test",
                    source_id="delete-me",
                    occurrence_date=date(2026, 1, 1),
                    event_ruleset_version="test",
                    decision="linked",
                    transaction_id=transaction.id,
                ),
            ]
        )
        await db.commit()

        assert await TransactionService(db).delete_transaction(transaction.id) is True

        assert await db.get(Transaction, transaction.id) is None
        assert (await db.get(StatementLine, card_line.id)).created_transaction_id is None
        assert (await db.get(DepositStatementLine, deposit_line.id)).created_transaction_id is None
        assert (
            await db.scalar(
                select(StatementLineMatch).where(
                    StatementLineMatch.transaction_id == transaction.id
                )
            )
            is None
        )
        card_decision = await db.scalar(
            select(StatementLineReviewDecision).where(
                StatementLineReviewDecision.statement_line_id == card_line.id
            )
        )
        deposit_decision = await db.scalar(
            select(DepositStatementLineReviewDecision).where(
                DepositStatementLineReviewDecision.deposit_statement_line_id == deposit_line.id
            )
        )
        temporal_decision = await db.scalar(
            select(TemporalEventDecision).where(TemporalEventDecision.event_id == "delete-me-event")
        )
        assert card_decision is not None and card_decision.matched_transaction_id is None
        assert deposit_decision is not None and deposit_decision.created_transaction_id is None
        assert temporal_decision is not None and temporal_decision.transaction_id is None


async def test_deposit_import_does_not_swallow_a_duplicate_that_rolled_back_the_unit_of_work(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "hdfc-deposit-duplicate-rollback")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********1234",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    original_create = TransactionService.create_transaction
    calls = 0

    async def rollback_on_second_create(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            await self.db.rollback()
            raise DuplicateTransactionError("induced duplicate race")
        return await original_create(self, *args, **kwargs)

    monkeypatch.setattr(TransactionService, "create_transaction", rollback_on_second_create)
    async with test_session_factory() as db:
        with pytest.raises(RuntimeError, match="lost its atomic transaction"):
            await FinancialPositionService(db).import_hdfc_deposit_statement_text(
                user["id"],
                StatementTextImport(
                    financial_account_id=account_response.json()["id"],
                    document_fingerprint="9" * 64,
                    statement_text=HDFC_DEPOSIT_FIXTURE,
                ),
            )

        for model in (
            StatementImport,
            DepositAccountStatement,
            DepositStatementLine,
            Transaction,
            AccountBalanceSnapshot,
        ):
            count = await db.scalar(
                select(func.count()).select_from(model).where(model.user_id == user["id"])
            )
            assert count == 0


async def test_email_sync_after_statement_reconciles_without_second_ledger_event(
    client,
    test_session_factory,
):
    user = await create_user(client, "statement-first")
    card = await _account(client, user["id"], "credit_card", "9915")
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "e" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 05/04/2026
            STATEMENT PERIOD: 06/03/2026 TO 05/04/2026
            TOTAL AMOUNT DUE: 725.00
            MINIMUM AMOUNT DUE: 72.50
            PAYMENT DUE DATE: 25/04/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 99,275.00
            02/04/2026 VERIFIED BOOK STORE 725.00
            """,
        },
    )
    imported.raise_for_status()
    statement_line_id = imported.json()["lines"][0]["id"]

    async with test_session_factory() as db:
        email = RawEmail(
            user_id=user["id"],
            gmail_message_id="statement-first-email",
            subject="Credit card transaction",
            body="Rs 725 spent at VERIFIED BOOK STORE on card 9915",
            sender="alerts@example.test",
        )
        db.add(email)
        await db.commit()
        await db.refresh(email)
        with pytest.raises(DuplicateTransactionError):
            await TransactionService(db).create_transaction(
                user["id"],
                TransactionCreate(
                    amount=725,
                    currency="INR",
                    transaction_type=TransactionTypeEnum.DEBIT,
                    payment_method=PaymentMethodEnum.CREDIT_CARD,
                    payment_rail=PaymentRailEnum.OTHER,
                    card_event=CardEventEnum.PURCHASE,
                    transaction_date=date(2026, 4, 2),
                    merchant_raw="VERIFIED BOOK STORE",
                    merchant_normalized="VERIFIED BOOK STORE",
                    account_last4="9915",
                    financial_account_id=card["id"],
                    source_email_id=email.id,
                    source_kind="email",
                    source_identifier=email.gmail_message_id,
                    confidence_score=0.99,
                ),
                commit=False,
            )
        await db.commit()

        count = await db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.user_id == user["id"],
                Transaction.financial_account_id == card["id"],
                Transaction.amount == 725,
            )
        )
        transaction = await db.scalar(
            select(Transaction).where(
                Transaction.user_id == user["id"],
                Transaction.financial_account_id == card["id"],
                Transaction.amount == 725,
            )
        )
        line = await db.get(StatementLine, statement_line_id)
        match = await db.scalar(
            select(StatementLineMatch).where(
                StatementLineMatch.statement_line_id == statement_line_id
            )
        )
        assert count == 1
        assert transaction is not None
        assert transaction.source_email_id == email.id
        assert transaction.review_outcome == "matched"
        assert line is not None and line.review_outcome == "matched"
        assert match is not None and match.transaction_id == transaction.id


async def test_statement_review_records_card_payment_transfer_and_immutable_decision(
    client,
    test_session_factory,
):
    user = await create_user(client, "statement-review")
    other = await create_user(client, "statement-review-other")
    bank = await _account(client, user["id"], "bank", "5511")
    card = await _account(client, user["id"], "credit_card", "9920")
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "f" * 64,
            "statement_text": """
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: 05/05/2026
            STATEMENT PERIOD: 06/04/2026 TO 05/05/2026
            TOTAL AMOUNT DUE: 0.00
            MINIMUM AMOUNT DUE: 0.00
            PAYMENT DUE DATE: 25/05/2026
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 100,000.00
            02/05/2026 CARD PAYMENT RECEIVED 1,500.00 CR
            """,
        },
    )
    imported.raise_for_status()
    line_id = imported.json()["lines"][0]["id"]

    review = await client.get(f"/api/review/statement-lines?user_id={user['id']}")
    review.raise_for_status()
    assert [item["id"] for item in review.json()] == [line_id]

    denied = await client.patch(
        f"/api/statement-lines/{line_id}/review?user_id={other['id']}",
        json={
            "decision": "record_card_payment",
            "paying_account_id": bank["id"],
        },
    )
    assert denied.status_code == 404

    resolved = await client.patch(
        f"/api/statement-lines/{line_id}/review?user_id={user['id']}",
        json={
            "decision": "record_card_payment",
            "paying_account_id": bank["id"],
            "note": "Confirmed from the bank account.",
        },
    )
    resolved.raise_for_status()
    assert resolved.json()["new_outcome"] == "matched"
    assert resolved.json()["paying_account_id"] == bank["id"]

    async with test_session_factory() as db:
        decisions = list(
            (
                await db.scalars(
                    select(StatementLineReviewDecision).where(
                        StatementLineReviewDecision.statement_line_id == line_id
                    )
                )
            ).all()
        )
        transfers = list(
            (
                await db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user["id"],
                        Transaction.is_transfer.is_(True),
                    )
                )
            ).all()
        )
        assert len(decisions) == 1
        assert decisions[0].previous_outcome == "needs_review"
        assert decisions[0].new_outcome == "matched"
        assert len(transfers) == 2
        assert {item.financial_account_id for item in transfers} == {
            bank["id"],
            card["id"],
        }
        assert len({item.transfer_group_id for item in transfers}) == 1


async def test_card_payment_intent_records_an_idempotent_manual_transfer(
    client, test_session_factory
):
    user = await create_user(client, "card-planning")
    other = await create_user(client, "card-planning-other")
    bank = await _account(client, user["id"], "bank", "4456")
    card = await _account(client, user["id"], "credit_card", "9912")
    preference = await client.put(
        f"/api/cards/{card['id']}/preferences?user_id={user['id']}",
        json={"preferred_payment_account_id": bank["id"], "utilization_target_pct": 30},
    )
    preference.raise_for_status()
    intent = await client.post(
        f"/api/cards/{card['id']}/payment-intents?user_id={user['id']}",
        json={
            "paying_account_id": bank["id"],
            "amount": 500,
            "planned_for": date.today().isoformat(),
        },
    )
    intent.raise_for_status()
    intent_id = intent.json()["id"]
    overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    overview.raise_for_status()
    assert overview.json()["planned_payments"][0]["status"] == "planned"
    assert overview.json()["planned_payments"][0]["transfer_group_id"] is None

    denied = await client.patch(
        f"/api/cards/{card['id']}/payment-intents/{intent_id}?user_id={other['id']}",
        json={"status": "recorded", "paying_account_id": bank["id"]},
    )
    assert denied.status_code == 404

    recorded = await client.patch(
        f"/api/cards/{card['id']}/payment-intents/{intent_id}?user_id={user['id']}",
        json={"status": "recorded", "paying_account_id": bank["id"]},
    )
    recorded.raise_for_status()
    assert recorded.json()["status"] == "recorded"
    assert recorded.json()["transfer_group_id"]

    repeated = await client.patch(
        f"/api/cards/{card['id']}/payment-intents/{intent_id}?user_id={user['id']}",
        json={"status": "recorded", "paying_account_id": bank["id"]},
    )
    repeated.raise_for_status()
    assert repeated.json()["transfer_group_id"] == recorded.json()["transfer_group_id"]

    async with test_session_factory() as db:
        transfers = list(
            (
                await db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.user_id == user["id"],
                        Transaction.transfer_group_id == recorded.json()["transfer_group_id"],
                    )
                    .order_by(Transaction.transaction_type)
                )
            ).all()
        )
        assert len(transfers) == 2
        card_leg = next(item for item in transfers if item.financial_account_id == card["id"])
        assert card_leg.card_event == CardEvent.PAYMENT
        assert card_leg.is_transfer is True

    historical_overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    historical_overview.raise_for_status()
    assert historical_overview.json()["planned_payments"][0]["status"] == "recorded"

    cancelled_intent = await client.post(
        f"/api/cards/{card['id']}/payment-intents?user_id={user['id']}",
        json={
            "paying_account_id": bank["id"],
            "amount": 250,
            "planned_for": date.today().isoformat(),
        },
    )
    cancelled_intent.raise_for_status()
    cancelled = await client.patch(
        (
            f"/api/cards/{card['id']}/payment-intents/"
            f"{cancelled_intent.json()['id']}?user_id={user['id']}"
        ),
        json={"status": "cancelled"},
    )
    cancelled.raise_for_status()
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["transfer_group_id"] is None


async def test_card_refund_tracker_exposes_pending_and_recent_posted_refunds(client):
    user = await create_user(client, "card-refund-tracker")
    card = await _account(client, user["id"], "credit_card", "9921")
    pending = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 850,
            "transaction_type": "credit",
            "transaction_status": "pending",
            "card_event": "refund",
            "transaction_date": (date.today() - timedelta(days=2)).isoformat(),
            "merchant_raw": "REFUND PENDING",
            "financial_account_id": card["id"],
        },
    )
    pending.raise_for_status()
    posted = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 400,
            "transaction_type": "credit",
            "transaction_status": "settled",
            "card_event": "refund",
            "transaction_date": (date.today() - timedelta(days=1)).isoformat(),
            "merchant_raw": "REFUND POSTED",
            "financial_account_id": card["id"],
        },
    )
    posted.raise_for_status()

    overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    overview.raise_for_status()
    tracker = overview.json()["refund_tracker"]
    assert tracker["status"] == "pending"
    assert tracker["pending_count"] == 1
    assert tracker["pending_amount"] == 850
    assert tracker["posted_count_90d"] == 1
    assert tracker["posted_amount_90d"] == 400


async def test_card_projection_includes_bounded_recurring_charge_candidates(client):
    user = await create_user(client, "card-recurring-projection")
    today = user_today(user)
    card = await _account(client, user["id"], "credit_card", "9922")
    statement_date = today - timedelta(days=5)
    period_start = statement_date - timedelta(days=30)

    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "c" * 64,
            "statement_text": f"""
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: {statement_date:%d/%m/%Y}
            STATEMENT PERIOD: {period_start:%d/%m/%Y} TO {statement_date:%d/%m/%Y}
            TOTAL AMOUNT DUE: 10,000.00
            MINIMUM AMOUNT DUE: 1,000.00
            PAYMENT DUE DATE: {(today + timedelta(days=15)):%d/%m/%Y}
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 90,000.00
            {(statement_date - timedelta(days=1)):%d/%m/%Y} STATEMENT PURCHASE 10,000.00
            """,
        },
    )
    imported.raise_for_status()

    pending_refund = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 750,
            "transaction_type": "credit",
            "transaction_status": "pending",
            "payment_method": "credit_card",
            "card_event": "refund",
            "transaction_date": (today - timedelta(days=1)).isoformat(),
            "merchant_raw": "STREAMCO REFUND PENDING",
            "financial_account_id": card["id"],
        },
    )
    pending_refund.raise_for_status()

    for offset, amount, merchant in (
        (86, 899, "STREAMCO"),
        (56, 899, "STREAMCO"),
        (26, 899, "STREAMCO"),
    ):
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": amount,
                "transaction_type": "debit",
                "transaction_status": "settled",
                "payment_method": "credit_card",
                "card_event": "purchase",
                "transaction_date": (today - timedelta(days=offset)).isoformat(),
                "merchant_raw": merchant,
                "merchant_normalized": merchant,
                "financial_account_id": card["id"],
            },
        )
        transaction.raise_for_status()

    for offset, merchant in ((4, "CURRENT ONE"), (3, "CURRENT TWO"), (2, "CURRENT THREE")):
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 500,
                "transaction_type": "debit",
                "transaction_status": "settled",
                "payment_method": "credit_card",
                "card_event": "purchase",
                "transaction_date": (today - timedelta(days=offset)).isoformat(),
                "merchant_raw": merchant,
                "merchant_normalized": merchant,
                "financial_account_id": card["id"],
            },
        )
        transaction.raise_for_status()

    overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    overview.raise_for_status()
    projection = overview.json()["next_statement_projection"]
    assert projection["status"] == "available"
    assert projection["known_future_recurring_charge_total"] == 899
    assert projection["potential_pending_refund_total"] == 750
    assert len(projection["daily_path"]) == 26
    assert projection["daily_path"][0]["days_from_today"] == 1
    assert projection["daily_path"][-1]["date"] == projection["projected_statement_date"]
    assert "daily_projection_path" in projection["reason_codes"]
    assert any(
        "Recurring: STREAMCO" in label
        for point in projection["daily_path"]
        for label in point["event_labels"]
    )
    assert "pending_refund_credit_uncertainty" in projection["reason_codes"]
    assert projection["recurring_charge_candidates"][0]["merchant"] == "STREAMCO"
    assert projection["recurring_charge_candidates"][0]["occurrences"] == 3
    assert projection["recurring_charge_candidates"][0]["expected_amount_low"] == 899
    assert projection["recurring_charge_candidates"][0]["expected_amount_high"] == 899
    assert (
        projection["recurring_charge_candidates"][0]["expected_date_low"]
        == projection["recurring_charge_candidates"][0]["expected_date"]
    )
    assert (
        projection["recurring_charge_candidates"][0]["expected_date_high"]
        == projection["recurring_charge_candidates"][0]["expected_date"]
    )
    assert "recurring_charge_candidates_included" in projection["reason_codes"]


async def test_card_projection_uses_prior_statement_cycle_calendar_profile(client):
    user = await create_user(client, "card-seasonal-projection")
    card = await _account(client, user["id"], "credit_card", "9923")
    today = date.today()
    statement_dates = [
        today - timedelta(days=67),
        today - timedelta(days=36),
        today - timedelta(days=5),
    ]

    for index, statement_date in enumerate(statement_dates):
        period_start = statement_date - timedelta(days=30)
        imported = await client.post(
            f"/api/statements/hdfc/text?user_id={user['id']}",
            json={
                "financial_account_id": card["id"],
                "document_fingerprint": f"seasonal-{index}".ljust(64, "a"),
                "statement_text": f"""
                HDFC BANK CREDIT CARD STATEMENT
                STATEMENT DATE: {statement_date:%d/%m/%Y}
                STATEMENT PERIOD: {period_start:%d/%m/%Y} TO {statement_date:%d/%m/%Y}
                TOTAL AMOUNT DUE: 3,000.00
                MINIMUM AMOUNT DUE: 300.00
                PAYMENT DUE DATE: {(statement_date + timedelta(days=20)):%d/%m/%Y}
                TOTAL CREDIT LIMIT: 100,000.00
                AVAILABLE CREDIT LIMIT: 97,000.00
                {(period_start + timedelta(days=2)):%d/%m/%Y} HISTORICAL ONE {500 + index}.00
                {(period_start + timedelta(days=5)):%d/%m/%Y} HISTORICAL TWO 500.00
                {(period_start + timedelta(days=10)):%d/%m/%Y} HISTORICAL DAY TEN 2,000.00
                """,
            },
        )
        imported.raise_for_status()

    for offset in (4, 3, 2):
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 500,
                "transaction_type": "debit",
                "transaction_status": "settled",
                "payment_method": "credit_card",
                "card_event": "purchase",
                "transaction_date": (today - timedelta(days=offset)).isoformat(),
                "merchant_raw": f"CURRENT SEASONAL {offset}",
                "merchant_normalized": f"CURRENT SEASONAL {offset}",
                "financial_account_id": card["id"],
            },
        )
        transaction.raise_for_status()

    overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    overview.raise_for_status()
    projection = overview.json()["next_statement_projection"]

    assert projection["status"] == "available"
    assert projection["seasonal_sample_count"] == 2
    assert projection["seasonal_days_covered"] > 0
    assert "calendar_spending_seasonality_blended" in projection["reason_codes"]
    assert "Calendar spending pattern" in {item["label"] for item in projection["evidence"]}


async def test_card_activity_centre_uses_deterministic_statement_and_status_evidence(client):
    user = await create_user(client, "card-activity-centre")
    card = await _account(client, user["id"], "credit_card", "9913")
    statement_text = """
    HDFC BANK CREDIT CARD STATEMENT
    STATEMENT DATE: 05/02/2026
    STATEMENT PERIOD: 06/01/2026 TO 05/02/2026
    TOTAL AMOUNT DUE: 13,000.00
    MINIMUM AMOUNT DUE: 1,300.00
    PAYMENT DUE DATE: 25/02/2026
    TOTAL CREDIT LIMIT: 100,000.00
    AVAILABLE CREDIT LIMIT: 87,000.00
    20/01/2026 LARGE ELECTRONICS 12,000.00
    22/01/2026 REPEAT CAFE 500.00
    22/01/2026 REPEAT CAFE 500.00
    """
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "b" * 64,
            "statement_text": statement_text,
        },
    )
    imported.raise_for_status()
    reversal = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 750,
            "currency": "INR",
            "transaction_type": "refund",
            "payment_method": "credit_card",
            "payment_rail": "other",
            "card_event": "reversal",
            "transaction_status": "pending",
            "transaction_date": date.today().isoformat(),
            "merchant_raw": "Pending reversal",
            "financial_account_id": card["id"],
        },
    )
    reversal.raise_for_status()

    overview = await client.get(f"/api/cards/{card['id']}?user_id={user['id']}")
    overview.raise_for_status()
    signals = overview.json()["activity_signals"]

    assert {signal["signal_type"] for signal in signals} == {
        "duplicate_candidate",
        "high_value",
        "pending_reversal",
    }
    duplicate = next(signal for signal in signals if signal["signal_type"] == "duplicate_candidate")
    assert duplicate["amount"] == 500
    assert "same date" in duplicate["description"]
    high_value = next(signal for signal in signals if signal["signal_type"] == "high_value")
    assert high_value["amount"] == 12000
    assert "10%" in high_value["description"]
