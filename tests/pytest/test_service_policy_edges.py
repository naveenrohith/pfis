"""Deterministic edge coverage for cross-domain financial policies."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.account import AccountBalanceSnapshot, AccountBalanceSource, FinancialAccount
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionType,
)
from app.schemas.operational import ReconciliationQualityResponse
from app.services.balance_observation_service import BalanceObservationService
from app.services.balance_provider_status_service import BalanceProviderStatusService
from app.services.financial_position_service import FinancialPositionService
from app.services.guidance_service import GuidanceService
from app.services.intelligence_service import IntelligenceService
from app.services.reconciliation_quality_service import ReconciliationQualityService
from app.services.transaction_transfer_service import TransactionTransferService

_NOW = datetime(2026, 8, 20, 12, tzinfo=UTC)


def _account(
    account_id: str,
    *,
    account_type: str = "bank",
    balance_kind: str = "asset",
    currency: str = "INR",
    active: bool = True,
) -> FinancialAccount:
    return FinancialAccount(
        id=account_id,
        user_id="user-1",
        institution_name="Policy Bank",
        account_type=account_type,
        balance_kind=balance_kind,
        masked_number=f"****{account_id[-4:]}",
        currency=currency,
        is_active=active,
    )


def _transaction(
    transaction_id: str,
    *,
    transaction_type: TransactionType = TransactionType.DEBIT,
    transaction_date: date = date(2026, 8, 15),
    transaction_timestamp: datetime | None = None,
    created_at: datetime = _NOW,
    amount: str = "100.00",
    currency: str = "INR",
    transaction_status: str = "settled",
    card_event: CardEvent = CardEvent.NONE,
    payment_method: PaymentMethod = PaymentMethod.OTHER,
    payment_rail: PaymentRail = PaymentRail.OTHER,
    financial_account_id: str | None = "bank-1",
    merchant: str = "Transfer to own account",
) -> Transaction:
    return Transaction(
        id=transaction_id,
        user_id="user-1",
        amount=Decimal(amount),
        currency=currency,
        transaction_type=transaction_type,
        payment_method=payment_method,
        payment_rail=payment_rail,
        card_event=card_event,
        transaction_status=transaction_status,
        transaction_timestamp=transaction_timestamp,
        merchant_raw=merchant,
        merchant_normalized=merchant,
        transaction_date=transaction_date,
        financial_account_id=financial_account_id,
        created_at=created_at,
        review_outcome="newly_imported",
        is_transfer=False,
        is_accounting_adjustment=False,
    )


def _snapshot(
    snapshot_id: str,
    *,
    as_of: date,
    effective_at: datetime | None = None,
) -> AccountBalanceSnapshot:
    return AccountBalanceSnapshot(
        id=snapshot_id,
        user_id="user-1",
        financial_account_id="bank-1",
        amount=Decimal("1000.00"),
        currency="INR",
        as_of=as_of,
        source="manual",
        verified=True,
        effective_at=effective_at,
    )


_CONFIRMED_AXIS_ACCOUNT = _account("axis", active=True)
_CONFIRMED_AXIS_ACCOUNT.identity_status = "confirmed"


def test_financial_position_cutoffs_and_provider_coverage_states():
    opening = _snapshot("opening", as_of=date(2026, 8, 10), effective_at=_NOW - timedelta(days=2))
    closing = _snapshot("closing", as_of=date(2026, 8, 20), effective_at=_NOW)
    timestamped = _transaction(
        "timestamped",
        transaction_date=date(2026, 8, 20),
        transaction_timestamp=_NOW - timedelta(hours=1),
    )
    same_day_without_timestamp = _transaction("date-only", transaction_date=date(2026, 8, 20))
    older = _transaction("older", transaction_date=date(2026, 8, 9))

    assert FinancialPositionService._transaction_after_snapshot(timestamped, opening)
    assert not FinancialPositionService._transaction_after_snapshot(older, opening)
    assert not FinancialPositionService._transaction_after_snapshot(timestamped, None)
    assert FinancialPositionService._transaction_after_snapshot(
        _transaction("date-fallback", transaction_date=date(2026, 8, 11)), opening
    )
    assert FinancialPositionService._transaction_between_snapshots(timestamped, opening, closing)
    assert not FinancialPositionService._transaction_between_snapshots(
        same_day_without_timestamp, opening, closing
    )
    assert FinancialPositionService._transaction_between_snapshots(
        _transaction("date-closing", transaction_date=date(2026, 8, 20)),
        _snapshot("opening-date", as_of=date(2026, 8, 10)),
        _snapshot("closing-date", as_of=date(2026, 8, 20)),
    )

    source = AccountBalanceSource(
        user_id="user-1",
        financial_account_id="bank-1",
        source="connector",
    )
    assert FinancialPositionService._coverage_status(source, now=_NOW) == "unknown"
    source.last_success_at = _NOW - timedelta(hours=1)
    source.expected_cadence_minutes = 60
    assert FinancialPositionService._coverage_status(source, now=_NOW) == "fresh"
    assert (
        FinancialPositionService._coverage_status(
            source,
            now=_NOW + timedelta(minutes=30),
        )
        == "due"
    )
    assert (
        FinancialPositionService._coverage_status(
            source,
            now=_NOW + timedelta(minutes=61),
        )
        == "overdue"
    )


@pytest.mark.parametrize(
    ("account", "require_hdfc", "message"),
    [
        (
            _account("card-1", account_type="credit_card", balance_kind="liability"),
            False,
            "asset bank",
        ),
        (_account("inactive", active=False), False, "active bank"),
        (_account("usd", currency="USD"), True, "INR only"),
        (_account("unconfirmed", active=True), False, "Confirm"),
        (_CONFIRMED_AXIS_ACCOUNT, True, "HDFC bank"),
    ],
)
def test_deposit_import_account_validation_rejects_unsafe_accounts(
    account: FinancialAccount,
    require_hdfc: bool,
    message: str,
):
    with pytest.raises(ValueError, match=message):
        FinancialPositionService._validate_deposit_account(account, require_hdfc=require_hdfc)


def test_deposit_import_account_validation_accepts_confirmed_hdfc_account():
    account = _account("hdfc-1")
    account.institution_name = "HDFC Bank"
    account.identity_status = "confirmed"
    FinancialPositionService._validate_deposit_account(account, require_hdfc=True)


def test_transfer_policy_classifies_card_and_asset_pairs_without_guessing():
    bank = _account("bank-1")
    card = _account("card-1", account_type="credit_card", balance_kind="liability")
    other_bank = _account("bank-2")
    unknown_account = _account("unknown", account_type="unknown")
    debit = _transaction("debit", financial_account_id=bank.id)
    card_credit = _transaction(
        "card-credit",
        transaction_type=TransactionType.CREDIT,
        financial_account_id=card.id,
        card_event=CardEvent.PAYMENT,
        payment_rail=PaymentRail.TRANSFER,
    )
    kind, confidence, reasons = TransactionTransferService._classify_pair(
        debit, card_credit, bank, card
    ) or (None, 0, [])
    assert kind == "card_payment"
    assert confidence == 0.98
    assert "card_payment_event" in reasons
    assert "transfer_rail_evidence" in reasons

    asset_credit = _transaction(
        "asset-credit",
        transaction_type=TransactionType.CREDIT,
        financial_account_id=other_bank.id,
        payment_method=PaymentMethod.BANK_TRANSFER,
    )
    classified = TransactionTransferService._classify_pair(debit, asset_credit, bank, other_bank)
    assert classified is not None
    assert classified[0] == "account_transfer"
    assert (
        TransactionTransferService._classify_pair(
            debit, card_credit, unknown_account, unknown_account
        )
        is None
    )
    assert TransactionTransferService._has_transfer_evidence(debit, asset_credit)
    assert TransactionTransferService._has_transfer_evidence(
        _transaction("text", merchant="NEFT own account"),
        _transaction("text-credit", transaction_type=TransactionType.CREDIT),
    )
    assert not TransactionTransferService._has_transfer_evidence(
        _transaction("ordinary", merchant="Coffee shop"),
        _transaction("ordinary-credit", transaction_type=TransactionType.CREDIT, merchant="Refund"),
    )

    debit.transfer_group_id = "group-1"
    card_credit.transfer_group_id = "group-1"
    debit.is_transfer = True
    card_credit.is_transfer = True
    response = TransactionTransferService._response_for_pair(debit, card_credit)
    assert response.transfer_group_id == "group-1"
    assert response.transaction_date == debit.transaction_date


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("compare minimum and total card payment plans", "card_portfolio_payment_plan"),
        ("can I pay my card before the due date", "card_due_affordability"),
        ("which cards are due across all cards", "card_portfolio_upcoming"),
        ("what happens next with my card", "card_upcoming_state"),
        ("is it safe to spend this month", "safe_to_spend"),
        ("what is my net worth", "current_net_worth"),
        ("what is my current outstanding balance", "card_position"),
        ("show my recurring subscriptions", "recurring_charges"),
        ("how is my budget", "budget_status"),
        ("compare this with last month", "month_comparison"),
        ("how much did I spend at Coffee Bar this month", "merchant_spend"),
        ("how much did I spend this month", "monthly_spend"),
        ("what was my income", "monthly_income"),
        ("how much were my savings", "monthly_savings"),
    ],
)
def test_guidance_query_plan_covers_supported_auditable_intents(query: str, intent: str):
    plan = GuidanceService._query_plan(query)
    assert plan is not None
    assert plan.intent == intent


def test_guidance_policy_helpers_fail_closed_and_render_results():
    assert GuidanceService._query_plan("predict the stock market") is None
    assert not GuidanceService._asks_card_due_affordability("show bank balance")
    assert not GuidanceService._asks_card_upcoming_state("show bank balance")
    assert GuidanceService._unsupported_query_result(8, 2026).supported is False
    assert GuidanceService._money(1234.4, "INR") == "₹1,234"
    assert GuidanceService._money(1234.4, "USD") == "USD 1,234"
    assert GuidanceService._expected_impact("review").startswith("Improve")
    assert GuidanceService._expected_impact("unknown") == (
        "Improve the quality of the selected financial decision."
    )

    result = GuidanceService._result(
        "safe_to_spend",
        "safe",
        [],
        8,
        2026,
        ["Review"],
        confidence=0.7,
        evidence_cutoff=date(2026, 8, 20),
    )
    assert result.intent == "safe_to_spend"
    assert len(result.evidence) >= 1
    assert len(result.uncertainty) >= 2

    workspace = SimpleNamespace(
        review_summary=SimpleNamespace(low_confidence_count=3),
        snapshot=SimpleNamespace(budget_risk_count=2, income=1000, savings=250),
        recurring_commitments=[{"monthly_equivalent": 120}],
    )
    assert (
        GuidanceService._recommendation_metric("review", workspace)[0] == "unresolved_review_count"
    )
    assert GuidanceService._recommendation_metric("budget", workspace)[0] == "budget_risk_count"
    assert GuidanceService._recommendation_metric("recurring", workspace)[1] == Decimal("120")
    assert GuidanceService._recommendation_metric("savings", workspace)[1] == Decimal("25.00")
    assert GuidanceService._recommendation_metric("unknown", workspace) is None


def test_intelligence_spend_effect_and_daily_cutoff_are_fail_closed():
    debit = _transaction("debit", amount="100")
    refund = _transaction("refund", transaction_type=TransactionType.REFUND, amount="20")
    credit = _transaction("credit", transaction_type=TransactionType.CREDIT, amount="500")
    assert IntelligenceService._transaction_spend_effect(debit, None, currency="INR") == 100
    assert IntelligenceService._transaction_spend_effect(refund, None, currency="INR") == -20
    assert IntelligenceService._transaction_spend_effect(credit, None, currency="INR") == 0

    for override in (
        {"currency": "USD"},
        {"transaction_status": "pending"},
        {"is_transfer": True},
        {"is_accounting_adjustment": True},
        {"review_outcome": "ignored_by_rule"},
        {"card_event": "payment"},
    ):
        assert IntelligenceService._transaction_spend_effect(debit, override, currency="INR") == 0

    late = _transaction(
        "late",
        transaction_date=date(2026, 8, 16),
        created_at=_NOW + timedelta(days=1),
    )
    daily = IntelligenceService._daily_spend_for_cutoff(
        [debit, refund, late],
        as_of=_NOW.date(),
        currency="INR",
    )
    assert daily[(2026, 8)][15] == 80
    assert 16 not in daily[(2026, 8)]


def test_intelligence_category_baseline_distinguishes_history_states():
    transactions: list[Transaction] = []
    for index, (year, month) in enumerate(((2024, 8), (2025, 8), (2025, 7))):
        transactions.extend(
            [
                _transaction(
                    f"food-{index}",
                    transaction_date=date(year, month, 10),
                    created_at=datetime(year, month, 11, tzinfo=UTC),
                    amount=str(100 + index * 10),
                ),
                _transaction(
                    f"travel-{index}",
                    transaction_date=date(year, month, 12),
                    created_at=datetime(year, month, 13, tzinfo=UTC),
                    amount=str(50 + index * 5),
                ),
            ]
        )
    for item in transactions[::2]:
        item.category_id = "food"
    for item in transactions[1::2]:
        item.category_id = "travel"

    same_month = IntelligenceService._category_mix_baseline_from_transactions(
        transactions,
        {},
        month=8,
        year=2026,
        as_of=date(2026, 8, 20),
        currency="INR",
    )
    assert same_month[0] == 157.5
    assert same_month[2] == "same_month_supported"

    insufficient = IntelligenceService._category_mix_baseline_from_transactions(
        transactions[:2],
        {},
        month=8,
        year=2026,
        as_of=date(2026, 8, 20),
        currency="INR",
    )
    assert insufficient[0] is None
    assert insufficient[2] == "insufficient_history"


def test_intelligence_confidence_breakdown_reports_strong_and_weak_remediation():
    strong = IntelligenceService._data_confidence_breakdown(
        coverage_score=90,
        observed_periods=4,
        freshness_score=90,
        stale_days=1,
        latest_transaction_date=date(2026, 8, 19),
        parsing_score=90,
        parse_confidence=0.9,
        merchant_confidence=0.9,
        review_score=90,
        pending_count=0,
        conflict_count=0,
        transaction_count=10,
        latest_sync_at=_NOW,
        sync_status="idle",
        sync_age_days=1,
        unprocessed_email_count=0,
    )
    weak = IntelligenceService._data_confidence_breakdown(
        coverage_score=30,
        observed_periods=1,
        freshness_score=30,
        stale_days=None,
        latest_transaction_date=None,
        parsing_score=30,
        parse_confidence=0.3,
        merchant_confidence=0.2,
        review_score=20,
        pending_count=4,
        conflict_count=2,
        transaction_count=5,
        latest_sync_at=None,
        sync_status="error",
        sync_age_days=None,
        unprocessed_email_count=2,
    )
    assert {item.status for item in strong} == {"strong"}
    assert all(item.remediation_label is None for item in strong)
    assert weak[0].status == "limited"
    assert weak[0].remediation_label == "Import more history"
    assert "needs attention" in weak[1].summary


def test_reconciliation_helpers_return_bounded_scores_and_readiness():
    assert ReconciliationQualityService._coverage(1, 4) == 25.0
    assert ReconciliationQualityService._coverage(0, 0) == 100.0
    report = ReconciliationQualityResponse(
        as_of=_NOW,
        status="ready",
        evidence_score=88,
        transaction_total=4,
        transaction_reviewed=4,
        transaction_needs_review=0,
        transaction_ignored=1,
        transaction_review_coverage_pct=100,
        account_total=2,
        accounts_with_history=2,
        accounts_reconciled=2,
        accounts_needs_review=0,
        accounts_not_ready=0,
        account_reconciliation_coverage_pct=100,
        statement_line_total=3,
        statement_lines_matched=2,
        statement_lines_newly_imported=0,
        statement_lines_ignored=1,
        statement_lines_needs_review=0,
        statement_resolution_coverage_pct=100,
        duplicate_candidate_groups=0,
        unexplained_movements=0,
        unresolved_items=0,
    )
    readiness = ReconciliationQualityService.readiness(report)
    assert readiness.status == "ready"
    assert readiness.evidence_score == 88
    assert readiness.unresolved_items == 0


def test_provider_status_policy_selects_exact_source_and_freshness_state():
    provider_now = datetime.now(UTC)
    exact = AccountBalanceSource(
        user_id="user-1",
        financial_account_id="bank-1",
        source="connector",
        source_account_id="provider-1",
        coverage_complete=True,
        expected_cadence_minutes=60,
        last_success_at=provider_now - timedelta(minutes=30),
    )
    fallback = AccountBalanceSource(
        user_id="user-1",
        financial_account_id="bank-1",
        source="connector",
        source_account_id="other",
        coverage_complete=False,
        last_error_code="connector_failed",
    )
    assert BalanceProviderStatusService._source_state([exact, fallback], "provider-1") is exact
    assert BalanceProviderStatusService._source_state([fallback], "missing") is fallback
    assert BalanceProviderStatusService._source_state([exact, fallback], "missing") is None
    assert BalanceProviderStatusService._as_utc(datetime(2026, 8, 20, 12)) == _NOW
    assert BalanceProviderStatusService._as_utc(None) is None

    observation_service = BalanceObservationService(None)
    account = _account("bank-1")
    unmapped = BalanceProviderStatusService._account_status(
        account,
        None,
        None,
        observation_service,
    )
    assert unmapped.status == "unmapped"
    missing = BalanceProviderStatusService._account_status(
        account,
        None,
        "provider-1",
        observation_service,
    )
    assert missing.status == "not_configured"
    fresh = BalanceProviderStatusService._account_status(
        account,
        exact,
        "provider-1",
        observation_service,
    )
    assert fresh.status == "ready"

    due = AccountBalanceSource(
        user_id="user-1",
        financial_account_id="bank-1",
        source="connector",
        source_account_id="provider-1",
        coverage_complete=True,
        expected_cadence_minutes=60,
        last_success_at=provider_now - timedelta(minutes=61),
    )
    due_status = BalanceProviderStatusService._account_status(
        account,
        due,
        "provider-1",
        observation_service,
    )
    assert due_status.status == "due"

    incomplete = BalanceProviderStatusService._account_status(
        account,
        fallback,
        "other",
        observation_service,
    )
    assert incomplete.status == "incomplete"
    assert "source_coverage_incomplete" in incomplete.reason_codes
