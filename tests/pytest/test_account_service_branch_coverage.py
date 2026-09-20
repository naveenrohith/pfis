"""Additional deterministic coverage for account identity and lifecycle paths."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.account import FinancialAccount
from app.schemas.account import FinancialAccountCreate
from app.services import account_service as account_module
from app.services.account_service import AccountService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _DB:
    def __init__(self, *, scalar_values=(), scalar_rows=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = f"generated-{len(self.added)}"
            if hasattr(row, "created_at") and row.created_at is None:
                row.created_at = datetime(2026, 9, 20, tzinfo=UTC)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        return None


def _account(account_id="account-1", *, account_type="bank", balance_kind="asset"):
    return FinancialAccount(
        id=account_id,
        user_id="u1",
        institution_name="Coverage Bank",
        account_type=account_type,
        balance_kind=balance_kind,
        masked_number="****1234",
        currency="INR",
        is_active=True,
        identity_status="confirmed",
        identity_confidence=Decimal("1.000"),
        identity_evidence_json="[]",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 20, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_create_account_enforces_kind_duplicate_and_legacy_reuse(monkeypatch):
    async def currency(_db, _user_id, _value, *, subject):
        assert subject == "Account"

    async def snapshot(_db, _account):
        return None

    async def response(self, account):
        return SimpleNamespace(id=account.id, account_type=account.account_type)

    monkeypatch.setattr(account_module, "require_ledger_currency", currency)
    monkeypatch.setattr(account_module, "capture_financial_account_snapshot", snapshot)
    monkeypatch.setattr(AccountService, "_account_response", response)

    service = AccountService(_DB(scalar_values=[None], scalar_rows=[[]]))
    created = await service.create_account(
        "u1",
        FinancialAccountCreate(
            institution_name="New Bank",
            account_type="bank",
            masked_number="****1234",
            currency="INR",
        ),
    )
    assert created.account_type == "bank"
    assert service.db.commits == 1

    with pytest.raises(ValueError, match="must be recorded as assets"):
        await AccountService(_DB()).create_account(
            "u1",
            FinancialAccountCreate(
                institution_name="Wrong",
                account_type="bank",
                balance_kind="liability",
                masked_number="****1234",
            ),
        )

    duplicate = AccountService(_DB(scalar_values=["existing"]))
    with pytest.raises(ValueError, match="already exists"):
        await duplicate.create_account(
            "u1",
            FinancialAccountCreate(
                institution_name="Duplicate",
                account_type="bank",
                masked_number="****1234",
            ),
        )

    legacy = _account("legacy", account_type="unknown")
    legacy.institution_name = "Unknown"
    reused = AccountService(_DB(scalar_values=[None], scalar_rows=[[legacy]]))
    response = await reused.create_account(
        "u1",
        FinancialAccountCreate(
            institution_name="Reidentified Bank",
            account_type="bank",
            masked_number="****1234",
        ),
    )
    assert response.id == "legacy"
    assert legacy.account_type == "bank"
    assert legacy.identity_status == "confirmed"


@pytest.mark.asyncio
async def test_identity_history_handles_empty_invalid_and_valid_snapshots(monkeypatch):
    account = _account()

    async def owned(self, user_id, account_id):
        return account if account_id == account.id else None

    monkeypatch.setattr(AccountService, "_owned_account", owned)
    empty = AccountService(_DB(scalar_rows=[[]]))
    fallback = await empty.identity_history("u1", account.id)
    assert len(fallback) == 1
    assert fallback[0].financial_account_id == account.id

    captured_at = datetime(2026, 9, 19, tzinfo=UTC)
    rows = [
        SimpleNamespace(
            captured_at=captured_at,
            payload_json=json.dumps(
                {
                    "effective_date": "2026-09-18",
                    "institution_name": "Captured Bank",
                    "identity_evidence": [
                        {
                            "source_type": "manual",
                            "source_id": "one",
                            "role": "creation",
                            "note": "confirmed",
                            "observed_at": captured_at.isoformat(),
                        }
                    ],
                }
            ),
        ),
        SimpleNamespace(captured_at=captured_at, payload_json="not-json"),
        SimpleNamespace(captured_at=captured_at, payload_json=json.dumps(["not-an-object"])),
        SimpleNamespace(
            captured_at=captured_at, payload_json=json.dumps({"effective_date": "invalid"})
        ),
    ]
    history = await AccountService(_DB(scalar_rows=[rows])).identity_history("u1", account.id)
    assert len(history) == 2
    assert history[0].institution_name == "Captured Bank"
    assert history[0].effective_date == date(2026, 9, 18)
    assert history[1].effective_date == captured_at.date()

    missing = await AccountService(_DB(scalar_rows=[[]])).identity_history("u1", "missing")
    assert missing is None
