"""Tests for cross-cutting endpoints: health, correlation id, categories, users."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.models.sync import ConnectorAuditEvent, PipelineEvent
from app.models.transaction import PaymentMethod, Transaction, TransactionType

from .helpers import create_user


async def test_health_endpoint_ok(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert "status" in response.json()

    capabilities = await client.get("/api/health/capabilities")
    assert capabilities.status_code == 200
    balance_source = next(
        source
        for source in capabilities.json()["sources"]
        if source["key"] == "connected_bank_card_balances"
    )
    assert balance_source["status"] == "deferred"
    assert "consented provider refresh" in balance_source["freshness"]


async def test_readiness_endpoint_checks_database(client):
    response = await client.get("/api/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "reachable"}


async def test_operational_health_exposes_safe_runtime_state(client):
    response = await client.get("/api/health/ops")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["environment"] == "local"
    assert body["database_profile"] == "postgresql"
    assert body["jobs"]["active_in_process"] >= 0
    assert set(body["jobs"]["persisted_by_status"]) == {
        "queued",
        "running",
        "completed",
        "failed",
    }
    assert body["ledger_currency"] == {
        "status": "healthy",
        "mismatch_count": 0,
        "transaction_mismatches": 0,
        "account_mismatches": 0,
        "balance_mismatches": 0,
    }
    assert "sync" in body
    assert "audit_events" in body["sync"]
    assert body["sync"]["duplicate_rate"] == 0.0
    assert body["data_quality"] == {
        "window_days": 30,
        "sync_runs_observed": 0,
        "ingestion_records_observed": 0,
        "duplicate_count": 0,
        "duplicate_rate": 0.0,
        "parse_attempts": 0,
        "parse_failure_count": 0,
        "parse_failure_rate": 0.0,
        "fallback_count": 0,
        "fallback_rate": 0.0,
        "imported_transactions": 0,
        "pending_review_count": 0,
        "pending_review_rate": 0.0,
        "parser_versions": {},
        "source_drift": {
            "window_days": 7,
            "minimum_samples_per_window": 20,
            "failure_rate_delta_threshold": 0.1,
            "fallback_rate_delta_threshold": 0.2,
            "alert_sources": [],
            "sources": {},
        },
        "statement_quality": {
            "window_days": 30,
            "attempts": 0,
            "imported": 0,
            "rejected": 0,
            "rejection_rate": 0.0,
            "layout_rejected": 0,
            "layout_rejection_rate": 0.0,
            "status": "insufficient_history",
            "minimum_attempts": 20,
            "layout_rejection_rate_threshold": 0.25,
            "issuers": {},
            "rejection_reasons": {},
        },
    }


async def test_operational_health_aggregates_quality_without_source_content(
    client, test_session_factory
):
    user = await create_user(client, "ops-quality")
    async with test_session_factory() as db:
        db.add(
            ConnectorAuditEvent(
                user_id=user["id"],
                connector_type="gmail",
                connector_account_id=None,
                event_type="sync_completed",
                payload_json=json.dumps({"emails_fetched": 10, "emails_skipped_duplicate": 2}),
            )
        )
        db.add_all(
            [
                PipelineEvent(
                    user_id=user["id"],
                    event_type="Parsed",
                    stage="parser",
                    status="success",
                    parser_name="GenericParser",
                    parser_version=1,
                    payload_json='{"fallback": true}',
                ),
                PipelineEvent(
                    user_id=user["id"],
                    event_type="ParseFailed",
                    stage="parser",
                    status="failed",
                    parser_name="GenericParser",
                    parser_version=1,
                    payload_json="{}",
                ),
                Transaction(
                    user_id=user["id"],
                    amount=Decimal("25.00"),
                    currency="INR",
                    transaction_type=TransactionType.DEBIT,
                    payment_method=PaymentMethod.UPI,
                    merchant_raw="SANITIZED SAMPLE",
                    transaction_date=date(2026, 7, 1),
                    source_kind="gmail",
                    reviewed_flag=False,
                    fingerprint="ops-quality-imported-transaction",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        await db.commit()

    response = await client.get("/api/health/ops")
    response.raise_for_status()
    quality = response.json()["data_quality"]

    assert quality["sync_runs_observed"] == 1
    assert quality["duplicate_rate"] == 0.2
    assert quality["parse_failure_rate"] == 1.0
    assert quality["fallback_rate"] == 1.0
    assert quality["pending_review_rate"] == 1.0
    assert quality["parser_versions"] == {"GenericParser:v1": 1}


async def test_operational_health_flags_source_level_parser_drift(client, test_session_factory):
    user = await create_user(client, "ops-source-drift")
    now = datetime.now(UTC)
    previous_at = now - timedelta(days=10)
    current_at = now - timedelta(days=1)
    async with test_session_factory() as db:
        db.add_all(
            [
                PipelineEvent(
                    user_id=user["id"],
                    event_type="Parsed",
                    stage="parser",
                    status="success",
                    parser_name="HDFCParser",
                    parser_version=4,
                    source_institution="HDFC",
                    payload_json='{"fallback": false}',
                    created_at=previous_at,
                )
                for _ in range(20)
            ]
            + [
                PipelineEvent(
                    user_id=user["id"],
                    event_type="Parsed",
                    stage="parser",
                    status="success",
                    parser_name="GenericParser",
                    parser_version=1,
                    source_institution="HDFC",
                    payload_json='{"fallback": true}',
                    created_at=current_at,
                )
                for _ in range(20)
            ]
            + [
                PipelineEvent(
                    user_id=user["id"],
                    event_type="ParseFailed",
                    stage="parser",
                    status="failed",
                    parser_name="GenericParser",
                    parser_version=1,
                    source_institution="HDFC",
                    payload_json="{}",
                    created_at=current_at,
                )
                for _ in range(10)
            ]
        )
        await db.commit()

    response = await client.get("/api/health/ops")
    response.raise_for_status()
    body = response.json()
    assert body["status"] == "degraded"
    assert "parser_source_drift" in body["status_reasons"]
    drift = body["data_quality"]["source_drift"]
    hdfc = drift["sources"]["HDFC"]

    assert drift["alert_sources"] == ["HDFC"]
    assert hdfc["status"] == "alert"
    assert hdfc["signals"] == [
        "parse_failure_rate_increased",
        "fallback_rate_increased",
    ]
    assert hdfc["current_samples"] == 20
    assert hdfc["previous_samples"] == 20
    assert hdfc["failure_rate_delta"] == 0.5
    assert hdfc["fallback_rate_delta"] == 1.0


async def test_request_id_header_is_added(client):
    response = await client.get("/api/health")
    assert response.headers.get("X-Request-ID")
    timing = response.headers.get("Server-Timing", "")
    assert timing.startswith("app;dur=")
    assert float(timing.removeprefix("app;dur=")) >= 0


async def test_request_id_header_is_echoed_when_supplied(client):
    response = await client.get("/api/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers.get("X-Request-ID") == "trace-abc-123"


async def test_metrics_endpoint_exposes_bounded_process_contract(client):
    await client.get("/api/health?probe=ignored")

    response = await client.get("/api/health/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["metrics_scope"] == "process"
    assert "No query strings" in body["privacy"]

    metrics = body["metrics"]
    assert metrics["requests_total"] >= 1
    assert metrics["latency_sample_count"] >= 1
    assert metrics["errors_4xx"] >= 0
    assert metrics["errors_5xx"] >= 0
    assert metrics["latency_ms"]["p50"] >= 0
    assert metrics["latency_ms"]["p95"] >= metrics["latency_ms"]["p50"]
    assert "/health" in metrics["routes"]
    assert all("probe=ignored" not in route for route in metrics["routes"])


async def test_categories_list_is_seeded(client):
    response = await client.get("/api/categories/")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) > 0


async def test_user_create_list_and_get(client):
    user = await create_user(client)
    user_id = user["id"]

    fetched = await client.get(f"/api/users/{user_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == user_id

    listed = await client.get("/api/users/")
    assert listed.status_code == 200
    assert any(u["id"] == user_id for u in listed.json())


async def test_user_get_unknown_returns_404(client):
    response = await client.get("/api/users/does-not-exist")
    assert response.status_code == 404
