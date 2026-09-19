import hashlib
import json
from pathlib import Path

from scripts.build_promotion_manifest import REQUIRED_EVIDENCE, build_manifest


def _scorecard(*, strict: bool, status: str = "approved") -> dict:
    return {
        "scorecard_version": "2026-08-09",
        "strict": strict,
        "measures": {
            "evidence_backed_product_intelligence": {"score": 85},
            "delivery_productivity": {"score": 85},
        },
        "promotion": {
            "status": status,
            "blockers": [] if status == "approved" else ["evidence is incomplete"],
        },
    }


def test_promotion_manifest_hashes_artifacts_and_defers_missing_evidence(tmp_path: Path):
    scorecard_path = tmp_path / "scorecard.json"
    scorecard_path.write_text(json.dumps(_scorecard(strict=False)), encoding="utf-8")
    parser_path = tmp_path / "parser.json"
    parser_path.write_text('{"status":"passed"}', encoding="utf-8")

    manifest = build_manifest(
        repo_root=tmp_path,
        output=tmp_path / "promotion.json",
        evidence_root=tmp_path,
        scorecard_report=scorecard_path,
        evidence_paths={"parser": parser_path},
        commit="abc123",
        alembic_head="053_deposit_statement_ledger",
        observed_at="2026-08-09T00:00:00Z",
    )

    parser_evidence = manifest["evidence"]["parser"]
    assert parser_evidence["status"] == "present"
    assert parser_evidence["sha256"] == hashlib.sha256(parser_path.read_bytes()).hexdigest()
    assert manifest["commit"] == {"value": "abc123", "dirty": None}
    assert manifest["alembic_head"] == "053_deposit_statement_ledger"
    assert manifest["decision"]["status"] == "deferred"
    assert any("strict mode" in blocker for blocker in manifest["decision"]["blockers"])
    assert any("provider_contract" in blocker for blocker in manifest["decision"]["blockers"])


def test_promotion_manifest_approves_only_with_strict_scorecard_and_all_evidence(tmp_path: Path):
    scorecard_path = tmp_path / "scorecard.json"
    scorecard_path.write_text(json.dumps(_scorecard(strict=True)), encoding="utf-8")
    evidence = {}
    for key in REQUIRED_EVIDENCE:
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps({"key": key}), encoding="utf-8")
        evidence[key] = path

    manifest = build_manifest(
        repo_root=tmp_path,
        output=tmp_path / "promotion.json",
        evidence_root=tmp_path,
        scorecard_report=scorecard_path,
        evidence_paths=evidence,
        commit="abc123",
        alembic_head="053",
        observed_at="2026-08-09T00:00:00Z",
    )

    assert manifest["decision"] == {
        "intelligence_score": 85.0,
        "delivery_flow_score": 85.0,
        "non_compensating_gates_passed": True,
        "status": "approved",
        "blockers": [],
    }
