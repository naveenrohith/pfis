"""Evaluate adjudicated category/merchant anomaly signals for release evidence.

The runtime anomaly service deliberately emits review prompts, not fraud claims.
This evaluator keeps that boundary measurable: each case records whether PFIS
raised a signal and whether a reviewer judged the departure material. The report
is privacy-safe and contains counts/rates only; source text and transaction
identifiers stay in the protected adjudication system.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPORT_VERSION = "pfis-anomaly-evaluation-1"
RULESET_VERSION = "pfis-anomaly-2"
KINDS = ("category", "merchant")


def _load_cases(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Anomaly adjudication file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Anomaly adjudication version must be 1")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Anomaly adjudication file must contain a cases list")
    coverage = payload.get("coverage")
    return (
        [_validate_case(case, index) for index, case in enumerate(cases, start=1)],
        coverage if isinstance(coverage, dict) else None,
    )


def _validate_case(case: Any, index: int) -> dict[str, Any]:
    if not isinstance(case, dict):
        raise ValueError(f"Anomaly case {index} must be an object")
    kind = case.get("kind")
    if kind not in KINDS:
        raise ValueError(f"Anomaly case {index} has unsupported kind: {kind!r}")
    required = ("predicted_alert", "adjudicated_material")
    if any(type(case.get(field)) is not bool for field in required):
        raise ValueError(
            f"Anomaly case {index} must provide boolean predicted_alert and adjudicated_material"
        )
    return {
        "kind": kind,
        "predicted_alert": case["predicted_alert"],
        "adjudicated_material": case["adjudicated_material"],
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    for case in cases:
        predicted = case["predicted_alert"]
        material = case["adjudicated_material"]
        counts[
            (
                "true_positive"
                if predicted and material
                else (
                    "false_positive"
                    if predicted
                    else "false_negative" if material else "true_negative"
                )
            )
        ] += 1

    true_positive = counts["true_positive"]
    false_positive = counts["false_positive"]
    false_negative = counts["false_negative"]
    true_negative = counts["true_negative"]
    return {
        "case_count": len(cases),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": _ratio(true_positive, true_positive + false_positive),
        "recall": _ratio(true_positive, true_positive + false_negative),
        "false_positive_rate": _ratio(false_positive, false_positive + true_negative),
        "false_negative_rate": _ratio(false_negative, false_negative + true_positive),
    }


def build_report(
    cases: list[dict[str, Any]], coverage: dict[str, Any] | None = None
) -> dict[str, Any]:
    by_kind = {kind: _metrics([case for case in cases if case["kind"] == kind]) for kind in KINDS}
    predicted_counts = {
        str(value): sum(1 for case in cases if case["predicted_alert"] is value)
        for value in (True, False)
    }
    adjudicated_counts = {
        str(value): sum(1 for case in cases if case["adjudicated_material"] is value)
        for value in (True, False)
    }
    balanced_prediction_evidence = all(predicted_counts[str(value)] > 0 for value in (True, False))
    balanced_adjudication_evidence = all(
        adjudicated_counts[str(value)] > 0 for value in (True, False)
    )
    report_coverage = dict(coverage) if coverage is not None else {}
    report_coverage.setdefault("kind_counts", dict(sorted(by_kind.items())))
    return {
        "report_version": REPORT_VERSION,
        "ruleset_version": RULESET_VERSION,
        "evidence_status": (
            "available"
            if cases and balanced_prediction_evidence and balanced_adjudication_evidence
            else "deferred"
        ),
        "metrics": _metrics(cases),
        "by_kind": by_kind,
        "coverage": {
            **report_coverage,
            "predicted_alert_counts": predicted_counts,
            "adjudicated_material_counts": adjudicated_counts,
            "balanced_prediction_evidence": balanced_prediction_evidence,
            "balanced_adjudication_evidence": balanced_adjudication_evidence,
        },
        "limitations": [
            "Adjudication labels material departures; they do not prove fraud or causality.",
            "Cases must be sampled across users, months, categories, and merchants before release credit is valid.",
            "Signals with insufficient history should be represented as non-alert cases rather than silently omitted; an all-alert artifact cannot establish recall or false-positive rate.",
        ],
    }


def _metric_or_zero(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Version-1 anomaly adjudication JSON")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-cases", type=int, default=50)
    parser.add_argument("--minimum-precision", type=float, default=0.90)
    parser.add_argument("--minimum-recall", type=float, default=0.80)
    parser.add_argument("--maximum-false-positive-rate", type=float, default=0.10)
    args = parser.parse_args()
    if args.minimum_cases < 1:
        parser.error("minimum-cases must be at least 1")
    for name in ("minimum_precision", "minimum_recall", "maximum_false_positive_rate"):
        value = getattr(args, name)
        if not 0 <= value <= 1:
            parser.error(f"{name.replace('_', ' ')} must be between 0 and 1")

    try:
        cases, coverage = _load_cases(args.input)
        report = build_report(cases, coverage)
    except ValueError as exc:
        print(f"Anomaly evaluation failed: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)

    metrics = report["metrics"]
    passed = (
        metrics["case_count"] >= args.minimum_cases
        and _metric_or_zero(metrics, "precision") >= args.minimum_precision
        and _metric_or_zero(metrics, "recall") >= args.minimum_recall
        and _metric_or_zero(metrics, "false_positive_rate") <= args.maximum_false_positive_rate
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
