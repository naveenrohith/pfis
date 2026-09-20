"""Coverage for single-ledger-currency safety checks."""

from types import SimpleNamespace

import pytest
from app.services.ledger_currency import (
    LedgerCurrencyMismatchError,
    get_ledger_currency,
    ledger_currency_health,
    require_ledger_currency,
    require_shared_ledger_currency,
)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _CurrencyDb:
    def __init__(self, *, scalar_values=(), rows=()):
        self.scalar_values = list(scalar_values)
        self.rows = list(rows)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def execute(self, _statement):
        return _Rows(self.rows)


@pytest.mark.asyncio
async def test_ledger_currency_guards_cover_missing_mismatch_and_health_states():
    with pytest.raises(LookupError, match="User"):
        await get_ledger_currency(_CurrencyDb(scalar_values=[None]), "missing")
    assert await get_ledger_currency(_CurrencyDb(scalar_values=["INR"]), "user-1") == "INR"

    assert (
        await require_ledger_currency(
            _CurrencyDb(scalar_values=["INR"]), "user-1", "INR", subject="Account"
        )
        == "INR"
    )
    with pytest.raises(LedgerCurrencyMismatchError, match="Account currency USD"):
        await require_ledger_currency(
            _CurrencyDb(scalar_values=["INR"]), "user-1", "USD", subject="Account"
        )

    same = await require_shared_ledger_currency(
        _CurrencyDb(rows=[SimpleNamespace(id="user-1", currency="INR")]),
        ["user-1"],
        subject="Household",
    )
    assert same == "INR"
    with pytest.raises(LookupError, match="User"):
        await require_shared_ledger_currency(_CurrencyDb(rows=[]), ["user-1"], subject="Household")
    with pytest.raises(ValueError, match="same ledger currency"):
        await require_shared_ledger_currency(
            _CurrencyDb(
                rows=[
                    SimpleNamespace(id="user-1", currency="INR"),
                    SimpleNamespace(id="user-2", currency="USD"),
                ]
            ),
            ["user-1", "user-2"],
            subject="Household",
        )

    health = await ledger_currency_health(_CurrencyDb(scalar_values=[0, 1, 2]))
    assert health == {
        "status": "needs_repair",
        "mismatch_count": 3,
        "transaction_mismatches": 0,
        "account_mismatches": 1,
        "balance_mismatches": 2,
    }
