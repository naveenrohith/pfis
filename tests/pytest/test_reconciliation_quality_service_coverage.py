"""Service-level reconciliation coverage without a database-driver trace gap."""

from datetime import date
from types import SimpleNamespace

import pytest
from app.models.account import FinancialAccount
from app.services.financial_position_service import FinancialPositionService
from app.services.reconciliation_quality_service import ReconciliationQualityService


class _Rows:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return self.rows


class _ReconciliationDb:
    def __init__(self, *, execute_rows, accounts, duplicate_groups):
        self.execute_rows = [list(rows) for rows in execute_rows]
        self.accounts = list(accounts)
        self.duplicate_groups = duplicate_groups

    async def execute(self, _statement):
        return _Rows(self.execute_rows.pop(0))

    async def scalars(self, _statement):
        return _Rows(self.accounts)

    async def scalar(self, _statement):
        return self.duplicate_groups


def _account(account_id: str) -> FinancialAccount:
    return FinancialAccount(
        id=account_id,
        user_id="user-1",
        institution_name="Reconciliation Unit",
        account_type="bank",
        balance_kind="asset",
        masked_number="****2001",
        currency="INR",
        is_active=True,
    )


@pytest.mark.asyncio
async def test_reconciliation_service_reports_blocked_quality_and_all_row_states(monkeypatch):
    accounts = [_account("missing"), _account("reconciled"), _account("review")]
    db = _ReconciliationDb(
        execute_rows=[
            [
                ("ignored_by_rule", False),
                ("matched", False),
                ("newly_imported", False),
                (None, False),
                ("matched", True),
            ],
            [
                ("matched", 2),
                ("ignored", 1),
                ("newly_imported", 1),
                ("needs_review", 1),
                ("unknown_outcome", 1),
                (None, 1),
            ],
        ],
        accounts=accounts,
        duplicate_groups=2,
    )
    positions = {
        "missing": None,
        "reconciled": SimpleNamespace(
            opening_as_of=date(2026, 9, 1),
            balance_as_of=date(2026, 9, 19),
            reconciliation_status="reconciled",
            reconciliation_items=[],
        ),
        "review": SimpleNamespace(
            opening_as_of=date(2026, 9, 1),
            balance_as_of=date(2026, 9, 19),
            reconciliation_status="needs_review",
            reconciliation_items=[
                SimpleNamespace(kind="unexplained_movement"),
                SimpleNamespace(kind="transaction_review"),
            ],
        ),
    }

    async def fake_position(self, user_id, account_id, *, as_of=None):
        assert user_id == "user-1"
        assert as_of is None
        return positions[account_id]

    monkeypatch.setattr(FinancialPositionService, "account_position", fake_position)

    report = await ReconciliationQualityService(db).report("user-1")
    readiness = ReconciliationQualityService.readiness(report)

    assert report.status == "blocked"
    assert report.transaction_total == 5
    assert report.transaction_reviewed == 3
    assert report.transaction_needs_review == 2
    assert report.transaction_ignored == 1
    assert report.statement_line_total == 7
    assert report.statement_lines_matched == 2
    assert report.statement_lines_ignored == 1
    assert report.statement_lines_newly_imported == 1
    assert report.statement_lines_needs_review == 3
    assert report.account_total == 3
    assert report.accounts_with_history == 2
    assert report.accounts_reconciled == 1
    assert report.accounts_needs_review == 1
    assert report.accounts_not_ready == 1
    assert report.unexplained_movements == 1
    assert report.duplicate_candidate_groups == 2
    assert report.unresolved_items == 8
    assert readiness.status == "blocked"
    assert readiness.unexplained_movements == 1


def test_reconciliation_coverage_returns_full_credit_for_empty_evidence():
    assert ReconciliationQualityService._coverage(0, 0) == 100.0
    assert ReconciliationQualityService._coverage(1, 4) == 25.0
