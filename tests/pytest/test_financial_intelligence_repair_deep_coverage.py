"""Deep branch coverage for deterministic financial-intelligence repair."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.transaction import CardEvent, PaymentRail, TransactionType
from app.services import financial_position_service as module
from app.services.classification import ClassificationType
from app.services.financial_position_service import FinancialPositionService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _ExecuteResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _RepairDb:
    def __init__(self, *, scalar_rows=(), scalar_values=(), get_values=None):
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]
        self.scalar_values = list(scalar_values)
        self.get_values = dict(get_values or {})
        self.added = []
        self.commits = 0
        self.flushed = 0

    async def execute(self, _statement):
        return _ExecuteResult()

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def get(self, _model, item_id):
        return self.get_values.get(item_id)

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.commits += 1


def _line(line_id: str, *, description: str, line_number: int, **values):
    defaults = {
        "id": line_id,
        "credit_card_statement_id": "statement-1",
        "line_number": line_number,
        "transaction_date": date(2026, 9, 10),
        "description": description,
        "amount": Decimal("100"),
        "transaction_type": "debit",
        "component_kind": "ordinary",
        "issuer_plan_reference": None,
        "installment_number": None,
        "card_event": "purchase",
        "reference_id": None,
        "merchant_normalized": "Old merchant",
        "merchant_confidence": 0.2,
        "created_transaction_id": None,
        "review_outcome": "newly_imported",
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _transaction(transaction_id: str, **values):
    defaults = {
        "id": transaction_id,
        "amount": Decimal("100"),
        "transaction_type": TransactionType.DEBIT,
        "payment_rail": PaymentRail.OTHER,
        "card_event": CardEvent.NONE,
        "transaction_status": "completed",
        "transaction_date": date(2026, 9, 10),
        "transaction_timestamp": None,
        "merchant_raw": "UNKNOWN",
        "merchant_normalized": "UNKNOWN",
        "category_id": None,
        "merchant_resolution_source": "parser",
        "merchant_resolution_confidence": 0.1,
        "merchant_rule_id": None,
        "merchant_resolver_version": 1,
        "source_kind": "statement",
        "source_identifier": None,
        "source_email_id": None,
        "source_email": None,
        "financial_account_id": None,
        "is_transfer": False,
        "is_accounting_adjustment": False,
        "ledger_subtype": None,
        "review_outcome": "matched",
        "reviewed_flag": False,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _parsed(**values):
    defaults = {
        "payment_rail": "other",
        "payment_method": "other",
        "card_event": "none",
        "transaction_status": "completed",
        "merchant_raw": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


async def _merchant(*_args, **_kwargs):
    return SimpleNamespace(
        normalized_name="Resolved merchant",
        category_id="category-1",
        confidence=0.9,
        source="coverage",
        rule_id="rule-1",
        resolver_version=2,
    )


async def _no_op(*_args, **_kwargs):
    return None


@pytest.mark.asyncio
async def test_repair_dry_run_covers_classification_and_protected_paths(monkeypatch):
    statement_transaction = _transaction(
        "statement-tx",
        source_kind="statement",
        is_transfer=True,
        merchant_normalized="UNKNOWN",
        merchant_resolution_confidence=0.1,
    )
    newsletter_email = SimpleNamespace(
        gmail_message_id="newsletter-message",
        sender="newsletter@example.com",
        subject="Weekly newsletter",
        body="A weekly digest",
    )
    atm_email = SimpleNamespace(
        gmail_message_id="atm-message",
        sender="bank@example.com",
        subject="ATM withdrawal",
        body="Cash withdrawn",
    )
    false_positive = _transaction(
        "false-positive",
        source_email_id="newsletter-email",
        source_email=newsletter_email,
    )
    atm_transaction = _transaction(
        "atm-tx",
        source_email_id="atm-email",
        source_email=atm_email,
        source_kind="statement",
        source_identifier=None,
        payment_rail=PaymentRail.OTHER,
        transaction_status="completed",
        merchant_raw="UNKNOWN",
        merchant_normalized="UNKNOWN",
        financial_account_id="card-1",
    )
    payment_transaction = _transaction(
        "payment-tx",
        merchant_raw="Credit card bill payment",
        merchant_normalized="Credit card bill payment",
        payment_rail=PaymentRail.OTHER,
    )
    lines = [
        _line(
            "ordinary-line",
            description="COFFEE SHOP",
            line_number=1,
            created_transaction_id="statement-tx",
            merchant_normalized="Unknown",
        ),
        _line(
            "interest-line",
            description="INT NB: 1 123456 (Ref# POST1)",
            line_number=2,
            component_kind="ordinary",
            reference_id="POST1",
            card_event="interest",
        ),
        _line(
            "tax-line",
            description="GST Ref# POST1",
            line_number=3,
            card_event="tax",
            reference_id="POST1",
        ),
        _line(
            "purchase-line",
            description="EMI PURCHASE",
            line_number=4,
            transaction_date=date(2026, 9, 10),
            amount=Decimal("1200"),
        ),
        _line(
            "credit-line",
            description="AGGREGATOR CREDIT",
            line_number=5,
            transaction_date=date(2026, 9, 11),
            amount=Decimal("1200"),
            transaction_type="credit",
        ),
        _line(
            "fee-line",
            description="EMI PROCESSING FEE 123456",
            line_number=6,
            transaction_date=date(2026, 9, 12),
            amount=Decimal("20"),
        ),
        _line(
            "unknown-tax-line",
            description="GST UNKNOWN",
            line_number=7,
            card_event="tax",
            component_kind="emi_tax",
            issuer_plan_reference="9999",
        ),
    ]
    registry = SimpleNamespace(
        parse_email=lambda _sender, _subject, _body: _parsed(
            payment_rail="atm",
            payment_method="other",
            card_event="none",
            transaction_status="pending",
            merchant_raw="123",
        )
    )
    db = _RepairDb(
        scalar_rows=[
            lines,
            [false_positive, atm_transaction],
            [SimpleNamespace(id="card-1", account_type="credit_card")],
            [payment_transaction],
        ],
        scalar_values=[0, None],
        get_values={"statement-tx": statement_transaction},
    )
    monkeypatch.setattr(module, "get_parser_registry", lambda: registry)
    monkeypatch.setattr(module, "resolve_merchant", _merchant)
    monkeypatch.setattr(module, "is_plausible_merchant_descriptor", lambda _value: False)
    monkeypatch.setattr(module, "infer_merchant_from_text", lambda *_args: _merchant_inferred())
    monkeypatch.setattr(
        module,
        "classify_source_record",
        lambda sender, _subject, _body: SimpleNamespace(
            classification=(
                ClassificationType.IGNORE
                if sender == "newsletter@example.com"
                else ClassificationType.TRANSACTION
            ),
            reason=(
                "newsletter sender or content signal"
                if sender == "newsletter@example.com"
                else "transaction"
            ),
        ),
    )
    service = FinancialPositionService(db)
    monkeypatch.setattr(service, "_project_emi_ledger_events", _no_op)
    monkeypatch.setattr(service, "_sync_card_emi_liabilities", _returning(3))

    result = await service.repair_financial_intelligence("user-1", dry_run=True)

    assert result.dry_run is True
    assert result.emi_components_classified >= 4
    assert result.statement_merchants_repaired >= 1
    assert result.false_positive_transactions_removed == 1
    assert result.source_provenance_repaired == 1
    assert result.transaction_semantics_repaired == 1
    assert result.non_spend_payments_classified == 1
    assert result.liabilities_synced == 3
    assert db.commits == 0
    assert false_positive.review_outcome == "matched"
    assert atm_transaction.payment_rail == PaymentRail.OTHER


@pytest.mark.asyncio
async def test_repair_persist_path_snapshots_and_commits(monkeypatch):
    line = _line("persist-line", description="ordinary", line_number=1)
    db = _RepairDb(
        scalar_rows=[[line], [], [], []],
        get_values={},
    )
    snapshots = []
    monkeypatch.setattr(module, "get_parser_registry", lambda: SimpleNamespace())
    monkeypatch.setattr(module, "capture_statement_line_snapshot", _recording(snapshots))
    monkeypatch.setattr(module, "capture_transaction_snapshot", _no_op)
    monkeypatch.setattr(module, "resolve_merchant", _merchant)
    monkeypatch.setattr(
        module,
        "classify_emi_component",
        lambda *_args, **_kwargs: {
            "component_kind": "ordinary",
            "issuer_plan_reference": None,
            "installment_number": None,
        },
    )
    service = FinancialPositionService(db)
    monkeypatch.setattr(service, "_project_emi_ledger_events", _no_op)
    monkeypatch.setattr(service, "_snapshot_transaction_mutations", _no_op)
    monkeypatch.setattr(service, "_sync_card_emi_liabilities", _returning(1))

    result = await service.repair_financial_intelligence("user-1", dry_run=False, commit=True)

    assert result.dry_run is False
    assert result.liabilities_synced == 1
    assert snapshots == [("persist-line", None)]
    assert db.commits == 1


def _returning(value):
    async def return_value(*_args, **_kwargs):
        return value

    return return_value


def _recording(target):
    async def record(_db, line, **kwargs):
        target.append((line.id, kwargs.get("financial_account_id")))

    return record


async def _merchant_inferred():
    return "Inferred merchant", 0.8
