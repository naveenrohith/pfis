"""Capture and read immutable planning-source snapshots for temporal evaluation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import (
    CardPaymentIntent,
    CreditCardStatement,
    DepositAccountStatement,
    DepositStatementLine,
    StatementLine,
)
from app.models.roadmap import CardDispute
from app.models.temporal_history import TemporalSourceSnapshot
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.temporal import (
    TemporalBackfillSourceType,
    TemporalHistoryBackfillResponse,
    TemporalHistoryBackfillSource,
)

RULESET_VERSION = "pfis-temporal-source-history-1"


def _json_default(value: Any) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported temporal snapshot value: {type(value).__name__}")


async def capture_temporal_source_snapshot(
    db: AsyncSession,
    *,
    user_id: str,
    source_type: str,
    source_id: str,
    payload: Mapping[str, Any] | None,
    deleted: bool = False,
    captured_at: datetime | None = None,
) -> None:
    """Append a changed source state without mutating prior evidence."""

    instant = captured_at or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)
    serialized = json.dumps(dict(payload or {}), default=_json_default, sort_keys=True)
    previous = await db.scalar(
        select(TemporalSourceSnapshot)
        .where(
            TemporalSourceSnapshot.user_id == user_id,
            TemporalSourceSnapshot.source_type == source_type,
            TemporalSourceSnapshot.source_id == source_id,
        )
        .order_by(TemporalSourceSnapshot.captured_at.desc())
        .limit(1)
    )
    if previous is not None and previous.deleted == deleted and previous.payload_json == serialized:
        return
    db.add(
        TemporalSourceSnapshot(
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            captured_at=instant,
            deleted=deleted,
            payload_json=serialized,
            ruleset_version=RULESET_VERSION,
        )
    )


async def capture_transaction_snapshot(
    db: AsyncSession,
    transaction: Transaction,
    *,
    deleted: bool = False,
    captured_at: datetime | None = None,
) -> None:
    """Capture the ledger state that was visible at a transaction mutation."""

    await capture_temporal_source_snapshot(
        db,
        user_id=transaction.user_id,
        source_type="transaction",
        source_id=transaction.id,
        payload={
            "amount": transaction.amount,
            "currency": transaction.currency,
            "transaction_type": transaction.transaction_type,
            "payment_rail": transaction.payment_rail,
            "card_event": transaction.card_event,
            "transaction_status": transaction.transaction_status,
            "transaction_date": transaction.transaction_date,
            "transaction_timestamp": transaction.transaction_timestamp,
            "merchant_raw": transaction.merchant_raw,
            "merchant_normalized": transaction.merchant_normalized,
            "category_id": transaction.category_id,
            "account_last4": transaction.account_last4,
            "reference_id": transaction.reference_id,
            "reviewed_flag": transaction.reviewed_flag,
            "review_outcome": transaction.review_outcome,
            "financial_account_id": transaction.financial_account_id,
            "transfer_group_id": transaction.transfer_group_id,
            "is_transfer": transaction.is_transfer,
            "is_accounting_adjustment": transaction.is_accounting_adjustment,
            "ledger_subtype": transaction.ledger_subtype,
            "source_kind": transaction.source_kind,
            "source_identifier": transaction.source_identifier,
        },
        deleted=deleted,
        captured_at=captured_at,
    )


def _identity_evidence_payload(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


async def capture_financial_account_snapshot(
    db: AsyncSession,
    account: FinancialAccount,
    *,
    effective_date: date | None = None,
    captured_at: datetime | None = None,
) -> None:
    """Capture the current account identity and lifecycle state immutably."""

    updated_at = account.updated_at or account.created_at or datetime.now(UTC)
    await capture_temporal_source_snapshot(
        db,
        user_id=account.user_id,
        source_type="financial_account",
        source_id=account.id,
        payload={
            "institution_name": account.institution_name,
            "account_type": account.account_type,
            "balance_kind": account.balance_kind,
            "masked_number": account.masked_number,
            "currency": account.currency,
            "connector_account_id": account.connector_account_id,
            "is_active": account.is_active,
            "identity_status": account.identity_status,
            "identity_confidence": account.identity_confidence,
            "identity_evidence": _identity_evidence_payload(account.identity_evidence_json),
            "effective_date": effective_date or updated_at.date(),
        },
        captured_at=captured_at,
    )


async def capture_statement_line_snapshot(
    db: AsyncSession,
    line: StatementLine,
    *,
    financial_account_id: str | None = None,
    deleted: bool = False,
    captured_at: datetime | None = None,
) -> None:
    """Capture issuer-line review and settlement lineage without rewriting history."""

    if financial_account_id is None:
        financial_account_id = await db.scalar(
            select(CreditCardStatement.financial_account_id).where(
                CreditCardStatement.id == line.credit_card_statement_id
            )
        )
    await capture_temporal_source_snapshot(
        db,
        user_id=line.user_id,
        source_type="statement_line",
        source_id=line.id,
        payload={
            "credit_card_statement_id": line.credit_card_statement_id,
            "financial_account_id": financial_account_id,
            "line_number": line.line_number,
            "transaction_date": line.transaction_date,
            "description": line.description,
            "amount": line.amount,
            "reference_id": line.reference_id,
            "transaction_type": line.transaction_type,
            "card_event": line.card_event,
            "component_kind": line.component_kind,
            "issuer_plan_reference": line.issuer_plan_reference,
            "installment_number": line.installment_number,
            "merchant_normalized": line.merchant_normalized,
            "merchant_confidence": line.merchant_confidence,
            "review_outcome": line.review_outcome,
            "created_transaction_id": line.created_transaction_id,
        },
        deleted=deleted,
        captured_at=captured_at,
    )


async def capture_deposit_statement_line_snapshot(
    db: AsyncSession,
    line: DepositStatementLine,
    *,
    financial_account_id: str | None = None,
    deleted: bool = False,
    captured_at: datetime | None = None,
) -> None:
    """Capture bank-statement rail review and settlement lineage."""

    if financial_account_id is None:
        financial_account_id = await db.scalar(
            select(DepositAccountStatement.financial_account_id).where(
                DepositAccountStatement.id == line.deposit_account_statement_id
            )
        )
    await capture_temporal_source_snapshot(
        db,
        user_id=line.user_id,
        source_type="deposit_statement_line",
        source_id=line.id,
        payload={
            "deposit_account_statement_id": line.deposit_account_statement_id,
            "financial_account_id": financial_account_id,
            "line_number": line.line_number,
            "transaction_date": line.transaction_date,
            "value_date": line.value_date,
            "description": line.description,
            "amount": line.amount,
            "reference_id": line.reference_id,
            "transaction_type": line.transaction_type,
            "payment_rail": line.payment_rail,
            "balance_after": line.balance_after,
            "review_outcome": line.review_outcome,
            "created_transaction_id": line.created_transaction_id,
        },
        deleted=deleted,
        captured_at=captured_at,
    )


async def capture_card_dispute_snapshot(
    db: AsyncSession,
    dispute: CardDispute,
    *,
    deleted: bool = False,
    captured_at: datetime | None = None,
) -> None:
    """Capture issuer-dispute status as append-only evidence."""

    await capture_temporal_source_snapshot(
        db,
        user_id=dispute.user_id,
        source_type="card_dispute",
        source_id=dispute.id,
        payload={
            "financial_account_id": dispute.financial_account_id,
            "statement_line_id": dispute.statement_line_id,
            "label": dispute.label,
            "amount": dispute.amount,
            "complaint_date": dispute.complaint_date,
            "reference_number": dispute.reference_number,
            "status": dispute.status,
            "note": dispute.note,
        },
        deleted=deleted,
        captured_at=captured_at,
    )


async def capture_card_payment_intent_snapshot(
    db: AsyncSession,
    intent: CardPaymentIntent,
    *,
    deleted: bool = False,
    captured_at: datetime | None = None,
) -> None:
    """Capture planned card-payment status without implying an external transfer."""

    await capture_temporal_source_snapshot(
        db,
        user_id=intent.user_id,
        source_type="card_payment_intent",
        source_id=intent.id,
        payload={
            "financial_account_id": intent.financial_account_id,
            "paying_account_id": intent.paying_account_id,
            "amount": intent.amount,
            "planned_for": intent.planned_for,
            "status": intent.status,
            "note": intent.note,
            "transfer_group_id": intent.transfer_group_id,
        },
        deleted=deleted,
        captured_at=captured_at,
    )


async def backfill_temporal_source_history(
    db: AsyncSession,
    *,
    user_id: str,
    source_types: list[TemporalBackfillSourceType],
    dry_run: bool,
    max_rows_per_source: int,
) -> TemporalHistoryBackfillResponse:
    """Capture a current baseline for legacy rows that lack source history.

    This is intentionally forward-only. A row created months ago is captured at
    the backfill instant; the operation must never pretend that its current
    state was known at the original transaction or account date.
    """

    if await db.scalar(select(User.id).where(User.id == user_id)) is None:
        raise LookupError("User not found")
    captured_at = datetime.now(UTC)
    source_results: list[TemporalHistoryBackfillSource] = []

    for source_type in source_types:
        if source_type == "transaction":
            transaction_rows = list(
                (
                    await db.scalars(
                        select(Transaction)
                        .where(Transaction.user_id == user_id)
                        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
                        .limit(max_rows_per_source)
                    )
                ).all()
            )
            source_ids = [row.id for row in transaction_rows]
            existing_ids = set(
                (
                    await db.scalars(
                        select(TemporalSourceSnapshot.source_id).where(
                            TemporalSourceSnapshot.user_id == user_id,
                            TemporalSourceSnapshot.source_type == source_type,
                            TemporalSourceSnapshot.source_id.in_(source_ids),
                        )
                    )
                ).all()
                if source_ids
                else []
            )
            missing_transaction_rows = [
                row for row in transaction_rows if row.id not in existing_ids
            ]
            if not dry_run:
                for transaction_row in missing_transaction_rows:
                    await capture_transaction_snapshot(db, transaction_row, captured_at=captured_at)
            candidate_count = len(transaction_rows)
            missing_snapshot_count = len(missing_transaction_rows)
        elif source_type == "financial_account":
            account_rows = list(
                (
                    await db.scalars(
                        select(FinancialAccount)
                        .where(FinancialAccount.user_id == user_id)
                        .order_by(FinancialAccount.created_at.asc(), FinancialAccount.id.asc())
                        .limit(max_rows_per_source)
                    )
                ).all()
            )
            source_ids = [row.id for row in account_rows]
            existing_ids = set(
                (
                    await db.scalars(
                        select(TemporalSourceSnapshot.source_id).where(
                            TemporalSourceSnapshot.user_id == user_id,
                            TemporalSourceSnapshot.source_type == source_type,
                            TemporalSourceSnapshot.source_id.in_(source_ids),
                        )
                    )
                ).all()
                if source_ids
                else []
            )
            missing_account_rows = [row for row in account_rows if row.id not in existing_ids]
            if not dry_run:
                for account_row in missing_account_rows:
                    await capture_financial_account_snapshot(
                        db, account_row, captured_at=captured_at
                    )
            candidate_count = len(account_rows)
            missing_snapshot_count = len(missing_account_rows)
        elif source_type == "statement_line":
            statement_line_rows = list(
                (
                    await db.scalars(
                        select(StatementLine)
                        .where(StatementLine.user_id == user_id)
                        .order_by(StatementLine.created_at.asc(), StatementLine.id.asc())
                        .limit(max_rows_per_source)
                    )
                ).all()
            )
            source_ids = [row.id for row in statement_line_rows]
            existing_ids = set(
                (
                    await db.scalars(
                        select(TemporalSourceSnapshot.source_id).where(
                            TemporalSourceSnapshot.user_id == user_id,
                            TemporalSourceSnapshot.source_type == source_type,
                            TemporalSourceSnapshot.source_id.in_(source_ids),
                        )
                    )
                ).all()
                if source_ids
                else []
            )
            statement_account_rows = (
                (
                    await db.execute(
                        select(StatementLine.id, CreditCardStatement.financial_account_id)
                        .join(
                            CreditCardStatement,
                            CreditCardStatement.id == StatementLine.credit_card_statement_id,
                        )
                        .where(StatementLine.id.in_(source_ids))
                    )
                ).all()
                if source_ids
                else []
            )
            account_by_line_id: dict[str, str] = {}
            for line_id, account_id in statement_account_rows:
                account_by_line_id[line_id] = account_id
            missing_statement_line_rows = [
                row for row in statement_line_rows if row.id not in existing_ids
            ]
            if not dry_run:
                for line_row in missing_statement_line_rows:
                    await capture_statement_line_snapshot(
                        db,
                        line_row,
                        financial_account_id=account_by_line_id.get(line_row.id),
                        captured_at=captured_at,
                    )
            candidate_count = len(statement_line_rows)
            missing_snapshot_count = len(missing_statement_line_rows)
        elif source_type == "deposit_statement_line":
            deposit_line_rows = list(
                (
                    await db.scalars(
                        select(DepositStatementLine)
                        .where(DepositStatementLine.user_id == user_id)
                        .order_by(DepositStatementLine.created_at.asc(), DepositStatementLine.id.asc())
                        .limit(max_rows_per_source)
                    )
                ).all()
            )
            source_ids = [row.id for row in deposit_line_rows]
            existing_ids = set(
                (
                    await db.scalars(
                        select(TemporalSourceSnapshot.source_id).where(
                            TemporalSourceSnapshot.user_id == user_id,
                            TemporalSourceSnapshot.source_type == source_type,
                            TemporalSourceSnapshot.source_id.in_(source_ids),
                        )
                    )
                ).all()
                if source_ids
                else []
            )
            deposit_account_rows = (
                (
                    await db.execute(
                        select(
                            DepositStatementLine.id,
                            DepositAccountStatement.financial_account_id,
                        )
                        .join(
                            DepositAccountStatement,
                            DepositAccountStatement.id
                            == DepositStatementLine.deposit_account_statement_id,
                        )
                        .where(DepositStatementLine.id.in_(source_ids))
                    )
                ).all()
                if source_ids
                else []
            )
            deposit_account_by_line_id: dict[str, str] = {}
            for deposit_account_row in deposit_account_rows:
                deposit_account_by_line_id[deposit_account_row[0]] = deposit_account_row[1]
            missing_deposit_line_rows = [
                row for row in deposit_line_rows if row.id not in existing_ids
            ]
            if not dry_run:
                for deposit_line_row in missing_deposit_line_rows:
                    await capture_deposit_statement_line_snapshot(
                        db,
                        deposit_line_row,
                        financial_account_id=deposit_account_by_line_id.get(deposit_line_row.id),
                        captured_at=captured_at,
                    )
            candidate_count = len(deposit_line_rows)
            missing_snapshot_count = len(missing_deposit_line_rows)
        elif source_type == "card_payment_intent":
            intent_rows = list(
                (
                    await db.scalars(
                        select(CardPaymentIntent)
                        .where(CardPaymentIntent.user_id == user_id)
                        .order_by(
                            CardPaymentIntent.planned_for.asc(),
                            CardPaymentIntent.created_at.asc(),
                            CardPaymentIntent.id.asc(),
                        )
                        .limit(max_rows_per_source)
                    )
                ).all()
            )
            source_ids = [row.id for row in intent_rows]
            existing_ids = set(
                (
                    await db.scalars(
                        select(TemporalSourceSnapshot.source_id).where(
                            TemporalSourceSnapshot.user_id == user_id,
                            TemporalSourceSnapshot.source_type == source_type,
                            TemporalSourceSnapshot.source_id.in_(source_ids),
                        )
                    )
                ).all()
                if source_ids
                else []
            )
            missing_intent_rows = [row for row in intent_rows if row.id not in existing_ids]
            if not dry_run:
                for intent_row in missing_intent_rows:
                    await capture_card_payment_intent_snapshot(
                        db,
                        intent_row,
                        captured_at=captured_at,
                    )
            candidate_count = len(intent_rows)
            missing_snapshot_count = len(missing_intent_rows)
        else:
            raise ValueError(f"Unsupported temporal source type: {source_type}")

        source_results.append(
            TemporalHistoryBackfillSource(
                source_type=source_type,
                candidate_count=candidate_count,
                existing_snapshot_count=len(existing_ids),
                missing_snapshot_count=missing_snapshot_count,
                captured_count=0 if dry_run else missing_snapshot_count,
                skipped_count=len(existing_ids),
                truncated=candidate_count >= max_rows_per_source,
            )
        )

    if not dry_run:
        await db.commit()

    return TemporalHistoryBackfillResponse(
        ruleset_version=RULESET_VERSION,
        dry_run=dry_run,
        captured_at=captured_at,
        sources=source_results,
        limitations=[
            "Backfill captures the current state at the backfill instant; it does not reconstruct what PFIS knew on an earlier financial day.",
            "Rows created or changed after this baseline are captured by normal mutation hooks when those hooks run.",
            "Statement-line baselines preserve issuer review and settlement lineage, but they do not prove that an external statement feed was complete.",
            "Historical forecast release evidence must still report the remaining cutoff coverage rather than treating a baseline capture as past evidence.",
        ],
    )


async def historical_source_snapshots(
    db: AsyncSession,
    *,
    user_id: str,
    timezone: str,
    as_of: date,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return the latest non-deleted source state known at a financial day."""

    try:
        zone: tzinfo = ZoneInfo(timezone)
    except Exception:
        zone = UTC
    cutoff = datetime.combine(as_of + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    rows = list(
        (
            await db.scalars(
                select(TemporalSourceSnapshot)
                .where(
                    TemporalSourceSnapshot.user_id == user_id,
                    TemporalSourceSnapshot.captured_at < cutoff,
                )
                .order_by(
                    TemporalSourceSnapshot.source_type,
                    TemporalSourceSnapshot.source_id,
                    TemporalSourceSnapshot.captured_at,
                    TemporalSourceSnapshot.id,
                )
            )
        ).all()
    )
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.source_type, row.source_id)
        if row.deleted:
            latest.pop(key, None)
            continue
        try:
            payload = json.loads(row.payload_json)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            latest[key] = payload
    return latest
