"""Deterministic quality scoring for sanitized parser and classifier corpora."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from enum import Enum
from typing import Any

from app.services.classification import KNOWN_BANK_SENDERS, classify_source_record
from app.services.parser.registry import get_parser_registry

REPORT_VERSION = 2
SUPPORT_POLICY_VERSION = 1
COHORT_MANIFEST_VERSION = 1
DEFAULT_CASE_COHORT = "synthetic_fixture"
REPRESENTATIVE_COHORTS = frozenset({"sanitized_production", "production_safe"})
TRANSACTION_FIELDS = (
    "bank",
    "amount",
    "transaction_type",
    "merchant_raw",
    "date",
    "transaction_timestamp",
    "account_last4",
    "reference_id",
    "payment_method",
    "payment_rail",
    "card_event",
    "transaction_status",
    "used_fallback",
)


def _public_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rate(correct: int, total: int) -> float | None:
    return round(correct / total, 4) if total else None


def _support_tier(
    case_count: int,
    exact_accuracy: float,
    format_count: int,
    dedicated_parser_rate: float | None,
) -> str:
    if (
        case_count >= 20
        and format_count >= 3
        and exact_accuracy >= 0.98
        and (dedicated_parser_rate or 0.0) >= 0.95
    ):
        return "verified"
    if (
        case_count >= 5
        and format_count >= 2
        and exact_accuracy >= 0.95
        and (dedicated_parser_rate or 0.0) >= 0.80
    ):
        return "supported"
    if case_count:
        return "best_effort"
    return "unsupported"


def _case_cohort(case: dict[str, Any], cohort_assignments: dict[str, str] | None = None) -> str:
    """Return a manifest-owned cohort, falling back to fixture labels for local reports."""

    if cohort_assignments is not None:
        assigned = cohort_assignments.get(str(case.get("id")))
        if assigned:
            return assigned
        # A manifest is authoritative: cases absent from it are not representative.
        return DEFAULT_CASE_COHORT

    value = case.get("cohort")
    return str(value).strip() if value and str(value).strip() else DEFAULT_CASE_COHORT


def _manifest_fingerprint(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_cohort_manifest(
    manifest: dict[str, Any] | None,
    *,
    corpus_fingerprint: str,
    cases: list[dict[str, Any]],
) -> tuple[dict[str, str] | None, dict[str, Any]]:
    """Validate independent representative-cohort metadata without exposing case bodies."""

    if manifest is None:
        return None, {
            "status": "not_supplied",
            "version": COHORT_MANIFEST_VERSION,
            "case_count": 0,
            "corpus_fingerprint": corpus_fingerprint,
        }
    if not isinstance(manifest, dict):
        return None, {
            "status": "invalid",
            "version": None,
            "case_count": 0,
            "corpus_fingerprint": corpus_fingerprint,
            "reason": "manifest must be a JSON object",
        }

    reason: str | None = None
    if manifest.get("version") != COHORT_MANIFEST_VERSION:
        reason = "unsupported manifest version"
    elif manifest.get("corpus_fingerprint") != corpus_fingerprint:
        reason = "manifest corpus fingerprint does not match the evaluated corpus"
    entries = manifest.get("cases")
    if reason is None and (not isinstance(entries, list) or not entries):
        reason = "manifest cases must be a non-empty list"
    manifest_entries: list[Any] = entries if isinstance(entries, list) else []

    known_ids = {str(case.get("id")) for case in cases}
    assignments: dict[str, str] = {}
    if reason is None:
        for entry in manifest_entries:
            if not isinstance(entry, dict):
                reason = "manifest cases must contain objects"
                break
            case_id = str(entry.get("id") or "").strip()
            cohort = str(entry.get("cohort") or "").strip()
            if not case_id or case_id not in known_ids:
                reason = "manifest references an unknown case id"
                break
            if case_id in assignments:
                reason = "manifest contains duplicate case ids"
                break
            if cohort not in REPRESENTATIVE_COHORTS:
                reason = "manifest cohort must be sanitized_production or production_safe"
                break
            assignments[case_id] = cohort

    attestation = manifest.get("attestation")
    if reason is None and not isinstance(attestation, dict):
        reason = "manifest attestation is required"
    manifest_attestation: dict[str, Any] = attestation if isinstance(attestation, dict) else {}
    if reason is None:
        if manifest_attestation.get("deidentified") is not True:
            reason = "manifest attestation must confirm de-identification"
        elif manifest_attestation.get("reviewed") is not True:
            reason = "manifest attestation must confirm independent review"
        elif not str(manifest_attestation.get("reviewer_id") or "").strip():
            reason = "manifest attestation reviewer_id is required"
        else:
            reviewed_at = str(manifest_attestation.get("reviewed_at") or "").strip()
            try:
                datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError:
                reason = "manifest attestation reviewed_at must be ISO-8601"

    evidence = {
        "status": "invalid" if reason else "verified",
        "version": manifest.get("version"),
        "case_count": len(assignments),
        "corpus_fingerprint": corpus_fingerprint,
        "manifest_fingerprint": _manifest_fingerprint(manifest),
    }
    if reason:
        evidence["reason"] = reason
        return None, evidence
    return assignments, evidence


def _cohort_report(records: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Serialize cohort accumulators without exposing case bodies."""

    return {
        cohort: {
            "case_count": int(values["case_count"]),
            "exact_count": int(values["exact_count"]),
            "exact_accuracy": _rate(values["exact_count"], values["case_count"]) or 0.0,
            "format_count": len(values["formats"]),
            "institution_count": len(values["institutions"]),
        }
        for cohort, values in sorted(records.items())
    }


def _representative_cohort_evidence(
    transaction_cohorts: dict[str, dict[str, Any]],
    classification_cohorts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Combine extraction/classification cohort coverage for the release gate."""

    merged: dict[str, dict[str, int | float]] = {}
    for cohort in sorted(set(transaction_cohorts) | set(classification_cohorts)):
        extraction = transaction_cohorts.get(cohort, {})
        classification = classification_cohorts.get(cohort, {})
        case_count = int(extraction.get("case_count", 0)) + int(classification.get("case_count", 0))
        exact_count = int(extraction.get("exact_count", 0)) + int(
            classification.get("exact_count", 0)
        )
        merged[cohort] = {
            "case_count": case_count,
            "exact_count": exact_count,
            "exact_accuracy": _rate(exact_count, case_count) or 0.0,
            "format_count": max(
                int(extraction.get("format_count", 0)),
                int(classification.get("format_count", 0)),
            ),
            "institution_count": max(
                int(extraction.get("institution_count", 0)),
                int(classification.get("institution_count", 0)),
            ),
        }
    representative = [
        values for cohort, values in merged.items() if cohort in REPRESENTATIVE_COHORTS
    ]
    return {
        "representative_cohorts": sorted(REPRESENTATIVE_COHORTS),
        "representative_case_count": sum(int(item["case_count"]) for item in representative),
        "representative_format_count": sum(int(item["format_count"]) for item in representative),
        "representative_institution_count": sum(
            int(item["institution_count"]) for item in representative
        ),
        "cohorts": merged,
    }


def evaluate_transaction_cases(
    cases: list[dict[str, Any]],
    *,
    cohort_assignments: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Score extraction accuracy, fallback use, and confidence calibration."""
    registry = get_parser_registry()
    field_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    institutions: dict[str, dict[str, int]] = defaultdict(
        lambda: {"cases": 0, "exact": 0, "dedicated": 0}
    )
    institution_formats: dict[str, set[str]] = defaultdict(set)
    parser_versions: dict[str, int] = defaultdict(int)
    format_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"cases": 0, "exact": 0})
    cohort_records: dict[str, dict[str, Any]] = {}
    case_results: list[dict[str, Any]] = []
    exact_count = 0
    fallback_count = 0
    fallback_exact_count = 0
    calibration_error_total = 0.0
    brier_total = 0.0

    for case in cases:
        result = registry.parse_email(case["sender"], case["subject"], case["body"])
        expected = case["expected"]
        comparisons: dict[str, bool] = {}
        for field in TRANSACTION_FIELDS:
            if field not in expected:
                continue
            actual = _public_value(getattr(result, field))
            wanted = _public_value(expected[field])
            matches = actual == wanted
            comparisons[field] = matches
            field_counts[field]["total"] += 1
            field_counts[field]["correct"] += int(matches)

        confidence_ok = result.confidence_score >= float(expected.get("min_confidence", 0))
        exact = all(comparisons.values()) and confidence_ok
        exact_count += int(exact)
        fallback_count += int(result.used_fallback)
        fallback_exact_count += int(result.used_fallback and exact)

        field_correctness = sum(comparisons.values()) / len(comparisons) if comparisons else 0.0
        calibration_error_total += abs(result.confidence_score - field_correctness)
        brier_total += (result.confidence_score - field_correctness) ** 2

        institution = str(expected.get("bank") or result.bank or "UNKNOWN")
        format_id = str(case.get("format_id") or case["id"])
        cohort = _case_cohort(case, cohort_assignments)
        cohort_record = cohort_records.setdefault(
            cohort,
            {"case_count": 0, "exact_count": 0, "formats": set(), "institutions": set()},
        )
        cohort_record["case_count"] += 1
        cohort_record["exact_count"] += int(exact)
        cohort_record["formats"].add(format_id)
        cohort_record["institutions"].add(institution)
        institutions[institution]["cases"] += 1
        institutions[institution]["exact"] += int(exact)
        institutions[institution]["dedicated"] += int(not result.used_fallback)
        institution_formats[institution].add(format_id)
        parser_key = f"{result.parser_name}:v{result.parser_version}"
        parser_versions[parser_key] += 1
        format_counts[format_id]["cases"] += 1
        format_counts[format_id]["exact"] += int(exact)
        case_results.append(
            {
                "id": case["id"],
                "cohort": cohort,
                "format_id": format_id,
                "institution": institution,
                "exact": exact,
                "confidence": round(result.confidence_score, 4),
                "field_correctness": round(field_correctness, 4),
                "used_fallback": result.used_fallback,
                "parser_name": result.parser_name,
                "parser_version": result.parser_version,
                "failed_fields": [field for field, matches in comparisons.items() if not matches],
                "confidence_threshold_met": confidence_ok,
            }
        )

    case_count = len(cases)
    exact_accuracy = _rate(exact_count, case_count) or 0.0
    institution_report = {}
    declared_institutions = sorted(set(KNOWN_BANK_SENDERS.values()) | set(institutions))
    for institution in declared_institutions:
        counts = institutions[institution]
        accuracy = _rate(counts["exact"], counts["cases"]) or 0.0
        dedicated_rate = _rate(counts["dedicated"], counts["cases"])
        format_count = len(institution_formats[institution])
        institution_report[institution] = {
            **counts,
            "format_count": format_count,
            "exact_accuracy": accuracy,
            "dedicated_parser_rate": dedicated_rate,
            "support_tier": _support_tier(counts["cases"], accuracy, format_count, dedicated_rate),
        }

    return {
        "case_count": case_count,
        "exact_count": exact_count,
        "exact_accuracy": exact_accuracy,
        "field_accuracy": {
            field: {
                **counts,
                "accuracy": _rate(counts["correct"], counts["total"]),
            }
            for field, counts in sorted(field_counts.items())
        },
        "fallback_count": fallback_count,
        "fallback_rate": _rate(fallback_count, case_count),
        "fallback_exact_accuracy": _rate(fallback_exact_count, fallback_count),
        "mean_absolute_calibration_error": (
            round(calibration_error_total / case_count, 4) if case_count else None
        ),
        "brier_score": round(brier_total / case_count, 4) if case_count else None,
        "institutions": institution_report,
        "support_tier_counts": _tier_counts(institution_report),
        "parser_versions": dict(sorted(parser_versions.items())),
        "formats": {
            format_id: {
                **counts,
                "exact_accuracy": _rate(counts["exact"], counts["cases"]),
            }
            for format_id, counts in sorted(format_counts.items())
        },
        "cohorts": _cohort_report(cohort_records),
        "cases": case_results,
    }


def evaluate_classification_cases(
    cases: list[dict[str, Any]],
    *,
    cohort_assignments: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Score source classification and institution recognition."""
    classification_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "total": 0}
    )
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    institution_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    cohort_records: dict[str, dict[str, Any]] = {}
    case_results: list[dict[str, Any]] = []
    exact_count = 0

    for case in cases:
        result = classify_source_record(case["sender"], case["subject"], case["body"])
        expected = case["expected"]
        expected_classification = str(expected["classification"])
        actual_classification = result.classification.value
        classification_ok = actual_classification == expected_classification
        institution_ok = "institution" not in expected or result.institution == str(
            expected["institution"]
        )
        exact = classification_ok and institution_ok
        exact_count += int(exact)
        classification_counts[expected_classification]["total"] += 1
        classification_counts[expected_classification]["correct"] += int(classification_ok)
        confusion[expected_classification][actual_classification] += 1
        expected_institution = expected.get("institution")
        cohort = _case_cohort(case, cohort_assignments)
        cohort_record = cohort_records.setdefault(
            cohort,
            {"case_count": 0, "exact_count": 0, "formats": set(), "institutions": set()},
        )
        cohort_record["case_count"] += 1
        cohort_record["exact_count"] += int(exact)
        cohort_record["formats"].add(str(case.get("format_id") or case["id"]))
        if expected_institution is not None:
            cohort_record["institutions"].add(str(expected_institution))
        if expected_institution is not None:
            institution = str(expected_institution)
            institution_counts[institution]["total"] += 1
            institution_counts[institution]["correct"] += int(institution_ok)
        case_results.append(
            {
                "id": case["id"],
                "cohort": cohort,
                "exact": exact,
                "expected_classification": expected_classification,
                "actual_classification": actual_classification,
                "expected_institution": expected_institution,
                "actual_institution": result.institution,
                "confidence": round(result.confidence, 4),
            }
        )

    case_count = len(cases)
    class_metrics = _classification_metrics(confusion)
    supported_metrics = [
        metric for metric in class_metrics.values() if int(metric["support"] or 0) > 0
    ]
    return {
        "case_count": case_count,
        "exact_count": exact_count,
        "exact_accuracy": _rate(exact_count, case_count) or 0.0,
        "classification_accuracy": {
            classification: {
                **counts,
                "accuracy": _rate(counts["correct"], counts["total"]),
            }
            for classification, counts in sorted(classification_counts.items())
        },
        "class_metrics": class_metrics,
        "macro_precision": _mean_metric(supported_metrics, "precision"),
        "macro_recall": _mean_metric(supported_metrics, "recall"),
        "macro_f1": _mean_metric(supported_metrics, "f1"),
        "weighted_f1": _weighted_metric(supported_metrics, "f1"),
        "institution_recognition": {
            institution: {
                **counts,
                "accuracy": _rate(counts["correct"], counts["total"]),
            }
            for institution, counts in sorted(institution_counts.items())
        },
        "confusion_matrix": {
            expected: dict(sorted(actual.items())) for expected, actual in sorted(confusion.items())
        },
        "cohorts": _cohort_report(cohort_records),
        "cases": case_results,
    }


def evaluate_corpora(
    transaction_cases: list[dict[str, Any]],
    classification_cases: list[dict[str, Any]],
    cohort_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical_corpus = json.dumps(
        {
            "transaction_cases": transaction_cases,
            "classification_cases": classification_cases,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    all_cases = [*transaction_cases, *classification_cases]
    cohort_assignments, manifest_evidence = _validate_cohort_manifest(
        cohort_manifest,
        corpus_fingerprint=hashlib.sha256(canonical_corpus).hexdigest(),
        cases=all_cases,
    )
    transaction_report = evaluate_transaction_cases(
        transaction_cases,
        cohort_assignments=cohort_assignments,
    )
    classification_report = evaluate_classification_cases(
        classification_cases,
        cohort_assignments=cohort_assignments,
    )
    cohort_evidence = _representative_cohort_evidence(
        transaction_report["cohorts"], classification_report["cohorts"]
    )
    representative_cases = [
        *[
            case
            for case in transaction_cases
            if _case_cohort(case, cohort_assignments) in REPRESENTATIVE_COHORTS
        ],
        *[
            case
            for case in classification_cases
            if _case_cohort(case, cohort_assignments) in REPRESENTATIVE_COHORTS
        ],
    ]
    representative_formats = {
        str(case.get("format_id") or case["id"])
        for case in transaction_cases
        if _case_cohort(case, cohort_assignments) in REPRESENTATIVE_COHORTS
    }
    representative_institutions = {
        institution
        for case in representative_cases
        for institution in [
            str(case.get("expected", {}).get("bank") or case.get("expected", {}).get("institution"))
        ]
        if institution.upper() not in {"UNKNOWN", "GENERIC", "NONE"}
    }
    cohort_evidence["representative_case_count"] = len(representative_cases)
    cohort_evidence["representative_format_count"] = len(representative_formats)
    cohort_evidence["representative_institution_count"] = len(representative_institutions)
    return {
        "report_version": REPORT_VERSION,
        "corpus_fingerprint": hashlib.sha256(canonical_corpus).hexdigest(),
        "support_policy": {
            "version": SUPPORT_POLICY_VERSION,
            "verified": {
                "minimum_cases": 20,
                "minimum_formats": 3,
                "minimum_exact_accuracy": 0.98,
                "minimum_dedicated_parser_rate": 0.95,
            },
            "supported": {
                "minimum_cases": 5,
                "minimum_formats": 2,
                "minimum_exact_accuracy": 0.95,
                "minimum_dedicated_parser_rate": 0.80,
            },
        },
        "transaction_extraction": transaction_report,
        "source_classification": classification_report,
        "cohort_evidence": cohort_evidence,
        "cohort_manifest": manifest_evidence,
    }


def _classification_metrics(
    confusion: dict[str, dict[str, int]],
) -> dict[str, dict[str, int | float | None]]:
    labels = sorted(set(confusion) | {actual for values in confusion.values() for actual in values})
    metrics: dict[str, dict[str, int | float | None]] = {}
    for label in labels:
        true_positive = confusion[label].get(label, 0)
        false_negative = sum(confusion[label].values()) - true_positive
        false_positive = sum(
            values.get(label, 0) for expected, values in confusion.items() if expected != label
        )
        precision = _rate(true_positive, true_positive + false_positive)
        recall = _rate(true_positive, true_positive + false_negative)
        f1 = None
        if precision is not None and recall is not None and precision + recall:
            f1 = round(2 * precision * recall / (precision + recall), 4)
        metrics[label] = {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "support": true_positive + false_negative,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return metrics


def _mean_metric(metrics: list[dict[str, Any]], key: str) -> float | None:
    values = [float(metric[key]) for metric in metrics if metric[key] is not None]
    return round(sum(values) / len(values), 4) if values else None


def _weighted_metric(metrics: list[dict[str, Any]], key: str) -> float | None:
    weighted = [
        (float(metric[key]), int(metric["support"]))
        for metric in metrics
        if metric[key] is not None
    ]
    total = sum(support for _, support in weighted)
    return round(sum(value * support for value, support in weighted) / total, 4) if total else None


def _tier_counts(institutions: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(("verified", "supported", "best_effort", "unsupported"), 0)
    for evidence in institutions.values():
        counts[str(evidence["support_tier"])] += 1
    return counts
