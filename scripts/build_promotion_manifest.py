"""Assemble a hash-addressed, fail-closed PFIS promotion handoff manifest.

The scorecard and strict release gate remain the authorities for whether an
artifact is semantically valid. This script joins their outputs with the
repository revision, Alembic head, and named evidence artifacts so a release
owner can see exactly what is present, missing, or still deferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED_EVIDENCE = (
    "parser",
    "provider_contract",
    "balance_reconciliation",
    "forecast",
    "anomaly",
    "recommendation",
    "grounded_query",
    "task_success",
    "performance",
    "restore",
    "privacy_security",
)
SCHEMA_VERSION = "pfis-promotion-manifest-1"


def sha256_file(path: Path) -> str:
    """Return the content digest without loading large artifacts at once."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _relative_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _artifact_record(
    path: Path | None,
    *,
    repo_root: Path,
    observed_at: str,
    status_if_missing: str = "missing",
) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {
            "status": status_if_missing,
            "artifact": None,
            "sha256": None,
            "observed_at": observed_at,
        }
    return {
        "status": "present",
        "artifact": _relative_path(path, repo_root),
        "sha256": sha256_file(path),
        "observed_at": observed_at,
    }


def _scorecard_score(payload: Mapping[str, Any], key: str) -> float | None:
    measures = payload.get("measures")
    if not isinstance(measures, Mapping):
        return None
    measure = measures.get(key)
    if not isinstance(measure, Mapping):
        return None
    score = measure.get("score")
    return float(score) if isinstance(score, int | float) and not isinstance(score, bool) else None


def _load_scorecard(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Scorecard report is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Scorecard report must contain a JSON object")
    return payload


def _evidence_path(root: Path, key: str) -> Path | None:
    aliases = {
        "provider_contract": ("provider-contract.json", "provider_contract.json"),
        "balance_reconciliation": (
            "balance-reconciliation.json",
            "balance_reconciliation.json",
        ),
        "privacy_security": ("privacy-security.json", "privacy_security.json"),
    }
    candidates = aliases.get(key, (f"{key}.json",))
    for candidate in candidates:
        path = root / candidate
        if path.is_file():
            return path
    return None


def build_manifest(
    *,
    repo_root: Path,
    output: Path,
    evidence_root: Path,
    scorecard_report: Path | None = None,
    evidence_paths: Mapping[str, Path] | None = None,
    commit: str = "unknown",
    alembic_head: str = "unknown",
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Build the manifest without turning missing evidence into a pass."""

    timestamp = observed_at or _iso_now()
    scorecard = _load_scorecard(scorecard_report)
    scorecard_artifact = _artifact_record(
        scorecard_report,
        repo_root=repo_root,
        observed_at=timestamp,
    )
    overrides = evidence_paths or {}
    evidence: dict[str, dict[str, Any]] = {}
    for key in REQUIRED_EVIDENCE:
        path = overrides.get(key) or _evidence_path(evidence_root, key)
        evidence[key] = _artifact_record(path, repo_root=repo_root, observed_at=timestamp)

    blockers: list[str] = []
    if scorecard is None:
        blockers.append("A scorecard report is missing.")
    elif scorecard.get("strict") is not True:
        blockers.append("The scorecard report was not produced in strict mode.")
    scorecard_promotion = scorecard.get("promotion") if scorecard else None
    if isinstance(scorecard_promotion, Mapping):
        if scorecard_promotion.get("status") != "approved":
            blockers.extend(str(item) for item in scorecard_promotion.get("blockers", []) if item)
    else:
        blockers.append("The scorecard report has no promotion decision.")

    missing = [key for key, item in evidence.items() if item["status"] != "present"]
    blockers.extend(f"Missing promotion evidence: {key}." for key in missing)

    status = "approved" if not blockers else "deferred"
    if any("blocked" in blocker.lower() for blocker in blockers):
        status = "blocked"

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": timestamp,
        "commit": {"value": commit or "unknown", "dirty": None},
        "alembic_head": alembic_head or "unknown",
        "scorecard": {
            "artifact": scorecard_artifact,
            "version": scorecard.get("scorecard_version") if scorecard else None,
            "intelligence_score": (
                _scorecard_score(scorecard, "evidence_backed_product_intelligence")
                if scorecard
                else None
            ),
            "delivery_flow_score": (
                _scorecard_score(scorecard, "delivery_productivity") if scorecard else None
            ),
        },
        "evidence": evidence,
        "decision": {
            "intelligence_score": (
                _scorecard_score(scorecard, "evidence_backed_product_intelligence")
                if scorecard
                else None
            ),
            "delivery_flow_score": (
                _scorecard_score(scorecard, "delivery_productivity") if scorecard else None
            ),
            "non_compensating_gates_passed": status == "approved",
            "status": status,
            "blockers": blockers,
        },
    }


def _git_value(repo_root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _alembic_head(repo_root: Path) -> str:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(repo_root / "backend" / "alembic.ini"))
        config.set_main_option("script_location", str(repo_root / "backend" / "alembic"))
        return ScriptDirectory.from_config(config).get_current_head() or "unknown"
    except (ImportError, OSError, ValueError):
        return "unknown"


def _parse_evidence(values: list[str], repo_root: Path) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        key, separator, raw_path = value.partition("=")
        if not separator or key not in REQUIRED_EVIDENCE or not raw_path.strip():
            raise ValueError(
                "Evidence overrides must use KEY=PATH for a known key: "
                + ", ".join(REQUIRED_EVIDENCE)
            )
        parsed[key] = (
            (repo_root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
        )
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--evidence-root", type=Path, default=Path("release-evidence"))
    parser.add_argument("--scorecard-report", type=Path)
    parser.add_argument("--evidence", action="append", default=[], metavar="KEY=PATH")
    parser.add_argument("--observed-at")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    evidence_root = (
        args.evidence_root if args.evidence_root.is_absolute() else repo_root / args.evidence_root
    )
    scorecard_report = (
        None
        if args.scorecard_report is None
        else (
            args.scorecard_report
            if args.scorecard_report.is_absolute()
            else repo_root / args.scorecard_report
        )
    )
    try:
        manifest = build_manifest(
            repo_root=repo_root,
            output=output,
            evidence_root=evidence_root,
            scorecard_report=scorecard_report,
            evidence_paths=_parse_evidence(args.evidence, repo_root),
            commit=_git_value(repo_root, "rev-parse", "HEAD"),
            alembic_head=_alembic_head(repo_root),
            observed_at=args.observed_at,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"promotion-manifest-error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": manifest["decision"]["status"], "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
