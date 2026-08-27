"""Export privacy-safe, aggregate anomaly labels for the release evaluator.

The export intentionally contains only the evaluator booleans and anomaly kind.
It must be written to a protected release-evidence directory; user IDs, labels,
amounts, notes, and source transaction identifiers never leave the database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import AsyncSessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.anomaly_adjudication_service import AnomalyAdjudicationService  # noqa: E402


async def collect_cases_with_summary() -> tuple[list[dict[str, bool | str]], int]:
    """Collect latest labels and a privacy-safe count of contributing users."""

    async with AsyncSessionLocal() as db:
        user_ids = list(
            (
                await db.scalars(
                    select(User.id)
                    .where(User.is_active.is_(True), User.deleted_at.is_(None))
                    .order_by(User.id)
                )
            ).all()
        )
        cases: list[dict[str, bool | str]] = []
        contributing_users = 0
        for user_id in user_ids:
            user_cases = await AnomalyAdjudicationService(db).protected_evaluation_cases(user_id)
            if user_cases:
                contributing_users += 1
                cases.extend(user_cases)
        return cases, contributing_users


async def collect_cases() -> list[dict[str, bool | str]]:
    """Preserve the legacy helper while exporting the richer summary in ``main``."""

    cases, _ = await collect_cases_with_summary()
    return cases


def build_export(
    cases: list[dict[str, bool | str]], *, contributing_users: int = 0
) -> dict[str, object]:
    """Build a versioned evaluator input without user-level metadata."""

    kinds = Counter(str(case["kind"]) for case in cases)
    prediction_counts = Counter(str(case["predicted_alert"]) for case in cases)
    return {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        "kind_counts": dict(sorted(kinds.items())),
        "prediction_counts": dict(sorted(prediction_counts.items())),
        "coverage": {
            "unique_users": contributing_users,
            "kind_counts": dict(sorted(kinds.items())),
        },
        "cases": cases,
        "limitations": [
            "Cases are aggregate evaluator labels only; source identities, amounts, notes, and user IDs are intentionally omitted.",
            "The release gate still requires balanced alert/non-alert and material/expected labels across representative users, months, categories, and merchants.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases, contributing_users = asyncio.run(collect_cases_with_summary())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            build_export(cases, contributing_users=contributing_users),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Exported {len(cases)} privacy-safe anomaly cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
