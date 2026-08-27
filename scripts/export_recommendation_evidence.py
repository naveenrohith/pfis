"""Export the aggregate recommendation-effectiveness report for release review.

The service already suppresses cohorts below the privacy threshold. This command
serializes that same aggregate contract from the protected database so release
evidence does not depend on a browser session or a copied API response.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import AsyncSessionLocal  # noqa: E402
from app.services.recommendation_evaluation_service import (  # noqa: E402
    RecommendationEvaluationService,
)

EXPORT_VERSION = 1


def build_export(report: dict[str, Any]) -> dict[str, Any]:
    """Add non-sensitive export provenance without changing gate fields."""

    return {
        **report,
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "limitations": [
            "Only cohorts meeting the service privacy thresholds are published; suppressed cohorts are represented by counts, not member identities.",
            "Aggregate effectiveness is evidence for release review, not a guarantee for an individual user or recommendation.",
        ],
    }


async def collect_report() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        report = await RecommendationEvaluationService(db).effectiveness_report()
        return build_export(report.model_dump(mode="json"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = asyncio.run(collect_report())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Exported aggregate recommendation evidence to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
