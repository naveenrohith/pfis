"""Deep deterministic coverage for financial-position CRUD and evidence helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.financial_position import Commitment, Liability, LiabilityScheduleItem, ReservePlan
from app.schemas.financial_position import (
    CardPaymentIntentCreate,
    CardPaymentIntentUpdate,
    CardPreferenceUpsert,
    CommitmentUpdate,
    LiabilityScheduleItemUpdate,
    ReservePlanUpdate,
)
from app.services import financial_position_service as service_module
from app.services.financial_position_service import FinancialPositionService

from tests.pytest.test_financial_position_service_additional_coverage import (
    TODAY,
    USER,
    _account,
    _async_value,
    _AsyncDb,
)


def _commitment(commitment_id="commitment-1"):
    return Commitment(
        id=commitment_id,
        user_id=USER,
        label="Rent",
        commitment_type="bill",
        amount=Decimal("500"),
        due_date=TODAY,
        source_kind="manual",
        confirmed=True,
        is_active=True,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _reserve(reserve_id="reserve-1"):
    return ReservePlan(
        id=reserve_id,
        user_id=USER,
        financial_account_id="bank-1",
        label="Tax",
        target_amount=Decimal("1200"),
        due_date=TODAY,
        monthly_allocation=Decimal("100"),
        approved=True,
        is_active=True,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _liability(liability_id="liability-1", *, status="confirmed"):
    return Liability(
        id=liability_id,
        user_id=USER,
        label="Loan",
        liability_type="loan",
        financial_account_id="bank-1",
        source_kind="manual",
        source_confidence=Decimal("1.000"),
        monthly_due=Decimal("400"),
        next_due_date=TODAY,
        remaining_installments=4,
        complete_schedule=status == "confirmed",
        schedule_status=status,
        evidence_line_count=0,
        is_active=True,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


def _schedule_item(item_id="item-1", *, status="upcoming"):
    return LiabilityScheduleItem(
        id=item_id,
        liability_id="liability-1",
        user_id=USER,
        due_date=TODAY,
        installment_amount=Decimal("400"),
        principal_amount=Decimal("350"),
        interest_amount=Decimal("50"),
        source_kind="manual",
        source_identifier="schedule:item-1",
        confidence=Decimal("1.000"),
        status=status,
    )


@pytest.mark.asyncio
async def test_source_coverage_and_owned_account_guards_cover_connector_states():
    account = _account()
    account.connector_account_id = None
    manual = FinancialPositionService(_AsyncDb(scalar_values=[None]))
    assert await manual._source_coverage_incomplete(USER, account, []) is False

    account.connector_account_id = "provider-account"
    incomplete = SimpleNamespace(coverage_complete=False)
    service = FinancialPositionService(_AsyncDb(scalar_values=[None, incomplete]))
    assert await service._source_coverage_incomplete(USER, account, []) is True

    source = SimpleNamespace(id="source-1")
    service = FinancialPositionService(_AsyncDb(scalar_values=[source]))
    assert await service._balance_source_state(USER, account.id) is source

    service = FinancialPositionService(_AsyncDb(scalar_values=[None]))
    assert await service._owned_account(USER, account.id) is None
    with pytest.raises(LookupError, match="Financial account not found"):
        await service._require_account(USER, account.id)
    with pytest.raises(LookupError, match="Financial account not found"):
        await service._require_card_account(USER, "missing")


@pytest.mark.asyncio
async def test_commitment_and_reserve_listing_updates_and_missing_rows(monkeypatch):
    commitment = _commitment()
    reserve = _reserve()
    db = _AsyncDb(scalar_rows=[[commitment], [reserve]], scalar_values=[])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service, "_snapshot_commitment", lambda *_: _async_value(None))
    monkeypatch.setattr(service, "_snapshot_reserve", lambda *_: _async_value(None))

    assert (await service.list_commitments(USER))[0].id == commitment.id
    assert (await service.list_reserves(USER))[0].id == reserve.id

    db.scalar_values = [commitment, reserve]
    updated_commitment = await service.update_commitment(
        USER, commitment.id, CommitmentUpdate(label="Updated rent", confirmed=False)
    )
    updated_reserve = await service.update_reserve(
        USER, reserve.id, ReservePlanUpdate(label="Updated tax", approved=False)
    )
    assert updated_commitment.label == "Updated rent"
    assert updated_reserve.label == "Updated tax"

    db.scalar_values = [None, None]
    assert await service.update_commitment(USER, "missing", CommitmentUpdate(label="x")) is None
    assert await service.update_reserve(USER, "missing", ReservePlanUpdate(label="x")) is None


@pytest.mark.asyncio
async def test_liability_schedule_listing_updates_and_overview_aggregate_states(monkeypatch):
    liability = _liability()
    item = _schedule_item()
    closed = _schedule_item("item-2", status="paid")
    db = _AsyncDb(scalar_values=[liability], scalar_rows=[[item, closed]])
    service = FinancialPositionService(db)
    assert (await service.liability_schedule(USER, liability.id))[0].id == item.id

    update_db = _AsyncDb(scalar_values=[liability, item, None], scalar_rows=[[item, closed]])
    service = FinancialPositionService(update_db)
    monkeypatch.setattr(service, "_snapshot_liability_schedule_item", lambda *_: _async_value(None))
    updated = await service.update_liability_schedule_item(
        USER, liability.id, item.id, LiabilityScheduleItemUpdate(status="paid")
    )
    assert updated.status == "paid"
    assert liability.remaining_installments == 0

    db.scalar_values = [None]
    with pytest.raises(LookupError, match="Liability not found"):
        await service.liability_schedule(USER, "missing")

    confirmed = _liability("confirmed", status="confirmed")
    partial = _liability("partial", status="observed_partial")
    manual = _liability("manual", status="not_provided")
    partial.observed_monthly_amount = Decimal("400")
    overview = await FinancialPositionService(
        _AsyncDb(scalar_rows=[[confirmed, partial, manual]])
    ).liability_overview(USER)
    assert overview.known_monthly_debt == 1200.0
    assert overview.confirmed_monthly_debt == 400.0
    assert overview.observed_card_emi_monthly == 400.0
    assert overview.next_due_amount == 400.0


@pytest.mark.asyncio
async def test_card_preference_and_payment_intent_guard_paths(monkeypatch):
    card = _account("card-1", account_type="credit_card", balance_kind="liability")
    service = FinancialPositionService(_AsyncDb(scalar_values=[None]))
    monkeypatch.setattr(service, "_require_card_account", lambda *_: _async_value(card))
    monkeypatch.setattr(service, "_validate_optional_account", lambda *_: _async_value(None))

    preference = await service.save_card_preference(
        USER,
        card.id,
        CardPreferenceUpsert(
            preferred_payment_account_id="bank-1",
            utilization_target_pct=Decimal("30"),
            reward_rules=[{"kind": "cashback", "value": 1}],
        ),
    )
    assert preference.preferred_payment_account_id == "bank-1"
    assert preference.reward_rules == [{"kind": "cashback", "value": 1}]

    intent_db = _AsyncDb()
    intent_service = FinancialPositionService(intent_db)
    monkeypatch.setattr(intent_service, "_require_card_account", lambda *_: _async_value(card))
    monkeypatch.setattr(intent_service, "_validate_optional_account", lambda *_: _async_value(None))
    monkeypatch.setattr(
        service_module, "capture_card_payment_intent_snapshot", lambda *_: _async_value(None)
    )

    async def flush_intent():
        await _AsyncDb.flush(intent_db)
        intent_db.added[0].status = "planned"

    intent_db.flush = flush_intent
    intent = await intent_service.create_card_payment_intent(
        USER,
        card.id,
        CardPaymentIntentCreate(amount=Decimal("250"), planned_for=TODAY),
    )
    assert intent.status == "planned"

    db = _AsyncDb(scalar_values=[None])
    missing_service = FinancialPositionService(db)
    monkeypatch.setattr(missing_service, "_require_card_account", lambda *_: _async_value(card))
    with pytest.raises(LookupError, match="payment intention"):
        await missing_service.update_card_payment_intent(
            USER, card.id, "missing", CardPaymentIntentUpdate(status="cancelled")
        )


@pytest.mark.asyncio
async def test_card_payment_intent_update_short_circuits_and_rejects_non_planned_state(monkeypatch):
    card = _account("card-1", account_type="credit_card", balance_kind="liability")
    from app.models.financial_position import CardPaymentIntent

    intent = CardPaymentIntent(
        id="intent-1",
        user_id=USER,
        financial_account_id=card.id,
        amount=Decimal("250"),
        planned_for=TODAY,
        status="cancelled",
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    db = _AsyncDb(scalar_values=[intent])
    service = FinancialPositionService(db)
    monkeypatch.setattr(service, "_require_card_account", lambda *_: _async_value(card))

    same = await service.update_card_payment_intent(
        USER, card.id, intent.id, CardPaymentIntentUpdate(status="cancelled")
    )
    assert same.status == "cancelled"
    db.scalar_values = [intent]
    with pytest.raises(ValueError, match="cannot be changed"):
        await service.update_card_payment_intent(
            USER, card.id, intent.id, CardPaymentIntentUpdate(status="recorded")
        )
