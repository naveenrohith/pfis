"""Explainable historical and current-cycle credit-card utilization evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import CardPreference, CreditCardStatement
from app.models.transaction import Transaction
from app.schemas.financial_position import (
    CardUtilizationHistoryPoint,
    CardUtilizationHistoryResponse,
)
from app.services.financial_clock import user_financial_today
from app.services.transaction_aggregates import (
    balance_transaction_eligible,
    is_pending_transaction_status,
    signed_balance_movement,
)

RULESET_VERSION = "pfis-card-utilization-history-1"
TREND_DELTA_THRESHOLD_PCT = Decimal("2.0")
_PERCENT = Decimal("100")

UtilizationStatus = Literal[
    "within_target",
    "within_limit",
    "over_target",
    "over_limit",
    "unavailable",
]


class CardUtilizationHistoryService:
    """Build a bounded utilization history without synthesizing issuer facts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def history(
        self,
        user_id: str,
        account_id: str,
        *,
        statement_limit: int = 12,
        daily_limit: int = 60,
    ) -> CardUtilizationHistoryResponse:
        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
        if account is None:
            raise LookupError("Financial account not found")
        if account.account_type != "credit_card":
            raise ValueError("This action requires a credit-card account")

        as_of = await user_financial_today(self.db, user_id)
        preference = await self.db.scalar(
            select(CardPreference).where(
                CardPreference.user_id == user_id,
                CardPreference.financial_account_id == account_id,
            )
        )
        target = preference.utilization_target_pct if preference is not None else None
        statements_desc = list(
            (
                await self.db.scalars(
                    select(CreditCardStatement)
                    .where(
                        CreditCardStatement.user_id == user_id,
                        CreditCardStatement.financial_account_id == account_id,
                        CreditCardStatement.statement_date <= as_of,
                    )
                    .order_by(CreditCardStatement.statement_date.desc())
                    .limit(statement_limit)
                )
            ).all()
        )
        statements = list(reversed(statements_desc))
        statement_points = [
            self._point(
                as_of=statement.statement_date,
                basis="issuer_statement",
                statement_id=statement.id,
                balance=statement.total_due,
                credit_limit=statement.credit_limit,
                target=target,
                source_transaction_count=0,
                confidence=1.0,
                reason_codes=[
                    "issuer_statement_total_due"
                    if statement.total_due is not None
                    else "statement_total_due_missing",
                    "issuer_statement_credit_limit"
                    if statement.credit_limit is not None and statement.credit_limit > 0
                    else "statement_credit_limit_missing",
                ],
            )
            for statement in statements
        ]

        daily_points: list[CardUtilizationHistoryPoint] = []
        daily_reason_codes: set[str] = set()
        latest = statements[-1] if statements else None
        if (
            latest is not None
            and latest.total_due is not None
            and as_of > latest.statement_date
        ):
            daily_points, daily_reason_codes = await self._daily_points(
                user_id,
                account_id,
                latest,
                as_of=as_of,
                target=target,
                daily_limit=daily_limit,
            )

        trend, trend_basis, trend_delta = self._trend(statement_points, daily_points)
        statement_utilizations = [
            point.utilization_pct
            for point in statement_points
            if point.utilization_pct is not None
        ]
        daily_utilizations = [
            point.utilization_pct for point in daily_points if point.utilization_pct is not None
        ]
        reason_codes: list[str] = []
        if not statements:
            reason_codes.append("no_statement_utilization_evidence")
        elif len(statement_utilizations) < 2:
            reason_codes.append("insufficient_statement_history")
        if target is None:
            reason_codes.append("utilization_target_not_configured")
        if daily_points:
            reason_codes.append("current_cycle_ledger_estimate_available")
        reason_codes.extend(sorted(daily_reason_codes))
        if not statement_points and not daily_points:
            trend = "unavailable"
            trend_basis = "unavailable"

        all_points = [*statement_points, *daily_points]
        return CardUtilizationHistoryResponse(
            financial_account_id=account_id,
            as_of=as_of,
            utilization_target_pct=(float(target) if target is not None else None),
            statement_points=statement_points,
            daily_points=daily_points,
            trend=trend,
            trend_basis=trend_basis,
            trend_delta_pct=trend_delta,
            peak_statement_utilization_pct=(
                max(statement_utilizations) if statement_utilizations else None
            ),
            peak_daily_utilization_pct=max(daily_utilizations) if daily_utilizations else None,
            target_breach_count=sum(point.status == "over_target" for point in all_points),
            credit_limit_breach_count=sum(point.status == "over_limit" for point in all_points),
            reason_codes=list(dict.fromkeys(reason_codes)),
            assumptions=[
                "Statement points use issuer-stated total due and credit limit values only.",
                "Daily points roll settled ledger movement forward from the latest statement anchor; they are estimates, not issuer current-outstanding values.",
                "Pending, failed, ignored, and unsupported activity is not added to the settled daily roll-forward.",
                "A utilization target is a user preference and does not change issuer credit-limit truth.",
            ],
            ruleset_version=RULESET_VERSION,
        )

    async def _daily_points(
        self,
        user_id: str,
        account_id: str,
        statement: CreditCardStatement,
        *,
        as_of: date,
        target: Decimal | None,
        daily_limit: int,
    ) -> tuple[list[CardUtilizationHistoryPoint], set[str]]:
        transactions = list(
            (
                await self.db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.user_id == user_id,
                        Transaction.financial_account_id == account_id,
                        Transaction.currency == statement.currency,
                        Transaction.transaction_date > statement.statement_date,
                        Transaction.transaction_date <= as_of,
                    )
                    .order_by(Transaction.transaction_date, Transaction.created_at, Transaction.id)
                )
            ).all()
        )
        start = max(
            statement.statement_date + timedelta(days=1),
            as_of - timedelta(days=daily_limit - 1),
        )
        daily_rows: dict[date, list[Transaction]] = defaultdict(list)
        for transaction in transactions:
            daily_rows[transaction.transaction_date].append(transaction)

        balance = statement.total_due or Decimal("0")
        for transaction in transactions:
            if transaction.transaction_date < start and balance_transaction_eligible(transaction):
                balance += signed_balance_movement(transaction, "liability")

        points: list[CardUtilizationHistoryPoint] = []
        reason_codes: set[str] = set()
        for offset in range((as_of - start).days + 1):
            point_date = start + timedelta(days=offset)
            rows = daily_rows.get(point_date, [])
            eligible_rows = [row for row in rows if balance_transaction_eligible(row)]
            for transaction in eligible_rows:
                balance += signed_balance_movement(transaction, "liability")
            pending_rows = [row for row in rows if is_pending_transaction_status(row.transaction_status)]
            unreviewed_rows = [
                row
                for row in eligible_rows
                if row.review_outcome == "needs_review" or not row.reviewed_flag
            ]
            point_reasons = ["ledger_rollforward_from_statement"]
            if eligible_rows:
                point_reasons.append("settled_activity_included")
            else:
                point_reasons.append("no_settled_activity")
            if pending_rows:
                point_reasons.append("pending_activity_excluded")
                reason_codes.add("pending_activity_excluded")
            if unreviewed_rows:
                point_reasons.append("unreviewed_activity_included")
                reason_codes.add("unreviewed_activity_included")
            if balance < 0:
                balance = Decimal("0")
                point_reasons.append("balance_floor_applied")
                reason_codes.add("balance_floor_applied")
            confidence = Decimal("0.82")
            if unreviewed_rows:
                confidence -= Decimal("0.18")
            if pending_rows:
                confidence -= Decimal("0.08")
            points.append(
                self._point(
                    as_of=point_date,
                    basis="ledger_estimate",
                    statement_id=statement.id,
                    balance=balance,
                    credit_limit=statement.credit_limit,
                    target=target,
                    source_transaction_count=len(eligible_rows),
                    confidence=float(max(confidence, Decimal("0"))),
                    reason_codes=point_reasons,
                )
            )
        return points, reason_codes

    @classmethod
    def _point(
        cls,
        *,
        as_of: date,
        basis: Literal["issuer_statement", "ledger_estimate"],
        statement_id: str,
        balance: Decimal | None,
        credit_limit: Decimal | None,
        target: Decimal | None,
        source_transaction_count: int,
        confidence: float,
        reason_codes: list[str],
    ) -> CardUtilizationHistoryPoint:
        utilization: Decimal | None = None
        status: UtilizationStatus = "unavailable"
        if balance is not None and credit_limit is not None and credit_limit > 0:
            utilization = balance / credit_limit * _PERCENT
            if balance >= credit_limit:
                status = "over_limit"
            elif target is not None and utilization >= target:
                status = "over_target"
            elif target is not None:
                status = "within_target"
            else:
                status = "within_limit"
        return CardUtilizationHistoryPoint(
            as_of=as_of,
            basis=basis,
            statement_id=statement_id,
            balance=float(balance) if balance is not None else None,
            credit_limit=float(credit_limit) if credit_limit is not None else None,
            utilization_pct=float(utilization) if utilization is not None else None,
            status=status,
            source_transaction_count=source_transaction_count,
            confidence=confidence,
            reason_codes=reason_codes,
        )

    @classmethod
    def _trend(
        cls,
        statement_points: list[CardUtilizationHistoryPoint],
        daily_points: list[CardUtilizationHistoryPoint],
    ) -> tuple[
        Literal["improving", "worsening", "stable", "insufficient_history", "unavailable"],
        Literal["issuer_statements", "issuer_to_current_estimate", "unavailable"],
        float | None,
    ]:
        statement_values = [
            point.utilization_pct
            for point in statement_points
            if point.utilization_pct is not None
        ]
        if not statement_values:
            return "unavailable", "unavailable", None
        if daily_points and daily_points[-1].utilization_pct is not None:
            delta = Decimal(str(daily_points[-1].utilization_pct)) - Decimal(
                str(statement_values[0])
            )
            basis: Literal["issuer_to_current_estimate", "issuer_statements"] = (
                "issuer_to_current_estimate"
            )
        elif len(statement_values) >= 2:
            delta = Decimal(str(statement_values[-1])) - Decimal(str(statement_values[0]))
            basis = "issuer_statements"
        else:
            return "insufficient_history", "issuer_statements", None
        if delta >= TREND_DELTA_THRESHOLD_PCT:
            trend: Literal["improving", "worsening", "stable"] = "worsening"
        elif delta <= -TREND_DELTA_THRESHOLD_PCT:
            trend = "improving"
        else:
            trend = "stable"
        return trend, basis, round(float(delta), 2)
