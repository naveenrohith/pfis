"""Coverage for issuer EMI materialization and ledger projection helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.transaction import CardEvent
from app.services import financial_position_service as module
from app.services.financial_position_service import FinancialPositionService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, rows=(), *, scalar_values=(), get_values=()):
        self.rows = list(rows)
        self.scalar_values = list(scalar_values)
        self.get_values = list(get_values)
        self.added = []
        self.flushes = 0

    async def scalars(self, _statement):
        return _Rows(self.rows.pop(0) if self.rows else [])

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def get(self, _model, _row_id):
        return self.get_values.pop(0) if self.get_values else None

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushes += 1


def _plan(reference, *, status="active", merchant="Laptop"):
    return SimpleNamespace(
        issuer_plan_reference=reference,
        merchant=merchant,
        original_amount=1000,
        latest_installment_amount=110,
        latest_statement_date=date(2026, 9, 1),
        latest_due_date=date(2026, 9, 20),
        latest_principal=90,
        latest_interest=10,
        latest_tax=0,
        latest_fees=2,
        status=status,
        evidence_line_count=3,
    )


def _liability(reference, **overrides):
    values = {
        "issuer_plan_reference": reference,
        "source_kind": "statement",
        "complete_schedule": False,
        "is_active": True,
        "label": "Old label",
        "source_identifier": "old",
        "source_confidence": Decimal("0.5"),
        "observed_original_amount": Decimal("900"),
        "observed_monthly_amount": Decimal("90"),
        "observed_principal_component": Decimal("80"),
        "observed_interest_component": Decimal("10"),
        "observed_tax_component": Decimal("0"),
        "observed_fee_component": Decimal("0"),
        "last_observed_statement_date": date(2026, 8, 1),
        "evidence_line_count": 1,
        "monthly_due": Decimal("90"),
        "next_due_date": date(2026, 8, 20),
        "schedule_status": "observed_partial",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_sync_card_emi_liabilities_creates_updates_and_deactivates_observed_rows(monkeypatch):
    statements = [SimpleNamespace(id="statement-1", financial_account_id="card-1")]
    lines = [SimpleNamespace(id="line-1")]
    stale = _liability("stale")
    existing = _liability("existing")
    plans = [_plan("new", merchant="New Laptop"), _plan("existing", merchant="Updated Laptop")]
    monkeypatch.setattr(module, "_build_card_emi_plans", lambda _statements, _lines: plans)
    db = _Db([statements, lines, [stale, existing]])
    changed = await FinancialPositionService(db)._sync_card_emi_liabilities("user-1")
    assert changed == 3
    assert stale.is_active is False
    assert existing.label == "Updated Laptop"
    assert len(db.added) == 1
    assert db.flushes == 1

    stale_again = _liability("stale")
    existing_again = _liability("existing")
    no_persist_db = _Db([statements, lines, [stale_again, existing_again]])
    changed = await FinancialPositionService(no_persist_db)._sync_card_emi_liabilities(
        "user-1", account_id="card-1", persist=False
    )
    assert changed == 3
    assert no_persist_db.added == []


@pytest.mark.asyncio
async def test_statement_matching_prefers_reference_and_reports_ambiguous_fuel_candidates(
    monkeypatch,
):
    exact = SimpleNamespace(
        id="exact",
        amount=Decimal("100"),
        merchant_normalized="Merchant",
        merchant_raw=None,
        source_email=None,
    )
    service = FinancialPositionService(_Db(scalar_values=[exact]))
    line = SimpleNamespace(
        reference_id="ref",
        amount=Decimal("100"),
        transaction_date=date(2026, 9, 20),
        transaction_type="debit",
        description="Merchant",
        merchant_normalized="Merchant",
    )
    matched = await service._match_statement_line("user-1", "account-1", line)
    assert matched == (exact, False, "reference")

    candidate = SimpleNamespace(
        id="candidate",
        amount=Decimal("100"),
        merchant_normalized="Merchant",
        merchant_raw=None,
        source_email=None,
        source_email_id=None,
    )
    no_reference_line = SimpleNamespace(
        reference_id=None,
        amount=Decimal("100"),
        transaction_date=date(2026, 9, 20),
        transaction_type="debit",
        description="Merchant",
        merchant_normalized="Merchant",
    )
    service = FinancialPositionService(_Db(rows=[[candidate]]))
    matched = await service._match_statement_line("user-1", "account-1", no_reference_line)
    assert matched == (candidate, False, "exact_amount")

    duplicate_values = dict(candidate.__dict__)
    duplicate_values["id"] = "duplicate"
    duplicate = SimpleNamespace(**duplicate_values)
    service = FinancialPositionService(_Db(rows=[[candidate, duplicate]]))
    unmatched = await service._match_statement_line("user-1", "account-1", no_reference_line)
    assert unmatched == (None, True, None)


@pytest.mark.asyncio
async def test_emi_ledger_projection_updates_event_and_merchant_evidence(monkeypatch):
    transaction = SimpleNamespace(
        id="txn-1",
        card_event=CardEvent.NONE,
        ledger_subtype=None,
        is_accounting_adjustment=False,
        merchant_normalized="Old",
        category_id=None,
        transaction_date=date(2026, 9, 20),
        merchant_resolution_source=None,
        merchant_resolution_confidence=None,
        merchant_rule_id=None,
        merchant_resolver_version=None,
    )
    line = SimpleNamespace(
        id="line-1",
        credit_card_statement_id="statement-1",
        created_transaction_id="txn-1",
        component_kind="emi_principal",
        card_event="purchase",
        merchant_normalized="Old",
        merchant_confidence=0.5,
    )
    component = SimpleNamespace(statement_line_id="line-1")
    plan = SimpleNamespace(merchant="Better Merchant", components=[component])
    statement = SimpleNamespace(id="statement-1")
    monkeypatch.setattr(module, "_build_card_emi_plans", lambda _statements, _lines: [plan])
    monkeypatch.setattr(module, "resolve_merchant", _merchant)
    service = FinancialPositionService(_Db([[statement]], get_values=[transaction]))
    monkeypatch.setattr(service, "_invalidate_monthly_summary", _async_noop)
    stats = {"accounting_adjustments_marked": 0, "emi_ledger_events_projected": 0}
    await service._project_emi_ledger_events("user-1", [line], {}, stats, dry_run=False)
    assert stats == {"accounting_adjustments_marked": 0, "emi_ledger_events_projected": 1}
    assert transaction.ledger_subtype == "emi_principal"
    assert transaction.card_event == CardEvent.PURCHASE
    assert transaction.merchant_normalized == "Better Merchant"


async def _merchant(*_args, **_kwargs):
    return SimpleNamespace(
        normalized_name="Better Merchant",
        category_id="category-1",
        confidence=0.8,
        source="test",
        rule_id="rule-1",
        resolver_version=1,
    )


async def _async_noop(*_args, **_kwargs):
    return None
