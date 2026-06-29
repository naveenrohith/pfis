"""Background job orchestration regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio

from app.models.email import RawEmail
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
