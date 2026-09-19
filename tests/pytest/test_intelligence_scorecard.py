"""Deterministic tests for the canonical PFIS intelligence scorecard."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from scripts.intelligence_scorecard import DEFAULT_MANIFEST, build_report, load_manifest, main

EVIDENCE = {
    "artifact": "protected/evidence.json",
    "sha256": "a" * 64,
    "observed_at": "2026-08-09T00:00:00Z",
    "representative": True,
}


def baseline_manifest() -> dict[str, Any]:
    return load_manifest(DEFAULT_MANIFEST)


def test_baseline_scorecard_keeps_product_workspace_and_delivery_scores_separate():
    report = build_report(baseline_manifest())
    measures = report["measures"]

    assert measures["product_breadth"]["score"] == 72
    assert measures["evidence_backed_product_intelligence"]["score"] == 42.05
    assert measures["evidence_backed_product_intelligence"]["weighted_target_score"] == 85.15
    assert measures["workspace_evidence_readiness"]["score"] is None
    assert measures["workspace_evidence_readiness"]["status"] == "runtime_only"
    assert measures["product_stage_readiness"]["score"] == 58
    assert measures["delivery_productivity"]["score"] is None
    assert measures["delivery_productivity"]["status"] == "unmeasured"
    assert report["promotion"]["status"] == "not_ready"
    assert report["promotion"]["non_compensating_gates_passed"] is False


def test_scorecard_rejects_invalid_dimension_weights():
    manifest = baseline_manifest()
    manifest["intelligence"]["dimensions"][0]["weight"] = 11

    with pytest.raises(ValueError, match="weight must remain 12"):
        build_report(manifest)


def test_scorecard_rejects_silently_lowered_targets_or_promotion_floor():
    manifest = baseline_manifest()
    manifest["intelligence"]["dimensions"][0]["target_score"] = 80
    with pytest.raises(ValueError, match="target_score must remain 85"):
        build_report(manifest)

    manifest = baseline_manifest()
    manifest["delivery_flow"]["minimum_promotion_score"] = 80
    with pytest.raises(ValueError, match="minimum_promotion_score must remain 85"):
        build_report(manifest)


def test_scorecard_rejects_score_increase_without_passed_evidence():
    manifest = baseline_manifest()
    dimension = manifest["intelligence"]["dimensions"][0]
    dimension["score"] = dimension["baseline_score"] + 1

    with pytest.raises(ValueError, match="raised score requires evidence_status passed"):
        build_report(manifest)


def test_intelligence_score_increase_requires_representative_hash_addressed_evidence():
    manifest = baseline_manifest()
    dimension = manifest["intelligence"]["dimensions"][0]
    dimension["score"] = dimension["baseline_score"] + 1
    dimension["evidence_status"] = "passed"
    dimension["promotion_evidence"] = [{**EVIDENCE, "representative": False}]

    with pytest.raises(ValueError, match="must be representative"):
        build_report(manifest)

    dimension["promotion_evidence"] = [{**EVIDENCE, "sha256": "not-a-digest"}]
    with pytest.raises(ValueError, match="SHA-256"):
        build_report(manifest)


def test_scorecard_approves_only_when_every_non_compensating_gate_passes(tmp_path):
    manifest = copy.deepcopy(baseline_manifest())
    artifact = tmp_path / "evidence.json"
    artifact.write_text('{"status":"passed"}\n', encoding="utf-8")
    evidence = {
        **EVIDENCE,
        "artifact": artifact.name,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    product_stage = manifest["measures"]["product_stage_readiness"]
    product_stage["score"] = product_stage["target_score"]
    product_stage["evidence_status"] = "passed"
    product_stage["promotion_evidence"] = [evidence]
    product_stage["blockers"] = []

    for dimension in manifest["intelligence"]["dimensions"]:
        dimension["score"] = dimension["target_score"]
        dimension["evidence_status"] = "passed"
        dimension["promotion_evidence"] = [evidence]
        dimension["blockers"] = []
    for component in manifest["delivery_flow"]["components"]:
        component["score"] = component["target_score"]
        component["evidence_status"] = "passed"
        component["promotion_evidence"] = [evidence]
        component["blockers"] = []

    report = build_report(manifest, strict=True, artifact_root=tmp_path)

    assert report["measures"]["evidence_backed_product_intelligence"]["score"] == 85.15
    assert report["measures"]["delivery_productivity"]["score"] == 85
    assert report["promotion"] == {
        "status": "approved",
        "non_compensating_gates_passed": True,
        "blockers": [],
    }


def test_scorecard_does_not_compensate_for_one_dimension_below_its_target():
    manifest = copy.deepcopy(baseline_manifest())
    product_stage = manifest["measures"]["product_stage_readiness"]
    product_stage["score"] = product_stage["target_score"]
    product_stage["evidence_status"] = "passed"
    product_stage["promotion_evidence"] = [EVIDENCE]
    product_stage["blockers"] = []

    for dimension in manifest["intelligence"]["dimensions"]:
        dimension["score"] = dimension["target_score"]
        dimension["evidence_status"] = "passed"
        dimension["promotion_evidence"] = [EVIDENCE]
        dimension["blockers"] = []
    manifest["intelligence"]["dimensions"][8]["score"] = 89
    for component in manifest["delivery_flow"]["components"]:
        component["score"] = component["target_score"]
        component["evidence_status"] = "passed"
        component["promotion_evidence"] = [EVIDENCE]
        component["blockers"] = []

    report = build_report(manifest)

    assert report["measures"]["evidence_backed_product_intelligence"]["score"] == 85.1
    assert report["measures"]["evidence_backed_product_intelligence"]["status"] == "deferred"
    assert report["promotion"]["status"] == "not_ready"


def test_scorecard_rejects_passed_status_while_blockers_remain():
    manifest = baseline_manifest()
    dimension = manifest["intelligence"]["dimensions"][0]
    dimension["score"] = dimension["target_score"]
    dimension["evidence_status"] = "passed"
    dimension["promotion_evidence"] = [EVIDENCE]

    with pytest.raises(ValueError, match="cannot pass while blockers remain"):
        build_report(manifest)


def test_strict_scorecard_rejects_missing_or_mismatched_evidence_artifact(tmp_path):
    manifest = baseline_manifest()
    dimension = manifest["intelligence"]["dimensions"][0]
    dimension["score"] = dimension["target_score"]
    dimension["evidence_status"] = "passed"
    dimension["blockers"] = []
    dimension["promotion_evidence"] = [EVIDENCE]

    with pytest.raises(ValueError, match="artifact was not found"):
        build_report(manifest, strict=True, artifact_root=tmp_path)

    artifact = tmp_path / "evidence.json"
    artifact.write_text('{"status":"passed"}\n', encoding="utf-8")
    dimension["promotion_evidence"] = [{**EVIDENCE, "artifact": artifact.name}]
    with pytest.raises(ValueError, match="does not match artifact content"):
        build_report(manifest, strict=True, artifact_root=tmp_path)


def test_scorecard_cli_writes_audit_report_and_strict_mode_fails_closed(
    tmp_path, monkeypatch, capsys
):
    output = tmp_path / "scorecard.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "intelligence_scorecard.py",
            "--manifest",
            str(DEFAULT_MANIFEST),
            "--output",
            str(output),
        ],
    )
    assert main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["promotion"]["status"] == "not_ready"

    monkeypatch.setattr(
        "sys.argv",
        ["intelligence_scorecard.py", "--manifest", str(DEFAULT_MANIFEST), "--strict"],
    )
    assert main() == 1
    assert '"status": "not_ready"' in capsys.readouterr().out
