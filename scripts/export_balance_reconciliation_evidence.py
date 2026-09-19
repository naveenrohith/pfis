"""Export protected aggregate balance-reconciliation evidence.

The artifact keeps only keyed cohort membership and aggregate interval-quality
metrics. Raw user IDs, institution names, balances, transaction IDs, and
movement amounts remain inside the release database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.account import FinancialAccount  # noqa: E402
from app.models.financial_position import AccountBalanceReconciliation  # noqa: E402
from app.models.user import User  # noqa: E402

from scripts.export_forecast_evidence import _validate_manifest  # noqa: E402

EXPORT_VERSION = 1
EVALUATION_VERSION = "pfis-balance-reconciliation-1"
REPRESENTATIVE_COHORT = "production_safe"


def _user_hash(user_id: str, secret: str) -> str:
    return hashlib.sha256(f"pfis-balance-reconciliation-v1:{secret}:{user_id}".encode()).hexdigest()


def _institution_hash(institution_name: str, secret: str) -> str:
    normalized = institution_name.strip().casefold()
    return hashlib.sha256(
        f"pfis-balance-reconciliation-institution-v1:{secret}:{normalized}".encode()
    ).hexdigest()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 4)


def _residual_ratio(row: AccountBalanceReconciliation) -> float:
    movement = abs(Decimal(row.known_movement))
    residual = abs(Decimal(row.residual))
    if movement == Decimal("0"):
        return 100.0 if residual != Decimal("0") else 0.0
    return float(residual / movement * Decimal("100"))


def _protected_report(
    user_id: str,
    secret: str,
    cohort: str,
    rows: list[AccountBalanceReconciliation],
    accounts: list[FinancialAccount],
) -> tuple[dict[str, Any], list[float]]:
    ratios = [_residual_ratio(row) for row in rows]
    reconciled_count = sum(row.reconciliation_status == "reconciled" for row in rows)
    report = {
        "evaluation_version": EVALUATION_VERSION,
        "cohort": cohort,
        "user_id_hash": _user_hash(user_id, secret),
        "interval_count": len(rows),
        "reconciled_interval_count": reconciled_count,
        "needs_review_interval_count": len(rows) - reconciled_count,
        "median_absolute_residual_pct": _percentile(ratios, 0.5),
        "p95_absolute_residual_pct": _percentile(ratios, 0.95),
        "account_count": len(accounts),
        "institution_count": len(
            {account.institution_name.strip().casefold() for account in accounts}
        ),
    }
    return report, ratios


def build_export(
    reports: list[dict[str, Any]],
    ratios: list[float],
    *,
    manifest_evidence: dict[str, Any],
    representative_institution_count: int = 0,
) -> dict[str, Any]:
    representative = [
        report
        for report in reports
        if report.get("cohort") == REPRESENTATIVE_COHORT
        and isinstance(report.get("user_id_hash"), str)
        and report["user_id_hash"].strip()
    ]
    # The export caller supplies all interval ratios; representative aggregate
    # metrics are intentionally computed from per-report summaries rather than
    # retaining individual interval amounts in the artifact.
    representative_medians = [
        float(report["median_absolute_residual_pct"])
        for report in representative
        if isinstance(report.get("median_absolute_residual_pct"), int | float)
    ]
    representative_p95s = [
        float(report["p95_absolute_residual_pct"])
        for report in representative
        if isinstance(report.get("p95_absolute_residual_pct"), int | float)
    ]
    return {
        "version": EXPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluation_version": EVALUATION_VERSION,
        "report_count": len(reports),
        "manifest": manifest_evidence,
        "aggregate": {
            "interval_count": sum(int(report.get("interval_count", 0)) for report in reports),
            "representative_interval_count": sum(
                int(report.get("interval_count", 0)) for report in representative
            ),
            "representative_user_count": len(representative),
            "representative_institution_count": representative_institution_count,
            "median_of_user_median_absolute_residual_pct": _percentile(representative_medians, 0.5),
            "p95_of_user_p95_absolute_residual_pct": _percentile(representative_p95s, 0.95),
            "representative_interval_median_absolute_residual_pct": _percentile(ratios, 0.5),
        },
        "reports": reports,
        "limitations": [
            "Metrics are derived from immutable verified-observation intervals and keyed cohort membership; raw balances, movements, transaction IDs, institution names, and user IDs are omitted.",
            "Intervals capture knowledge available when the closing observation was newest; later source history does not rewrite them.",
            "A missing or invalid roster cannot create production_safe cohort membership.",
        ],
    }


async def collect_reports(manifest: Mapping[str, Any] | None) -> dict[str, Any]:
    """Collect protected reconciliation metrics for active users."""

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
        assignments, manifest_evidence = _validate_manifest(manifest, set(user_ids))
        secret = get_settings().SECRET_KEY
        reports: list[dict[str, Any]] = []
        all_ratios: list[float] = []
        representative_institutions: set[str] = set()
        for user_id in user_ids:
            rows = list(
                (
                    await db.scalars(
                        select(AccountBalanceReconciliation)
                        .where(AccountBalanceReconciliation.user_id == user_id)
                        .order_by(AccountBalanceReconciliation.closing_as_of)
                    )
                ).all()
            )
            accounts = list(
                (
                    await db.scalars(
                        select(FinancialAccount).where(
                            FinancialAccount.user_id == user_id,
                            FinancialAccount.is_active.is_(True),
                        )
                    )
                ).all()
            )
            report, ratios = _protected_report(
                user_id,
                secret,
                assignments.get(user_id, "observed"),
                rows,
                accounts,
            )
            reports.append(report)
            if report["cohort"] == REPRESENTATIVE_COHORT:
                all_ratios.extend(ratios)
                representative_institutions.update(
                    _institution_hash(account.institution_name, secret) for account in accounts
                )
        return build_export(
            reports,
            all_ratios,
            manifest_evidence=manifest_evidence,
            representative_institution_count=len(representative_institutions),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cohort-manifest", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = None
    if args.cohort_manifest:
        try:
            manifest = json.loads(args.cohort_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"Balance cohort manifest is not valid JSON: {exc}") from exc
    export = asyncio.run(collect_reports(manifest))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Exported {export['report_count']} protected balance-reconciliation reports to {args.output}"
    )
    return 1 if export.get("manifest", {}).get("status") == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
