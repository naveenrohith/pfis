"""Export protected, aggregate forecast backtests for the release evaluator.

The export keeps only leakage-safe forecast metrics and a keyed user hash. Raw
user IDs, transaction counts, projected amounts, and transaction evidence stay
inside the database and never enter the release artifact. Production-safe cohort
membership is supplied by an independently reviewed roster manifest.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.intelligence_service import IntelligenceService  # noqa: E402

MANIFEST_VERSION = 1
EXPORT_VERSION = 1
REPRESENTATIVE_COHORTS = frozenset({"sanitized_production", "production_safe"})


def _manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_manifest(
    manifest: Mapping[str, Any] | None,
    active_user_ids: set[str],
) -> tuple[dict[str, str], dict[str, Any]]:
    """Validate a protected roster without returning its user identifiers."""

    if manifest is None:
        return {}, {"status": "not_supplied", "version": MANIFEST_VERSION, "user_count": 0}
    if not isinstance(manifest, Mapping):
        return {}, {
            "status": "invalid",
            "version": None,
            "user_count": 0,
            "reason": "manifest must be a JSON object",
        }

    reason: str | None = None
    if manifest.get("version") != MANIFEST_VERSION:
        reason = "unsupported manifest version"
    entries = manifest.get("users")
    if reason is None and (not isinstance(entries, list) or not entries):
        reason = "manifest users must be a non-empty list"
    manifest_entries: list[Any] = entries if isinstance(entries, list) else []

    assignments: dict[str, str] = {}
    if reason is None:
        for entry in manifest_entries:
            if not isinstance(entry, Mapping):
                reason = "manifest users must contain objects"
                break
            user_id = str(entry.get("id") or "").strip()
            cohort = str(entry.get("cohort") or "").strip()
            if not user_id or user_id not in active_user_ids:
                reason = "manifest references an unknown active user id"
                break
            if user_id in assignments:
                reason = "manifest contains duplicate user ids"
                break
            if cohort not in REPRESENTATIVE_COHORTS:
                reason = "manifest cohort must be sanitized_production or production_safe"
                break
            assignments[user_id] = cohort

    attestation = manifest.get("attestation")
    if reason is None and not isinstance(attestation, Mapping):
        reason = "manifest attestation is required"
    manifest_attestation: Mapping[str, Any] = (
        attestation if isinstance(attestation, Mapping) else {}
    )
    if reason is None:
        if manifest_attestation.get("deidentified") is not True:
            reason = "manifest attestation must confirm de-identification"
        elif manifest_attestation.get("reviewed") is not True:
            reason = "manifest attestation must confirm independent review"
        elif not str(manifest_attestation.get("reviewer_id") or "").strip():
            reason = "manifest attestation reviewer_id is required"
        else:
            reviewed_at = str(manifest_attestation.get("reviewed_at") or "").strip()
            try:
                datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except ValueError:
                reason = "manifest attestation reviewed_at must be ISO-8601"

    evidence: dict[str, Any] = {
        "status": "invalid" if reason else "verified",
        "version": manifest.get("version"),
        "user_count": len(assignments),
        "manifest_fingerprint": _manifest_fingerprint(manifest),
    }
    if reason:
        evidence["reason"] = reason
        return {}, evidence
    return assignments, evidence


def _user_hash(user_id: str, secret: str) -> str:
    return hashlib.sha256(f"pfis-forecast-v1:{secret}:{user_id}".encode()).hexdigest()


def _protected_report(report: Any, *, cohort: str, user_id_hash: str) -> dict[str, Any]:
    """Keep only fields needed by the release gate, excluding spend amounts."""

    return {
        "evaluation_version": report.evaluation_version,
        "ruleset_version": report.ruleset_version,
        "as_of": report.as_of.isoformat(),
        "cohort": cohort,
        "user_id_hash": user_id_hash,
        "evaluated_months": report.evaluated_months,
        "horizons": [
            {
                "cutoff_day": horizon.cutoff_day,
                "eligible_periods": horizon.eligible_periods,
                "median_absolute_percentage_error": horizon.median_absolute_percentage_error,
                "interval_coverage_pct": horizon.interval_coverage_pct,
            }
            for horizon in report.horizons
        ],
        "temporal_evidence_evaluated": report.temporal_evidence_evaluated,
        "temporal_evidence_periods": report.temporal_evidence_periods,
        "transaction_history_evaluated": report.transaction_history_evaluated,
        "transaction_history_cutoffs": report.transaction_history_cutoffs,
        "transaction_history_coverage_pct": report.transaction_history_coverage_pct,
        "category_mix_supported_periods": report.category_mix_supported_periods,
    }


def build_export(
    reports: list[dict[str, Any]],
    *,
    manifest_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Build a release artifact that contains no raw user or ledger values."""

    return {
        "version": EXPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "report_count": len(reports),
        "manifest": manifest_evidence,
        "reports": reports,
        "limitations": [
            "Each report is a leakage-safe retained-ledger backtest with a keyed user hash; raw user IDs, projections, amounts, and transaction rows are omitted.",
            "A missing or invalid roster cannot create production_safe cohort membership; the strict release gate remains deferred or failed.",
        ],
    }


async def collect_reports(
    manifest: Mapping[str, Any] | None,
    *,
    months: int,
) -> dict[str, Any]:
    """Run protected backtests for active users and apply reviewed cohorts."""

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
        intelligence = IntelligenceService(db)
        reports: list[dict[str, Any]] = []
        for user_id in user_ids:
            report = await intelligence.cash_flow_backtest(user_id, months=months)
            reports.append(
                _protected_report(
                    report,
                    cohort=assignments.get(user_id, "observed"),
                    user_id_hash=_user_hash(user_id, secret),
                )
            )
        return build_export(reports, manifest_evidence=manifest_evidence)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cohort-manifest", type=Path)
    parser.add_argument("--months", type=int, default=6)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 3 <= args.months <= 12:
        raise SystemExit("--months must be between 3 and 12")
    manifest = None
    if args.cohort_manifest:
        try:
            manifest = json.loads(args.cohort_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cohort manifest is not valid JSON: {exc}") from exc
    export = asyncio.run(collect_reports(manifest, months=args.months))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Exported {export['report_count']} protected forecast reports to {args.output}")
    return 1 if export.get("manifest", {}).get("status") == "invalid" else 0


if __name__ == "__main__":
    raise SystemExit(main())
