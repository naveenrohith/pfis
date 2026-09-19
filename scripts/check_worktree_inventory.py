"""Assign every changed PFIS file to one ordered integration packet."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

PACKET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "IR-0",
        re.compile(
            r"^\.github/workflows/ci\.yml$|^\.github/mcp\.json$|^\.vscode/mcp\.json$|"
            r"^Makefile$|^scripts/|^docs/audit/|^test-results/|"
            r"^tests/pytest/test_release_gates\.py$|"
            r"^backend/app/(observability\.py|api/routes/health\.py|schemas/operational\.py)$"
        ),
    ),
    (
        "IR-1",
        re.compile(
            r"^tests/parser_corpus/|"
            r"^tests/fixtures/hdfc_deposit_statement_reviewed\.txt$|"
            r"^backend/\.env\.example$|"
            r"^backend/app/services/(classification|connectors|gmail|ingestion|parser)/|"
            r"^backend/app/services/(hdfc.*statement_extractor|statement_detection)\.py$|"
            r"^backend/app/(models/(email|sync)\.py|api/routes/(gmail|jobs)\.py|schemas/job\.py)$|"
            r"^backend/alembic/versions/(030|042|056)_|"
            r"^tests/pytest/test_(connector|gmail|ingestion|jobs|parser|pipeline|hdfc.*statement).*\.py$|"
            r"^docs/(parser|integrations)\.md$"
        ),
    ),
    (
        "IR-2",
        re.compile(
            r"^backend/alembic/versions/(015|018|019|020|021|022|023|024|025|026|027|028|029|034|038|040)_|"
            r"^backend/app/(models/(account|transaction|user|workspace)\.py|"
            r"schemas/(account|auth|transaction|user)\.py|"
            r"api/routes/(accounts|auth|budgets|transactions|users)\.py)$|"
            r"^backend/app/services/(account_|transaction_|retention_|portable_export|"
            r"financial_clock|ledger_currency|auto_sync|seed_service)|"
            r"^tests/pytest/test_(account|api_error|api_regression|auth|budgets|database|dedup|"
            r"endpoints|portable_export|premium_workspace|raw_email_retention|transaction|transfer).*\.py$"
        ),
    ),
    (
        "IR-3",
        re.compile(
            r"^backend/alembic/versions/(031|032|033|035|036|037|039|041)_|"
            r"^backend/app/models/(anomaly|forecast|knowledge|roadmap|temporal_history)\.py$|"
            r"^backend/app/schemas/(guidance|intelligence|roadmap|temporal)\.py$|"
            r"^backend/app/api/routes/(analytics|guidance|insights|knowledge|roadmap)\.py$|"
            r"^backend/app/services/(anomaly_|forecast_|guidance_|insights_|intelligence_|"
            r"knowledge/|recommendation_|roadmap_|temporal_)|"
            r"^tests/pytest/test_(anomaly|forecast|insights|intelligence|knowledge|recommendation|"
            r"roadmap|temporal).*\.py$|^docs/feature-ideas-roadmap\.md$"
        ),
    ),
    (
        "IR-4",
        re.compile(
            r"^backend/alembic/versions/(043|044|045|046|047|048|049|050|051|052|053|054|055)_|"
            r"^backend/app/models/financial_position\.py$|"
            r"^backend/app/schemas/(balance_forecast|financial_position)\.py$|"
            r"^backend/app/api/routes/financial_position\.py$|"
            r"^backend/app/services/(balance_|card_|financial_position|reconciliation_)|"
            r"^tests/pytest/test_(balance|card|financial_position).*\.py$|"
            r"^docs/financial-position-roadmap-implementation\.md$"
        ),
    ),
    (
        "IR-5",
        re.compile(
            r"^frontend/|^backend/requirements\.txt$|^backend/app/|^tests/pytest/|^\.github/|^Makefile$"
        ),
    ),
    ("IR-6", re.compile(r"^README\.md$|^docs/")),
)


def classify_path(path: str) -> str | None:
    """Return the first integration packet matching a repository-relative path."""

    normalized = path.replace("\\", "/")
    for packet, pattern in PACKET_RULES:
        if pattern.search(normalized):
            return packet
    return None


def _git_paths(workspace: Path, *arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_paths(workspace: Path, *, base_ref: str | None = None) -> list[str]:
    """Return committed changes from a base plus modified and untracked files."""

    effective_base_ref = base_ref if base_ref and base_ref != "0" * 40 else None
    paths = set(
        _git_paths(
            workspace,
            "diff",
            "--name-only",
            f"{effective_base_ref}...HEAD" if effective_base_ref else "HEAD",
        )
    )
    if effective_base_ref:
        paths.update(_git_paths(workspace, "diff", "--name-only", "HEAD"))
    paths.update(_git_paths(workspace, "ls-files", "--others", "--exclude-standard"))
    return sorted(paths)


def build_report(workspace: Path, *, base_ref: str | None = None) -> dict[str, object]:
    assignments = []
    for path in changed_paths(workspace, base_ref=base_ref):
        assignments.append({"path": path, "packet": classify_path(path)})
    counts = Counter(item["packet"] for item in assignments if item["packet"] is not None)
    return {
        "schema_version": "pfis-worktree-inventory-1",
        "total": len(assignments),
        "packet_counts": dict(sorted(counts.items())),
        "unassigned": [item["path"] for item in assignments if item["packet"] is None],
        "assignments": assignments,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--base-ref",
        help="Compare committed changes from this ref to HEAD instead of only the worktree.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    report = build_report(workspace, base_ref=args.base_ref)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "total": report["total"],
                "packet_counts": report["packet_counts"],
                "unassigned": report["unassigned"],
            },
            sort_keys=True,
        )
    )
    return 1 if report["unassigned"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
