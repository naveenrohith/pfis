"""Background job orchestration regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio

from app.models.email import RawEmail
from app.models.sync import JobStatus
from app.services import job_service
from app.services.job_service import create_job, recover_interrupted_jobs, run_job
from app.services.parser.pipeline import process_raw_emails

from tests.pytest.helpers import create_user


async def test_demo_sync_pipeline_job_runs_to_completion(client):
    user = await create_user(client, "jobdemo")

    enqueue_response = await client.post(f"/api/jobs/demo-sync-pipeline?user_id={user['id']}")
    enqueue_response.raise_for_status()
    job = enqueue_response.json()
    assert job["status"] == "queued"

    final_payload = None
    for _ in range(40):
        status_response = await client.get(f"/api/jobs/{job['id']}")
        status_response.raise_for_status()
        final_payload = status_response.json()
        if final_payload["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.05)

    assert final_payload is not None
    assert final_payload["status"] == "completed"
    assert final_payload["result"]["sync"]["emails_stored"] == 13
    assert final_payload["result"]["pipeline"]["stored"] == 13


async def test_retry_parse_failures_job_completes_when_nothing_pending(client):
    user = await create_user(client, "retryjob")

    enqueue_response = await client.post(f"/api/jobs/retry-parse-failures?user_id={user['id']}")
    enqueue_response.raise_for_status()
    job = enqueue_response.json()

    final_payload = None
    for _ in range(20):
        status_response = await client.get(f"/api/jobs/{job['id']}")
        status_response.raise_for_status()
        final_payload = status_response.json()
        if final_payload["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.05)

    assert final_payload is not None
    assert final_payload["status"] == "completed"
    assert final_payload["result"]["retried_failures"] == 0


async def test_statement_email_does_not_create_balance_transaction(client, test_session_factory):
    user = await create_user(client, "statementskip")

    async with test_session_factory() as db:
        db.add(
            RawEmail(
                user_id=user["id"],
                gmail_message_id=f"{user['id']}:balance-update",
                sender="HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
                subject="View: Account update for your HDFC Bank A/c",
                body=(
                    "HDFC BANK Dear Customer, Greetings from HDFC Bank! "
                    "The available balance in your account ending XX1441 is "
                    "Rs. INR 42,055.05 as of 02-FEB-26. For real-time balance updates."
                ),
            )
        )
        await db.commit()

        stats = await process_raw_emails(db, user["id"])

    assert stats["skipped_non_transaction"] == 1
    assert stats["stored"] == 0

    response = await client.get(f"/api/transactions/?user_id={user['id']}&limit=10")
    response.raise_for_status()
    assert response.json() == []


async def test_gmail_pipeline_job_failure_includes_error_type(client):
    user = await create_user(client, "nogmail")

    enqueue_response = await client.post(f"/api/jobs/gmail-sync-pipeline?user_id={user['id']}")
    enqueue_response.raise_for_status()
    job = enqueue_response.json()

    final_payload = None
    for _ in range(20):
        status_response = await client.get(f"/api/jobs/{job['id']}")
        status_response.raise_for_status()
        final_payload = status_response.json()
        if final_payload["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.05)

    assert final_payload is not None
    assert final_payload["status"] == "failed"
    assert final_payload["error_message"] == "No Gmail account connected for this user"
    assert final_payload["result"]["error_type"] == "missing_gmail_account"


async def test_unsupported_job_type_failure_includes_error_type(test_session_factory):
    async with test_session_factory() as db:
        job = await create_job(db, "not_supported", user_id=None)
        job_id = job.id

    await run_job(job_id)

    async with test_session_factory() as db:
        from app.services.job_service import get_job, serialize_job

        failed_job = await get_job(db, job_id)
        payload = serialize_job(failed_job)

    assert payload["status"] == "failed"
    assert payload["error_message"] == "Unsupported job type: not_supported"
    assert payload["result"]["error_type"] == "unsupported_job_type"


async def test_recover_interrupted_jobs_requeues_only_running_leases(test_session_factory):
    async with test_session_factory() as db:
        queued = await create_job(db, "demo_sync_pipeline", user_id=None)
        running = await create_job(db, "gmail_sync_pipeline", user_id=None)
        completed = await create_job(db, "retry_parse_failures", user_id=None)

        running.status = JobStatus.RUNNING
        completed.status = JobStatus.COMPLETED
        await db.commit()

        recovered = await recover_interrupted_jobs(db)
        assert recovered == 1

        await db.refresh(queued)
        await db.refresh(running)
        await db.refresh(completed)

    assert queued.status == JobStatus.QUEUED
    assert running.status == JobStatus.QUEUED
    assert queued.error_message is None
    assert running.error_message == "Job lease recovered after server restart"
    assert completed.status == JobStatus.COMPLETED


async def test_job_claim_is_atomic_across_concurrent_workers(test_session_factory, monkeypatch):
    calls = 0

    async def handler(_db, _user_id, _payload):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"ok": True}

    monkeypatch.setitem(job_service.JOB_HANDLERS, "atomic-test", handler)
    async with test_session_factory() as db:
        job = await create_job(db, "atomic-test", user_id=None)

    await asyncio.gather(run_job(job.id), run_job(job.id))

    async with test_session_factory() as db:
        completed = await job_service.get_job(db, job.id)

    assert calls == 1
    assert completed.status == JobStatus.COMPLETED
    assert completed.attempt_count == 1


async def test_job_idempotency_key_returns_original_job(client):
    user = await create_user(client, "job-idempotency")
    headers = {"Idempotency-Key": "same-user-action"}

    first = await client.post(
        f"/api/jobs/retry-parse-failures?user_id={user['id']}", headers=headers
    )
    second = await client.post(
        f"/api/jobs/retry-parse-failures?user_id={user['id']}", headers=headers
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    for _ in range(40):
        status = await client.get(f"/api/jobs/{first.json()['id']}")
        if status.json()["status"] in {"completed", "failed"}:
            break
        await asyncio.sleep(0.05)
    assert status.json()["status"] == "completed"


async def test_unexpected_job_failure_is_retried_until_attempts_exhausted(
    test_session_factory, monkeypatch
):
    async def handler(_db, _user_id, _payload):
        raise RuntimeError("temporary worker failure")

    monkeypatch.setitem(job_service.JOB_HANDLERS, "retry-test", handler)
    async with test_session_factory() as db:
        job = await create_job(db, "retry-test", user_id=None, max_attempts=2)

    await run_job(job.id)
    async with test_session_factory() as db:
        retrying = await job_service.get_job(db, job.id)
        assert retrying.status == JobStatus.QUEUED
        assert retrying.attempt_count == 1
        retrying.available_at = None
        await db.commit()

    await run_job(job.id)
    async with test_session_factory() as db:
        failed = await job_service.get_job(db, job.id)

    assert failed.status == JobStatus.FAILED
    assert failed.attempt_count == 2
    assert failed.result_json
