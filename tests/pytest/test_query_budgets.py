"""Critical-read SQL statement budgets for representative PFIS workspaces."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import app.database as database_module
import pytest
import pytest_asyncio
from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.category import Category
from app.models.financial_position import (
    CardPaymentIntent,
    CardPositionObservation,
    CardPreference,
    CashPlan,
    Commitment,
    CreditCardStatement,
    ReservePlan,
    StatementImport,
)
from app.models.sync import Budget
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionType,
)
from app.models.user import User
from httpx import AsyncClient
from sqlalchemy import select

from tests.pytest.query_budget_helpers import count_request_statements, load_query_budgets


@dataclass(frozen=True)
class RepresentativeWorkspace:
    user_id: str
    month: int
    year: int
    bank_account_id: str
    card_account_id: str


@dataclass(frozen=True)
class EndpointCase:
    key: str
    method: str
    path: str
    json_body: dict[str, Any] | None = None


@pytest_asyncio.fixture
async def representative_workspace(
    client: AsyncClient,  # noqa: ARG001 - ensures the app dependency override is installed
    test_session_factory,
) -> RepresentativeWorkspace:
    today = date.today()
    user_id = str(uuid.uuid4())

    async with test_session_factory() as session:
        categories = list((await session.scalars(select(Category).order_by(Category.name))).all())
        assert len(categories) >= 5

        user = User(
            id=user_id,
            email=f"query-budget-{uuid.uuid4().hex[:10]}@pfis.local",
            name="Query Budget User",
            currency="INR",
            timezone="Asia/Kolkata",
        )
        session.add(user)

        checking = FinancialAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            institution_name="Budget Primary Bank",
            account_type="bank",
            balance_kind="asset",
            masked_number="****1111",
            currency="INR",
            identity_status="confirmed",
            identity_confidence=Decimal("1.000"),
        )
        savings = FinancialAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            institution_name="Budget Savings Bank",
            account_type="bank",
            balance_kind="asset",
            masked_number="****2222",
            currency="INR",
            identity_status="confirmed",
            identity_confidence=Decimal("1.000"),
        )
        travel_card = FinancialAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            institution_name="Budget Travel Card",
            account_type="credit_card",
            balance_kind="liability",
            masked_number="****3333",
            currency="INR",
            identity_status="confirmed",
            identity_confidence=Decimal("1.000"),
        )
        grocery_card = FinancialAccount(
            id=str(uuid.uuid4()),
            user_id=user_id,
            institution_name="Budget Grocery Card",
            account_type="credit_card",
            balance_kind="liability",
            masked_number="****4444",
            currency="INR",
            identity_status="confirmed",
            identity_confidence=Decimal("1.000"),
        )
        accounts = [checking, savings, travel_card, grocery_card]
        session.add_all(accounts)
        await session.flush()

        for index, (account, amount) in enumerate(
            (
                (checking, "185000.00"),
                (savings, "420000.00"),
                (travel_card, "38500.00"),
                (grocery_card, "16250.00"),
            ),
            start=1,
        ):
            session.add(
                AccountBalanceSnapshot(
                    user_id=user_id,
                    financial_account_id=account.id,
                    amount=Decimal(amount),
                    currency="INR",
                    as_of=today - timedelta(days=1),
                    source="manual",
                    verified=True,
                    source_record_id=f"qb-balance-{index}-{uuid.uuid4().hex}",
                    observed_at=datetime.now(UTC) - timedelta(hours=6),
                    effective_at=datetime.now(UTC) - timedelta(hours=6),
                )
            )

        for index, (card, current_outstanding, billed_due, credit_limit) in enumerate(
            (
                (travel_card, "42100.00", "38500.00", "250000.00"),
                (grocery_card, "17600.00", "16250.00", "180000.00"),
            ),
            start=1,
        ):
            session.add(
                CardPositionObservation(
                    user_id=user_id,
                    financial_account_id=card.id,
                    currency="INR",
                    current_outstanding=Decimal(current_outstanding),
                    billed_due=Decimal(billed_due),
                    pending_amount=Decimal("1250.00"),
                    credit_limit=Decimal(credit_limit),
                    available_credit=Decimal(credit_limit) - Decimal(current_outstanding),
                    as_of=today,
                    source="connector",
                    source_record_id=f"qb-card-position-{index}-{uuid.uuid4().hex}",
                    observed_at=datetime.now(UTC) - timedelta(hours=2),
                    effective_at=datetime.now(UTC) - timedelta(hours=2),
                    expected_cadence_minutes=1440,
                    coverage_start=datetime.now(UTC) - timedelta(days=30),
                    coverage_end=datetime.now(UTC),
                    coverage_complete=True,
                )
            )
            statement_import = StatementImport(
                id=str(uuid.uuid4()),
                user_id=user_id,
                financial_account_id=card.id,
                issuer="query-budget-card",
                document_fingerprint=f"{index}{uuid.uuid4().hex * 2}"[:64],
                extractor_version="query-budget-fixture",
            )
            session.add(statement_import)
            await session.flush()
            session.add(
                CreditCardStatement(
                    user_id=user_id,
                    statement_import_id=statement_import.id,
                    financial_account_id=card.id,
                    statement_date=today - timedelta(days=8),
                    period_start=today - timedelta(days=38),
                    period_end=today - timedelta(days=8),
                    due_date=today + timedelta(days=10 + index),
                    total_due=Decimal(billed_due),
                    minimum_due=(Decimal(billed_due) * Decimal("0.05")).quantize(Decimal("0.01")),
                    credit_limit=Decimal(credit_limit),
                    available_credit_limit=Decimal(credit_limit) - Decimal(current_outstanding),
                    currency="INR",
                )
            )
            session.add(
                CardPreference(
                    user_id=user_id,
                    financial_account_id=card.id,
                    preferred_payment_account_id=checking.id,
                    utilization_target_pct=Decimal("30.00"),
                )
            )
            session.add(
                CardPaymentIntent(
                    user_id=user_id,
                    financial_account_id=card.id,
                    paying_account_id=checking.id,
                    amount=Decimal("5000.00"),
                    planned_for=today + timedelta(days=5 + index),
                    status="planned",
                    note="Fixture payment intent",
                )
            )

        session.add(
            CashPlan(
                user_id=user_id,
                primary_financial_account_id=checking.id,
                next_income_date=today + timedelta(days=7),
                next_income_amount=Decimal("180000.00"),
                show_daily_allowance=True,
            )
        )
        session.add_all(
            [
                ReservePlan(
                    user_id=user_id,
                    financial_account_id=checking.id,
                    label="Insurance reserve",
                    target_amount=Decimal("24000.00"),
                    due_date=today + timedelta(days=45),
                    monthly_allocation=Decimal("8000.00"),
                    approved=True,
                ),
                Commitment(
                    user_id=user_id,
                    financial_account_id=checking.id,
                    label="Rent",
                    commitment_type="rent",
                    amount=Decimal("42000.00"),
                    due_date=today + timedelta(days=3),
                    cadence="monthly",
                    confirmed=True,
                ),
            ]
        )

        for index, category in enumerate(categories[:5], start=1):
            session.add(
                Budget(
                    user_id=user_id,
                    category_id=category.id,
                    monthly_limit=Decimal(20000 + index * 5000),
                )
            )

        merchant_names = [
            "Metro Grocery",
            "Office Cafeteria",
            "Salary",
            "Fuel Station",
            "Utility Board",
            "Travel Portal",
            "Pharmacy",
            "Subscription Service",
        ]
        for index in range(200):
            is_income = index % 17 == 0
            is_card = index % 3 != 0
            account = travel_card if index % 2 == 0 else grocery_card
            tx_type = TransactionType.CREDIT if is_income else TransactionType.DEBIT
            card_event = CardEvent.NONE
            payment_method = PaymentMethod.BANK_TRANSFER
            payment_rail = PaymentRail.TRANSFER
            financial_account_id = checking.id
            if is_card and not is_income:
                financial_account_id = account.id
                card_event = CardEvent.PURCHASE
                payment_method = PaymentMethod.CREDIT_CARD
                payment_rail = PaymentRail.DEBIT_CARD
            session.add(
                Transaction(
                    user_id=user_id,
                    amount=Decimal("90000.00") if is_income else Decimal(350 + index * 11),
                    currency="INR",
                    transaction_type=tx_type,
                    payment_method=payment_method,
                    payment_rail=payment_rail,
                    card_event=card_event,
                    transaction_status="settled",
                    transaction_timestamp=datetime.combine(
                        today - timedelta(days=index % 60),
                        datetime.min.time(),
                        tzinfo=UTC,
                    ),
                    merchant_raw=merchant_names[index % len(merchant_names)],
                    merchant_normalized=merchant_names[index % len(merchant_names)],
                    category_id=categories[index % len(categories[:5])].id,
                    transaction_date=today - timedelta(days=index % 60),
                    account_last4="1111",
                    reference_id=f"QB-{index:03d}-{uuid.uuid4().hex[:8]}",
                    confidence_score=0.95 if index % 9 else 0.72,
                    reviewed_flag=index % 9 != 0,
                    parser_version=1,
                    fingerprint=f"query-budget-{uuid.uuid4().hex}",
                    financial_account_id=financial_account_id,
                    source_kind="manual",
                    review_outcome="matched" if index % 9 != 0 else "needs_review",
                )
            )

        await session.commit()

    return RepresentativeWorkspace(
        user_id=user_id,
        month=today.month,
        year=today.year,
        bank_account_id=checking.id,
        card_account_id=travel_card.id,
    )


def _endpoint_cases(workspace: RepresentativeWorkspace) -> list[EndpointCase]:
    query = f"user_id={workspace.user_id}"
    return [
        EndpointCase("accounts_balance_list", "GET", f"/api/accounts?{query}"),
        EndpointCase(
            "account_position",
            "GET",
            f"/api/accounts/{workspace.bank_account_id}/position?{query}",
        ),
        EndpointCase("net_worth", "GET", f"/api/net-worth?{query}"),
        EndpointCase("cash_plan", "GET", f"/api/cash-plan?{query}"),
        EndpointCase(
            "card_portfolio_payment_plan",
            "GET",
            f"/api/cards/portfolio/payment-plan?{query}",
        ),
        EndpointCase(
            "card_overview",
            "GET",
            f"/api/cards/{workspace.card_account_id}?{query}",
        ),
        EndpointCase(
            "workspace_dashboard_summary",
            "GET",
            (f"/api/dashboard/workspace?{query}" f"&month={workspace.month}&year={workspace.year}"),
        ),
        EndpointCase(
            "guidance_query",
            "POST",
            f"/api/guidance/query?{query}",
            {
                "query": "Can I pay my card dues this month?",
                "month": workspace.month,
                "year": workspace.year,
            },
        ),
        EndpointCase("readiness", "GET", f"/api/analytics/intelligence-readiness?{query}"),
    ]


@pytest.mark.asyncio
async def test_critical_read_query_budgets(
    client: AsyncClient,
    representative_workspace: RepresentativeWorkspace,
):
    budget_document = load_query_budgets()
    budgets = budget_document["budgets"]
    observed_counts: dict[str, int] = {}

    for case in _endpoint_cases(representative_workspace):
        result = await count_request_statements(
            client,
            database_module.engine.sync_engine,
            case.method,
            case.path,
            json_body=case.json_body,
        )
        assert result.response.status_code == 200, result.response.text
        observed_counts[case.key] = result.count
        budget = budgets[case.key]
        assert result.count <= budget["max_statements"], (
            f"{case.key} executed {result.count} SQL statements, "
            f"budget is {budget['max_statements']}. Observed counts: {observed_counts}"
        )
    assert set(observed_counts) == set(budgets)
    assert set(observed_counts) == set(budgets)
