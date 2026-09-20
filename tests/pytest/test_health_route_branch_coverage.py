"""Direct branch coverage for privacy-safe health and drift calculations."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.routes import health as health_module


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)

    def __iter__(self):
        return iter(self.rows)


class _Result:
    def __init__(self, *, rows=(), one_value=None, scalar_value=None):
        self.rows = list(rows)
        self.one_value = one_value
        self.scalar_value = scalar_value

    def all(self):
        return list(self.rows)

    def one(self):
        return self.one_value

    def scalar(self):
        return self.scalar_value


class _Db:
    def __init__(self, *, execute_results=(), scalar_values=(), scalars_results=()):
        self.execute_results = list(execute_results)
        self.scalar_values = list(scalar_values)
        self.scalars_results = list(scalars_results)

    async def execute(self, _statement):
        return self.execute_results.pop(0)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def scalars(self, _statement):
        return _Rows(self.scalars_results.pop(0) if self.scalars_results else ())


def test_small_health_helpers_fail_closed_and_bound_ratios():
    assert health_module._safe_payload('{"count": 2}') == {"count": 2}
    assert health_module._safe_payload("not-json") == {}
    assert health_module._safe_payload("[]") == {}
    assert health_module._safe_payload(None) == {}
    assert health_module._non_negative_int(4.9) == 4
    assert health_module._non_negative_int(-2) == 0
    assert health_module._non_negative_int("bad") == 0
    assert health_module._non_negative_int(object()) == 0
    assert health_module._ratio(1, 3) == 0.3333
    assert health_module._ratio(1, 0) == 0.0


@pytest.mark.parametrize(
    ("ledger", "quality", "jobs", "expected_status", "reasons", "warnings"),
    [
        ({"status": "healthy"}, {}, {}, "healthy", [], []),
        (
            {"status": "healthy"},
            {
                "parse_failures_open": 1,
                "source_drift": {"alert_sources": ["BANK"]},
                "statement_quality": {"status": "alert"},
            },
            {"failed": 2},
            "degraded",
            [
                "unresolved_parse_failures",
                "parser_source_drift",
                "statement_layout_drift",
                "failed_background_jobs",
            ],
            [],
        ),
        (
            {"status": "needs_repair"},
            {},
            {},
            "needs_repair",
            ["ledger_currency_needs_repair"],
            [],
        ),
        (
            {"status": "healthy"},
            {},
            {},
            "healthy",
            [],
            [
                "provider_query_coverage_is_partial",
                "latest_provider_query_was_capped",
                "historical_sync_runs_failed",
            ],
        ),
    ],
)
def test_operational_status_separates_service_failures_from_data_warnings(
    ledger, quality, jobs, expected_status, reasons, warnings
):
    sync = {
        "coverage": {"incomplete_runs": 1, "latest_truncated": True},
        "failed_runs": 1,
    }
    if not warnings:
        sync = {"coverage": {}, "failed_runs": 0}
    result = health_module._operational_status(
        sync_metrics=sync,
        quality_metrics=quality,
        job_statuses=jobs,
        ledger_health=ledger,
    )
    assert result[0] == expected_status
    assert result[1] == reasons
    assert result[2] == warnings


@pytest.mark.asyncio
async def test_source_window_and_drift_metrics_cover_parser_and_alert_states(monkeypatch):
    db = _Db(
        execute_results=[
            _Result(
                rows=[
                    ("HDFC", "Parsed", "GenericParser", "2", 22),
                    ("HDFC", "ParseFailed", "HdfcParser", "1", 3),
                    ("OTHER", "Parsed", None, None, 2),
                ]
            )
        ]
    )
    window = await health_module._source_window_metrics(
        db,
        datetime(2026, 9, 1, tzinfo=UTC),
        datetime(2026, 9, 2, tzinfo=UTC),
    )
    assert window["HDFC"] == {
        "parsed": 22,
        "failed": 3,
        "fallback": 22,
        "parser_versions": {"GenericParser:v2": 22},
    }
    assert window["OTHER"]["parser_versions"] == {"unknown:v0": 2}

    windows = iter(
        [
            {
                "BANK": {
                    "parsed": 25,
                    "failed": 10,
                    "fallback": 8,
                    "parser_versions": {"v2": 25},
                },
                "SMALL": {"parsed": 1, "failed": 0, "fallback": 0, "parser_versions": {}},
            },
            {
                "BANK": {
                    "parsed": 20,
                    "failed": 1,
                    "fallback": 1,
                    "parser_versions": {"v1": 20},
                }
            },
        ]
    )

    async def fake_window(*_args):
        return next(windows)

    monkeypatch.setattr(health_module, "_source_window_metrics", fake_window)
    drift = await health_module._source_drift_metrics(db, datetime.now(UTC))
    assert drift["alert_sources"] == ["BANK"]
    assert drift["sources"]["BANK"]["status"] == "alert"
    assert drift["sources"]["SMALL"]["status"] == "insufficient_history"
    assert "parse_failure_rate_increased" in drift["sources"]["BANK"]["signals"]


@pytest.mark.asyncio
async def test_statement_quality_reports_insufficient_alert_and_stable_states():
    started = datetime(2026, 9, 1, tzinfo=UTC)
    insufficient = _Db(
        execute_results=[_Result(rows=[("HDFC", "v1", 2)])],
        scalars_results=[
            [
                '{"reason_code": "unsupported_layout"}',
                '{"reason_code": "other"}',
            ]
        ],
    )
    result = await health_module._statement_quality_metrics(insufficient, started)
    assert result["status"] == "insufficient_history"
    assert result["rejection_reasons"] == {"other": 1, "unsupported_layout": 1}

    alert = _Db(
        execute_results=[_Result(rows=[("HDFC", "v1", 15)])],
        scalars_results=[
            ['{"reason_code": "unsupported_layout"}'] * 5,
        ],
    )
    result = await health_module._statement_quality_metrics(alert, started)
    assert result["status"] == "alert"
    assert result["layout_rejection_rate"] == 0.25

    stable = _Db(
        execute_results=[_Result(rows=[("HDFC", "v1", 19)])],
        scalars_results=[['{"reason_code": "other"}']],
    )
    result = await health_module._statement_quality_metrics(stable, started)
    assert result["status"] == "stable"


@pytest.mark.asyncio
async def test_sync_and_quality_metrics_aggregate_safe_values(monkeypatch):
    latest = SimpleNamespace(
        coverage_complete=True,
        coverage_truncated=False,
        coverage_result_size_estimate=12,
    )
    db = _Db(
        execute_results=[
            _Result(one_value=(2, 10, 8, 1)),
            _Result(scalar_value=1),
            _Result(scalar_value=2),
            _Result(rows=[("sync_failed", 2)]),
        ],
        scalar_values=[0, latest],
    )
    metrics = await health_module._sync_metrics(db)
    assert metrics["runs"] == 2
    assert metrics["failed_runs"] == 1
    assert metrics["parse_failures_open"] == 2
    assert metrics["audit_events"] == {"sync_failed": 2}
    assert metrics["coverage"]["latest_result_size_estimate"] == 12

    quality_db = _Db(
        execute_results=[
            _Result(rows=[("Parsed", 4), ("ParseFailed", 1)]),
            _Result(rows=[("Parser", "2", 4)]),
            _Result(one_value=(7, 2)),
        ],
        scalar_values=[3],
        scalars_results=[
            [SimpleNamespace(payload_json='{"emails_fetched": 5, "emails_skipped_duplicate": 1}')]
        ],
    )

    async def fake_drift(*_args):
        return {"alert_sources": [], "sources": {}}

    async def fake_statement(*_args):
        return {"status": "stable"}

    monkeypatch.setattr(health_module, "_source_drift_metrics", fake_drift)
    monkeypatch.setattr(health_module, "_statement_quality_metrics", fake_statement)
    quality = await health_module._quality_metrics(quality_db)
    assert quality["ingestion_records_observed"] == 5
    assert quality["duplicate_count"] == 1
    assert quality["parse_failure_rate"] == 0.25
    assert quality["parser_versions"] == {"Parser:v2": 4}
