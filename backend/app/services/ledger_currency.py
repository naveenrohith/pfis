"""Single-ledger-currency policy for financially safe aggregation."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.transaction import Transaction
from app.models.user import User


class LedgerCurrencyMismatchError(ValueError):
    """Money cannot be posted because it uses a different ledger currency."""


async def get_ledger_currency(db: AsyncSession, user_id: str) -> str:
    """Return the user's immutable ledger currency."""
    currency = await db.scalar(select(User.currency).where(User.id == user_id))
    if currency is None:
        raise LookupError("User not found")
    return currency


async def require_ledger_currency(
    db: AsyncSession,
    user_id: str,
    currency: str,
    *,
    subject: str,
) -> str:
    """Reject money that would make a user's ledger unsafe to aggregate."""
    ledger_currency = await get_ledger_currency(db, user_id)
    if currency != ledger_currency:
        raise LedgerCurrencyMismatchError(
            f"{subject} currency {currency} does not match ledger currency {ledger_currency}"
        )
    return ledger_currency


async def require_shared_ledger_currency(
    db: AsyncSession,
    user_ids: Iterable[str],
    *,
    subject: str,
) -> str:
    """Require all participants in a shared financial record to use one currency."""
    expected_ids = set(user_ids)
    rows = (await db.execute(select(User.id, User.currency).where(User.id.in_(expected_ids)))).all()
    currencies_by_user: dict[str, str] = {row.id: row.currency for row in rows}
    missing = expected_ids - currencies_by_user.keys()
    if missing:
        raise LookupError("User not found")
    currencies = set(currencies_by_user.values())
    if len(currencies) != 1:
        raise ValueError(f"{subject} requires members with the same ledger currency")
    return currencies.pop()


async def ledger_currency_health(db: AsyncSession) -> dict[str, int | str]:
    """Return non-secret aggregate integrity counts for operational monitoring."""

    async def mismatch_count(model: type[Transaction | FinancialAccount | AccountBalanceSnapshot]):
        return int(
            (
                await db.scalar(
                    select(func.count(model.id))
                    .join(User, User.id == model.user_id)
                    .where(model.currency != User.currency)
                )
            )
            or 0
        )

    transactions = await mismatch_count(Transaction)
    accounts = await mismatch_count(FinancialAccount)
    balances = await mismatch_count(AccountBalanceSnapshot)
    total = transactions + accounts + balances
    return {
        "status": "healthy" if total == 0 else "needs_repair",
        "mismatch_count": total,
        "transaction_mismatches": transactions,
        "account_mismatches": accounts,
        "balance_mismatches": balances,
    }
