"""Fail-closed production release verification for a deployed PFIS instance."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

REQUIRED_OWNERS = ("INCIDENT_OWNER", "DATA_RECOVERY_OWNER", "SECURITY_OWNER")
REQUIRED_CONTROLS = (
    "DATABASE_RESOURCE_ID",
    "PRODUCTION_DATABASE_NAME",
    "BACKUP_POLICY_ID",
    "MONITORING_DASHBOARD_ID",
    "ALERT_POLICY_ID",
    "TLS_POLICY_ID",
    "NETWORK_POLICY_ID",
)
REQUIRED_HEADERS = {
    "cache-control": "no-store",
    "strict-transport-security": "max-age=",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}
RESTORE_TABLES = (
    "users",
    "transactions",
    "raw_emails",
    "background_jobs",
    "gmail_accounts",
)
MIN_LOAD_REQUESTS = 200
MAX_ERROR_RATE_PCT = 0.5
MAX_P95_MS = 750.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_RESTORE_AGE = timedelta(hours=24)
MAX_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class LoadResult:
    requests: int
    failures: int
    error_rate_pct: float
    p50_ms: float
    p95_ms: float
    max_ms: float


def validate_owners(environment: Mapping[str, str]) -> dict[str, str]:
    """Require named operational owners without inventing deployment identities."""
    owners = {name: environment.get(name, "").strip() for name in REQUIRED_OWNERS}
    missing = [name for name, value in owners.items() if not value]
    if missing:
        raise ValueError(f"Missing required operational owners: {', '.join(missing)}")
    return owners


def validate_controls(environment: Mapping[str, str]) -> dict[str, str]:
    """Require provider resource identifiers for deployment-owned controls."""
    controls = {name: environment.get(name, "").strip() for name in REQUIRED_CONTROLS}
    missing = [name for name, value in controls.items() if not value]
    if missing:
        raise ValueError(f"Missing required deployment controls: {', '.join(missing)}")
    return controls


def validate_target(base_url: str) -> str:
    """Validate and normalize the deployment URL."""
    parsed = urlsplit(base_url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Production target must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Target URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Target URL must not contain an application path")
    return base_url.rstrip("/") + "/"


def validate_backup_evidence(
    path: Path,
    *,
    expected_source_database: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Require successful, machine-readable restore-drill evidence."""
    if not path.is_file():
        raise ValueError(f"Restore-drill evidence not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Restore-drill evidence is not valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "passed":
        raise ValueError("Restore-drill evidence does not report passed status")

    required = {
        "completed_at",
        "source_database",
        "restore_database",
        "alembic_revision",
        "row_counts",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"Restore-drill evidence is incomplete: {', '.join(missing)}")
    if payload["source_database"] == payload["restore_database"]:
        raise ValueError("Restore-drill evidence used the source as its restore target")
    if expected_source_database and payload["source_database"] != expected_source_database:
        raise ValueError("Restore-drill source does not match the production database")

    try:
        completed_at = datetime.fromisoformat(str(payload["completed_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Restore-drill completion time is invalid") from exc
    if completed_at.tzinfo is None:
        raise ValueError("Restore-drill completion time must include a timezone")
    current_time = now or datetime.now(UTC)
    if completed_at > current_time + MAX_CLOCK_SKEW:
        raise ValueError("Restore-drill evidence completion time is in the future")
    if current_time - completed_at > MAX_RESTORE_AGE:
        raise ValueError("Restore-drill evidence is older than 24 hours")

    if not str(payload["alembic_revision"]).strip():
        raise ValueError("Restore-drill evidence has no Alembic revision")
    row_counts = payload["row_counts"]
    if not isinstance(row_counts, dict) or any(
        type(row_counts.get(table)) is not int or row_counts[table] < 0 for table in RESTORE_TABLES
    ):
        raise ValueError("Restore-drill evidence has invalid critical row counts")
    return payload


def validate_probe_settings(args: argparse.Namespace) -> None:
    """Prevent CLI overrides from weakening the production release standard."""
    if args.requests < MIN_LOAD_REQUESTS:
        raise ValueError(f"Load probe must send at least {MIN_LOAD_REQUESTS} requests")
    if args.concurrency < 1 or args.concurrency > args.requests:
        raise ValueError("Concurrency must be between 1 and the request count")
    if not 0 <= args.max_error_rate_pct <= MAX_ERROR_RATE_PCT:
        raise ValueError(f"Maximum error rate cannot exceed {MAX_ERROR_RATE_PCT}%")
    if not 0 < args.max_p95_ms <= MAX_P95_MS:
        raise ValueError(f"Maximum p95 latency cannot exceed {MAX_P95_MS}ms")
    if not 0 < args.timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"Request timeout cannot exceed {MAX_TIMEOUT_SECONDS} seconds")


def validate_health_payload(response: httpx.Response, expected_status: str) -> dict:
    """Require the documented health contract rather than only an HTTP status."""
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("Health endpoint did not return valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != expected_status:
        raise RuntimeError(f"Health endpoint did not report {expected_status}")
    return payload


def validate_security_headers(headers: httpx.Headers) -> None:
    """Require the browser-security baseline on the deployed API."""
    missing_headers = {
        name: expected
        for name, expected in REQUIRED_HEADERS.items()
        if expected.lower() not in headers.get(name, "").lower()
    }
    if missing_headers:
        raise RuntimeError(f"Missing required security headers: {sorted(missing_headers)}")


def summarize_load(latencies_ms: list[float], failures: int) -> LoadResult:
    """Calculate deterministic release-threshold metrics."""
    requests = len(latencies_ms) + failures
    if requests <= 0:
        raise ValueError("At least one request is required")
    ordered = sorted(latencies_ms)
    p50 = statistics.median(ordered) if ordered else 0.0
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    p95 = ordered[p95_index] if ordered else 0.0
    return LoadResult(
        requests=requests,
        failures=failures,
        error_rate_pct=round((failures / requests) * 100, 3),
        p50_ms=round(p50, 3),
        p95_ms=round(p95, 3),
        max_ms=round(max(ordered), 3) if ordered else 0.0,
    )


async def run_load_probe(
    client: httpx.AsyncClient,
    url: str,
    *,
    requests: int,
    concurrency: int,
) -> LoadResult:
    """Run a bounded read-only readiness probe."""
    semaphore = asyncio.Semaphore(concurrency)

    async def probe() -> tuple[bool, float]:
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError:
                return False, 0.0
            return True, (time.perf_counter() - started) * 1000

    results = await asyncio.gather(*(probe() for _ in range(requests)))
    latencies = [latency for success, latency in results if success]
    failures = sum(1 for success, _ in results if not success)
    return summarize_load(latencies, failures)


async def verify_release(args: argparse.Namespace) -> dict:
    validate_probe_settings(args)
    base_url = validate_target(args.base_url)
    owners = validate_owners(os.environ)
    controls = validate_controls(os.environ)
    restore_evidence = validate_backup_evidence(
        args.restore_evidence,
        expected_source_database=controls["PRODUCTION_DATABASE_NAME"],
    )
    timeout = httpx.Timeout(args.timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        health = await client.get(urljoin(base_url, "api/health"))
        health.raise_for_status()
        validate_health_payload(health, "healthy")
        readiness_url = urljoin(base_url, "api/health/ready")
        readiness = await client.get(readiness_url)
        readiness.raise_for_status()
        readiness_payload = validate_health_payload(readiness, "ready")
        if readiness_payload.get("database") != "reachable":
            raise RuntimeError("Readiness endpoint did not report a reachable database")
        validate_security_headers(readiness.headers)

        load = await run_load_probe(
            client,
            readiness_url,
            requests=args.requests,
            concurrency=args.concurrency,
        )

    if load.error_rate_pct > args.max_error_rate_pct:
        raise RuntimeError(f"Error rate {load.error_rate_pct}% exceeds {args.max_error_rate_pct}%")
    if load.p95_ms > args.max_p95_ms:
        raise RuntimeError(f"p95 latency {load.p95_ms}ms exceeds {args.max_p95_ms}ms")

    return {
        "status": "passed",
        "target": f"{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}",
        "owners": owners,
        "deployment_controls": controls,
        "restore_drill": {
            "completed_at": restore_evidence.get("completed_at"),
            "source_database": restore_evidence.get("source_database"),
            "restore_database": restore_evidence.get("restore_database"),
        },
        "load": asdict(load),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--restore-evidence", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=MIN_LOAD_REQUESTS)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--max-error-rate-pct", type=float, default=MAX_ERROR_RATE_PCT)
    parser.add_argument("--max-p95-ms", type=float, default=MAX_P95_MS)
    parser.add_argument("--output", type=Path, default=Path("release-evidence.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(verify_release(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise SystemExit(f"Release gate failed: {exc}") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Release gate passed; evidence written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
