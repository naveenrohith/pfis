"""Integrated reconciliation quality and ownership coverage."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.models.financial_position import CreditCardStatement, StatementImport, StatementLine
from app.models.transaction import PaymentMethod, PaymentRail, Transaction, TransactionType
from app.schemas.operational import ReconciliationQualityResponse
from app.services.reconciliation_quality_service import ReconciliationQualityService
from sqlalchemy import select

from tests.pytest.helpers import create_user


async def test_reconciliation_quality_empty_workspace_is_collecting(client):
    user = await create_user(client, "reconciliation-empty")

    response = await client.get(f"/api/analytics/reconciliation-quality?user_id={user['id']}")

    response.raise_for_status()
    body = response.json()
    assert body["status"] == "collecting"
    assert body["transaction_total"] == 0
    assert body["statement_line_total"] == 0
    assert body["account_total"] == 0
    assert body["transaction_review_coverage_pct"] == 100.0
    assert body["statement_resolution_coverage_pct"] == 100.0
    assert body["account_reconciliation_coverage_pct"] == 100.0
    assert body["unresolved_items"] == 0
    assert body["duplicate_candidate_groups"] == 0


async def test_reconciliation_quality_aggregates_review_statement_and_duplicate_evidence(
    client, test_session_factory
):
    user = await create_user(client, "reconciliation-matrix")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Reconciliation Card",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****4411",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account_id = account_response.json()["id"]

    async with test_session_factory() as db:
        db.add_all(
            [
                Transaction(
                    user_id=user["id"],
                    financial_account_id=account_id,
                    amount=Decimal("100.00"),
                    currency="INR",
                    transaction_type=TransactionType.DEBIT,
                    payment_method=PaymentMethod.OTHER,
                    payment_rail=PaymentRail.OTHER,
                    transaction_date=date(2026, 8, 10),
                    merchant_raw="Duplicate Shop",
                    merchant_normalized="Duplicate Shop",
                    review_outcome="matched",
                    reviewed_flag=True,
                    is_transfer=False,
                    is_accounting_adjustment=False,
                ),
                Transaction(
                    user_id=user["id"],
                    financial_account_id=account_id,
                    amount=Decimal("100.00"),
                    currency="INR",
                    transaction_type=TransactionType.DEBIT,
                    payment_method=PaymentMethod.OTHER,
                    payment_rail=PaymentRail.OTHER,
                    transaction_date=date(2026, 8, 10),
                    merchant_raw="Duplicate Shop",
                    merchant_normalized="Duplicate Shop",
                    review_outcome="newly_imported",
                    reviewed_flag=False,
                    is_transfer=False,
                    is_accounting_adjustment=False,
                ),
                Transaction(
                    user_id=user["id"],
                    financial_account_id=account_id,
                    amount=Decimal("50.00"),
                    currency="INR",
                    transaction_type=TransactionType.DEBIT,
                    payment_method=PaymentMethod.OTHER,
                    payment_rail=PaymentRail.OTHER,
                    transaction_date=date(2026, 8, 11),
                    merchant_raw="Ignored Shop",
                    merchant_normalized="Ignored Shop",
                    review_outcome="ignored_by_rule",
                    reviewed_flag=False,
                    is_transfer=False,
                    is_accounting_adjustment=False,
                ),
            ]
        )
        await db.flush()

        statement_import = StatementImport(
            user_id=user["id"],
            financial_account_id=account_id,
            issuer="reconciliation-test",
            document_fingerprint="reconciliation-fingerprint",
            extractor_version="test",
        )
        db.add(statement_import)
        await db.flush()
        statement = CreditCardStatement(
            user_id=user["id"],
            statement_import_id=statement_import.id,
            financial_account_id=account_id,
            statement_date=date(2026, 8, 20),
            period_start=date(2026, 7, 21),
            period_end=date(2026, 8, 20),
            currency="INR",
        )
        db.add(statement)
        await db.flush()
        db.add_all(
            [
                StatementLine(
                    user_id=user["id"],
                    credit_card_statement_id=statement.id,
                    line_number=1,
                    transaction_date=date(2026, 8, 10),
                    description="Matched line",
                    amount=Decimal("100.00"),
                    transaction_type="debit",
                    review_outcome="matched",
                ),
                StatementLine(
                    user_id=user["id"],
                    credit_card_statement_id=statement.id,
                    line_number=2,
                    transaction_date=date(2026, 8, 11),
                    description="New line",
                    amount=Decimal("75.00"),
                    transaction_type="debit",
                    review_outcome="newly_imported",
                ),
                StatementLine(
                    user_id=user["id"],
                    credit_card_statement_id=statement.id,
                    line_number=3,
                    transaction_date=date(2026, 8, 12),
                    description="Ignored line",
                    amount=Decimal("25.00"),
                    transaction_type="debit",
                    review_outcome="ignored",
                ),
                StatementLine(
                    user_id=user["id"],
                    credit_card_statement_id=statement.id,
                    line_number=4,
                    transaction_date=date(2026, 8, 13),
                    description="Review line",
                    amount=Decimal("30.00"),
                    transaction_type="debit",
                    review_outcome="needs_review",
                ),
            ]
        )
        await db.commit()

    response = await client.get(f"/api/analytics/reconciliation-quality?user_id={user['id']}")

    response.raise_for_status()
    body = response.json()
    assert body["status"] == "collecting"
    assert body["transaction_total"] == 3
    assert body["transaction_reviewed"] == 2
    assert body["transaction_needs_review"] == 1
    assert body["transaction_ignored"] == 1
    assert body["statement_line_total"] == 4
    assert body["statement_lines_matched"] == 1
    assert body["statement_lines_newly_imported"] == 1
    assert body["statement_lines_ignored"] == 1
    assert body["statement_lines_needs_review"] == 1
    assert body["duplicate_candidate_groups"] == 1
    assert body["account_total"] == 1
    assert body["accounts_not_ready"] == 1
    assert body["unresolved_items"] >= 3

    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(Transaction).where(
                    Transaction.user_id == user["id"],
                    Transaction.merchant_normalized == "Duplicate Shop",
                )
            )
            is not None
        )

    assert "Duplicate candidate groups: 1" in body["evidence"]
    assert body["limitations"]
    readiness = ReconciliationQualityService.readiness(
        ReconciliationQualityResponse.model_validate(body)
    )
    assert readiness.status == "collecting"
