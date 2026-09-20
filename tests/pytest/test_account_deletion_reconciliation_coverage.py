"""Direct unit coverage for account deletion and balance reconciliation services."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.sync import ConnectorAuditEvent
from app.models.user import User
from app.services import account_deletion_service, balance_reconciliation_service
from app.services.account_deletion_service import delete_owned_account, has_recent_authentication
from app.services.balance_reconciliation_service import BalanceReconciliationService


class FakeDeletionDb:
    def __init__(self, user: User | None, account=None):
        self.scalar_values = [user, account]
        self.get_value = user
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.executed = []

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def execute(self, statement):
        self.executed.append(statement)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def get(self, _model, _identity):
        return self.get_value

    def add(self, value):
        self.added.append(value)


class FakeScalarResult:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class FakeReconciliationDb:
    def __init__(self, scalar_values, scalars_values):
        self.scalar_values = list(scalar_values)
        self.scalars_values = list(scalars_values)
        self.added = []
        self.flushes = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def scalars(self, _statement):
        return FakeScalarResult(self.scalars_values.pop(0))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1
        for value in self.added:
            value.id = value.id or "reconciliation-created"
            value.created_at = value.created_at or datetime(2026, 9, 3, tzinfo=UTC)


def _user(user_id: str = "user-1") -> User:
    return User(
        id=user_id,
        email="owner@example.test",
        name="Owner",
        password_hash="hashed",
        is_active=True,
        timezone="Asia/Calcutta",
        raw_email_retention_days=90,
        gmail_connection_generation=2,
    )


@pytest.mark.asyncio
async def test_delete_owned_account_tombstones_user_and_records_non_secret_audit(monkeypatch):
    user = _user()
    account = SimpleNamespace(
        id="gmail-1",
        refresh_token_ref="encrypted-refresh",
        access_token_ref=None,
        auto_sync_enabled=True,
        auto_sync_status="idle",
        auto_sync_error="old error",
    )
    db = FakeDeletionDb(user, account)
    calls = []

    async def record(name, *args):
        calls.append((name, args))

    monkeypatch.setattr(
        account_deletion_service, "stop_user_jobs", lambda user_id: record("jobs", user_id)
    )
    monkeypatch.setattr(
        account_deletion_service,
        "stop_auto_sync_for_account",
        lambda account_id: record("auto-sync", account_id),
    )
    monkeypatch.setattr(
        account_deletion_service,
        "stop_user_ingestions",
        lambda user_id: record("ingestions", user_id),
    )
    monkeypatch.setattr(account_deletion_service, "_revoke_gmail", lambda value: _result("revoked"))
    monkeypatch.setattr(
        account_deletion_service,
        "_leave_households",
        lambda *_args: _result(
            {
                "households_deleted": 1,
                "household_ownership_transferred": 0,
                "household_memberships_closed": 1,
            }
        ),
    )
    monkeypatch.setattr(
        account_deletion_service,
        "_delete_private_rows",
        lambda *_args: _result({"transactions": 2, "raw_emails": 1}),
    )

    result = await delete_owned_account(db, user, deleted_at=datetime(2026, 9, 20, 12, tzinfo=UTC))

    assert result["status"] == "deleted"
    assert result["provider_revocation"] == "revoked"
    assert result["private_rows_deleted"] == 3
    assert user.email == "deleted-user-1@deleted.invalid"
    assert user.name == "Deleted participant"
    assert user.password_hash is None
    assert user.is_active is False
    assert user.deleted_at == datetime(2026, 9, 20, 12, tzinfo=UTC)
    assert user.deletion_started_at is None
    assert db.commits == 2
    assert [name for name, _args in calls] == ["jobs", "auto-sync", "ingestions"]
    audit = next(value for value in db.added if isinstance(value, ConnectorAuditEvent))
    payload = json.loads(audit.payload_json)
    assert payload["private_rows_deleted"] == 3
    assert "encrypted-refresh" not in audit.payload_json


@pytest.mark.asyncio
async def test_delete_owned_account_rolls_back_and_clears_deletion_fence_on_failure(monkeypatch):
    user = _user()
    db = FakeDeletionDb(user, None)

    async def fail_jobs(_user_id):
        raise RuntimeError("job shutdown failed")

    monkeypatch.setattr(account_deletion_service, "stop_user_jobs", fail_jobs)

    with pytest.raises(RuntimeError, match="job shutdown failed"):
        await delete_owned_account(db, user, deleted_at=datetime(2026, 9, 20, tzinfo=UTC))

    assert db.rollbacks == 1
    assert db.commits == 2
    assert user.deletion_started_at is None
    assert user.deleted_at is None
    assert user.is_active is True


@pytest.mark.asyncio
async def test_delete_owned_account_rejects_missing_owned_user():
    db = FakeDeletionDb(None)

    with pytest.raises(LookupError, match="User account not found"):
        await delete_owned_account(db, _user("missing"))

    assert db.commits == 0
    assert db.rollbacks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decrypt_value", "provider_result", "expected"),
    [
        ("secret", True, "revoked"),
        ("secret", False, "provider_rejected"),
        ("secret", RuntimeError("offline"), "unconfirmed"),
        (None, True, "token_unavailable"),
    ],
)
async def test_revoke_gmail_classifies_provider_and_credential_outcomes(
    monkeypatch, decrypt_value, provider_result, expected
):
    account = SimpleNamespace(
        refresh_token_ref="refresh-ref",
        access_token_ref="access-ref",
    )

    def decrypt(_value):
        if decrypt_value is None:
            raise ValueError("cannot decrypt")
        return decrypt_value

    async def revoke(_token):
        if isinstance(provider_result, Exception):
            raise provider_result
        return provider_result

    monkeypatch.setattr(account_deletion_service, "decrypt_secret", decrypt)
    monkeypatch.setattr(account_deletion_service, "revoke_google_token", revoke)

    assert await account_deletion_service._revoke_gmail(account) == expected
    assert await account_deletion_service._revoke_gmail(None) == "not_connected"


@pytest.mark.asyncio
async def test_has_recent_authentication_requires_auth_mode_and_recent_timestamp(monkeypatch):
    now = datetime(2026, 9, 20, 12, tzinfo=UTC)
    db = object()

    async def recent_session(_token, _db):
        return _session(mode="auth", created_at=now - timedelta(minutes=14))

    monkeypatch.setattr(account_deletion_service, "get_active_auth_session", recent_session)
    assert await has_recent_authentication(db, "raw-token", now=now) is True

    async def bearer_session(_token, _db):
        return _session(mode="bearer", created_at=now)

    monkeypatch.setattr(account_deletion_service, "get_active_auth_session", bearer_session)
    assert await has_recent_authentication(db, "raw-token", now=now) is False
    assert await has_recent_authentication(db, None, now=now) is False


@pytest.mark.asyncio
async def test_reconciliation_persists_eligible_and_excluded_activity(monkeypatch):
    opening = SimpleNamespace(
        id="opening", amount=Decimal("1000"), as_of=date(2026, 9, 1), effective_at=None
    )
    closing = SimpleNamespace(
        id="closing", amount=Decimal("900"), as_of=date(2026, 9, 3), effective_at=None
    )
    account = SimpleNamespace(currency="INR", balance_kind="asset")
    eligible = SimpleNamespace(id="tx-eligible", transaction_date=date(2026, 9, 2))
    excluded = SimpleNamespace(
        id="tx-pending",
        transaction_date=date(2026, 9, 2),
        transaction_status="pending",
        review_outcome="newly_imported",
        reviewed_flag=False,
        is_accounting_adjustment=False,
    )
    db = FakeReconciliationDb(
        [account, closing, None],
        [[opening, closing], [eligible, excluded]],
    )
    monkeypatch.setattr(
        balance_reconciliation_service,
        "balance_transaction_eligible",
        lambda transaction: transaction.id == "tx-eligible",
    )
    monkeypatch.setattr(
        balance_reconciliation_service,
        "signed_balance_movement",
        lambda _transaction, _kind: Decimal("-100"),
    )

    response = await BalanceReconciliationService(db).ensure_for_closing_snapshot(
        "user-1", "account-1", "closing"
    )

    assert response is not None
    assert response.known_movement == -100.0
    assert response.expected_closing_balance == 900.0
    assert response.residual == 0.0
    assert response.reconciliation_status == "needs_review"
    assert response.eligible_transaction_ids == ["tx-eligible"]
    assert response.excluded_transaction_ids == ["tx-pending"]
    assert response.reason_codes == ["pending_activity_in_interval"]
    assert db.flushes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("account_value, closing_value", [(None, object()), (object(), None)])
async def test_reconciliation_returns_none_for_missing_or_unowned_resources(
    account_value, closing_value
):
    db = FakeReconciliationDb([account_value, closing_value], [])

    assert (
        await BalanceReconciliationService(db).ensure_for_closing_snapshot(
            "wrong-user", "account-1", "closing"
        )
        is None
    )


@pytest.mark.asyncio
async def test_reconciliation_skips_late_and_duplicate_intervals():
    opening = SimpleNamespace(id="opening", as_of=date(2026, 9, 1))
    closing = SimpleNamespace(id="closing", as_of=date(2026, 9, 3))
    later = SimpleNamespace(id="later", as_of=date(2026, 9, 4))
    account = SimpleNamespace(currency="INR", balance_kind="asset")

    late_db = FakeReconciliationDb([account, closing], [[opening, closing, later]])
    assert (
        await BalanceReconciliationService(late_db).ensure_for_closing_snapshot(
            "user-1", "account-1", "closing"
        )
        is None
    )

    existing = SimpleNamespace(
        id="reconciliation-1",
        financial_account_id="account-1",
        opening_snapshot_id="opening",
        closing_snapshot_id="closing",
        currency="INR",
        balance_kind="asset",
        opening_as_of=date(2026, 9, 1),
        closing_as_of=date(2026, 9, 3),
        opening_balance=Decimal("1000"),
        known_movement=Decimal("-100"),
        expected_closing_balance=Decimal("900"),
        observed_closing_balance=Decimal("900"),
        residual=Decimal("0"),
        absolute_residual=Decimal("0"),
        transaction_count=1,
        eligible_transaction_count=1,
        excluded_transaction_count=0,
        eligible_transaction_ids_json='["tx-1"]',
        excluded_transaction_ids_json="[]",
        reason_codes_json="[]",
        reconciliation_status="reconciled",
        ruleset_version="pfis-balance-reconciliation-1",
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
    )
    duplicate_db = FakeReconciliationDb([account, closing, existing], [[opening, closing]])
    response = await BalanceReconciliationService(duplicate_db).ensure_for_closing_snapshot(
        "user-1", "account-1", "closing"
    )
    assert response is not None
    assert response.id == "reconciliation-1"
    assert duplicate_db.added == []


def test_reconciliation_reason_codes_cover_classifications_and_deduplicate():
    def tx(status="settled", outcome="reviewed", reviewed=True, adjustment=False):
        return SimpleNamespace(
            transaction_status=status,
            review_outcome=outcome,
            reviewed_flag=reviewed,
            is_accounting_adjustment=adjustment,
        )

    reasons = BalanceReconciliationService._reason_codes(
        Decimal("1"),
        [
            tx(status="pending"),
            tx(outcome="ignored_by_rule"),
            tx(adjustment=True),
            tx(outcome="needs_review"),
            tx(outcome="reviewed", reviewed=False),
            tx(outcome="reviewed", reviewed=True),
        ],
    )

    assert reasons == [
        "unexplained_balance_movement",
        "pending_activity_in_interval",
        "ignored_activity_in_interval",
        "accounting_adjustment_in_interval",
        "unreviewed_activity_in_interval",
        "unsettled_activity_in_interval",
    ]


def _result(value):
    async def resolved(*_args):
        return value

    return resolved()


def _session(*, mode, created_at):
    return SimpleNamespace(mode=mode, created_at=created_at)
