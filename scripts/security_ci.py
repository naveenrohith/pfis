"""Run bounded lab checks and export only sanitized security assessment artifacts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from security.assessment import AssessmentCoordinator  # noqa: E402
from security.auth_boundary import run_auth_boundary_checks  # noqa: E402
from security.lab import LabManager  # noqa: E402
from security.parsers import sanitize_evidence  # noqa: E402
from security.registry import ALL_PROFILE_IDS  # noqa: E402
from security.scope import resolve_targets  # noqa: E402
from security.store import SecurityStore  # noqa: E402

ARTIFACT_DIR = ROOT / ".security-local" / "ci-artifacts"


def _write_artifact(name: str, value: dict[str, Any]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    destination = ARTIFACT_DIR / name
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    with suppress(OSError):
        os.chmod(temporary, 0o600)
    temporary.replace(destination)
    event_path = ARTIFACT_DIR / "security-ci-events.jsonl"
    with event_path.open("a", encoding="utf-8", newline="\n") as handle:
        event = {key: item for key, item in value.items() if key != "report"}
        handle.write(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")
    with suppress(OSError):
        os.chmod(event_path, 0o600)


def verify_boundaries() -> int:
    lab = LabManager(ROOT)
    try:
        config = lab.config()
        lab.verify_identity(required_targets=("sqli-fixture",))
        checks, findings = run_auth_boundary_checks(
            ROOT,
            https_port=config.https_port,
            ca_path=lab.metadata / "caddy-root.crt",
            expected_generation=config.generation,
        )
        failed = [check.check_id for check in checks if check.status != "passed"]
        result = {
            "kind": "auth-boundary",
            "generation": config.generation,
            "commit_sha": _branch_commit(),
            "synthetic_data": True,
            "check_count": len(checks),
            "passed_count": len(checks) - len(failed),
            "failed_checks": failed,
            "critical_high_count": len(findings),
            "coverage_complete": bool(checks) and not failed,
        }
    except Exception as exc:
        result = {
            "kind": "auth-boundary",
            "commit_sha": _branch_commit(),
            "coverage_complete": False,
            "error": sanitize_evidence(str(exc)),
        }
    _write_artifact("auth-boundary.json", result)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0 if result.get("coverage_complete") else 1


def run_profile(profile: str) -> int:
    lab = LabManager(ROOT)
    store = SecurityStore(lab.metadata / "security.sqlite3")
    try:
        targets = resolve_targets(profile)
        coordinator = AssessmentCoordinator(ROOT, store, lab)
        record = coordinator.enqueue(profile, list(targets))
        coordinator.wait()
        record = store.get_run(str(record["id"])) or record
        report = store.report(str(record["id"]))
        summary = json.loads(record.get("summary") or "{}")
        result: dict[str, Any] = {
            "kind": "assessment",
            "run": record,
            "coverage": summary,
            "report": report,
        }
        if report is None:
            result["error"] = "assessment report was not persisted"
    except Exception as exc:
        result = {
            "kind": "assessment",
            "profile": profile,
            "commit_sha": _branch_commit(),
            "coverage_complete": False,
            "error": sanitize_evidence(str(exc)),
        }
    run = result.get("run")
    run_id = str(run.get("id", "")) if isinstance(run, dict) else ""
    name = f"{profile}-{run_id}.json" if run_id else f"{profile}-preflight.json"
    _write_artifact(name, result)
    summary = result.get("coverage")
    if isinstance(summary, dict):
        print(
            json.dumps(
                {
                    "profile": profile,
                    "run_id": run_id,
                    "state": run.get("state") if isinstance(run, dict) else "failed",
                    "coverage_complete": summary.get("coverage_complete", False),
                    "critical_high_count": summary.get("critical_high_count", 0),
                    "artifact": name,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )
        return (
            0
            if (
                isinstance(run, dict)
                and run.get("state") == "completed"
                and summary.get("coverage_complete") is True
                and summary.get("critical_high_count") == 0
                and result.get("report") is not None
            )
            else 1
        )
    print(json.dumps({"profile": profile, "error": result.get("error"), "artifact": name}))
    return 1


def _branch_commit() -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
        shell=False,
    )
    commit = result.stdout.decode("ascii", errors="ignore").strip()
    return commit if result.returncode == 0 and len(commit) == 40 else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("verify-boundaries")
    run = actions.add_parser("run-profile")
    run.add_argument("--profile", required=True, choices=sorted(ALL_PROFILE_IDS))
    args = parser.parse_args()
    if args.action == "verify-boundaries":
        return verify_boundaries()
    return run_profile(args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
