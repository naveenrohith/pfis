"""Verify persisted end-to-end financial pipeline results without writing data."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# ruff: noqa: E402
from app.database import normalize_async_database_url
from app.models.email import RawEmail
from app.models.financial_change import FinancialChangeEvent
from app.models.sync import BackgroundJob, ParseFailure, PipelineEvent
from app.models.transaction import Transaction
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.e2e_safety import E2EGuardError, e2e_database_name, validate_fixture_write


async def verify(args: argparse.Namespace) -> dict:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("run_id") != args.run_id or manifest.get("database") != args.database_name:
        raise E2EGuardError("E2E manifest does not match the requested run and database")
    if args.database_name != e2e_database_name(args.run_id):
        raise E2EGuardError("--database-name must match the exact E2E run ID")

    database_url = os.environ.get("DATABASE_URL", "")
    engine = create_async_engine(normalize_async_database_url(database_url), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            target = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT current_database() AS database_name,
                               shobj_description(
                                   (SELECT oid FROM pg_database WHERE datname = current_database()),
                                   'pg_database'
                               ) AS database_comment
                        """
                        )
                    )
                )
                .mappings()
                .one()
            )
            validate_fixture_write(
                env=dict(os.environ),
                database_url=database_url,
                database_name=target["database_name"],
                run_id=args.run_id,
                database_comment=target["database_comment"],
            )
            profile = manifest["profiles"]["pipeline"]
            user_id = profile["user_id"]
            expected = profile["expected"]
            source_count = int(
                await session.scalar(
                    select(func.count(RawEmail.id)).where(RawEmail.user_id == user_id)
                )
                or 0
            )
            transaction_count = int(
                await session.scalar(
                    select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
                )
                or 0
            )
            ledger_total = Decimal(
                str(
                    await session.scalar(
                        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                            Transaction.user_id == user_id
                        )
                    )
                    or 0
                )
            ).quantize(Decimal("0.01"))
            unresolved_failures = int(
                await session.scalar(
                    select(func.count(ParseFailure.id))
                    .join(RawEmail, ParseFailure.email_id == RawEmail.id)
                    .where(RawEmail.user_id == user_id, ParseFailure.resolved.is_(False))
                )
                or 0
            )
            duplicate_pipeline_events = int(
                await session.scalar(
                    select(func.count(PipelineEvent.id)).where(
                        PipelineEvent.user_id == user_id,
                        PipelineEvent.event_type == "DuplicateDetected",
                    )
                )
                or 0
            )
            change_event_count = int(
                await session.scalar(
                    select(func.count(FinancialChangeEvent.id)).where(
                        FinancialChangeEvent.user_id == user_id
                    )
                )
                or 0
            )
            job = await session.scalar(
                select(BackgroundJob)
                .where(
                    BackgroundJob.user_id == user_id,
                    BackgroundJob.job_type == "demo_sync_pipeline",
                )
                .order_by(BackgroundJob.created_at.desc())
            )
            if job is None:
                sync = {}
                pipeline = {}
                job_status = "missing"
            else:
                job_status = job.status.value
                result = json.loads(job.result_json or "{}")
                sync = result.get("sync", {})
                pipeline = result.get("pipeline", {})

            source_transaction = await session.scalar(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.source_email_id == profile["source_raw_email_id"],
                )
            )
            actual = {
                "job_status": job_status,
                "source_count": source_count,
                "sync_new_source_count": int(sync.get("emails_stored", 0)),
                "sync_fetched_source_count": int(sync.get("emails_fetched", 0)),
                "sync_duplicate_source_count": int(sync.get("emails_skipped_duplicate", 0)),
                "otp_skips": int(sync.get("emails_skipped_otp", 0)),
                "promotion_skips": int(sync.get("emails_skipped_promo", 0)),
                "transaction_count": transaction_count,
                "gross_ledger_amount": str(ledger_total),
                "unresolved_parse_failures": unresolved_failures,
                "pipeline_duplicate_count": duplicate_pipeline_events,
                "job_pipeline_duplicate_count": int(pipeline.get("duplicates", 0)),
                "committed_financial_change_events": change_event_count,
                "source_transaction": {
                    "amount": str(source_transaction.amount) if source_transaction else None,
                    "currency": source_transaction.currency if source_transaction else None,
                    "transaction_type": (
                        source_transaction.transaction_type.value if source_transaction else None
                    ),
                    "merchant_raw": source_transaction.merchant_raw if source_transaction else None,
                    "transaction_date": (
                        source_transaction.transaction_date.isoformat()
                        if source_transaction
                        else None
                    ),
                    "account_last4": (
                        source_transaction.account_last4 if source_transaction else None
                    ),
                    "reviewed_flag": (
                        source_transaction.reviewed_flag if source_transaction else None
                    ),
                    "merchant_normalized": (
                        source_transaction.merchant_normalized if source_transaction else None
                    ),
                },
            }
            checks = {
                "job_completed": actual["job_status"] == "completed",
                "source_count_matches": source_count
                == int(expected["stored_source_count_after_sync"]),
                "duplicate_source_outcome_matches": actual["sync_duplicate_source_count"]
                == int(expected["initial_source_collision_count"]),
                "sync_source_insert_count_matches": actual["sync_new_source_count"]
                == int(expected["sync_new_source_count"]),
                "transaction_count_matches": transaction_count
                == int(expected["stored_transaction_count"]),
                "gross_ledger_total_matches": actual["gross_ledger_amount"]
                == str(expected["gross_ledger_amount"]),
                "no_unresolved_failures": unresolved_failures == 0,
                "pipeline_duplicate_count_matches": actual["job_pipeline_duplicate_count"]
                == int(expected["pipeline_duplicate_count"])
                and duplicate_pipeline_events == int(expected["pipeline_duplicate_count"]),
                "committed_financial_change_exists": change_event_count > 0,
                "source_transaction_matches": actual["source_transaction"]["amount"]
                == str(expected["amount"])
                and actual["source_transaction"]["currency"] == expected["currency"]
                and actual["source_transaction"]["transaction_type"] == expected["transaction_type"]
                and actual["source_transaction"]["merchant_raw"] == expected["merchant_raw"]
                and actual["source_transaction"]["transaction_date"] == expected["date"]
                and actual["source_transaction"]["account_last4"] == expected["account_last4"]
                and actual["source_transaction"]["reviewed_flag"] is True
                and actual["source_transaction"]["merchant_normalized"] == "PFIS E2E Grocery",
            }
            report = {
                "schema_version": 1,
                "run_id": args.run_id,
                "database": args.database_name,
                "corpus_version": expected["corpus_version"],
                "expected": {
                    "source_count": expected["stored_source_count_after_sync"],
                    "sync_new_source_count": expected["sync_new_source_count"],
                    "duplicate_source_count": expected["initial_source_collision_count"],
                    "transaction_count": expected["stored_transaction_count"],
                    "gross_ledger_amount": expected["gross_ledger_amount"],
                    "unresolved_parse_failures": 0,
                },
                "actual": actual,
                "checks": checks,
                "passed": all(checks.values()),
            }
            if args.check_restart_recovery:
                restart_profile = manifest.get("profiles", {}).get("restart", {})
                restart_user_id = restart_profile.get("user_id")
                restart_job_id = restart_profile.get("recovery_job_id")
                if not restart_user_id or not restart_job_id:
                    raise E2EGuardError("Manifest has no prepared restart-recovery fixture")
                restart_job = await session.get(BackgroundJob, restart_job_id)
                for _ in range(180):
                    if restart_job is None or restart_job.status.value not in {"queued", "running"}:
                        break
                    await asyncio.sleep(0.5)
                    await session.refresh(restart_job)
                restart_result = json.loads(restart_job.result_json or "{}") if restart_job else {}
                restart_sync = restart_result.get("sync", {})
                restart_pipeline = restart_result.get("pipeline", {})
                restart_transaction_count = int(
                    await session.scalar(
                        select(func.count(Transaction.id)).where(
                            Transaction.user_id == restart_user_id
                        )
                    )
                    or 0
                )
                restart_source_count = int(
                    await session.scalar(
                        select(func.count(RawEmail.id)).where(RawEmail.user_id == restart_user_id)
                    )
                    or 0
                )
                restart_ledger_total = Decimal(
                    str(
                        await session.scalar(
                            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                                Transaction.user_id == restart_user_id
                            )
                        )
                        or 0
                    )
                ).quantize(Decimal("0.01"))
                restart_linked_count = int(
                    await session.scalar(
                        select(func.count(Transaction.id)).where(
                            Transaction.user_id == restart_user_id,
                            Transaction.source_email_id == restart_profile["source_raw_email_id"],
                        )
                    )
                    or 0
                )
                restart_failures = int(
                    await session.scalar(
                        select(func.count(ParseFailure.id))
                        .join(RawEmail, ParseFailure.email_id == RawEmail.id)
                        .where(
                            RawEmail.user_id == restart_user_id,
                            ParseFailure.resolved.is_(False),
                        )
                    )
                    or 0
                )
                restart_duplicates = int(
                    await session.scalar(
                        select(func.count(PipelineEvent.id)).where(
                            PipelineEvent.user_id == restart_user_id,
                            PipelineEvent.event_type == "DuplicateDetected",
                        )
                    )
                    or 0
                )
                restart_actual = {
                    "job_status": restart_job.status.value if restart_job else "missing",
                    "job_attempt_count": restart_job.attempt_count if restart_job else 0,
                    "source_count": restart_source_count,
                    "sync_fetched_source_count": int(restart_sync.get("emails_fetched", 0)),
                    "sync_new_source_count": int(restart_sync.get("emails_stored", 0)),
                    "sync_duplicate_source_count": int(
                        restart_sync.get("emails_skipped_duplicate", 0)
                    ),
                    "transaction_count": restart_transaction_count,
                    "source_transaction_count": restart_linked_count,
                    "gross_ledger_amount": str(restart_ledger_total),
                    "unresolved_parse_failures": restart_failures,
                    "pipeline_duplicate_count": int(restart_pipeline.get("duplicates", 0)),
                    "persisted_duplicate_events": restart_duplicates,
                }
                restart_checks = {
                    "interrupted_job_recovered_and_completed": restart_actual["job_status"]
                    == "completed"
                    and restart_actual["job_attempt_count"] >= 2,
                    "expected_sources_persisted": restart_source_count
                    == int(expected["stored_source_count_after_sync"]),
                    "source_counts_match": restart_actual["sync_fetched_source_count"] == 15
                    and restart_actual["sync_new_source_count"]
                    == int(expected["sync_new_source_count"])
                    and restart_actual["sync_duplicate_source_count"]
                    == int(expected["initial_source_collision_count"]),
                    "expected_ledger_persisted_once": restart_transaction_count
                    == int(expected["stored_transaction_count"])
                    and restart_linked_count == 1
                    and str(restart_ledger_total) == str(expected["gross_ledger_amount"]),
                    "no_duplicate_financial_results": restart_duplicates == 0
                    and int(restart_pipeline.get("duplicates", 0)) == 0,
                    "no_unresolved_parse_failures": restart_failures == 0,
                }
                report["restart_recovery"] = {
                    "expected": {
                        "job_status": "completed",
                        "transaction_count": expected["stored_transaction_count"],
                        "single_source_transaction": 1,
                        "gross_ledger_amount": expected["gross_ledger_amount"],
                        "unresolved_parse_failures": 0,
                    },
                    "actual": restart_actual,
                    "checks": restart_checks,
                    "passed": all(restart_checks.values()),
                }
                report["passed"] = report["passed"] and report["restart_recovery"]["passed"]
            return report
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-restart-recovery", action="store_true")
    args = parser.parse_args(argv)
    report = asyncio.run(verify(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Financial pipeline persisted-state verification: {'PASS' if report['passed'] else 'FAIL'}"
    )
    for name, passed in report["checks"].items():
        print(f"  {'PASS' if passed else 'FAIL'} {name}")
    for name, passed in report.get("restart_recovery", {}).get("checks", {}).items():
        print(f"  {'PASS' if passed else 'FAIL'} restart_recovery.{name}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (E2EGuardError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Pipeline report could not verify this run: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
