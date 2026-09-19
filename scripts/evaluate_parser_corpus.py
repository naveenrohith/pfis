"""Score PFIS's sanitized parser corpus and enforce accuracy thresholds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.parser.evaluation import evaluate_corpora  # noqa: E402

CORPUS_DIR = ROOT_DIR / "tests" / "parser_corpus"


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("cases"), list):
        raise ValueError(f"Unsupported corpus format: {path}")
    return payload["cases"]


def build_report(cohort_manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    return evaluate_corpora(
        _load_cases(CORPUS_DIR / "transaction_alerts.json"),
        _load_cases(CORPUS_DIR / "source_classification.json"),
        cohort_manifest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-transaction-accuracy", type=float, default=0.95)
    parser.add_argument("--minimum-classification-accuracy", type=float, default=0.95)
    parser.add_argument("--minimum-classification-macro-recall", type=float, default=0.95)
    parser.add_argument("--minimum-critical-field-accuracy", type=float, default=0.98)
    parser.add_argument("--minimum-transaction-cases", type=int, default=50)
    parser.add_argument("--minimum-classification-cases", type=int, default=50)
    parser.add_argument(
        "--cohort-manifest",
        type=Path,
        help="Independent reviewed cohort metadata; representative cases are release-eligible only when this is verified.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Optional prior report; fail when a comparable metric regresses beyond the limit.",
    )
    parser.add_argument("--maximum-accuracy-regression", type=float, default=0.0)
    args = parser.parse_args()
    for threshold in (
        args.minimum_transaction_accuracy,
        args.minimum_classification_accuracy,
        args.minimum_classification_macro_recall,
        args.minimum_critical_field_accuracy,
        args.maximum_accuracy_regression,
    ):
        if not 0 <= threshold <= 1:
            parser.error("accuracy thresholds must be between 0 and 1")
    if args.minimum_transaction_cases < 0 or args.minimum_classification_cases < 0:
        parser.error("minimum case counts cannot be negative")

    cohort_manifest = None
    if args.cohort_manifest:
        try:
            cohort_manifest = json.loads(args.cohort_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"cohort manifest is not valid JSON: {exc}")
    report = build_report(cohort_manifest)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)

    if report.get("cohort_manifest", {}).get("status") == "invalid":
        print(
            "cohort manifest is invalid; representative evidence was not accepted", file=sys.stderr
        )
        return 1

    transaction_accuracy = report["transaction_extraction"]["exact_accuracy"]
    classification_accuracy = report["source_classification"]["exact_accuracy"]
    classification_recall = report["source_classification"]["macro_recall"] or 0.0
    critical_field_accuracies = [
        evidence["accuracy"]
        for field, evidence in report["transaction_extraction"]["field_accuracy"].items()
        if field in {"amount", "transaction_type", "date", "account_last4"}
        and evidence["accuracy"] is not None
    ]
    critical_field_accuracy = min(critical_field_accuracies, default=0.0)
    regression_failures: list[str] = []
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        regression_failures = _find_regressions(
            report,
            baseline,
            args.maximum_accuracy_regression,
        )
        for failure in regression_failures:
            print(f"quality regression: {failure}", file=sys.stderr)
    if (
        transaction_accuracy < args.minimum_transaction_accuracy
        or classification_accuracy < args.minimum_classification_accuracy
        or classification_recall < args.minimum_classification_macro_recall
        or critical_field_accuracy < args.minimum_critical_field_accuracy
        or report["transaction_extraction"]["case_count"] < args.minimum_transaction_cases
        or report["source_classification"]["case_count"] < args.minimum_classification_cases
        or regression_failures
    ):
        return 1
    return 0


def _find_regressions(
    current: dict[str, Any],
    baseline: dict[str, Any],
    maximum_drop: float,
) -> list[str]:
    comparable: dict[str, tuple[float | None, float | None]] = {
        "transaction exact accuracy": (
            current["transaction_extraction"].get("exact_accuracy"),
            baseline.get("transaction_extraction", {}).get("exact_accuracy"),
        ),
        "classification exact accuracy": (
            current["source_classification"].get("exact_accuracy"),
            baseline.get("source_classification", {}).get("exact_accuracy"),
        ),
        "classification macro recall": (
            current["source_classification"].get("macro_recall"),
            baseline.get("source_classification", {}).get("macro_recall"),
        ),
    }
    current_fields = current["transaction_extraction"].get("field_accuracy", {})
    baseline_fields = baseline.get("transaction_extraction", {}).get("field_accuracy", {})
    for field in sorted(set(current_fields) & set(baseline_fields)):
        comparable[f"field {field} accuracy"] = (
            current_fields[field].get("accuracy"),
            baseline_fields[field].get("accuracy"),
        )

    failures = []
    for label, (current_value, baseline_value) in comparable.items():
        if current_value is None or baseline_value is None:
            continue
        drop = float(baseline_value) - float(current_value)
        if drop > maximum_drop + 1e-12:
            failures.append(f"{label} dropped from {baseline_value:.4f} to {current_value:.4f}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
