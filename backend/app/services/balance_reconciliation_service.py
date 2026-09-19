"""Immutable balance-observation reconciliation and drift evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.financial_position import AccountBalanceReconciliation
from app.models.transaction import Transaction
from app.schemas.financial_position import BalanceReconciliationResponse
from app.services.transaction_aggregates import (
    balance_transaction_eligible,
    is_pending_transaction_status,
    signed_balance_movement,
)

RULESET_VERSION = "pfis-balance-reconciliation-1"


class BalanceReconciliationService:
    """Persist one explainable result for each forward verified-observation interval."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_for_closing_snapshot(
        self,
        user_id: str,
        account_id: str,
        closing_snapshot_id: str,
    ) -> BalanceReconciliationResponse | None:
        """Create the interval ending at a newly observed verified snapshot.

        The interval is only captured when the closing observation is currently
        the newest verified observation in canonical observation order. Late
        historical observations remain append-only evidence and are not allowed
        to rewrite an already recorded reconciliation interval.
        """

        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.user_id == user_id,
                FinancialAccount.id == account_id,
            )
        )
        closing = await self.db.scalar(
            select(AccountBalanceSnapshot).where(
                AccountBalanceSnapshot.user_id == user_id,
                AccountBalanceSnapshot.financial_account_id == account_id,
                AccountBalanceSnapshot.id == closing_snapshot_id,
                AccountBalanceSnapshot.verified.is_(True),
            )
        )
        if account is None or closing is None:
            return None

        snapshots = list(
            (
                await self.db.scalars(
                    select(AccountBalanceSnapshot)
                    .where(
                        AccountBalanceSnapshot.user_id == user_id,
                        AccountBalanceSnapshot.financial_account_id == account_id,
                        AccountBalanceSnapshot.verified.is_(True),
                    )
                    .order_by(
                        AccountBalanceSnapshot.as_of,
                        AccountBalanceSnapshot.effective_at.asc().nulls_last(),
                        AccountBalanceSnapshot.observed_at,
                        AccountBalanceSnapshot.created_at,
                        AccountBalanceSnapshot.id,
                    )
                )
            ).all()
        )
        closing_index = next(
            (index for index, snapshot in enumerate(snapshots) if snapshot.id == closing.id),
            None,
        )
        if closing_index is None or closing_index == 0 or closing_index != len(snapshots) - 1:
            return None
        opening = snapshots[closing_index - 1]

        existing = await self.db.scalar(
            select(AccountBalanceReconciliation).where(
                AccountBalanceReconciliation.opening_snapshot_id == opening.id,
                AccountBalanceReconciliation.closing_snapshot_id == closing.id,
            )
        )
        if existing is not None:
            return self._response(existing)

        transactions = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.financial_account_id == account_id,
                        Transaction.currency == account.currency,
                    )
                )
            ).all()
        )
        between = [
            transaction
            for transaction in transactions
            if self._transaction_between_snapshots(transaction, opening, closing)
        ]
        eligible = [
            transaction for transaction in between if balance_transaction_eligible(transaction)
        ]
        excluded = [transaction for transaction in between if transaction not in eligible]
        known_movement = sum(
            (
                signed_balance_movement(transaction, account.balance_kind)
                for transaction in eligible
            ),
            Decimal("0"),
        )
        expected_closing = opening.amount + known_movement
        residual = closing.amount - expected_closing
        reason_codes = self._reason_codes(residual, excluded)
        row = AccountBalanceReconciliation(
            user_id=user_id,
            financial_account_id=account_id,
            opening_snapshot_id=opening.id,
            closing_snapshot_id=closing.id,
            currency=account.currency,
            balance_kind=account.balance_kind,
            opening_as_of=opening.as_of,
            closing_as_of=closing.as_of,
            opening_balance=opening.amount,
            known_movement=known_movement,
            expected_closing_balance=expected_closing,
            observed_closing_balance=closing.amount,
            residual=residual,
            absolute_residual=abs(residual),
            transaction_count=len(between),
            eligible_transaction_count=len(eligible),
            excluded_transaction_count=len(excluded),
            eligible_transaction_ids_json=json.dumps(
                sorted(transaction.id for transaction in eligible), separators=(",", ":")
            ),
            excluded_transaction_ids_json=json.dumps(
                sorted(transaction.id for transaction in excluded), separators=(",", ":")
            ),
            reason_codes_json=json.dumps(reason_codes, separators=(",", ":")),
            reconciliation_status="needs_review" if reason_codes else "reconciled",
            ruleset_version=RULESET_VERSION,
        )
        self.db.add(row)
        await self.db.flush()
        return self._response(row)

    async def list_for_account(
        self,
        user_id: str,
        account_id: str,
    ) -> list[BalanceReconciliationResponse] | None:
        """Return immutable reconciliation intervals for one owned account."""

        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.user_id == user_id,
                FinancialAccount.id == account_id,
            )
        )
        if account is None:
            return None
        rows = list(
            (
                await self.db.scalars(
                    select(AccountBalanceReconciliation)
                    .where(
                        AccountBalanceReconciliation.user_id == user_id,
                        AccountBalanceReconciliation.financial_account_id == account_id,
                    )
                    .order_by(
                        AccountBalanceReconciliation.closing_as_of.desc(),
                        AccountBalanceReconciliation.created_at.desc(),
                    )
                )
            ).all()
        )
        return [self._response(row) for row in rows]

    @staticmethod
    def _reason_codes(
        residual: Decimal,
        excluded: list[Transaction],
    ) -> list[str]:
        reason_codes: list[str] = []
        if residual != Decimal("0"):
            reason_codes.append("unexplained_balance_movement")
        for transaction in excluded:
            if is_pending_transaction_status(transaction.transaction_status):
                reason_codes.append("pending_activity_in_interval")
            elif transaction.review_outcome == "ignored_by_rule":
                reason_codes.append("ignored_activity_in_interval")
            elif transaction.is_accounting_adjustment:
                reason_codes.append("accounting_adjustment_in_interval")
            elif transaction.review_outcome == "needs_review" or not transaction.reviewed_flag:
                reason_codes.append("unreviewed_activity_in_interval")
            else:
                reason_codes.append("unsettled_activity_in_interval")
        return list(dict.fromkeys(reason_codes))

    @classmethod
    def _transaction_between_snapshots(
        cls,
        transaction: Transaction,
        opening: AccountBalanceSnapshot,
        closing: AccountBalanceSnapshot,
    ) -> bool:
        if not cls._transaction_after_snapshot(transaction, opening):
            return False
        if closing.effective_at is None:
            return transaction.transaction_date <= closing.as_of
        if transaction.transaction_timestamp is None:
            return transaction.transaction_date < closing.as_of
        transaction_at = cls._as_utc(transaction.transaction_timestamp)
        closing_at = cls._as_utc(closing.effective_at)
        return transaction_at <= closing_at

    @classmethod
    def _transaction_after_snapshot(
        cls,
        transaction: Transaction,
        snapshot: AccountBalanceSnapshot,
    ) -> bool:
        if snapshot.effective_at is not None and transaction.transaction_timestamp is not None:
            return cls._as_utc(transaction.transaction_timestamp) > cls._as_utc(
                snapshot.effective_at
            )
        return transaction.transaction_date > snapshot.as_of

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _json_list(value: str) -> list[str]:
        try:
            parsed = json.loads(value or "[]")
        except json.JSONDecodeError:
            return []
        return (
            [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []
        )

    @classmethod
    def _response(cls, row: AccountBalanceReconciliation) -> BalanceReconciliationResponse:
        return BalanceReconciliationResponse(
            id=row.id,
            financial_account_id=row.financial_account_id,
            opening_snapshot_id=row.opening_snapshot_id,
            closing_snapshot_id=row.closing_snapshot_id,
            currency=row.currency,
            balance_kind=cast(Literal["asset", "liability"], row.balance_kind),
            opening_as_of=row.opening_as_of,
            closing_as_of=row.closing_as_of,
            opening_balance=float(row.opening_balance),
            known_movement=float(row.known_movement),
            expected_closing_balance=float(row.expected_closing_balance),
            observed_closing_balance=float(row.observed_closing_balance),
            residual=float(row.residual),
            absolute_residual=float(row.absolute_residual),
            transaction_count=row.transaction_count,
            eligible_transaction_count=row.eligible_transaction_count,
            excluded_transaction_count=row.excluded_transaction_count,
            eligible_transaction_ids=cls._json_list(row.eligible_transaction_ids_json),
            excluded_transaction_ids=cls._json_list(row.excluded_transaction_ids_json),
            reason_codes=cls._json_list(row.reason_codes_json),
            reconciliation_status=cast(
                Literal["reconciled", "needs_review"], row.reconciliation_status
            ),
            ruleset_version=row.ruleset_version,
            created_at=row.created_at,
        )
