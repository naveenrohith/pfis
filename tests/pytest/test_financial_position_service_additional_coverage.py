"""Additional deterministic branch coverage for the financial-position service."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.financial_position import (
    CardCalendarEvent,
    CardPaymentIntent,
    CashPlan,
    Commitment,
    CreditCardStatement,
    Liability,
    LiabilityScheduleItem,
    ReservePlan,
    StatementLine,
    StatementLineMatch,
)
from app.models.transaction import CardEvent, PaymentRail, Transaction, TransactionType
from app.schemas.financial_position import (
    CardCalendarEventCreate,
    CardCalendarEventUpdate,
    CardPaymentIntentUpdate,
    CommitmentCreate,
    LiabilityCreate,
    LiabilityScheduleConfirm,
    LiabilityScheduleItemCreate,
    ReservePlanCreate,
    StatementLineReviewRequest,
)
from app.services import financial_position_service as service_module
from app.services.financial_position_service import FinancialPositionService

USER = "user-1"
TODAY = date(2026, 9, 20)


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)

    def __iter__(self):
        return iter(self.rows)

    def one_or_none(self):
        if len(self.rows) > 1:
            raise AssertionError("expected at most one row")
        return self.rows[0] if self.rows else None


class _AsyncDb:
    def __init__(self, *, scalar_values=(), scalar_rows=(), execute_values=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]
        self.execute_values = list(execute_values)
        self.added = []
        self.deleted = []
        self.flushed = 0
        self.commits = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()

    async def execute(self, _statement):
        value = self.execute_values.pop(0) if self.execute_values else _Rows()
        return value

    async def flush(self):
        self.flushed += 1
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = str(uuid4())
            if hasattr(item, "created_at") and item.created_at is None:
                item.created_at = datetime(2026, 9, 20, tzinfo=UTC)
            if isinstance(item, Commitment) and item.is_active is None:
                item.is_active = True
            if isinstance(item, Commitment) and item.source_kind is None:
                item.source_kind = "manual"
            if isinstance(item, ReservePlan) and item.is_active is None:
                item.is_active = True
            if isinstance(item, LiabilityScheduleItem) and item.status is None:
                item.status = "upcoming"
            if isinstance(item, CardCalendarEvent) and item.source_kind is None:
                item.source_kind = "manual"

    async def commit(self):
        self.commits += 1

    async def refresh(self, _item):
        return None

    def add(self, item):
        self.added.append(item)

    async def delete(self, item):
        self.deleted.append(item)

    async def get(self, _model, _item_id):
        return None


def _account(account_id="bank-1", *, account_type="bank", balance_kind="asset", active=True):
    return FinancialAccount(
        id=account_id,
        user_id=USER,
        institution_name="Coverage Bank",
        account_type=account_type,
        balance_kind=balance_kind,
        masked_number="****1001",
        currency="INR",
        is_active=active,
        identity_status="confirmed",
    )


def _transaction(
    transaction_id="txn-1",
    *,
    amount="100",
    transaction_type=TransactionType.DEBIT,
    transaction_date=TODAY,
    status="settled",
    reviewed=True,
    review_outcome="matched",
    rail=PaymentRail.OTHER,
    card_event=CardEvent.NONE,
    merchant="Coffee House",
    source_kind="manual",
    source_email_id=None,
):
    return Transaction(
        id=transaction_id,
        user_id=USER,
        amount=Decimal(amount),
        currency="INR",
        transaction_type=transaction_type,
        payment_rail=rail,
        card_event=card_event,
        transaction_status=status,
        transaction_date=transaction_date,
        merchant_raw=merchant,
        merchant_normalized=merchant,
        financial_account_id="bank-1",
        reviewed_flag=reviewed,
        review_outcome=review_outcome,
        source_kind=source_kind,
        source_email_id=source_email_id,
    )


def _statement_line(line_id="line-1", *, amount="100", description="Coffee House"):
    return StatementLine(
        id=line_id,
        user_id=USER,
        credit_card_statement_id="statement-1",
        line_number=1,
        transaction_date=TODAY,
        description=description,
        amount=Decimal(amount),
        transaction_type="debit",
        component_kind="ordinary",
        review_outcome="needs_review",
    )


def _statement(statement_id="statement-1"):
    return CreditCardStatement(
        id=statement_id,
        user_id=USER,
        statement_import_id="import-1",
        financial_account_id="card-1",
        statement_date=TODAY,
        period_start=TODAY - timedelta(days=30),
        period_end=TODAY,
        due_date=TODAY + timedelta(days=15),
        total_due=Decimal("500"),
        minimum_due=Decimal("50"),
        currency="INR",
    )


def _cash_position(**values):
    fields = {
        "estimated_balance": 900.0,
        "estimated_as_of": TODAY,
        "position_status": "estimated",
        "position_confidence": 0.8,
        "position_reason_codes": [],
        "observed_source": "manual",
        "observed_at": None,
        "coverage_start": None,
        "coverage_end": None,
        "latest_sync_at": None,
        "coverage_complete": True,
        "coverage_status": "fresh",
        "settled_movement_since_observation": -100.0,
        "pending_increase": 0.0,
        "pending_decrease": 0.0,
    }
    fields.update(values)
    return SimpleNamespace(**fields)


@pytest.mark.asyncio
async def test_account_position_builds_estimate_and_reconciliation_reasons(monkeypatch):
    account = _account()
    latest = AccountBalanceSnapshot(
        id="latest",
        user_id=USER,
        financial_account_id=account.id,
        amount=Decimal("1000"),
        currency="INR",
        as_of=TODAY - timedelta(days=1),
        effective_at=datetime(2026, 9, 19, 12, tzinfo=UTC),
        verified=True,
        observed_at=datetime(2026, 9, 19, 13, tzinfo=UTC),
    )
    previous = AccountBalanceSnapshot(
        id="previous",
        user_id=USER,
        financial_account_id=account.id,
        amount=Decimal("900"),
        currency="INR",
        as_of=TODAY - timedelta(days=4),
        effective_at=datetime(2026, 9, 16, 12, tzinfo=UTC),
        verified=True,
    )
    transactions = [
        _transaction("settled", amount="50", transaction_date=TODAY, reviewed=False),
        _transaction(
            "pending",
            amount="25",
            status="pending",
            reviewed=False,
            review_outcome="needs_review",
            rail=PaymentRail.TRANSFER,
            card_event=CardEvent.PAYMENT,
        ),
        _transaction("ignored", amount="99", review_outcome="ignored_by_rule"),
    ]
    db = _AsyncDb(scalar_rows=[[latest, previous], transactions])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service, "_owned_account", lambda *_: _async_value(account))
    monkeypatch.setattr(service, "_source_coverage_incomplete", lambda *_: _async_value(False))
    state = SimpleNamespace(
        coverage_start=None,
        coverage_end=None,
        last_success_at=None,
        coverage_complete=True,
        expected_cadence_minutes=None,
    )
    monkeypatch.setattr(service, "_balance_source_state", lambda *_: _async_value(state))

    result = await service.account_position(USER, account.id, as_of=TODAY)

    assert result is not None
    assert result.estimated_balance == 950.0
    assert result.pending_decrease == 25.0
    assert result.position_status == "needs_review"
    assert {"pending_activity_excluded", "unreviewed_activity", "unlinked_card_payment"} <= set(
        result.position_reason_codes
    )
    assert result.reconciliation_delta == 100.0


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_commitment_reserve_and_liability_validation_and_updates(monkeypatch):
    db = _AsyncDb(scalar_values=[None, None, None, None])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service, "_validate_optional_account", lambda *_: _async_value(None))

    async def require_account(user_id, account_id):
        if account_id == "missing":
            raise LookupError("Financial account not found")
        return _account(account_id)

    monkeypatch.setattr(service, "_require_account", require_account)
    monkeypatch.setattr(service, "_snapshot_commitment", lambda *_: _async_value(None))
    monkeypatch.setattr(service, "_snapshot_reserve", lambda *_: _async_value(None))

    commitment = await service.create_commitment(
        USER,
        CommitmentCreate(
            label="Rent",
            commitment_type="bill",
            amount=Decimal("500"),
            due_date=TODAY + timedelta(days=2),
            financial_account_id="bank-1",
        ),
    )
    reserve = await service.create_reserve(
        USER,
        ReservePlanCreate(
            financial_account_id="bank-1",
            label="Insurance",
            target_amount=Decimal("1200"),
            due_date=TODAY + timedelta(days=60),
            monthly_allocation=Decimal("100"),
        ),
    )

    assert commitment.label == "Rent"
    assert reserve.monthly_allocation == 100.0
    assert db.commits == 2

    db.scalar_values = [None]
    with pytest.raises(LookupError, match="Financial account not found"):
        await service.create_reserve(
            USER,
            ReservePlanCreate(
                financial_account_id="missing",
                label="Invalid",
                target_amount=Decimal("10"),
                due_date=TODAY,
                monthly_allocation=Decimal("1"),
            ),
        )

    with pytest.raises(ValueError, match="Confirm the instalment rows"):
        await service.create_liability(
            USER,
            LiabilityCreate(label="Loan", liability_type="loan", complete_schedule=True),
        )


@pytest.mark.asyncio
async def test_confirm_liability_schedule_creates_only_upcoming_commitments(monkeypatch):
    liability = Liability(
        id="loan-1",
        user_id=USER,
        financial_account_id="bank-1",
        label="Personal loan",
        liability_type="loan",
        source_kind="manual",
        complete_schedule=False,
        schedule_status="not_provided",
    )
    db = _AsyncDb(scalar_values=[liability, 0])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service_module, "user_financial_today", lambda *_: _async_value(TODAY))
    monkeypatch.setattr(service, "_snapshot_liability_schedule_item", lambda *_: _async_value(None))
    monkeypatch.setattr(service, "_snapshot_commitment", lambda *_: _async_value(None))
    data = LiabilityScheduleConfirm(
        source_kind="statement",
        items=[
            LiabilityScheduleItemCreate(
                due_date=TODAY - timedelta(days=2),
                installment_amount=Decimal("100"),
                principal_amount=Decimal("80"),
                interest_amount=Decimal("20"),
            ),
            LiabilityScheduleItemCreate(
                due_date=TODAY + timedelta(days=10),
                installment_amount=Decimal("120"),
                principal_amount=Decimal("100"),
                interest_amount=Decimal("20"),
            ),
        ],
    )

    rows = await service.confirm_liability_schedule(USER, liability.id, data)

    assert len(rows) == 2
    assert liability.complete_schedule is True
    assert liability.schedule_status == "confirmed"
    assert liability.remaining_installments == 1
    assert liability.next_due_date == TODAY + timedelta(days=10)
    commitments = [item for item in db.added if isinstance(item, Commitment)]
    assert len(commitments) == 1
    assert commitments[0].source_kind == "statement"


@pytest.mark.asyncio
async def test_confirm_liability_schedule_rejects_duplicate_or_unbalanced_rows():
    liability = Liability(id="loan-1", user_id=USER, label="Loan", liability_type="loan")
    service = FinancialPositionService(_AsyncDb(scalar_values=[liability, 0]))
    duplicate = LiabilityScheduleConfirm(
        items=[
            LiabilityScheduleItemCreate(due_date=TODAY, installment_amount=Decimal("10")),
            LiabilityScheduleItemCreate(due_date=TODAY, installment_amount=Decimal("10")),
        ]
    )
    with pytest.raises(ValueError, match="only one instalment"):
        await service.confirm_liability_schedule(USER, liability.id, duplicate)

    unbalanced = LiabilityScheduleConfirm(
        items=[
            LiabilityScheduleItemCreate(
                due_date=TODAY, installment_amount=Decimal("10"), principal_amount=Decimal("9")
            )
        ]
    )
    with pytest.raises(ValueError, match="components must equal"):
        await FinancialPositionService(
            _AsyncDb(scalar_values=[liability, 0])
        ).confirm_liability_schedule(USER, liability.id, unbalanced)


@pytest.mark.asyncio
async def test_card_calendar_crud_snapshots_and_deletes(monkeypatch):
    db = _AsyncDb()
    service = FinancialPositionService(db)
    card = _account("card-1", account_type="credit_card", balance_kind="liability")
    monkeypatch.setattr(service, "_require_card_account", lambda *_: _async_value(card))
    monkeypatch.setattr(
        service, "_snapshot_card_calendar_event", lambda *_args, **_kwargs: _async_value(None)
    )
    event = await service.create_card_calendar_event(
        USER,
        card.id,
        CardCalendarEventCreate(event_type="annual_fee", label="Annual fee", event_date=TODAY),
    )
    db.scalar_values = [db.added[-1]]
    updated = await service.update_card_calendar_event(
        USER,
        card.id,
        event.id,
        CardCalendarEventUpdate(label="Waived annual fee"),
    )
    db.scalar_values = [db.added[-1]]
    await service.delete_card_calendar_event(USER, card.id, event.id)

    assert updated.label == "Waived annual fee"
    assert db.deleted == [db.added[-1]]
    assert db.commits == 3


@pytest.mark.asyncio
async def test_card_payment_intent_cancel_and_recording_guards(monkeypatch):
    card = _account("card-1", account_type="credit_card", balance_kind="liability")
    intent = CardPaymentIntent(
        id="intent-1",
        user_id=USER,
        financial_account_id=card.id,
        amount=Decimal("250"),
        planned_for=TODAY,
        status="planned",
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    db = _AsyncDb(scalar_values=[intent])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service, "_require_card_account", lambda *_: _async_value(card))
    monkeypatch.setattr(
        service_module, "capture_card_payment_intent_snapshot", lambda *_: _async_value(None)
    )

    cancelled = await service.update_card_payment_intent(
        USER, card.id, intent.id, CardPaymentIntentUpdate(status="cancelled")
    )
    assert cancelled.status == "cancelled"

    intent.status = "planned"
    db.scalar_values = [intent]
    with pytest.raises(ValueError, match="Choose the bank account"):
        await service.update_card_payment_intent(
            USER, card.id, intent.id, CardPaymentIntentUpdate(status="recorded")
        )


@pytest.mark.asyncio
async def test_cash_plan_returns_empty_and_ready_read_models(monkeypatch):
    db = _AsyncDb(scalar_values=[None])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service_module, "user_financial_today", lambda *_: _async_value(TODAY))
    monkeypatch.setattr(service_module, "get_ledger_currency", lambda *_: _async_value("INR"))
    empty = await service.cash_plan(USER)
    assert empty.readiness == "needs_verified_balance"
    assert empty.primary_financial_account_id == ""

    plan = CashPlan(
        id="plan-1",
        user_id=USER,
        primary_financial_account_id="bank-1",
        next_income_date=TODAY + timedelta(days=10),
        next_income_amount=Decimal("5000"),
        show_daily_allowance=True,
    )
    snapshot = AccountBalanceSnapshot(
        id="snap-1",
        user_id=USER,
        financial_account_id="bank-1",
        amount=Decimal("1000"),
        currency="INR",
        as_of=TODAY,
        verified=True,
    )
    commitment = Commitment(
        id="commitment-1",
        user_id=USER,
        label="Rent",
        commitment_type="bill",
        amount=Decimal("200"),
        due_date=TODAY + timedelta(days=2),
        confirmed=True,
        is_active=True,
        source_kind="manual",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    reserve = ReservePlan(
        id="reserve-1",
        user_id=USER,
        financial_account_id="bank-1",
        label="Tax",
        target_amount=Decimal("500"),
        due_date=TODAY + timedelta(days=40),
        monthly_allocation=Decimal("50"),
        approved=True,
        is_active=True,
    )
    db.scalar_values = [plan, snapshot]
    db.scalar_rows = [_Rows([commitment]), _Rows([reserve])]
    account = _account()
    position = SimpleNamespace(
        estimated_balance=900.0,
        estimated_as_of=TODAY,
        position_status="estimated",
        position_confidence=0.8,
        position_reason_codes=[],
        observed_source="manual",
        observed_at=None,
        coverage_start=None,
        coverage_end=None,
        latest_sync_at=None,
        coverage_complete=True,
        coverage_status="fresh",
        settled_movement_since_observation=-100.0,
        pending_increase=0.0,
        pending_decrease=0.0,
    )
    monkeypatch.setattr(service, "_require_account", lambda *_: _async_value(account))
    monkeypatch.setattr(service, "account_position", lambda *_: _async_value(position))

    ready = await service.cash_plan(USER)
    assert ready.readiness == "ready"
    assert ready.planning_balance == 900.0
    assert ready.flexible_money == 650.0
    assert ready.daily_allowance == 65.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account", "position", "snapshot", "next_income", "expected"),
    [
        (_account(active=False), None, None, TODAY + timedelta(days=10), "needs_verified_balance"),
        (
            _account(),
            _cash_position(),
            None,
            TODAY + timedelta(days=10),
            "needs_verified_balance",
        ),
        (
            _account(),
            _cash_position(),
            SimpleNamespace(amount=1000, as_of=TODAY - timedelta(days=8)),
            TODAY + timedelta(days=10),
            "needs_fresh_balance",
        ),
        (
            _account(),
            _cash_position(position_status="needs_review"),
            SimpleNamespace(amount=1000, as_of=TODAY),
            TODAY + timedelta(days=10),
            "needs_position_review",
        ),
        (
            _account(),
            _cash_position(),
            SimpleNamespace(amount=1000, as_of=TODAY),
            None,
            "needs_next_income",
        ),
        (
            _account(),
            _cash_position(estimated_balance=None),
            SimpleNamespace(amount=1000, as_of=TODAY),
            TODAY + timedelta(days=10),
            "needs_position_review",
        ),
    ],
)
async def test_cash_plan_exposes_each_readiness_blocker(
    monkeypatch, account, position, snapshot, next_income, expected
):
    plan = CashPlan(
        id="plan-1",
        user_id=USER,
        primary_financial_account_id=account.id,
        next_income_date=next_income,
        show_daily_allowance=True,
    )
    db = _AsyncDb(scalar_values=[plan, snapshot])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service_module, "user_financial_today", lambda *_: _async_value(TODAY))
    monkeypatch.setattr(service, "_require_account", lambda *_: _async_value(account))
    monkeypatch.setattr(service, "account_position", lambda *_: _async_value(position))

    result = await service.cash_plan(USER)

    assert result.readiness == expected


@pytest.mark.asyncio
async def test_statement_matching_prefers_reference_and_reports_ambiguity():
    line = _statement_line()
    referenced = _transaction("referenced", merchant="Different", source_email_id=None)
    referenced.reference_id = "REF-1"
    line.reference_id = "REF-1"
    db = _AsyncDb(scalar_values=[referenced])
    service = FinancialPositionService(db)
    assert await service._match_statement_line(USER, "card-1", line) == (
        referenced,
        False,
        "reference",
    )

    first = _transaction("candidate-1")
    second = _transaction("candidate-2")
    line.reference_id = None
    db = _AsyncDb(scalar_rows=[[first, second]])
    service = FinancialPositionService(db)
    assert await service._match_statement_line(USER, "card-1", line) == (None, True, None)


@pytest.mark.parametrize(
    ("account", "require_hdfc", "message"),
    [
        (_account(account_type="loan"), False, "asset bank"),
        (_account(active=False), False, "active"),
        (_account(), True, "HDFC"),
        (_account(), False, "identity"),
    ],
)
def test_deposit_account_validation_fails_closed(account, require_hdfc, message):
    if message == "identity":
        account.identity_status = "unresolved"
    with pytest.raises(ValueError, match=message):
        FinancialPositionService._validate_deposit_account(account, require_hdfc=require_hdfc)


@pytest.mark.asyncio
async def test_statement_match_recording_is_idempotent_but_rejects_conflicts():
    line = _statement_line()
    existing = StatementLineMatch(user_id=USER, statement_line_id=line.id, transaction_id="txn-1")
    service = FinancialPositionService(_AsyncDb(scalar_values=[existing]))
    await service._record_statement_match(USER, line, "txn-1", "reference", Decimal("1.0"))
    assert service.db.added == []

    conflict_db = _AsyncDb(scalar_values=[existing])
    service = FinancialPositionService(conflict_db)
    with pytest.raises(ValueError, match="already matched"):
        await service._record_statement_match(USER, line, "other-txn", "reference", Decimal("1.0"))


@pytest.mark.asyncio
async def test_card_payment_candidates_filter_evidence_and_rank(monkeypatch):
    line = _statement_line(amount="250")
    line.card_event = "payment"
    line.reference_id = "REF-1"
    card = _account("card-1", account_type="credit_card", balance_kind="liability")
    bank = _account("bank-1")
    good = _transaction(
        "good", amount="250", merchant="Credit Card Payment", transaction_date=TODAY
    )
    good.reference_id = "REF-1"
    bad = _transaction("bad", amount="250", merchant="Grocery", transaction_date=TODAY)
    db = _AsyncDb(
        execute_values=[
            _Rows([(line, _statement(), card)]),
            _Rows([(good, bank), (bad, bank)]),
        ]
    )
    candidates = await FinancialPositionService(db).card_payment_candidates(USER, line.id)
    assert len(candidates) == 1
    assert candidates[0].transaction_id == "good"
    assert candidates[0].match_method == "reference"
    assert "statement_reference_match" in candidates[0].evidence


@pytest.mark.asyncio
async def test_review_statement_line_rejects_missing_match_inputs():
    line = _statement_line()
    line.card_event = "purchase"
    db = _AsyncDb(
        execute_values=[
            _Rows(
                [
                    (
                        line,
                        _statement(),
                        _account("card-1", account_type="credit_card", balance_kind="liability"),
                    )
                ]
            )
        ]
    )
    service = FinancialPositionService(db)
    with pytest.raises(ValueError, match="existing ledger transaction"):
        await service.review_statement_line(
            USER,
            line.id,
            StatementLineReviewRequest(decision="match", matched_transaction_id=None),
        )

    payment_line = _statement_line("payment-line")
    payment_line.card_event = "payment"
    db = _AsyncDb(
        execute_values=[
            _Rows(
                [
                    (
                        payment_line,
                        _statement(),
                        _account("card-1", account_type="credit_card", balance_kind="liability"),
                    )
                ]
            )
        ]
    )
    service = FinancialPositionService(db)
    with pytest.raises(ValueError, match="bank account used"):
        await service.review_statement_line(
            USER,
            payment_line.id,
            StatementLineReviewRequest(decision="record_card_payment"),
        )
