"""Shared persistence for reconciled deposit-statement extractors."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.financial_position import (
    DepositAccountStatement,
    DepositStatementLine,
    StatementImport,
)
from app.schemas.financial_position import DepositAccountStatementResponse, StatementTextImport
from app.services.temporal_source_history import capture_deposit_statement_line_snapshot
from app.services.transaction_service import DuplicateTransactionError

if TYPE_CHECKING:
    from app.services.financial_position_service import FinancialPositionService


async def persist_deposit_statement(
    service: FinancialPositionService,
    user_id: str,
    data: StatementTextImport,
    account: FinancialAccount,
    extracted: dict[str, Any],
    *,
    issuer: str,
    extractor_version: str,
    account_last4: str,
) -> DepositAccountStatementResponse:
    """Persist one already-validated deposit extraction atomically.

    Extractors own source parsing and balance proof. This helper owns the
    existing idempotent statement/line/transaction workflow so HDFC and
    generic bank profiles cannot drift apart.
    """

    existing_import = await service.db.scalar(
        select(StatementImport).where(
            StatementImport.user_id == user_id,
            StatementImport.document_fingerprint == data.document_fingerprint,
        )
    )
    if existing_import is not None:
        existing_statement = await service.db.scalar(
            select(DepositAccountStatement).where(
                DepositAccountStatement.statement_import_id == existing_import.id,
                DepositAccountStatement.user_id == user_id,
            )
        )
        if existing_statement is None:
            raise ValueError("The existing statement import is incomplete")
        return await service.deposit_statement(user_id, existing_statement.id)

    statement_import = StatementImport(
        user_id=user_id,
        financial_account_id=account.id,
        issuer=issuer[:40],
        document_fingerprint=data.document_fingerprint,
        extractor_version=extractor_version,
    )
    service.db.add(statement_import)
    try:
        await service.db.flush()
        statement = DepositAccountStatement(
            user_id=user_id,
            statement_import_id=statement_import.id,
            financial_account_id=account.id,
            period_start=extracted["period_start"],
            period_end=extracted["period_end"],
            opening_balance=extracted["opening_balance"],
            closing_balance=extracted["closing_balance"],
            currency=account.currency,
        )
        service.db.add(statement)
        await service.db.flush()

        for line_number, line in enumerate(extracted["lines"], start=1):
            line_record = DepositStatementLine(
                user_id=user_id,
                deposit_account_statement_id=statement.id,
                line_number=line_number,
                **line,
            )
            service.db.add(line_record)
            await service.db.flush()
            if line_record.review_outcome != "ready_to_import":
                await capture_deposit_statement_line_snapshot(
                    service.db,
                    line_record,
                    financial_account_id=account.id,
                )
                continue

            existing_transaction, has_conflict = await service._match_deposit_statement_line(
                user_id, account.id, line_record
            )
            if existing_transaction is not None:
                line_record.created_transaction_id = existing_transaction.id
                line_record.review_outcome = "matched"
            elif has_conflict:
                line_record.review_outcome = "needs_review"
            else:
                try:
                    created = await service._create_deposit_statement_transaction(
                        user_id,
                        account,
                        line_record,
                        account_last4=account_last4,
                        source_identifier=statement_import.id,
                    )
                    line_record.created_transaction_id = created.id
                    line_record.review_outcome = "newly_imported"
                except DuplicateTransactionError:
                    line_state = inspect(line_record)
                    if line_state.transient or line_state.detached:
                        raise RuntimeError(
                            "Deposit statement import lost its atomic transaction"
                        ) from None
                    line_record.review_outcome = "needs_review"
            await capture_deposit_statement_line_snapshot(
                service.db,
                line_record,
                financial_account_id=account.id,
            )

        service.db.add(
            AccountBalanceSnapshot(
                user_id=user_id,
                financial_account_id=account.id,
                amount=statement.closing_balance,
                currency=statement.currency,
                as_of=statement.period_end,
                source="statement",
                source_record_id=f"deposit-statement:{statement.id}",
                verified=True,
                observed_at=datetime.now(UTC),
            )
        )
        await service.db.commit()
    except IntegrityError as exc:
        await service.db.rollback()
        concurrent_import = await service.db.scalar(
            select(StatementImport).where(
                StatementImport.user_id == user_id,
                StatementImport.document_fingerprint == data.document_fingerprint,
            )
        )
        if concurrent_import is not None:
            concurrent_statement = await service.db.scalar(
                select(DepositAccountStatement).where(
                    DepositAccountStatement.statement_import_id == concurrent_import.id,
                    DepositAccountStatement.user_id == user_id,
                )
            )
            if concurrent_statement is not None:
                return await service.deposit_statement(user_id, concurrent_statement.id)
        raise ValueError("The deposit statement conflicts with an existing statement") from exc
    except Exception:
        await service.db.rollback()
        raise
    return await service.deposit_statement(user_id, statement.id)
