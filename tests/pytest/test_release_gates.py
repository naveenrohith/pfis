"""Deterministic tests for provider-neutral production release gates."""

import json
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from scripts import postgres_restore_drill
from scripts.postgres_restore_drill import (
    connection_identity,
    parse_postgres_url,
    pg_environment,
    run_drill,
)
from scripts.release_gate import (
    summarize_load,
    validate_backup_evidence,
    validate_controls,
    validate_health_payload,
    validate_owners,
    validate_probe_settings,
    validate_security_headers,
    validate_target,
)


def test_release_gate_requires_named_operational_owners():
    with pytest.raises(ValueError, match="DATA_RECOVERY_OWNER"):
        validate_owners(
            {
                "INCIDENT_OWNER": "incident@example.com",
                "SECURITY_OWNER": "security@example.com",
            }
        )

    owners = validate_owners(
        {
            "INCIDENT_OWNER": "incident@example.com",
            "DATA_RECOVERY_OWNER": "recovery@example.com",
            "SECURITY_OWNER": "security@example.com",
        }
    )
    assert owners["DATA_RECOVERY_OWNER"] == "recovery@example.com"


def test_release_gate_requires_provider_control_identifiers():
    with pytest.raises(ValueError, match="ALERT_POLICY_ID"):
        validate_controls({"BACKUP_POLICY_ID": "backup-policy-1"})

    controls = validate_controls(
        {
            "DATABASE_RESOURCE_ID": "postgres-1",
            "PRODUCTION_DATABASE_NAME": "pfis_prod",
            "BACKUP_POLICY_ID": "backup-policy-1",
            "MONITORING_DASHBOARD_ID": "dashboard-1",
            "ALERT_POLICY_ID": "alerts-1",
            "TLS_POLICY_ID": "tls-1",
            "NETWORK_POLICY_ID": "network-1",
        }
    )
    assert controls["NETWORK_POLICY_ID"] == "network-1"


def test_release_gate_requires_clean_https_target():
    assert validate_target("https://pfis.example.com") == "https://pfis.example.com/"
    with pytest.raises(ValueError, match="HTTPS"):
        validate_target("http://pfis.example.com")
    with pytest.raises(ValueError, match="credentials"):
        validate_target("https://user:secret@pfis.example.com")
    with pytest.raises(ValueError, match="application path"):
        validate_target("https://pfis.example.com/application")


def test_release_gate_requires_passed_restore_evidence(tmp_path):
    evidence = tmp_path / "restore.json"
    evidence.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    with pytest.raises(ValueError, match="passed"):
        validate_backup_evidence(evidence)

    payload = {
        "status": "passed",
        "completed_at": datetime.now(UTC).isoformat(),
        "source_database": "pfis_prod",
        "restore_database": "pfis_restore",
        "alembic_revision": "017",
        "row_counts": {
            "users": 2,
            "transactions": 5,
            "raw_emails": 6,
            "background_jobs": 1,
            "gmail_accounts": 1,
        },
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        validate_backup_evidence(evidence, expected_source_database="pfis_prod")["restore_database"]
        == "pfis_restore"
    )


def test_release_gate_rejects_stale_or_wrong_database_restore_evidence(tmp_path):
    evidence = tmp_path / "restore.json"
    now = datetime.now(UTC)
    payload = {
        "status": "passed",
        "completed_at": (now - timedelta(hours=25)).isoformat(),
        "source_database": "other_database",
        "restore_database": "pfis_restore",
        "alembic_revision": "017",
        "row_counts": {
            "users": 2,
            "transactions": 5,
            "raw_emails": 6,
            "background_jobs": 1,
            "gmail_accounts": 1,
        },
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="production database"):
        validate_backup_evidence(
            evidence,
            expected_source_database="pfis_prod",
            now=now,
        )

    payload["source_database"] = "pfis_prod"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="older than 24 hours"):
        validate_backup_evidence(
            evidence,
            expected_source_database="pfis_prod",
            now=now,
        )


def test_release_gate_prevents_weakened_load_thresholds():
    valid = Namespace(
        requests=200,
        concurrency=10,
        max_error_rate_pct=0.5,
        max_p95_ms=750,
        timeout_seconds=10,
    )
    validate_probe_settings(valid)

    with pytest.raises(ValueError, match="at least 200"):
        validate_probe_settings(Namespace(**{**vars(valid), "requests": 199}))
    with pytest.raises(ValueError, match="error rate"):
        validate_probe_settings(Namespace(**{**vars(valid), "max_error_rate_pct": 1}))
    with pytest.raises(ValueError, match="p95"):
        validate_probe_settings(Namespace(**{**vars(valid), "max_p95_ms": 751}))


def test_release_gate_validates_health_payload_and_hsts():
    response = httpx.Response(200, json={"status": "ready", "database": "reachable"})
    assert validate_health_payload(response, "ready")["database"] == "reachable"
    with pytest.raises(RuntimeError, match="healthy"):
        validate_health_payload(response, "healthy")

    headers = httpx.Headers(
        {
            "cache-control": "no-store",
            "strict-transport-security": "max-age=31536000; includeSubDomains",
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
        }
    )
    validate_security_headers(headers)
    with pytest.raises(RuntimeError, match="strict-transport-security"):
        validate_security_headers(httpx.Headers({"cache-control": "no-store"}))


def test_load_summary_enforces_exact_request_accounting():
    summary = summarize_load([10.0, 20.0, 30.0, 40.0], failures=1)
    assert summary.requests == 5
    assert summary.failures == 1
    assert summary.error_rate_pct == 20.0
    assert summary.p50_ms == 25.0
    assert summary.p95_ms == 40.0


def test_postgres_url_parsing_keeps_secrets_out_of_identity():
    parsed = parse_postgres_url(
        "postgresql+asyncpg://pfis:p%40ss@db.example.com:5433/pfis_prod?sslmode=require"
    )
    assert parsed["password"] == "p@ss"
    assert parsed["sslmode"] == "require"
    assert connection_identity(parsed) == ("db.example.com", "5433", "pfis_prod")
    environment = pg_environment(parsed)
    assert environment["PGPASSWORD"] == "p@ss"
    assert "p@ss" not in str(connection_identity(parsed))


def test_restore_drill_refuses_source_database_as_target(tmp_path):
    database_url = "postgresql+asyncpg://pfis:secret@db.example.com/pfis_prod"
    args = Namespace(
        source_url=database_url,
        restore_url=database_url,
        confirm_restore_database="pfis_prod",
        artifact_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="must not be the source"):
        run_drill(args)


def test_restore_drill_requires_exact_disposable_database_confirmation(tmp_path):
    args = Namespace(
        source_url="postgresql://pfis:secret@db.example.com/pfis_prod",
        restore_url="postgresql://pfis:secret@db.example.com/pfis_restore",
        confirm_restore_database="wrong_database",
        artifact_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="Confirmation"):
        run_drill(args)


def test_restore_drill_passes_archive_to_pg_restore(monkeypatch, tmp_path):
    snapshots = [
        {"alembic_revision": "017", "row_counts": {"users": 2}},
        {"alembic_revision": "017", "row_counts": {"users": 2}},
        {"alembic_revision": "017", "row_counts": {"users": 2}},
    ]
    commands = []

    async def fake_snapshot(_url):
        return snapshots.pop(0)

    def fake_run(command, **_kwargs):
        commands.append(command)

    monkeypatch.setattr(postgres_restore_drill, "snapshot", fake_snapshot)
    monkeypatch.setattr(postgres_restore_drill, "require_tool", lambda name: name)
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", fake_run)

    result = run_drill(
        Namespace(
            source_url="postgresql://pfis:secret@db.example.com/pfis_prod",
            restore_url="postgresql://pfis:secret@db.example.com/pfis_restore",
            confirm_restore_database="pfis_restore",
            artifact_dir=tmp_path,
        )
    )

    archive = tmp_path / "pfis-restore-drill.dump"
    assert commands[0][-1] == f"--file={archive}"
    assert commands[1][-1] == str(archive)
    assert result["status"] == "passed"


def test_restore_drill_rejects_source_changes_during_backup(monkeypatch, tmp_path):
    snapshots = [
        {"alembic_revision": "017", "row_counts": {"users": 2}},
        {"alembic_revision": "017", "row_counts": {"users": 3}},
    ]

    async def fake_snapshot(_url):
        return snapshots.pop(0)

    monkeypatch.setattr(postgres_restore_drill, "snapshot", fake_snapshot)
    monkeypatch.setattr(postgres_restore_drill, "require_tool", lambda name: name)
    monkeypatch.setattr(postgres_restore_drill.subprocess, "run", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="changed during backup"):
        run_drill(
            Namespace(
                source_url="postgresql://pfis:secret@db.example.com/pfis_prod",
                restore_url="postgresql://pfis:secret@db.example.com/pfis_restore",
                confirm_restore_database="pfis_restore",
                artifact_dir=tmp_path,
            )
        )


def test_restore_drill_sanitizes_database_inspection_failures(monkeypatch):
    async def failed_snapshot(_url):
        raise OperationalError("SELECT 1", {}, Exception("secret database error"))

    monkeypatch.setattr(postgres_restore_drill, "snapshot", failed_snapshot)
    with pytest.raises(RuntimeError, match="Could not inspect source database") as error:
        postgres_restore_drill.collect_snapshot(
            "postgresql://user:password@db.example.com/pfis",
            "source",
        )
    assert "password" not in str(error.value)
