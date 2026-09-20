"""Deterministic coverage for durable job orchestration branches."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.models.sync import JobStatus
from app.services import job_service as module
from google.auth.exceptions import RefreshError
from sqlalchemy.exc import IntegrityError


class _Result:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar_value = scalar
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.scalar_value

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, *, scalar_values=(), execute_values=(), commit_errors=()):
        self.scalar_values = list(scalar_values)
        self.execute_values = list(execute_values)
        self.commit_errors = list(commit_errors)
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def execute(self, _statement):
        return self.execute_values.pop(0) if self.execute_values else _Result()

    async def scalars(self, _statement):
        result = self.execute_values.pop(0) if self.execute_values else _Result()
        return result

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1
        if self.commit_errors:
            error = self.commit_errors.pop(0)
            if error is not None:
                raise error

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, item):
        if getattr(item, "id", None) is None:
            item.id = "generated-job"
        if getattr(item, "created_at", None) is None:
            item.created_at = datetime(2026, 9, 20, tzinfo=UTC)


def _job(**overrides):
    values = {
        "id": "job-1",
        "user_id": "user-1",
        "job_type": "demo_sync_pipeline",
        "status": JobStatus.RUNNING,
        "payload_json": "{}",
        "result_json": "{}",
        "error_message": None,
        "attempt_count": 1,
        "max_attempts": 3,
        "created_at": datetime(2026, 9, 20, tzinfo=UTC),
        "started_at": None,
        "finished_at": None,
        "available_at": None,
        "lease_owner": "worker",
        "lease_expires_at": datetime(2026, 9, 20, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_job_persistence_and_recovery_cover_idempotency_and_attempt_exhaustion():
    existing = _job(status=JobStatus.QUEUED)
    reused = await module.create_job(
        _Db(scalar_values=[existing]),
        "demo_sync_pipeline",
        "user-1",
        {"limit": 2},
        idempotency_key="same",
    )
    assert reused is existing

    created_db = _Db()
    created = await module.create_job(created_db, "demo_sync_pipeline", "user-1", {"limit": 2})
    assert created.id == "generated-job"
    assert created_db.commits == 1
    assert json.loads(created.payload_json) == {"limit": 2}

    conflict_db = _Db(
        scalar_values=[None, existing],
        commit_errors=[IntegrityError("duplicate", {}, Exception("duplicate"))],
    )
    assert (
        await module.create_job(conflict_db, "demo_sync_pipeline", "user-1", idempotency_key="same")
        is existing
    )
    assert conflict_db.rollbacks == 1

    running = _job(attempt_count=1, max_attempts=3)
    exhausted = _job(id="job-2", attempt_count=3, max_attempts=3)
    recovery_db = _Db(execute_values=[_Result(rows=[running, exhausted])])
    assert await module.recover_interrupted_jobs(recovery_db) == 2
    assert running.status == JobStatus.QUEUED
    assert exhausted.status == JobStatus.FAILED
    assert json.loads(exhausted.result_json)["error_type"] == "attempts_exhausted"

    future = datetime.now(UTC) + timedelta(minutes=1)
    recoverable = _job(id="job-3", attempt_count=1, max_attempts=3, lease_expires_at=future)
    expired = _job(id="job-4", attempt_count=3, max_attempts=3, lease_expires_at=future)
    expired_db = _Db(execute_values=[_Result(rows=[recoverable, expired])])
    assert (
        await module._recover_expired_leases(expired_db, datetime.now(UTC) + timedelta(minutes=2))
        == 2
    )
    assert recoverable.status == JobStatus.QUEUED
    assert expired.status == JobStatus.FAILED
    assert expired_db.commits == 1


@pytest.mark.asyncio
async def test_job_handlers_cover_sync_retention_and_balance_provider_outcomes(monkeypatch):
    async def demo_sync(_db, _user_id):
        return {"emails_stored": 2}

    async def process(_db, _user_id, *, limit):
        return {"stored": limit}

    monkeypatch.setattr(module, "demo_sync_gmail_emails", demo_sync)
    monkeypatch.setattr(module, "process_raw_emails", process)
    assert await module._handle_demo_sync_pipeline(_Db(), "user-1", {"limit": 7}) == {
        "sync": {"emails_stored": 2},
        "pipeline": {"stored": 7},
    }

    async def retry(_db, _user_id, *, limit):
        return {"retried": limit}

    async def redact(_db, *, user_id, batch_size):
        return {"redacted": (user_id, batch_size)}

    monkeypatch.setattr(module, "retry_parse_failures", retry)
    monkeypatch.setattr(module, "redact_expired_raw_email_content", redact)
    assert await module._handle_retry_parse_failures(_Db(), "user-1", {}) == {"retried": 20}
    assert await module._handle_raw_email_retention(_Db(), "user-1", {"batch_size": 9999}) == {
        "redacted": ("user-1", 2000)
    }
    assert await module._handle_raw_email_retention(_Db(), "", {"batch_size": 0}) == {
        "redacted": (None, 1)
    }

    gmail_account = SimpleNamespace(id="gmail-1", auto_sync_status="active")

    async def gmail_sync(**_kwargs):
        return {"emails_stored": 3, "emails_skipped_duplicate": 1, "emails_failed": 0}

    async def pipeline(_db, _user_id, *, limit):
        return {"stored": limit, "duplicates": 1, "parsed_success": 2}

    broadcasts = []

    async def broadcast(*args):
        broadcasts.append(args)

    monkeypatch.setattr(module, "sync_gmail_emails", gmail_sync)
    monkeypatch.setattr(module, "process_raw_emails", pipeline)
    monkeypatch.setattr(module.sync_event_manager, "broadcast", broadcast)
    gmail_db = _Db(execute_values=[_Result(scalar=gmail_account)])
    result = await module._handle_gmail_sync_pipeline(
        gmail_db, "user-1", {"max_results": 4, "limit": 5}
    )
    assert result["sync"]["emails_stored"] == 3
    assert [event[1] for event in broadcasts] == [
        "emails_stored",
        "pipeline_started",
        "transactions_updated",
    ]

    missing_db = _Db(execute_values=[_Result(scalar=None)])
    with pytest.raises(ValueError, match="No Gmail"):
        await module._handle_gmail_sync_pipeline(missing_db, "user-1", {})
    disconnecting = SimpleNamespace(id="gmail-1", auto_sync_status="disconnecting")
    with pytest.raises(ValueError, match="disconnect"):
        await module._handle_gmail_sync_pipeline(
            _Db(execute_values=[_Result(scalar=disconnecting)]), "user-1", {}
        )

    class _ConnectionService:
        def __init__(self, _db):
            pass

        async def require_active_connection(self, *_args):
            return SimpleNamespace(id="connection-1")

        async def mark_started(self, *_args):
            return None

        async def mark_completed(self, *_args):
            return None

        async def mark_failed(self, *_args):
            return None

    class _Registry:
        def get(self, _provider_type):
            return SimpleNamespace(factory=self.factory)

        async def factory(self, *_args):
            return "connector"

    class _BalanceSync:
        def __init__(self, _db):
            pass

        async def run(self, *_args, **_kwargs):
            return SimpleNamespace(
                source_type="mock",
                financial_account_ids=["account-1"],
                observations_ingested=1,
                card_observations_ingested=0,
                coverage_complete=True,
                error_types=[],
                cursor_advanced=True,
            )

    monkeypatch.setattr(module, "BalanceProviderConnectionService", _ConnectionService)
    monkeypatch.setattr(module, "balance_connector_registry", _Registry())
    monkeypatch.setattr(module, "BalanceSyncService", _BalanceSync)
    refreshed = await module._handle_balance_refresh(
        _Db(), "user-1", {"provider_type": " MOCK ", "account_ids": ["account-1"]}
    )
    assert refreshed["coverage_complete"] is True
    with pytest.raises(ValueError, match="user"):
        await module._handle_balance_refresh(_Db(), "", {})
    monkeypatch.setattr(
        module, "balance_connector_registry", SimpleNamespace(get=lambda _key: None)
    )
    with pytest.raises(ValueError, match="not configured"):
        await module._handle_balance_refresh(_Db(), "user-1", {"provider_type": "mock"})


def test_job_error_classification_and_public_messages_are_stable():
    assert module.classify_job_error(RefreshError("expired")) == "credential_error"
    assert (
        module.classify_job_error(ValueError("No Gmail account connected for this user"))
        == "missing_gmail_account"
    )
    assert (
        module.classify_job_error(ValueError("balance provider is not configured"))
        == "missing_balance_provider"
    )
    assert (
        module.classify_job_error(ValueError("provider consent is missing"))
        == "missing_provider_consent"
    )
    assert module.classify_job_error(ValueError("bad input")) == "validation_error"
    assert module.classify_job_error(RuntimeError("oauth token failed")) == "credential_error"
    assert module.classify_job_error(RuntimeError("boom")) == "unexpected_error"
    assert module.public_job_error_message("unknown") == "Background job failed"
    assert module.public_job_error_message("credential_error") == "Connector authorization failed"
    assert module._scoped_idempotency_key(None, "job", " key ")
    assert module._scoped_idempotency_key("user", "job", "   ") is None


@pytest.mark.asyncio
async def test_job_status_counts_and_claim_paths_cover_empty_and_claimed_jobs(monkeypatch):
    counts = _Result(rows=[(JobStatus.QUEUED, 2), (JobStatus.FAILED, 1)])
    status_counts = await module.get_job_status_counts(_Db(execute_values=[counts]))
    assert status_counts[JobStatus.QUEUED.value] == 2
    assert status_counts[JobStatus.COMPLETED.value] == 0

    job = _job(status=JobStatus.QUEUED)
    claim_db = _Db(execute_values=[_Result(scalar="job-1"), _Result(scalar=job)])
    assert await module._claim_job(claim_db, "job-1") is job
    assert claim_db.commits == 1
    no_claim_db = _Db(execute_values=[_Result(scalar=None)])
    assert await module._claim_job(no_claim_db, "job-1") is None

    monkeypatch.setattr(module, "_active_tasks", set())
    await module.stop_job_worker()
