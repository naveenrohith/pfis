"""Aggregate cross-source reconciliation evidence for a single workspace."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import StatementLine
from app.models.transaction import Transaction
from app.schemas.operational import (
    IntelligenceReadinessStatus,
    ReconciliationQualityResponse,
    ReconciliationReadiness,
)
from app.services.financial_position_service import FinancialPositionService


class ReconciliationQualityService:
    """Turn row-level review and balance evidence into a bounded quality report."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def report(self, user_id: str) -> ReconciliationQualityResponse:
        transaction_counts = await self._transaction_counts(user_id)
        statement_counts = await self._statement_counts(user_id)
        account_counts = await self._account_counts(user_id)
        duplicate_groups = await self._duplicate_candidate_groups(user_id)

        transaction_total = transaction_counts["total"]
        transaction_reviewed = transaction_counts["reviewed"]
        transaction_needs_review = transaction_counts["needs_review"]
        transaction_coverage = self._coverage(transaction_reviewed, transaction_total)

        statement_total = statement_counts["total"]
        statement_resolved = statement_counts["matched"] + statement_counts["ignored"]
        statement_coverage = self._coverage(statement_resolved, statement_total)

        accounts_with_history = account_counts["with_history"]
        accounts_reconciled = account_counts["reconciled"]
        account_coverage = self._coverage(accounts_reconciled, accounts_with_history)
        if account_counts["total"] and not accounts_with_history:
            account_coverage = 0.0

        unexplained_movements = account_counts["unexplained"]
        unresolved_items = (
            transaction_needs_review
            + statement_counts["needs_review"]
            + account_counts["needs_review"]
            + statement_counts["newly_imported"]
            + unexplained_movements
        )

        integrity_score = 100.0
        if duplicate_groups:
            integrity_score -= min(60.0, duplicate_groups * 10.0)
        if unexplained_movements:
            integrity_score -= min(60.0, unexplained_movements * 20.0)
        evidence_score = round(
            transaction_coverage * 0.4
            + statement_coverage * 0.25
            + account_coverage * 0.25
            + max(integrity_score, 0.0) * 0.1
        )

        if unexplained_movements:
            status: IntelligenceReadinessStatus = "blocked"
        elif unresolved_items or not transaction_total and not account_counts["total"]:
            status = "collecting"
        else:
            status = "ready"

        return ReconciliationQualityResponse(
            as_of=datetime.now(UTC),
            status=status,
            evidence_score=max(0, min(100, evidence_score)),
            transaction_total=transaction_total,
            transaction_reviewed=transaction_reviewed,
            transaction_needs_review=transaction_needs_review,
            transaction_ignored=transaction_counts["ignored"],
            transaction_review_coverage_pct=transaction_coverage,
            account_total=account_counts["total"],
            accounts_with_history=accounts_with_history,
            accounts_reconciled=accounts_reconciled,
            accounts_needs_review=account_counts["needs_review"],
            accounts_not_ready=account_counts["not_ready"],
            account_reconciliation_coverage_pct=account_coverage,
            statement_line_total=statement_total,
            statement_lines_matched=statement_counts["matched"],
            statement_lines_newly_imported=statement_counts["newly_imported"],
            statement_lines_ignored=statement_counts["ignored"],
            statement_lines_needs_review=statement_counts["needs_review"],
            statement_resolution_coverage_pct=statement_coverage,
            duplicate_candidate_groups=duplicate_groups,
            unexplained_movements=unexplained_movements,
            unresolved_items=unresolved_items,
            evidence=[
                f"Transactions resolved: {transaction_reviewed}/{transaction_total}",
                f"Statement lines resolved: {statement_resolved}/{statement_total}",
                f"Accounts reconciled after history: {accounts_reconciled}/{accounts_with_history}",
                f"Duplicate candidate groups: {duplicate_groups}",
            ],
            limitations=[
                "Review coverage describes rows PFIS has observed; it cannot prove a provider feed is complete.",
                "Newly imported statement lines remain unresolved until matched, imported, or explicitly ignored.",
                "Duplicate candidates and unexplained balance movements require user adjudication; neither is treated as fraud evidence.",
                "Account reconciliation requires two verified balance observations and excludes accounting adjustments from known movement.",
            ],
        )

    async def _transaction_counts(self, user_id: str) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(Transaction.review_outcome, Transaction.reviewed_flag).where(
                    Transaction.user_id == user_id
                )
            )
        ).all()
        counts = {"total": len(rows), "reviewed": 0, "needs_review": 0, "ignored": 0}
        for outcome, reviewed_flag in rows:
            outcome_value = str(outcome or "")
            if outcome_value == "ignored_by_rule":
                counts["ignored"] += 1
            resolved = bool(reviewed_flag) or outcome_value in {"matched", "ignored_by_rule"}
            if resolved:
                counts["reviewed"] += 1
            else:
                counts["needs_review"] += 1
        return counts

    async def _statement_counts(self, user_id: str) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(StatementLine.review_outcome, func.count(StatementLine.id))
                .where(StatementLine.user_id == user_id)
                .group_by(StatementLine.review_outcome)
            )
        ).all()
        counts = {"total": 0, "matched": 0, "newly_imported": 0, "ignored": 0, "needs_review": 0}
        for outcome, count in rows:
            key = str(outcome or "needs_review")
            if key not in counts or key == "total":
                key = "needs_review"
            value = int(count or 0)
            counts[key] += value
            counts["total"] += value
        return counts

    async def _account_counts(self, user_id: str) -> dict[str, int]:
        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount)
                    .where(
                        FinancialAccount.user_id == user_id, FinancialAccount.is_active.is_(True)
                    )
                    .order_by(FinancialAccount.created_at)
                )
            ).all()
        )
        counts = {
            "total": len(accounts),
            "with_history": 0,
            "reconciled": 0,
            "needs_review": 0,
            "not_ready": 0,
            "unexplained": 0,
        }
        service = FinancialPositionService(self.db)
        for account in accounts:
            position = await service.account_position(user_id, account.id)
            if position is None:
                counts["not_ready"] += 1
                continue
            if position.opening_as_of is not None and position.balance_as_of is not None:
                counts["with_history"] += 1
            if position.reconciliation_status == "reconciled":
                counts["reconciled"] += 1
            elif position.reconciliation_status == "needs_review":
                counts["needs_review"] += 1
                counts["unexplained"] += sum(
                    1
                    for item in position.reconciliation_items
                    if item.kind == "unexplained_movement"
                )
            else:
                counts["not_ready"] += 1
        return counts

    async def _duplicate_candidate_groups(self, user_id: str) -> int:
        merchant = func.coalesce(Transaction.merchant_normalized, Transaction.merchant_raw, "")
        grouped = (
            select(
                Transaction.financial_account_id,
                Transaction.transaction_date,
                Transaction.amount,
                Transaction.transaction_type,
                merchant.label("merchant"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.review_outcome != "ignored_by_rule",
                Transaction.is_accounting_adjustment.is_(False),
            )
            .group_by(
                Transaction.financial_account_id,
                Transaction.transaction_date,
                Transaction.amount,
                Transaction.transaction_type,
                merchant,
            )
            .having(func.count(Transaction.id) > 1)
            .subquery()
        )
        return int((await self.db.scalar(select(func.count()).select_from(grouped))) or 0)

    @staticmethod
    def _coverage(resolved: int, total: int) -> float:
        return round(resolved / total * 100.0, 2) if total else 100.0

    @staticmethod
    def readiness(report: ReconciliationQualityResponse) -> ReconciliationReadiness:
        return ReconciliationReadiness(
            status=report.status,
            evidence_score=report.evidence_score,
            transaction_review_coverage_pct=report.transaction_review_coverage_pct,
            statement_resolution_coverage_pct=report.statement_resolution_coverage_pct,
            account_reconciliation_coverage_pct=report.account_reconciliation_coverage_pct,
            unresolved_items=report.unresolved_items,
            duplicate_candidate_groups=report.duplicate_candidate_groups,
            unexplained_movements=report.unexplained_movements,
        )
