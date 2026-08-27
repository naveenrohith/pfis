"""Compute PFIS product intelligence and delivery scores from a versioned manifest.

The scorecard keeps audited product intelligence, runtime workspace readiness,
product-stage readiness, product breadth, and delivery productivity separate.
It fails closed when a score is raised above its audited baseline without
hash-addressed evidence. ``--strict`` succeeds only when every non-compensating
target and the combined product promotion decision pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_VERSION = "pfis-intelligence-scorecard-manifest-1"
REPORT_VERSION = "pfis-intelligence-scorecard-report-1"
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1] / "docs" / "audit" / "intelligence-scorecard-manifest.json"
)
EVIDENCE_STATUSES = {
    "audited_baseline",
    "collecting",
    "deferred",
    "blocked",
    "passed",
    "unmeasured",
    "runtime_only",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MINIMUM_PROMOTION_SCORE = 85.0
AUDITED_MEASURE_CONTRACT: dict[str, tuple[float, float | None]] = {
    "product_breadth": (72.0, None),
    "product_stage_readiness": (58.0, 85.0),
}
INTELLIGENCE_CONTRACT: dict[str, tuple[float, float, float]] = {
    "representative_source_coverage": (12.0, 40.0, 85.0),
    "ledger_correctness": (18.0, 48.0, 90.0),
    "account_position_reconciliation": (15.0, 32.0, 90.0),
    "temporal_knowledge": (10.0, 55.0, 85.0),
    "forecasting_uncertainty": (12.0, 38.0, 80.0),
    "decision_quality": (10.0, 45.0, 80.0),
    "learning_personalization": (8.0, 25.0, 80.0),
    "query_reasoning": (5.0, 20.0, 80.0),
    "explainability_safety": (5.0, 70.0, 90.0),
    "evaluation_operations": (5.0, 55.0, 85.0),
}
DELIVERY_FLOW_CONTRACT: dict[str, tuple[float, float]] = {
    "integration_hygiene": (25.0, 85.0),
    "first_pass_verification": (20.0, 85.0),
    "lead_time_wip_age": (20.0, 85.0),
    "evidence_conversion": (20.0, 85.0),
    "operational_completeness": (15.0, 85.0),
}


def load_manifest(path: Path) -> dict[str, Any]:
    """Load one JSON scorecard manifest without accepting non-object roots."""

    if not path.is_file():
        raise ValueError(f"Scorecard manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Scorecard manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Scorecard manifest must contain a JSON object")
    return payload


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _objects(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, dict) for item in value)
    ):
        raise ValueError(f"{key} must be a non-empty list of objects")
    return value


def _text(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _score(
    payload: dict[str, Any], key: str, context: str, *, optional: bool = False
) -> float | None:
    value = payload.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError(f"{context}.{key} must be a number between 0 and 100")
    return float(value)


def _weight(payload: dict[str, Any], context: str) -> float:
    value = _score(payload, "weight", context)
    assert value is not None
    if value <= 0:
        raise ValueError(f"{context}.weight must be greater than zero")
    return value


def _status(payload: dict[str, Any], context: str) -> str:
    value = payload.get("evidence_status")
    if value not in EVIDENCE_STATUSES:
        raise ValueError(
            f"{context}.evidence_status must be one of {', '.join(sorted(EVIDENCE_STATUSES))}"
        )
    return str(value)


def _blockers(payload: dict[str, Any], context: str) -> list[str]:
    value = payload.get("blockers", [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{context}.blockers must be a list of non-empty strings")
    return [item.strip() for item in value]


def _validate_timestamp(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty ISO-8601 timestamp")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{context} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{context} must include a timezone")
    return value


def _validate_evidence(
    payload: dict[str, Any],
    context: str,
    *,
    required: bool,
    representative_required: bool,
    verify_artifacts: bool,
    artifact_root: Path | None,
) -> list[dict[str, Any]]:
    evidence = payload.get("promotion_evidence", [])
    if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
        raise ValueError(f"{context}.promotion_evidence must be a list of objects")
    if required and not evidence:
        raise ValueError(f"{context} raised score requires promotion_evidence")
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(evidence):
        evidence_context = f"{context}.promotion_evidence[{index}]"
        artifact = _text(item, "artifact", evidence_context)
        digest = _text(item, "sha256", evidence_context).lower()
        if not SHA256_RE.fullmatch(digest):
            raise ValueError(f"{evidence_context}.sha256 must be a lowercase SHA-256 digest")
        observed_at = _validate_timestamp(
            item.get("observed_at"), f"{evidence_context}.observed_at"
        )
        representative = item.get("representative")
        if not isinstance(representative, bool):
            raise ValueError(f"{evidence_context}.representative must be a boolean")
        if representative_required and not representative:
            raise ValueError(f"{evidence_context} must be representative")
        if verify_artifacts:
            artifact_path = Path(artifact)
            if not artifact_path.is_absolute():
                artifact_path = (artifact_root or Path.cwd()) / artifact_path
            if not artifact_path.is_file():
                raise ValueError(f"{evidence_context}.artifact was not found: {artifact}")
            actual_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            if actual_digest != digest:
                raise ValueError(f"{evidence_context}.sha256 does not match artifact content")
        validated.append(
            {
                "artifact": artifact,
                "sha256": digest,
                "observed_at": observed_at,
                "representative": representative,
            }
        )
    return validated


def _validate_audited_measure(
    key: str,
    payload: dict[str, Any],
    *,
    verify_artifacts: bool,
    artifact_root: Path | None,
) -> dict[str, Any]:
    context = f"measures.{key}"
    label = _text(payload, "label", context)
    baseline = _score(payload, "baseline_score", context)
    current = _score(payload, "score", context)
    target = _score(payload, "target_score", context, optional=True)
    status = _status(payload, context)
    _text(payload, "baseline_source", context)
    assert baseline is not None and current is not None
    expected_baseline, expected_target = AUDITED_MEASURE_CONTRACT[key]
    if baseline != expected_baseline:
        raise ValueError(f"{context}.baseline_score must remain {expected_baseline:g}")
    if target != expected_target:
        raise ValueError(f"{context}.target_score must remain {expected_target}")
    raised = current > baseline
    if raised and status != "passed":
        raise ValueError(f"{context} raised score requires evidence_status passed")
    evidence = _validate_evidence(
        payload,
        context,
        required=raised or status == "passed",
        representative_required=False,
        verify_artifacts=verify_artifacts,
        artifact_root=artifact_root,
    )
    blockers = _blockers(payload, context)
    if status == "passed" and blockers:
        raise ValueError(f"{context} cannot pass while blockers remain")
    passed = target is not None and current >= target and status == "passed"
    return {
        "key": key,
        "label": label,
        "score": round(current, 2),
        "target_score": round(target, 2) if target is not None else None,
        "status": "passed" if passed else "audited" if target is None else "not_ready",
        "evidence_status": status,
        "promotion_evidence": evidence,
        "blockers": blockers,
    }


def _validate_workspace_measure(payload: dict[str, Any]) -> dict[str, Any]:
    context = "measures.workspace_evidence_readiness"
    if payload.get("score") is not None:
        raise ValueError(f"{context}.score must remain null; obtain it from the runtime API")
    if _status(payload, context) != "runtime_only":
        raise ValueError(f"{context}.evidence_status must be runtime_only")
    return {
        "key": "workspace_evidence_readiness",
        "label": _text(payload, "label", context),
        "score": None,
        "status": "runtime_only",
        "source": _text(payload, "source", context),
        "blockers": _blockers(payload, context),
    }


def _weighted_section(
    payload: dict[str, Any],
    *,
    section: str,
    items_key: str,
    baseline_required: bool,
    representative_required: bool,
    verify_artifacts: bool,
    artifact_root: Path | None,
    contract: Mapping[str, tuple[float, ...]],
) -> dict[str, Any]:
    minimum = _score(payload, "minimum_promotion_score", section)
    assert minimum is not None
    if minimum != MINIMUM_PROMOTION_SCORE:
        raise ValueError(
            f"{section}.minimum_promotion_score must remain {MINIMUM_PROMOTION_SCORE:g}"
        )
    items = _objects(payload, items_key)
    seen: set[str] = set()
    weights = 0.0
    current_total = 0.0
    target_total = 0.0
    measured = True
    results: list[dict[str, Any]] = []
    blockers: list[str] = []

    for index, item in enumerate(items):
        context = f"{section}.{items_key}[{index}]"
        key = _text(item, "key", context)
        if key in seen:
            raise ValueError(f"{section}.{items_key} contains duplicate key {key}")
        if key not in contract:
            raise ValueError(f"{section}.{items_key} contains unsupported key {key}")
        seen.add(key)
        label = _text(item, "label", context)
        weight = _weight(item, context)
        target = _score(item, "target_score", context)
        assert target is not None
        current = _score(item, "score", context, optional=not baseline_required)
        status = _status(item, context)
        baseline: float | None = None
        if baseline_required:
            baseline = _score(item, "baseline_score", context)
            _text(item, "baseline_source", context)
            assert baseline is not None and current is not None
            expected_weight, expected_baseline, expected_target = contract[key]
            if baseline != expected_baseline:
                raise ValueError(f"{context}.baseline_score must remain {expected_baseline:g}")
        else:
            expected_weight, expected_target = contract[key]
        if weight != expected_weight:
            raise ValueError(f"{context}.weight must remain {expected_weight:g}")
        if target != expected_target:
            raise ValueError(f"{context}.target_score must remain {expected_target:g}")
        raised = baseline is not None and current is not None and current > baseline
        if raised and status != "passed":
            raise ValueError(f"{context} raised score requires evidence_status passed")
        if status == "passed" and current is None:
            raise ValueError(f"{context} cannot pass without a measured score")
        evidence = _validate_evidence(
            item,
            context,
            required=raised or status == "passed",
            representative_required=representative_required,
            verify_artifacts=verify_artifacts,
            artifact_root=artifact_root,
        )
        item_blockers = _blockers(item, context)
        if status == "passed" and item_blockers:
            raise ValueError(f"{context} cannot pass while blockers remain")
        blockers.extend(f"{key}: {blocker}" for blocker in item_blockers)
        item_passed = current is not None and current >= target and status == "passed"
        if not item_passed and not item_blockers:
            if current is None:
                blockers.append(f"{key}: score is unmeasured")
            else:
                blockers.append(f"{key}: score {current:g} has not passed target {target:g}")
        weights += weight
        target_total += weight * target
        if current is None:
            measured = False
        else:
            current_total += weight * current
        results.append(
            {
                "key": key,
                "label": label,
                "weight": round(weight, 2),
                "score": round(current, 2) if current is not None else None,
                "target_score": round(target, 2),
                "status": (
                    "passed" if item_passed else "not_ready" if status == "passed" else status
                ),
                "evidence_status": status,
                "promotion_evidence": evidence,
                "blockers": item_blockers,
            }
        )

    if round(weights, 6) != 100:
        raise ValueError(f"{section}.{items_key} weights must sum to 100; found {weights:g}")
    missing = sorted(set(contract) - seen)
    if missing:
        raise ValueError(f"{section}.{items_key} is missing canonical keys: {', '.join(missing)}")
    weighted_score = round(current_total / 100, 2) if measured else None
    weighted_target = round(target_total / 100, 2)
    all_targets_passed = all(item["status"] == "passed" for item in results)
    passed = weighted_score is not None and weighted_score >= minimum and all_targets_passed
    if passed:
        status = "passed"
    elif not measured:
        status = "unmeasured"
    elif any(item["status"] == "blocked" for item in results):
        status = "blocked"
    else:
        status = "deferred"
    return {
        "score": weighted_score,
        "minimum_promotion_score": round(minimum, 2),
        "weighted_target_score": weighted_target,
        "status": status,
        items_key: results,
        "blockers": blockers,
    }


def build_report(
    manifest: dict[str, Any],
    *,
    strict: bool = False,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the manifest and return one non-compensating promotion report."""

    if manifest.get("schema_version") != MANIFEST_VERSION:
        raise ValueError(
            f"schema_version must be {MANIFEST_VERSION}; found {manifest.get('schema_version')!r}"
        )
    scorecard_version = _text(manifest, "scorecard_version", "manifest")
    as_of = _validate_timestamp(manifest.get("as_of"), "manifest.as_of")
    measures = _object(manifest, "measures")
    product_breadth = _validate_audited_measure(
        "product_breadth",
        _object(measures, "product_breadth"),
        verify_artifacts=strict,
        artifact_root=artifact_root,
    )
    product_stage = _validate_audited_measure(
        "product_stage_readiness",
        _object(measures, "product_stage_readiness"),
        verify_artifacts=strict,
        artifact_root=artifact_root,
    )
    workspace = _validate_workspace_measure(_object(measures, "workspace_evidence_readiness"))
    intelligence = _weighted_section(
        _object(manifest, "intelligence"),
        section="intelligence",
        items_key="dimensions",
        baseline_required=True,
        representative_required=True,
        verify_artifacts=strict,
        artifact_root=artifact_root,
        contract=INTELLIGENCE_CONTRACT,
    )
    delivery_flow = _weighted_section(
        _object(manifest, "delivery_flow"),
        section="delivery_flow",
        items_key="components",
        baseline_required=False,
        representative_required=False,
        verify_artifacts=strict,
        artifact_root=artifact_root,
        contract=DELIVERY_FLOW_CONTRACT,
    )
    promotion_passed = (
        intelligence["status"] == "passed"
        and delivery_flow["status"] == "passed"
        and product_stage["status"] == "passed"
    )
    promotion_blockers = [
        *([] if intelligence["status"] == "passed" else intelligence["blockers"]),
        *([] if delivery_flow["status"] == "passed" else delivery_flow["blockers"]),
        *([] if product_stage["status"] == "passed" else product_stage["blockers"]),
    ]
    return {
        "schema_version": REPORT_VERSION,
        "scorecard_version": scorecard_version,
        "as_of": as_of,
        "strict": strict,
        "measures": {
            "product_breadth": product_breadth,
            "evidence_backed_product_intelligence": intelligence,
            "workspace_evidence_readiness": workspace,
            "product_stage_readiness": product_stage,
            "delivery_productivity": delivery_flow,
        },
        "promotion": {
            "status": "approved" if promotion_passed else "not_ready",
            "non_compensating_gates_passed": promotion_passed,
            "blockers": promotion_blockers,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless intelligence, product-stage, and delivery gates all pass.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = build_report(
            load_manifest(args.manifest),
            strict=args.strict,
            artifact_root=args.manifest.resolve().parent,
        )
    except (OSError, ValueError) as exc:
        print(f"Intelligence scorecard failed: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 1 if args.strict and report["promotion"]["status"] != "approved" else 0


if __name__ == "__main__":
    raise SystemExit(main())
