"""Quality metrics for the sanitized parser and classification corpora."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.parser.evaluation import (
    evaluate_classification_cases,
    evaluate_corpora,
    evaluate_transaction_cases,
)

from scripts.evaluate_parser_corpus import _find_regressions

CORPUS_DIR = Path(__file__).resolve().parents[1] / "parser_corpus"


def _cases(name: str) -> list[dict]:
    payload = json.loads((CORPUS_DIR / name).read_text(encoding="utf-8"))
    assert payload["version"] == 1
    return payload["cases"]


def test_transaction_corpus_publishes_accuracy_fallback_and_calibration_metrics():
    report = evaluate_transaction_cases(_cases("transaction_alerts.json"))

    assert report["case_count"] >= 4
    assert report["exact_accuracy"] == 1.0
    assert report["field_accuracy"]["amount"]["accuracy"] == 1.0
    assert report["fallback_count"] >= 1
    assert report["fallback_rate"] is not None
    assert report["mean_absolute_calibration_error"] is not None
    assert report["parser_versions"]
    assert report["formats"]
    assert report["institutions"]["HDFC"]["support_tier"] in {
        "best_effort",
        "supported",
        "verified",
    }
    assert report["institutions"]["GENERIC"]["support_tier"] == "best_effort"
    assert report["institutions"]["GENERIC"]["dedicated_parser_rate"] == 0.0
    assert report["support_tier_counts"]["unsupported"] == 0


def test_transaction_evaluation_identifies_the_incorrect_field():
    case = {
        "id": "intentional-mismatch",
        "sender": "alerts@example-payments.test",
        "subject": "Payment successful",
        "body": "Payment of Rs.750.00 to BOOKMYSHOW via UPI on 07-05-2026.",
        "expected": {
            "bank": "GENERIC",
            "amount": 751.0,
            "transaction_type": "debit",
            "merchant_raw": "BOOKMYSHOW",
            "min_confidence": 0.5,
        },
    }

    report = evaluate_transaction_cases([case])

    assert report["exact_accuracy"] == 0.0
    assert report["field_accuracy"]["amount"]["accuracy"] == 0.0
    assert report["cases"][0]["failed_fields"] == ["amount"]


def test_classification_corpus_publishes_per_class_and_confusion_metrics():
    report = evaluate_classification_cases(_cases("source_classification.json"))

    assert report["case_count"] >= 10
    assert report["exact_accuracy"] >= 0.95
    assert report["classification_accuracy"]["transaction"]["accuracy"] == 1.0
    assert report["confusion_matrix"]["transaction"]["transaction"] >= 1
    transaction_metrics = report["class_metrics"]["transaction"]
    assert transaction_metrics["support"] >= 5
    assert transaction_metrics["true_positive"] == transaction_metrics["support"]
    assert transaction_metrics["false_positive"] == 0
    assert transaction_metrics["false_negative"] == 0
    assert transaction_metrics["precision"] == 1.0
    assert transaction_metrics["recall"] == 1.0
    assert transaction_metrics["f1"] == 1.0
    assert report["macro_recall"] == 1.0
    assert report["weighted_f1"] == 1.0
    assert report["institution_recognition"]["HDFC"]["accuracy"] == 1.0


def test_corpus_report_is_versioned_and_content_addressed():
    transaction_cases = _cases("transaction_alerts.json")
    classification_cases = _cases("source_classification.json")

    first = evaluate_corpora(transaction_cases, classification_cases)
    second = evaluate_corpora(transaction_cases, classification_cases)
    changed = evaluate_corpora(transaction_cases[:-1], classification_cases)

    assert first["report_version"] == 2
    assert first["corpus_fingerprint"] == second["corpus_fingerprint"]
    assert first["corpus_fingerprint"] != changed["corpus_fingerprint"]
    assert first["support_policy"]["verified"]["minimum_cases"] == 20
    assert first["support_policy"]["supported"]["minimum_dedicated_parser_rate"] == 0.80


def test_baseline_comparison_reports_overall_and_field_regressions():
    baseline = {
        "transaction_extraction": {
            "exact_accuracy": 1.0,
            "field_accuracy": {"amount": {"accuracy": 1.0}},
        },
        "source_classification": {"exact_accuracy": 1.0, "macro_recall": 1.0},
    }
    current = {
        "transaction_extraction": {
            "exact_accuracy": 0.9,
            "field_accuracy": {"amount": {"accuracy": 0.8}},
        },
        "source_classification": {"exact_accuracy": 0.95, "macro_recall": 1.0},
    }

    failures = _find_regressions(current, baseline, maximum_drop=0.05)

    assert failures == [
        "transaction exact accuracy dropped from 1.0000 to 0.9000",
        "field amount accuracy dropped from 1.0000 to 0.8000",
    ]
