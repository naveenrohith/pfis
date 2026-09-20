"""Validation and extractor-boundary coverage for statement imports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.schemas.financial_position import StatementTextImport
from app.services import financial_position_service as module
from app.services.financial_position_service import FinancialPositionService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, *, scalar_values=(), scalar_rows=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()


def _account(**overrides):
    values = {
        "id": "account-1",
        "account_type": "credit_card",
        "balance_kind": "liability",
        "currency": "INR",
        "is_active": True,
        "masked_number": "****1234",
        "institution_name": "HDFC Bank",
        "identity_status": "confirmed",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _data():
    return StatementTextImport(
        financial_account_id="account-1",
        document_fingerprint="f" * 64,
        statement_text="statement text with enough content for import tests",
    )


@pytest.mark.asyncio
async def test_hdfc_and_generic_card_imports_cover_profile_validation(monkeypatch):
    service = FinancialPositionService(_Db())
    monkeypatch.setattr(FinancialPositionService, "_require_account", _returning(_account()))
    monkeypatch.setattr(
        FinancialPositionService, "_existing_credit_card_statement", _returning(None)
    )
    monkeypatch.setattr(FinancialPositionService, "_persist_credit_card_statement", _persist)
    monkeypatch.setattr(module, "is_reviewed_layout", lambda _text: True)
    monkeypatch.setattr(module, "is_legacy_layout", lambda _text: False)
    monkeypatch.setattr(
        module,
        "extract_hdfc_statement",
        lambda _text: {
            "statement_date": date(2026, 9, 1),
            "period_start": date(2026, 8, 1),
            "period_end": date(2026, 8, 31),
            "card_last4": "1234",
            "lines": [],
        },
    )
    assert await service.import_hdfc_statement_text("user-1", _data()) == "persisted-HDFC"

    monkeypatch.setattr(
        module,
        "extract_generic_credit_card_statement",
        lambda _text: {"currency": "INR", "card_last4": "1234", "lines": []},
    )
    assert (
        await service.import_generic_credit_card_statement_text("user-1", _data())
        == "persisted-GENERIC"
    )

    monkeypatch.setattr(
        FinancialPositionService, "_existing_credit_card_statement", _returning("existing")
    )
    assert await service.import_hdfc_statement_text("user-1", _data()) == "existing"
    assert await service.import_generic_credit_card_statement_text("user-1", _data()) == "existing"

    monkeypatch.setattr(
        FinancialPositionService, "_existing_credit_card_statement", _returning(None)
    )
    monkeypatch.setattr(module, "is_reviewed_layout", lambda _text: False)
    monkeypatch.setattr(module, "is_legacy_layout", lambda _text: False)
    with pytest.raises(ValueError, match="supported HDFC"):
        await service.import_hdfc_statement_text("user-1", _data())
    monkeypatch.setattr(module, "is_legacy_layout", lambda _text: True)
    monkeypatch.setattr(
        module,
        "extract_hdfc_statement",
        lambda _text: {
            "statement_date": None,
            "period_start": None,
            "period_end": date(2026, 8, 31),
            "card_last4": "1234",
            "lines": [],
        },
    )
    with pytest.raises(ValueError, match="billing period"):
        await service.import_hdfc_statement_text("user-1", _data())
    monkeypatch.setattr(module, "is_reviewed_layout", lambda _text: True)
    monkeypatch.setattr(
        module,
        "extract_hdfc_statement",
        lambda _text: {
            "statement_date": date(2026, 9, 1),
            "period_start": date(2026, 8, 1),
            "period_end": date(2026, 8, 31),
            "card_last4": None,
            "lines": [],
        },
    )
    with pytest.raises(ValueError, match="masked card"):
        await service.import_hdfc_statement_text("user-1", _data())
    monkeypatch.setattr(
        module,
        "extract_hdfc_statement",
        lambda _text: {
            "statement_date": date(2026, 9, 1),
            "period_start": date(2026, 8, 1),
            "period_end": date(2026, 8, 31),
            "card_last4": "9999",
            "lines": [],
        },
    )
    with pytest.raises(ValueError, match="different credit-card"):
        await service.import_hdfc_statement_text("user-1", _data())

    monkeypatch.setattr(
        module,
        "extract_generic_credit_card_statement",
        lambda _text: {"currency": "USD", "card_last4": "1234", "lines": []},
    )
    with pytest.raises(ValueError, match="currency"):
        await service.import_generic_credit_card_statement_text("user-1", _data())
    monkeypatch.setattr(
        module,
        "extract_generic_credit_card_statement",
        lambda _text: {"currency": "INR", "card_last4": "9999", "lines": []},
    )
    with pytest.raises(ValueError, match="different credit-card"):
        await service.import_generic_credit_card_statement_text("user-1", _data())

    monkeypatch.setattr(
        FinancialPositionService, "_require_account", _returning(_account(account_type="bank"))
    )
    with pytest.raises(ValueError, match="credit-card"):
        await service.import_generic_credit_card_statement_text("user-1", _data())
    monkeypatch.setattr(
        FinancialPositionService, "_require_account", _returning(_account(is_active=False))
    )
    with pytest.raises(ValueError, match="active"):
        await service.import_generic_credit_card_statement_text("user-1", _data())
    monkeypatch.setattr(
        FinancialPositionService, "_require_account", _returning(_account(currency="USD"))
    )
    with pytest.raises(ValueError, match="INR"):
        await service.import_hdfc_statement_text("user-1", _data())


@pytest.mark.asyncio
async def test_deposit_import_validation_and_exact_line_matching(monkeypatch):
    service = FinancialPositionService(_Db())
    bank = _account(account_type="bank", balance_kind="asset", institution_name="HDFC Bank")
    monkeypatch.setattr(FinancialPositionService, "_require_account", _returning(bank))
    monkeypatch.setattr(
        module,
        "extract_hdfc_deposit_statement",
        lambda _text: {"account_last4": "1234", "lines": []},
    )
    monkeypatch.setattr(module, "persist_deposit_statement", _persist_deposit)
    assert await service.import_hdfc_deposit_statement_text("user-1", _data()) == "persisted-HDFC"

    monkeypatch.setattr(
        module,
        "extract_generic_deposit_statement",
        lambda _text: {"currency": "unknown", "account_last4": "1234", "lines": []},
    )
    assert (
        await service.import_generic_deposit_statement_text("user-1", _data())
        == "persisted-GENERIC"
    )

    monkeypatch.setattr(
        module,
        "extract_hdfc_deposit_statement",
        lambda _text: {"account_last4": "9999", "lines": []},
    )
    with pytest.raises(ValueError, match="different bank"):
        await service.import_hdfc_deposit_statement_text("user-1", _data())
    monkeypatch.setattr(
        module,
        "extract_generic_deposit_statement",
        lambda _text: {"currency": "USD", "account_last4": "1234", "lines": []},
    )
    with pytest.raises(ValueError, match="currency"):
        await service.import_generic_deposit_statement_text("user-1", _data())

    for account, message in [
        (_account(account_type="credit_card", balance_kind="liability"), "asset bank"),
        (_account(is_active=False, account_type="bank", balance_kind="asset"), "active"),
        (_account(currency="USD", account_type="bank", balance_kind="asset"), "INR"),
        (
            _account(identity_status="unresolved", account_type="bank", balance_kind="asset"),
            "identity",
        ),
        (_account(institution_name="Axis Bank", account_type="bank", balance_kind="asset"), "HDFC"),
    ]:
        with pytest.raises(ValueError, match=message):
            FinancialPositionService._validate_deposit_account(account, require_hdfc=True)

    line = SimpleNamespace(
        reference_id=None,
        amount=Decimal("10.00"),
        transaction_date=date(2026, 9, 20),
        transaction_type="debit",
    )
    assert await service._match_deposit_statement_line("user-1", "account-1", line) == (None, False)
    line.reference_id = "ref-1"
    one = SimpleNamespace(id="txn-1")
    assert await FinancialPositionService(_Db(scalar_rows=[[one]]))._match_deposit_statement_line(
        "user-1", "account-1", line
    ) == (one, False)
    assert await FinancialPositionService(
        _Db(scalar_rows=[[one, SimpleNamespace(id="txn-2")]])
    )._match_deposit_statement_line("user-1", "account-1", line) == (None, True)


@pytest.mark.asyncio
async def test_deposit_transaction_builder_maps_payment_rails(monkeypatch):
    captured = []

    class _TransactionService:
        def __init__(self, _db):
            pass

        async def create_transaction(self, *_args, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(id="txn-created")

    monkeypatch.setattr(module, "TransactionService", _TransactionService)
    monkeypatch.setattr(module, "resolve_merchant", _merchant)
    account = _account(account_type="bank", balance_kind="asset")
    service = FinancialPositionService(_Db())
    for rail in ("upi", "debit_card", "transfer", "other"):
        line = SimpleNamespace(
            payment_rail=rail,
            amount=Decimal("10.00"),
            transaction_type="debit",
            transaction_date=date(2026, 9, 20),
            description="Merchant",
            reference_id="ref",
        )
        result = await service._create_deposit_statement_transaction(
            "user-1", account, line, account_last4="1234", source_identifier="statement-1"
        )
        assert result.id == "txn-created"
    assert len(captured) == 4


def _returning(value):
    async def returning(self, *_args):
        return value

    return returning


async def _persist(self, _user_id, _data, _account, _extracted, *, issuer, extractor_version):
    del self, _data, _account, _extracted, extractor_version
    return f"persisted-{issuer}"


async def _persist_deposit(
    self, _user_id, _data, _account, _extracted, *, issuer, extractor_version, account_last4
):
    del self, _data, _account, _extracted, extractor_version, account_last4
    return f"persisted-{issuer}"


async def _merchant(*_args, **_kwargs):
    return SimpleNamespace(
        normalized_name="Merchant",
        category_id=None,
        source="test",
        confidence=1.0,
        rule_id=None,
        resolver_version=1,
    )
