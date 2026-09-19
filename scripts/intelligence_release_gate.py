"""Validate evidence before enabling PFIS intelligence rules in production.

The application publishes separate parser, forecast, anomaly, and
recommendation reports. This script is the join point for those reports: it
makes missing evidence visible, applies the thresholds from the intelligence
maturity definition, and can be run in an audit mode while cohorts are still
being collected. ``--strict`` is the release mode; deferred evidence then
fails closed instead of being mistaken for a passing result.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MINIMUM_TOTAL_PARSER_CASES = 100
DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_CASES = 100
DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_FORMATS = 10
DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_INSTITUTIONS = 6
DEFAULT_MINIMUM_CLASSIFICATION_ACCURACY = 0.95
DEFAULT_MINIMUM_CLASSIFICATION_MACRO_RECALL = 0.95
DEFAULT_MINIMUM_CRITICAL_FIELD_ACCURACY = 0.98
DEFAULT_MINIMUM_FORECAST_USERS = 5
DEFAULT_MINIMUM_REPRESENTATIVE_FORECAST_USERS = 5
DEFAULT_MINIMUM_FORECAST_PERIODS = 3
DEFAULT_MAXIMUM_FORECAST_MAPE_PCT = 20.0
DEFAULT_MINIMUM_FORECAST_INTERVAL_COVERAGE_PCT = 70.0
DEFAULT_MINIMUM_FORECAST_TRANSACTION_HISTORY_COVERAGE_PCT = 95.0
DEFAULT_MINIMUM_RECONCILIATION_USERS = 10
DEFAULT_MINIMUM_RECONCILIATION_INTERVALS = 100
DEFAULT_MINIMUM_RECONCILIATION_INSTITUTIONS = 6
DEFAULT_MAXIMUM_RECONCILIATION_MEDIAN_RESIDUAL_PCT = 1.0
DEFAULT_MAXIMUM_RECONCILIATION_P95_RESIDUAL_PCT = 5.0
DEFAULT_MINIMUM_RECOMMENDATION_COHORTS = 1
DEFAULT_MINIMUM_RECOMMENDATION_SAMPLE = 10
DEFAULT_MINIMUM_RECOMMENDATION_USERS = 5
DEFAULT_MINIMUM_ANOMALY_CASES = 50
DEFAULT_MINIMUM_ANOMALY_USERS = 5
DEFAULT_MINIMUM_ANOMALY_PRECISION = 0.90
DEFAULT_MINIMUM_ANOMALY_RECALL = 0.80
DEFAULT_MAXIMUM_ANOMALY_FALSE_POSITIVE_RATE = 0.10
PARSER_REPORT_VERSION = 2
FORECAST_EVALUATION_VERSION = "pfis-cash-flow-backtest-2"
BALANCE_RECONCILIATION_EVALUATION_VERSION = "pfis-balance-reconciliation-1"
REPRESENTATIVE_FORECAST_COHORT = "production_safe"
REPRESENTATIVE_COHORT = "production_safe"
RECOMMENDATION_EFFECTIVENESS_VERSION = "pfis-recommendation-effectiveness-1"
ANOMALY_EVALUATION_VERSION = "pfis-anomaly-evaluation-1"
ANOMALY_RULESET_VERSION = "pfis-anomaly-2"

CRITICAL_FIELDS = ("amount", "transaction_type", "date", "account_last4")


@dataclass(frozen=True)
class CheckResult:
    """One machine-readable release check."""

    name: str
    status: str
    message: str
    evidence: dict[str, Any]


def _check(
    name: str,
    passed: bool,
    message: str,
    evidence: dict[str, Any],
) -> CheckResult:
    return CheckResult(name, "passed" if passed else "failed", message, evidence)


def _deferred(name: str, message: str, evidence: dict[str, Any] | None = None) -> CheckResult:
    return CheckResult(name, "deferred", message, evidence or {})


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"Evidence file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Evidence file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Evidence file must contain a JSON object: {path}")
    return payload


def _number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _count(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    return value if type(value) is int and value >= 0 else 0


def validate_parser_report(
    report: dict[str, Any],
    *,
    minimum_total_cases: int,
    minimum_classification_accuracy: float,
    minimum_classification_macro_recall: float,
    minimum_critical_field_accuracy: float,
    minimum_representative_cases: int = DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_CASES,
    minimum_representative_formats: int = DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_FORMATS,
    minimum_representative_institutions: int = DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_INSTITUTIONS,
) -> list[CheckResult]:
    """Validate the parser/classifier quality contract without recomputing it."""
    extraction = report.get("transaction_extraction")
    classification = report.get("source_classification")
    if not isinstance(extraction, dict) or not isinstance(classification, dict):
        raise ValueError("Parser report is missing transaction_extraction or source_classification")

    extraction_cases = int(extraction.get("case_count", 0))
    classification_cases = int(classification.get("case_count", 0))
    total_cases = extraction_cases + classification_cases
    critical_fields = extraction.get("field_accuracy", {})
    field_values = {
        field: _number(critical_fields.get(field, {}), "accuracy")
        for field in CRITICAL_FIELDS
        if isinstance(critical_fields.get(field), dict)
    }
    available_fields = [value for value in field_values.values() if value is not None]
    critical_accuracy = min(available_fields, default=0.0)

    checks = [
        _check(
            "parser_report_version",
            report.get("report_version") == PARSER_REPORT_VERSION,
            (
                "Parser report version is supported."
                if report.get("report_version") == PARSER_REPORT_VERSION
                else "Parser report version is missing or unsupported."
            ),
            {"value": report.get("report_version"), "required": PARSER_REPORT_VERSION},
        ),
        _check(
            "parser_total_cases",
            total_cases >= minimum_total_cases,
            f"Parser corpus has {total_cases} cases; minimum is {minimum_total_cases}.",
            {
                "transaction_cases": extraction_cases,
                "classification_cases": classification_cases,
                "total_cases": total_cases,
                "minimum": minimum_total_cases,
            },
        ),
        _check(
            "classification_exact_accuracy",
            (_number(classification, "exact_accuracy") or 0.0) >= minimum_classification_accuracy,
            (
                "Classification exact accuracy meets the release threshold."
                if (_number(classification, "exact_accuracy") or 0.0)
                >= minimum_classification_accuracy
                else "Classification exact accuracy is below the release threshold."
            ),
            {
                "value": _number(classification, "exact_accuracy"),
                "minimum": minimum_classification_accuracy,
            },
        ),
        _check(
            "classification_macro_recall",
            (_number(classification, "macro_recall") or 0.0) >= minimum_classification_macro_recall,
            (
                "Classification macro recall meets the release threshold."
                if (_number(classification, "macro_recall") or 0.0)
                >= minimum_classification_macro_recall
                else "Classification macro recall is below the release threshold."
            ),
            {
                "value": _number(classification, "macro_recall"),
                "minimum": minimum_classification_macro_recall,
            },
        ),
        _check(
            "critical_field_accuracy",
            critical_accuracy >= minimum_critical_field_accuracy
            and len(available_fields) == len(CRITICAL_FIELDS),
            (
                "All critical fields meet the release threshold."
                if critical_accuracy >= minimum_critical_field_accuracy
                and len(available_fields) == len(CRITICAL_FIELDS)
                else "One or more critical fields are missing or below the release threshold."
            ),
            {
                "values": field_values,
                "minimum": minimum_critical_field_accuracy,
            },
        ),
    ]
    cohort_evidence = report.get("cohort_evidence")
    cohort_manifest = report.get("cohort_manifest")
    if isinstance(cohort_manifest, dict) and cohort_manifest.get("status") == "invalid":
        checks.append(
            _check(
                "parser_representative_cohort",
                False,
                "Representative parser cohort manifest is invalid; release evidence cannot be trusted.",
                {
                    "manifest_status": cohort_manifest.get("status"),
                    "reason": cohort_manifest.get("reason"),
                    "manifest_fingerprint": cohort_manifest.get("manifest_fingerprint"),
                },
            )
        )
        return checks
    if not isinstance(cohort_manifest, dict) or cohort_manifest.get("status") != "verified":
        checks.append(
            _deferred(
                "parser_representative_cohort",
                "No independently attested parser cohort manifest was supplied; review de-identified production-safe cases before promotion.",
                {
                    "manifest_status": (
                        cohort_manifest.get("status")
                        if isinstance(cohort_manifest, dict)
                        else "not_supplied"
                    ),
                    "minimum_cases": minimum_representative_cases,
                    "minimum_formats": minimum_representative_formats,
                    "minimum_institutions": minimum_representative_institutions,
                },
            )
        )
        return checks
    if not isinstance(cohort_evidence, dict):
        checks.append(
            _deferred(
                "parser_representative_cohort",
                "No representative parser cohort evidence was supplied; label sanitized production-safe cases before promotion.",
                {
                    "minimum_cases": minimum_representative_cases,
                    "minimum_formats": minimum_representative_formats,
                    "minimum_institutions": minimum_representative_institutions,
                },
            )
        )
        return checks
    representative_cases = int(cohort_evidence.get("representative_case_count", 0))
    representative_formats = int(cohort_evidence.get("representative_format_count", 0))
    representative_institutions = int(cohort_evidence.get("representative_institution_count", 0))
    representative_passed = (
        representative_cases >= minimum_representative_cases
        and representative_formats >= minimum_representative_formats
        and representative_institutions >= minimum_representative_institutions
    )
    cohort_check_evidence = {
        "representative_cases": representative_cases,
        "minimum_cases": minimum_representative_cases,
        "representative_formats": representative_formats,
        "minimum_formats": minimum_representative_formats,
        "representative_institutions": representative_institutions,
        "minimum_institutions": minimum_representative_institutions,
        "cohorts": cohort_evidence.get("cohorts", {}),
    }
    checks.append(
        _check(
            "parser_representative_cohort",
            representative_passed,
            (
                "Representative parser cohort coverage meets the release threshold."
                if representative_passed
                else "Representative parser cohort evidence is below the release threshold."
            ),
            cohort_check_evidence,
        )
        if representative_passed
        else _deferred(
            "parser_representative_cohort",
            "Representative parser cohort evidence is below the release threshold.",
            cohort_check_evidence,
        )
    )
    return checks


def _forecast_reports(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept one report or an envelope containing reports."""
    reports = payload.get("reports")
    if reports is None:
        return [payload]
    if not isinstance(reports, list) or not all(isinstance(item, dict) for item in reports):
        raise ValueError("Forecast evidence envelope reports must be a list of objects")
    return reports


def validate_forecast_reports(
    reports: list[dict[str, Any]],
    *,
    minimum_users: int,
    minimum_periods: int,
    maximum_mape_pct: float,
    minimum_interval_coverage_pct: float = DEFAULT_MINIMUM_FORECAST_INTERVAL_COVERAGE_PCT,
    minimum_transaction_history_coverage_pct: float = DEFAULT_MINIMUM_FORECAST_TRANSACTION_HISTORY_COVERAGE_PCT,
    minimum_representative_users: int = DEFAULT_MINIMUM_REPRESENTATIVE_FORECAST_USERS,
) -> CheckResult:
    """Require an eligible, leakage-safe backtest for every evidence user."""
    if not reports:
        return _deferred(
            "forecast_backtest",
            "No forecast backtest reports were supplied; collect completed-user evidence.",
        )

    eligible_users = 0
    evaluated_horizons = 0
    failing_horizons: list[dict[str, Any]] = []
    coverage_failures: list[dict[str, Any]] = []
    coverage_missing: list[dict[str, Any]] = []
    temporal_evidence_missing: list[int] = []
    transaction_history_missing: list[int] = []
    transaction_history_coverage_failures: list[dict[str, Any]] = []
    missing_representative_metadata: list[int] = []
    representative_users: set[str] = set()
    raw_user_id_reports = [
        index for index, report in enumerate(reports, start=1) if "user_id" in report
    ]
    for index, report in enumerate(reports, start=1):
        if report.get("evaluation_version") != FORECAST_EVALUATION_VERSION:
            return _check(
                "forecast_backtest",
                False,
                f"Forecast report {index} has an unsupported evaluation ruleset.",
                {
                    "report_index": index,
                    "value": report.get("evaluation_version"),
                    "required": FORECAST_EVALUATION_VERSION,
                },
            )
        horizons = report.get("horizons")
        if not isinstance(horizons, list):
            return _check(
                "forecast_backtest",
                False,
                f"Forecast report {index} has no horizons list.",
                {"report_index": index},
            )
        eligible = [
            horizon
            for horizon in horizons
            if isinstance(horizon, dict)
            and int(horizon.get("eligible_periods", 0)) >= minimum_periods
            and _number(horizon, "median_absolute_percentage_error") is not None
        ]
        if not eligible:
            continue
        eligible_users += 1
        cohort = report.get("cohort")
        # Representative evidence must be keyed; never accept a raw user ID in
        # a release artifact, even when a legacy report includes one.
        user_key = report.get("user_id_hash")
        if (
            cohort == REPRESENTATIVE_FORECAST_COHORT
            and isinstance(user_key, str)
            and user_key.strip()
        ):
            representative_users.add(user_key.strip())
        elif cohort == REPRESENTATIVE_FORECAST_COHORT:
            missing_representative_metadata.append(index)
        if report.get("temporal_evidence_evaluated") is not True:
            temporal_evidence_missing.append(index)
        if report.get("transaction_history_evaluated") is not True:
            transaction_history_missing.append(index)
        transaction_coverage = _number(report, "transaction_history_coverage_pct")
        if (
            transaction_coverage is None
            or transaction_coverage < minimum_transaction_history_coverage_pct
        ):
            transaction_history_coverage_failures.append(
                {
                    "report_index": index,
                    "coverage_pct": transaction_coverage,
                }
            )
        for horizon in eligible:
            evaluated_horizons += 1
            mape = _number(horizon, "median_absolute_percentage_error")
            if mape is not None and mape > maximum_mape_pct:
                failing_horizons.append(
                    {
                        "report_index": index,
                        "cutoff_day": horizon.get("cutoff_day"),
                        "eligible_periods": horizon.get("eligible_periods"),
                        "median_absolute_percentage_error": mape,
                    }
                )
            coverage = _number(horizon, "interval_coverage_pct")
            if coverage is None:
                coverage_missing.append(
                    {
                        "report_index": index,
                        "cutoff_day": horizon.get("cutoff_day"),
                    }
                )
            elif coverage < minimum_interval_coverage_pct:
                coverage_failures.append(
                    {
                        "report_index": index,
                        "cutoff_day": horizon.get("cutoff_day"),
                        "eligible_periods": horizon.get("eligible_periods"),
                        "interval_coverage_pct": coverage,
                    }
                )

    evidence = {
        "reports": len(reports),
        "eligible_users": eligible_users,
        "evaluated_horizons": evaluated_horizons,
        "minimum_users": minimum_users,
        "minimum_periods": minimum_periods,
        "maximum_mape_pct": maximum_mape_pct,
        "failing_horizons": failing_horizons,
        "minimum_interval_coverage_pct": minimum_interval_coverage_pct,
        "coverage_failures": coverage_failures,
        "coverage_missing": coverage_missing,
        "temporal_evidence_missing_reports": temporal_evidence_missing,
        "transaction_history_missing_reports": transaction_history_missing,
        "minimum_transaction_history_coverage_pct": minimum_transaction_history_coverage_pct,
        "transaction_history_coverage_failures": transaction_history_coverage_failures,
        "representative_cohort": REPRESENTATIVE_FORECAST_COHORT,
        "representative_users": len(representative_users),
        "minimum_representative_users": minimum_representative_users,
        "missing_representative_metadata_reports": missing_representative_metadata,
        "raw_user_id_reports": raw_user_id_reports,
    }
    if raw_user_id_reports:
        return _check(
            "forecast_privacy",
            False,
            "Forecast release evidence contains raw user IDs; export keyed hashes only.",
            evidence,
        )
    if eligible_users < minimum_users:
        return _deferred(
            "forecast_backtest",
            f"Only {eligible_users} eligible forecast users; minimum is {minimum_users}.",
            evidence,
        )
    if len(representative_users) < minimum_representative_users:
        return _deferred(
            "forecast_representative_cohort",
            f"Only {len(representative_users)} distinct production-safe forecast users; minimum is {minimum_representative_users}.",
            evidence,
        )
    if (
        coverage_missing
        or coverage_failures
        or temporal_evidence_missing
        or transaction_history_missing
        or transaction_history_coverage_failures
    ):
        message = (
            "Eligible forecast horizons are missing interval coverage, below the coverage floor, or missing historical transaction/temporal evidence."
            if not failing_horizons
            else "Forecast horizons exceed MAPE or fail interval coverage and historical-evidence gates."
        )
    elif failing_horizons:
        message = "One or more eligible forecast horizons exceed the MAPE threshold."
    else:
        message = "Eligible forecast horizons meet the MAPE threshold."
    return _check(
        "forecast_backtest",
        not failing_horizons
        and not coverage_missing
        and not coverage_failures
        and not temporal_evidence_missing
        and not transaction_history_missing
        and not transaction_history_coverage_failures,
        message,
        evidence,
    )


def _balance_reconciliation_reports(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept an aggregate balance report envelope."""

    reports = payload.get("reports")
    if not isinstance(reports, list) or not all(isinstance(item, dict) for item in reports):
        raise ValueError("Balance reconciliation evidence reports must be a list of objects")
    return reports


def validate_balance_reconciliation_report(
    report: dict[str, Any] | None,
    *,
    minimum_users: int = DEFAULT_MINIMUM_RECONCILIATION_USERS,
    minimum_intervals: int = DEFAULT_MINIMUM_RECONCILIATION_INTERVALS,
    minimum_institutions: int = DEFAULT_MINIMUM_RECONCILIATION_INSTITUTIONS,
    maximum_median_residual_pct: float = DEFAULT_MAXIMUM_RECONCILIATION_MEDIAN_RESIDUAL_PCT,
    maximum_p95_residual_pct: float = DEFAULT_MAXIMUM_RECONCILIATION_P95_RESIDUAL_PCT,
) -> CheckResult:
    """Require representative, privacy-safe balance reconciliation evidence."""

    if report is None:
        return _deferred(
            "balance_reconciliation",
            "No balance-reconciliation report was supplied; collect verified-observation intervals.",
        )
    if report.get("evaluation_version") != BALANCE_RECONCILIATION_EVALUATION_VERSION:
        return _check(
            "balance_reconciliation",
            False,
            "Balance-reconciliation evidence uses an unsupported evaluation ruleset.",
            {
                "value": report.get("evaluation_version"),
                "required": BALANCE_RECONCILIATION_EVALUATION_VERSION,
            },
        )
    reports = _balance_reconciliation_reports(report)
    raw_user_id_reports = [
        index for index, item in enumerate(reports, start=1) if "user_id" in item
    ]
    unsupported_report_versions = [
        index
        for index, item in enumerate(reports, start=1)
        if item.get("evaluation_version") != BALANCE_RECONCILIATION_EVALUATION_VERSION
    ]
    representative = [
        item
        for item in reports
        if item.get("cohort") == REPRESENTATIVE_COHORT
        and isinstance(item.get("user_id_hash"), str)
        and item["user_id_hash"].strip()
        and _count(item, "interval_count") > 0
    ]
    aggregate = report.get("aggregate")
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    interval_count = _count(aggregate, "representative_interval_count")
    median_residual = _number(aggregate, "median_of_user_median_absolute_residual_pct")
    p95_residual = _number(aggregate, "p95_of_user_p95_absolute_residual_pct")
    representative_user_hashes = {
        item["user_id_hash"].strip()
        for item in representative
        if isinstance(item.get("user_id_hash"), str)
    }
    distinct_representative_users = len(representative_user_hashes)
    evidence = {
        "reports": len(reports),
        "representative_users": len(representative),
        "distinct_representative_users": distinct_representative_users,
        "minimum_users": minimum_users,
        "representative_intervals": interval_count,
        "minimum_intervals": minimum_intervals,
        "representative_institutions": _count(aggregate, "representative_institution_count"),
        "minimum_institutions": minimum_institutions,
        "median_residual_pct": median_residual,
        "maximum_median_residual_pct": maximum_median_residual_pct,
        "p95_residual_pct": p95_residual,
        "maximum_p95_residual_pct": maximum_p95_residual_pct,
        "raw_user_id_reports": raw_user_id_reports,
        "unsupported_report_versions": unsupported_report_versions,
        "manifest": report.get("manifest"),
    }
    if raw_user_id_reports:
        return _check(
            "balance_reconciliation_privacy",
            False,
            "Balance-reconciliation evidence contains raw user IDs; export keyed hashes only.",
            evidence,
        )
    if unsupported_report_versions:
        return _check(
            "balance_reconciliation",
            False,
            "One or more balance-reconciliation reports use an unsupported evaluation ruleset.",
            evidence,
        )
    manifest = report.get("manifest")
    if isinstance(manifest, dict) and manifest.get("status") == "invalid":
        return _check(
            "balance_reconciliation_representative_cohort",
            False,
            "Representative balance cohort manifest is invalid; release evidence cannot be trusted.",
            evidence,
        )
    if not isinstance(manifest, dict) or manifest.get("status") != "verified":
        return _deferred(
            "balance_reconciliation_representative_cohort",
            "No independently attested balance cohort manifest was supplied; review de-identified production-safe intervals before promotion.",
            evidence,
        )
    institution_count = _count(aggregate, "representative_institution_count")
    if (
        distinct_representative_users < minimum_users
        or interval_count < minimum_intervals
        or institution_count < minimum_institutions
    ):
        return _deferred(
            "balance_reconciliation",
            "Representative verified-balance interval evidence is below the user, interval, or institution release floor.",
            evidence,
        )
    if median_residual is None or p95_residual is None:
        return _check(
            "balance_reconciliation",
            False,
            "Balance-reconciliation evidence is missing residual quality metrics.",
            evidence,
        )
    passed = (
        median_residual <= maximum_median_residual_pct and p95_residual <= maximum_p95_residual_pct
    )
    return _check(
        "balance_reconciliation",
        passed,
        (
            "Representative balance intervals meet residual-drift thresholds."
            if passed
            else "Representative balance intervals exceed residual-drift thresholds."
        ),
        evidence,
    )


def validate_recommendation_report(
    report: dict[str, Any] | None,
    *,
    minimum_cohorts: int,
    minimum_sample: int,
    minimum_users: int,
) -> CheckResult:
    """Require privacy-safe, measured recommendation outcome cohorts."""
    if report is None:
        return _deferred(
            "recommendation_effectiveness",
            "No aggregate recommendation report was supplied; collect outcome evidence.",
        )
    if report.get("effectiveness_ruleset_version") != RECOMMENDATION_EFFECTIVENESS_VERSION:
        return _check(
            "recommendation_effectiveness",
            False,
            "Recommendation effectiveness report has an unsupported ruleset.",
            {
                "value": report.get("effectiveness_ruleset_version"),
                "required": RECOMMENDATION_EFFECTIVENESS_VERSION,
            },
        )
    cohorts = report.get("cohorts")
    if not isinstance(cohorts, list):
        return _check(
            "recommendation_effectiveness",
            False,
            "Recommendation effectiveness report has no cohorts list.",
            {},
        )

    eligible = [
        cohort
        for cohort in cohorts
        if isinstance(cohort, dict)
        and _count(cohort, "sample_size") >= minimum_sample
        and _count(cohort, "unique_users") >= minimum_users
    ]
    measured_user_coverage_failures = []
    measured = []
    for index, cohort in enumerate(eligible, start=1):
        if cohort.get("measured_evidence_status") != "available":
            continue
        measured_sample_size = _count(cohort, "measured_sample_size")
        measured_unique_users = _count(cohort, "measured_unique_users")
        if measured_sample_size < minimum_sample:
            continue
        if measured_unique_users < minimum_users:
            measured_user_coverage_failures.append(
                {
                    "cohort_index": index,
                    "measured_unique_users": measured_unique_users,
                    "minimum_users": minimum_users,
                }
            )
            continue
        measured.append(cohort)
    evidence = {
        "report_status": report.get("evidence_status"),
        "published_cohorts": len(cohorts),
        "eligible_cohorts": len(eligible),
        "measured_cohorts": len(measured),
        "minimum_cohorts": minimum_cohorts,
        "minimum_sample": minimum_sample,
        "minimum_users": minimum_users,
        "measured_user_coverage_failures": measured_user_coverage_failures,
    }
    if report.get("evidence_status") != "available":
        return _deferred(
            "recommendation_effectiveness",
            "Aggregate recommendation evidence is not yet available at the privacy threshold.",
            evidence,
        )
    passed = len(eligible) >= minimum_cohorts and len(measured) >= minimum_cohorts
    return _check(
        "recommendation_effectiveness",
        passed,
        (
            "Recommendation cohorts have measured outcome evidence."
            if passed
            else "Recommendation cohorts exist, but measured outcome evidence is insufficient."
        ),
        evidence,
    )


def validate_anomaly_report(
    report: dict[str, Any] | None,
    *,
    minimum_cases: int,
    minimum_precision: float,
    minimum_recall: float,
    maximum_false_positive_rate: float,
    minimum_users: int = DEFAULT_MINIMUM_ANOMALY_USERS,
) -> CheckResult:
    """Require adjudicated anomaly quality before enabling anomaly actions."""
    if report is None:
        return _deferred(
            "anomaly_quality",
            "No anomaly adjudication report was supplied; collect category and merchant labels.",
        )
    if report.get("report_version") != ANOMALY_EVALUATION_VERSION:
        return _check(
            "anomaly_quality",
            False,
            "Anomaly evaluation report has an unsupported version.",
            {
                "value": report.get("report_version"),
                "required": ANOMALY_EVALUATION_VERSION,
            },
        )
    if report.get("ruleset_version") != ANOMALY_RULESET_VERSION:
        return _check(
            "anomaly_quality",
            False,
            "Anomaly evaluation report targets an unsupported ruleset.",
            {"value": report.get("ruleset_version"), "required": ANOMALY_RULESET_VERSION},
        )
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        return _check(
            "anomaly_quality",
            False,
            "Anomaly evaluation report has no aggregate metrics.",
            {},
        )
    case_count = int(metrics.get("case_count", 0))
    precision = _number(metrics, "precision")
    recall = _number(metrics, "recall")
    false_positive_rate = _number(metrics, "false_positive_rate")
    coverage = report.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
    unique_users = coverage.get("unique_users")
    unique_users_value = unique_users if type(unique_users) is int and unique_users >= 0 else 0
    kind_counts = coverage.get("kind_counts")
    if not isinstance(kind_counts, dict):
        kind_counts = {}
    kind_coverage = {
        kind: kind_counts.get(kind, 0)
        for kind in ("category", "merchant")
        if type(kind_counts.get(kind, 0)) is int and kind_counts.get(kind, 0) >= 0
    }
    representative_coverage = unique_users_value >= minimum_users and all(
        kind_coverage.get(kind, 0) > 0 for kind in ("category", "merchant")
    )
    evidence = {
        "evidence_status": report.get("evidence_status"),
        "case_count": case_count,
        "minimum_cases": minimum_cases,
        "precision": precision,
        "minimum_precision": minimum_precision,
        "recall": recall,
        "minimum_recall": minimum_recall,
        "false_positive_rate": false_positive_rate,
        "maximum_false_positive_rate": maximum_false_positive_rate,
        "unique_users": unique_users_value,
        "minimum_users": minimum_users,
        "kind_counts": kind_coverage,
        "representative_coverage": representative_coverage,
    }
    if report.get("evidence_status") != "available":
        return _deferred(
            "anomaly_quality",
            "Anomaly adjudication evidence is not yet available at the release threshold.",
            evidence,
        )
    if not representative_coverage:
        return _deferred(
            "anomaly_quality",
            "Anomaly quality evidence lacks the minimum contributing-user and category/merchant coverage.",
            evidence,
        )
    passed = (
        case_count >= minimum_cases
        and precision is not None
        and precision >= minimum_precision
        and recall is not None
        and recall >= minimum_recall
        and false_positive_rate is not None
        and false_positive_rate <= maximum_false_positive_rate
    )
    return _check(
        "anomaly_quality",
        passed,
        (
            "Adjudicated anomaly precision, recall, and false-positive rate meet release thresholds."
            if passed
            else "Adjudicated anomaly quality is below one or more release thresholds."
        ),
        evidence,
    )


def build_report(
    *,
    parser_report: dict[str, Any] | None,
    forecast_reports: list[dict[str, Any]],
    recommendation_report: dict[str, Any] | None,
    args: argparse.Namespace,
    anomaly_report: dict[str, Any] | None = None,
    balance_reconciliation_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks: list[CheckResult] = []
    if parser_report is None:
        checks.append(
            _deferred(
                "parser_quality",
                "No parser report was supplied; run evaluate_parser_corpus.py first.",
            )
        )
    else:
        checks.extend(
            validate_parser_report(
                parser_report,
                minimum_total_cases=args.minimum_total_parser_cases,
                minimum_classification_accuracy=args.minimum_classification_accuracy,
                minimum_classification_macro_recall=args.minimum_classification_macro_recall,
                minimum_critical_field_accuracy=args.minimum_critical_field_accuracy,
                minimum_representative_cases=getattr(
                    args,
                    "minimum_representative_parser_cases",
                    DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_CASES,
                ),
                minimum_representative_formats=getattr(
                    args,
                    "minimum_representative_parser_formats",
                    DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_FORMATS,
                ),
                minimum_representative_institutions=getattr(
                    args,
                    "minimum_representative_parser_institutions",
                    DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_INSTITUTIONS,
                ),
            )
        )
    checks.append(
        validate_forecast_reports(
            forecast_reports,
            minimum_users=args.minimum_forecast_users,
            minimum_periods=args.minimum_forecast_periods,
            maximum_mape_pct=args.maximum_forecast_mape_pct,
            minimum_interval_coverage_pct=getattr(
                args,
                "minimum_forecast_interval_coverage_pct",
                DEFAULT_MINIMUM_FORECAST_INTERVAL_COVERAGE_PCT,
            ),
            minimum_transaction_history_coverage_pct=getattr(
                args,
                "minimum_forecast_transaction_history_coverage_pct",
                DEFAULT_MINIMUM_FORECAST_TRANSACTION_HISTORY_COVERAGE_PCT,
            ),
            minimum_representative_users=getattr(
                args,
                "minimum_representative_forecast_users",
                DEFAULT_MINIMUM_REPRESENTATIVE_FORECAST_USERS,
            ),
        )
    )
    checks.append(
        validate_balance_reconciliation_report(
            balance_reconciliation_report,
            minimum_users=getattr(
                args,
                "minimum_reconciliation_users",
                DEFAULT_MINIMUM_RECONCILIATION_USERS,
            ),
            minimum_intervals=getattr(
                args,
                "minimum_reconciliation_intervals",
                DEFAULT_MINIMUM_RECONCILIATION_INTERVALS,
            ),
            minimum_institutions=getattr(
                args,
                "minimum_reconciliation_institutions",
                DEFAULT_MINIMUM_RECONCILIATION_INSTITUTIONS,
            ),
            maximum_median_residual_pct=getattr(
                args,
                "maximum_reconciliation_median_residual_pct",
                DEFAULT_MAXIMUM_RECONCILIATION_MEDIAN_RESIDUAL_PCT,
            ),
            maximum_p95_residual_pct=getattr(
                args,
                "maximum_reconciliation_p95_residual_pct",
                DEFAULT_MAXIMUM_RECONCILIATION_P95_RESIDUAL_PCT,
            ),
        )
    )
    checks.append(
        validate_recommendation_report(
            recommendation_report,
            minimum_cohorts=args.minimum_recommendation_cohorts,
            minimum_sample=args.minimum_recommendation_sample,
            minimum_users=args.minimum_recommendation_users,
        )
    )
    checks.append(
        validate_anomaly_report(
            anomaly_report,
            minimum_cases=args.minimum_anomaly_cases,
            minimum_users=args.minimum_anomaly_users,
            minimum_precision=args.minimum_anomaly_precision,
            minimum_recall=args.minimum_anomaly_recall,
            maximum_false_positive_rate=args.maximum_anomaly_false_positive_rate,
        )
    )

    failed = [check for check in checks if check.status == "failed"]
    deferred = [check for check in checks if check.status == "deferred"]
    status = "passed" if not failed and not deferred else "not_ready"
    if failed or (args.strict and deferred):
        status = "failed"
    return {
        "status": status,
        "strict": args.strict,
        "ruleset_version": "pfis-intelligence-release-1",
        "checks": [asdict(check) for check in checks],
        "failed_checks": [check.name for check in failed],
        "deferred_checks": [check.name for check in deferred],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parser-report", type=Path)
    parser.add_argument("--forecast-report", type=Path, action="append", default=[])
    parser.add_argument("--forecast-report-glob", type=str)
    parser.add_argument("--balance-reconciliation-report", type=Path)
    parser.add_argument("--recommendation-report", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument(
        "--minimum-total-parser-cases", type=int, default=DEFAULT_MINIMUM_TOTAL_PARSER_CASES
    )
    parser.add_argument(
        "--minimum-representative-parser-cases",
        type=int,
        default=DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_CASES,
    )
    parser.add_argument(
        "--minimum-representative-parser-formats",
        type=int,
        default=DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_FORMATS,
    )
    parser.add_argument(
        "--minimum-representative-parser-institutions",
        type=int,
        default=DEFAULT_MINIMUM_REPRESENTATIVE_PARSER_INSTITUTIONS,
    )
    parser.add_argument(
        "--minimum-classification-accuracy",
        type=float,
        default=DEFAULT_MINIMUM_CLASSIFICATION_ACCURACY,
    )
    parser.add_argument(
        "--minimum-classification-macro-recall",
        type=float,
        default=DEFAULT_MINIMUM_CLASSIFICATION_MACRO_RECALL,
    )
    parser.add_argument(
        "--minimum-critical-field-accuracy",
        type=float,
        default=DEFAULT_MINIMUM_CRITICAL_FIELD_ACCURACY,
    )
    parser.add_argument(
        "--minimum-forecast-users", type=int, default=DEFAULT_MINIMUM_FORECAST_USERS
    )
    parser.add_argument(
        "--minimum-representative-forecast-users",
        type=int,
        default=DEFAULT_MINIMUM_REPRESENTATIVE_FORECAST_USERS,
    )
    parser.add_argument(
        "--minimum-forecast-periods",
        type=int,
        default=DEFAULT_MINIMUM_FORECAST_PERIODS,
    )
    parser.add_argument(
        "--maximum-forecast-mape-pct",
        type=float,
        default=DEFAULT_MAXIMUM_FORECAST_MAPE_PCT,
    )
    parser.add_argument(
        "--minimum-forecast-interval-coverage-pct",
        type=float,
        default=DEFAULT_MINIMUM_FORECAST_INTERVAL_COVERAGE_PCT,
    )
    parser.add_argument(
        "--minimum-forecast-transaction-history-coverage-pct",
        type=float,
        default=DEFAULT_MINIMUM_FORECAST_TRANSACTION_HISTORY_COVERAGE_PCT,
    )
    parser.add_argument(
        "--minimum-reconciliation-users",
        type=int,
        default=DEFAULT_MINIMUM_RECONCILIATION_USERS,
    )
    parser.add_argument(
        "--minimum-reconciliation-intervals",
        type=int,
        default=DEFAULT_MINIMUM_RECONCILIATION_INTERVALS,
    )
    parser.add_argument(
        "--minimum-reconciliation-institutions",
        type=int,
        default=DEFAULT_MINIMUM_RECONCILIATION_INSTITUTIONS,
    )
    parser.add_argument(
        "--maximum-reconciliation-median-residual-pct",
        type=float,
        default=DEFAULT_MAXIMUM_RECONCILIATION_MEDIAN_RESIDUAL_PCT,
    )
    parser.add_argument(
        "--maximum-reconciliation-p95-residual-pct",
        type=float,
        default=DEFAULT_MAXIMUM_RECONCILIATION_P95_RESIDUAL_PCT,
    )
    parser.add_argument(
        "--minimum-recommendation-cohorts",
        type=int,
        default=DEFAULT_MINIMUM_RECOMMENDATION_COHORTS,
    )
    parser.add_argument(
        "--minimum-recommendation-sample",
        type=int,
        default=DEFAULT_MINIMUM_RECOMMENDATION_SAMPLE,
    )
    parser.add_argument(
        "--minimum-recommendation-users",
        type=int,
        default=DEFAULT_MINIMUM_RECOMMENDATION_USERS,
    )
    parser.add_argument("--anomaly-report", type=Path)
    parser.add_argument(
        "--minimum-anomaly-cases",
        type=int,
        default=DEFAULT_MINIMUM_ANOMALY_CASES,
    )
    parser.add_argument(
        "--minimum-anomaly-users",
        type=int,
        default=DEFAULT_MINIMUM_ANOMALY_USERS,
    )
    parser.add_argument(
        "--minimum-anomaly-precision",
        type=float,
        default=DEFAULT_MINIMUM_ANOMALY_PRECISION,
    )
    parser.add_argument(
        "--minimum-anomaly-recall",
        type=float,
        default=DEFAULT_MINIMUM_ANOMALY_RECALL,
    )
    parser.add_argument(
        "--maximum-anomaly-false-positive-rate",
        type=float,
        default=DEFAULT_MAXIMUM_ANOMALY_FALSE_POSITIVE_RATE,
    )
    parser.add_argument("--output", type=Path)
    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    for name in (
        "minimum_total_parser_cases",
        "minimum_representative_parser_cases",
        "minimum_representative_parser_formats",
        "minimum_representative_parser_institutions",
    ):
        if getattr(args, name) < 0:
            parser.error(f"{name.replace('_', ' ')} cannot be negative")
    for name in (
        "minimum_forecast_users",
        "minimum_representative_forecast_users",
        "minimum_forecast_periods",
        "minimum_recommendation_cohorts",
        "minimum_recommendation_sample",
        "minimum_recommendation_users",
        "minimum_anomaly_cases",
        "minimum_anomaly_users",
        "minimum_reconciliation_users",
        "minimum_reconciliation_intervals",
        "minimum_reconciliation_institutions",
    ):
        if getattr(args, name) < 1:
            parser.error(f"{name.replace('_', ' ')} must be at least 1")
    for name in (
        "minimum_classification_accuracy",
        "minimum_classification_macro_recall",
        "minimum_critical_field_accuracy",
        "maximum_forecast_mape_pct",
        "minimum_forecast_interval_coverage_pct",
        "minimum_forecast_transaction_history_coverage_pct",
        "maximum_reconciliation_median_residual_pct",
        "maximum_reconciliation_p95_residual_pct",
        "minimum_anomaly_precision",
        "minimum_anomaly_recall",
        "maximum_anomaly_false_positive_rate",
    ):
        value = getattr(args, name)
        if name == "maximum_forecast_mape_pct":
            if not 0 <= value <= DEFAULT_MAXIMUM_FORECAST_MAPE_PCT:
                parser.error(
                    f"{name.replace('_', ' ')} must be between 0 and "
                    f"{DEFAULT_MAXIMUM_FORECAST_MAPE_PCT}%"
                )
        elif name in {
            "minimum_forecast_interval_coverage_pct",
            "minimum_forecast_transaction_history_coverage_pct",
            "maximum_reconciliation_median_residual_pct",
            "maximum_reconciliation_p95_residual_pct",
        }:
            if not 0 <= value <= 100:
                parser.error(f"{name.replace('_', ' ')} must be between 0 and 100%")
        elif not 0 <= value <= 1:
            parser.error(f"{name.replace('_', ' ')} must be between 0 and 1")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)
    try:
        parser_report = _load_json(args.parser_report) if args.parser_report else None
        forecast_paths = list(args.forecast_report)
        if args.forecast_report_glob:
            forecast_paths.extend(
                Path(path) for path in sorted(glob.glob(args.forecast_report_glob))
            )
        forecast_reports = [_load_json(path) for path in forecast_paths]
        recommendation_report = (
            _load_json(args.recommendation_report) if args.recommendation_report else None
        )
        anomaly_report = _load_json(args.anomaly_report) if args.anomaly_report else None
        balance_reconciliation_report = (
            _load_json(args.balance_reconciliation_report)
            if args.balance_reconciliation_report
            else None
        )
        report = build_report(
            parser_report=parser_report,
            forecast_reports=[
                item for payload in forecast_reports for item in _forecast_reports(payload)
            ],
            recommendation_report=recommendation_report,
            args=args,
            anomaly_report=anomaly_report,
            balance_reconciliation_report=balance_reconciliation_report,
        )
    except (OSError, ValueError) as exc:
        print(f"Intelligence release gate failed: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
