"""Background job orchestration regression tests."""

# pyright: reportMissingImports=false

from __future__ import annotations

import asyncio

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