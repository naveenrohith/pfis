"""Shared statement detection and product dispatch for uploaded and Gmail PDFs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.email import GmailAccount
from app.models.user import User
from app.schemas.financial_position import (
    StatementAnalysisResponse,
    StatementDetectionResponse,
    StatementImportResultResponse,
    StatementTextImport,
)
from app.services.financial_position_service import FinancialPositionService
from app.services.gmail.statement_attachment_service import public_error
from app.services.statement_analysis import analyze_statement
from app.services.statement_detection import detect_statement


def statement_detection_response(statement_text: str) -> StatementDetectionResponse:
    detection = detect_statement(statement_text)
    return StatementDetectionResponse(
        institution=detection.institution,
        product_type=detection.product_type,
        format_id=detection.format_id,
        support_status=detection.support_status,
        confidence=detection.confidence,
        reason_codes=list(detection.reason_codes),
        activity_types=list(detection.activity_types),
        detector_version=detection.detector_version,
        analysis=StatementAnalysisResponse.model_validate(
            analyze_statement(statement_text, detection)
        ),
    )


async def lock_statement_user(db: AsyncSession, user_id: str) -> User:
    owner = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if owner is None or not owner.is_active or owner.deletion_started_at is not None:
        raise public_error("user_unavailable", "User account is not available", 403)
    return owner


async def import_detected_statement(
    db: AsyncSession,
    user_id: str,
    data: StatementTextImport,
    *,
    detection: StatementDetectionResponse | None = None,
    service: FinancialPositionService | None = None,
    expected_connection: tuple[str, int] | None = None,
) -> StatementImportResultResponse:
    detection = detection or statement_detection_response(data.statement_text)
    if detection.support_status != "supported":
        raise ValueError("Statement is recognized but not supported for import")
    owner = await lock_statement_user(db, user_id)
    if expected_connection is not None:
        account_id, generation = expected_connection
        account = await db.scalar(
            select(GmailAccount)
            .where(
                GmailAccount.id == account_id,
                GmailAccount.user_id == user_id,
                GmailAccount.auto_sync_status != "disconnecting",
            )
            .execution_options(populate_existing=True)
        )
        if owner.gmail_connection_generation != generation or account is None:
            raise public_error("source_expired", "The Gmail connection changed; search again", 409)
        if account.auto_sync_status == "paused" and account.auto_sync_error:
            raise public_error(
                "gmail_reauthorization_required", "Reconnect Gmail to read statements", 409
            )
        target = await db.scalar(
            select(FinancialAccount)
            .where(
                FinancialAccount.id == data.financial_account_id,
                FinancialAccount.user_id == user_id,
            )
            .execution_options(populate_existing=True)
        )
        if target is None:
            raise LookupError("Choose an owned compatible financial account")
        if not target.is_active:
            raise ValueError("Statement imports require an active financial account")
        if detection.institution == "hdfc" and "HDFC" not in target.institution_name.upper():
            raise ValueError("HDFC statements require an HDFC financial account")
    service = service or FinancialPositionService(db)
    if detection.product_type == "credit_card":
        card = (
            await service.import_hdfc_statement_text(user_id, data)
            if detection.institution == "hdfc"
            else await service.import_generic_credit_card_statement_text(user_id, data)
        )
        return StatementImportResultResponse(
            product_type="credit_card", detection=detection, credit_card_statement=card
        )
    if detection.product_type == "deposit_account":
        deposit = (
            await service.import_hdfc_deposit_statement_text(user_id, data)
            if detection.institution == "hdfc"
            else await service.import_generic_deposit_statement_text(user_id, data)
        )
        return StatementImportResultResponse(
            product_type="deposit_account", detection=detection, deposit_account_statement=deposit
        )
    raise ValueError("Statement product could not be determined safely")
