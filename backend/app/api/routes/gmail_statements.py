"""User-triggered, ephemeral Gmail statement intake."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.error_responses import error_response
from app.database import get_db
from app.models.email import GmailAccount
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.financial_position import StatementImportResultResponse, StatementTextImport
from app.schemas.gmail_statements import (
    GmailStatementCandidate,
    GmailStatementCandidates,
    GmailStatementDetection,
    GmailStatementImportRequest,
    GmailStatementRequest,
)
from app.security import get_current_user_optional, resolve_user_scope
from app.services.gmail.statement_attachment_service import (
    GmailStatementAttachments,
    open_reference,
    public_error,
    seal_reference,
)
from app.services.ingestion.activity import UserUnavailableError, tracked_user_ingestion
from app.services.statement_import_service import (
    import_detected_statement,
    statement_detection_response,
)
from app.services.statement_pdf_extractor import (
    StatementPdfPasswordError,
    extract_statement_pdf_text,
)

router = APIRouter(prefix="/statements/gmail", tags=["Gmail statements"])
CANDIDATE_DEADLINE_SECONDS = 60
FETCH_DEADLINE_SECONDS = 45


async def _statement_user(
    request: Request,
    user_id: str,
    current_user: User | None = Depends(get_current_user_optional),
) -> str:
    scoped = resolve_user_scope(user_id, current_user)
    request.state.gmail_statement_user = scoped
    return scoped


def _user_limit_key(request: Request) -> str:
    return getattr(request.state, "gmail_statement_user", "anonymous")


async def _connection(db: AsyncSession, user_id: str) -> tuple[GmailAccount, int]:
    owner = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if owner is None or not owner.is_active or owner.deletion_started_at is not None:
        raise public_error("user_unavailable", "Sign in to an active workspace", 403)
    account = await db.scalar(select(GmailAccount).where(GmailAccount.user_id == user_id))
    if account is None or account.auto_sync_status == "disconnecting":
        raise public_error("gmail_disconnected", "Connect Gmail to choose a statement", 409)
    if account.auto_sync_status == "paused" and account.auto_sync_error:
        raise public_error(
            "gmail_reauthorization_required", "Reconnect Gmail to read statements", 409
        )
    generation = owner.gmail_connection_generation
    await db.commit()
    return account, generation


async def _lock_connection(
    db: AsyncSession,
    user_id: str,
    account_id: str,
    generation: int,
    credentials: tuple[str | None, str | None] | None = None,
    provider: GmailStatementAttachments | None = None,
) -> None:
    # Match disconnect's lock order; credential persistence is a short transaction.
    owner = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    query = (
        select(GmailAccount)
        .where(GmailAccount.id == account_id, GmailAccount.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    account = await db.scalar(query.with_for_update() if provider is not None else query)
    if (
        owner is None
        or not owner.is_active
        or owner.deletion_started_at is not None
        or owner.gmail_connection_generation != generation
        or account is None
        or account.auto_sync_status == "disconnecting"
    ):
        raise public_error("source_expired", "The Gmail connection changed; search again", 409)
    if account.auto_sync_status == "paused" and account.auto_sync_error:
        raise public_error(
            "gmail_reauthorization_required", "Reconnect Gmail to read statements", 409
        )
    if (
        provider is not None
        and (account.access_token_ref, account.refresh_token_ref) == credentials
    ):
        refreshed = provider.connector.account
        account.access_token_ref = refreshed.access_token_ref
        account.refresh_token_ref = refreshed.refresh_token_ref
        account.token_expires_at = refreshed.token_expires_at


def _failure(request: Request, exc: HTTPException):
    if not isinstance(exc.detail, dict) or "code" not in exc.detail:
        raise exc
    return error_response(
        request, exc.status_code, code=exc.detail["code"], message=exc.detail["message"]
    )


def _password(data: GmailStatementRequest) -> str | None:
    value = data.password.get_secret_value() if data.password is not None else None
    if value is not None and len(value) > 256:
        raise public_error("invalid_password", "The PDF password must be 256 characters or fewer")
    return value


@router.get("/candidates", response_model=GmailStatementCandidates)
@limiter.limit("10/minute", key_func=_user_limit_key)
async def list_gmail_statement_candidates(
    request: Request,
    user_id: str = Depends(_statement_user),
    start_date: date | None = None,
    end_date: date | None = None,
    cursor: str | None = Query(None, max_length=4096),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(UTC).date()
    start = start_date or today - timedelta(days=365)
    end = end_date or today + timedelta(days=1)
    try:
        if start >= end or (end - start).days > 3660 or end > today + timedelta(days=1):
            raise public_error(
                "invalid_date_range",
                "Choose a date window of up to ten years ending no later than tomorrow",
            )
        async with tracked_user_ingestion(db, user_id):
            account, generation = await _connection(db, user_id)
            account_id = account.id
            credentials = (account.access_token_ref, account.refresh_token_ref)
            provider = GmailStatementAttachments(account)
            page_token = None
            if cursor:
                values = open_reference(cursor, user_id, account_id, generation, "cursor")
                if values.get("start") != str(start) or values.get("end") != str(end):
                    raise public_error(
                        "source_expired", "Search dates changed; start a new search", 409
                    )
                page_token = values["page"]
            await db.commit()
            page = await asyncio.wait_for(
                provider.candidates(start, end, page_token), timeout=CANDIDATE_DEADLINE_SECONDS
            )
            await _lock_connection(db, user_id, account_id, generation, credentials, provider)
            await db.commit()
        candidates = [
            GmailStatementCandidate(
                source_ref=seal_reference(
                    user_id,
                    account_id,
                    generation,
                    "source",
                    message=item["message_id"],
                    part=item["part_id"],
                ),
                **{
                    key: value
                    for key, value in item.items()
                    if key not in {"message_id", "part_id"}
                },
            )
            for item in page.candidates
        ]
        return GmailStatementCandidates(
            candidates=candidates,
            next_cursor=(
                seal_reference(
                    user_id,
                    account_id,
                    generation,
                    "cursor",
                    start=str(start),
                    end=str(end),
                    page=page.next_page_token,
                )
                if page.next_page_token
                else None
            ),
            coverage_complete=not (page.next_page_token or page.message_failures or page.truncated),
            message_failures=page.message_failures,
            truncated=page.truncated,
        )
    except TimeoutError:
        await db.rollback()
        return _failure(
            request, public_error("gmail_unavailable", "Gmail took too long; try again", 503)
        )
    except UserUnavailableError:
        await db.rollback()
        return _failure(
            request, public_error("user_unavailable", "Sign in to an active workspace", 403)
        )
    except HTTPException as exc:
        await db.rollback()
        return _failure(request, exc)


async def _read_source(db: AsyncSession, user_id: str, data: GmailStatementRequest):
    password = _password(data)
    account, generation = await _connection(db, user_id)
    account_id = account.id
    credentials = (account.access_token_ref, account.refresh_token_ref)
    reference = open_reference(data.source_ref, user_id, account_id, generation, "source")
    provider = GmailStatementAttachments(account)
    payload = await asyncio.wait_for(
        provider.fetch(reference["message"], reference["part"]), timeout=FETCH_DEADLINE_SECONDS
    )
    await _lock_connection(db, user_id, account_id, generation, credentials, provider)
    await db.commit()
    fingerprint = hashlib.sha256(payload).hexdigest()
    try:
        extracted = await asyncio.to_thread(extract_statement_pdf_text, payload, password=password)
    except StatementPdfPasswordError as exc:
        await _lock_connection(db, user_id, account_id, generation)
        await db.commit()
        raise exc
    except ImportError:
        raise public_error(
            "extractor_unavailable", "PDF reading is unavailable on this server", 503
        ) from None
    except ValueError as exc:
        raise public_error("unreadable_pdf", str(exc)) from None
    return extracted.text, fingerprint, (account_id, generation)


@router.post("/detect", response_model=GmailStatementDetection)
@limiter.limit("20/minute", key_func=_user_limit_key)
async def detect_gmail_statement(
    request: Request,
    data: GmailStatementRequest,
    user_id: str = Depends(_statement_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        async with tracked_user_ingestion(db, user_id):
            text, fingerprint, connection = await _read_source(db, user_id, data)
            detection = await asyncio.to_thread(statement_detection_response, text)
            await _lock_connection(db, user_id, *connection)
            await db.commit()
        return GmailStatementDetection(
            status="detected", detection=detection, document_fingerprint=fingerprint
        )
    except StatementPdfPasswordError as exc:
        return GmailStatementDetection(status=exc.code)
    except TimeoutError:
        await db.rollback()
        return _failure(
            request, public_error("gmail_unavailable", "Gmail took too long; try again", 503)
        )
    except UserUnavailableError:
        await db.rollback()
        return _failure(
            request, public_error("user_unavailable", "Sign in to an active workspace", 403)
        )
    except HTTPException as exc:
        await db.rollback()
        return _failure(request, exc)


@router.post("/import", response_model=StatementImportResultResponse, status_code=201)
@limiter.limit("20/minute", key_func=_user_limit_key)
async def import_gmail_statement(
    request: Request,
    data: GmailStatementImportRequest,
    user_id: str = Depends(_statement_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        async with tracked_user_ingestion(db, user_id):
            text, fingerprint, connection = await _read_source(db, user_id, data)
            if fingerprint != data.document_fingerprint:
                raise public_error(
                    "source_changed", "The PDF changed; check it again before import", 409
                )
            result = await import_detected_statement(
                db,
                user_id,
                StatementTextImport(
                    financial_account_id=data.financial_account_id,
                    statement_text=text,
                    document_fingerprint=fingerprint,
                ),
                expected_connection=connection,
            )
            await db.commit()
        return result
    except StatementPdfPasswordError as exc:
        return _failure(request, public_error(exc.code, str(exc)))
    except TimeoutError:
        await db.rollback()
        return _failure(
            request, public_error("gmail_unavailable", "Gmail took too long; try again", 503)
        )
    except UserUnavailableError:
        await db.rollback()
        return _failure(
            request, public_error("user_unavailable", "Sign in to an active workspace", 403)
        )
    except LookupError:
        await db.rollback()
        return _failure(
            request,
            public_error(
                "account_unavailable", "Choose an owned compatible financial account", 404
            ),
        )
    except ValueError as exc:
        await db.rollback()
        return _failure(request, public_error("statement_rejected", str(exc), 409))
    except HTTPException as exc:
        await db.rollback()
        return _failure(request, exc)
    except Exception:
        await db.rollback()
        raise
