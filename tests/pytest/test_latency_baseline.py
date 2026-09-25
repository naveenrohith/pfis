from __future__ import annotations

from scripts.latency_baseline import (
    MAX_P95_MS,
    Sample,
    build_routes,
    measure_baseline,
)


def test_latency_baseline_uses_stub_transport_without_exposing_query_values():
    calls: list[str] = []

    def transport(url: str, _headers: dict[str, str], _timeout: float) -> Sample:
        calls.append(url)
        return Sample(status_code=200, duration_ms=42.0)

    result = measure_baseline(
        "https://pfis.example",
        build_routes(
            user_id="user-secret",
            account_id="acct-secret",
            card_account_id="card-secret",
            month=9,
            year=2026,
        ),
        samples=20,
        headers={},
        timeout=1.0,
        transport=transport,
    )

    assert result["status"] == "passed"
    assert result["routes"]["net_worth"]["p50_ms"] == 42.0
    assert result["routes"]["workspace"]["route"] == "/api/dashboard/workspace"
    assert "user-secret" not in str(result)
    assert "acct-secret" not in str(result)
    assert any("user-secret" in call for call in calls)


def test_latency_baseline_fails_on_p95_or_error_rate():
    attempts = 0

    def transport(_url: str, _headers: dict[str, str], _timeout: float) -> Sample:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return Sample(status_code=503, duration_ms=5.0, error="http_503")
        return Sample(status_code=200, duration_ms=MAX_P95_MS + 1)

    result = measure_baseline(
        "https://pfis.example",
        build_routes(
            user_id="user",
            account_id="acct",
            card_account_id="card",
            month=9,
            year=2026,
        ),
        samples=20,
        headers={},
        timeout=1.0,
        transport=transport,
    )

    assert result["status"] == "failed"
    assert set(result["failed_routes"]) == {
        "net_worth",
        "account_position",
        "card_due_runway",
        "workspace",
        "intelligence_readiness",
    }
