"""
Gmail Auth & Sync Routes
Handles OAuth flow and email synchronization.

Endpoints:
- GET  /api/auth/gmail/connect     → Redirect to Google consent screen
- GET  /api/auth/gmail/callback    → Handle OAuth callback
- POST /api/gmail/sync             → Trigger email sync
- GET  /api/gmail/status           → Get sync status
- GET  /api/gmail/emails           → List stored raw emails
"""

import logging
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.email import GmailAccount, RawEmail
from app.models.sync import ConnectorAuditEvent, OAuthState, SyncRun
from app.models.user import User
from app.security import (
    decrypt_secret,
    encrypt_secret,
    get_current_user_optional,
    hash_session_token,
    resolve_user_scope,
)
from app.services.auto_sync_service import stop_auto_sync_for_account
from app.services.gmail.oauth_service import (
    GMAIL_SCOPES,
    exchange_code_for_tokens,
    get_authorization_url,
    has_gmail_readonly_scope,
    revoke_google_token,
    verify_google_identity,
)
from app.services.gmail.sync_service import demo_sync_gmail_emails, sync_gmail_emails
from app.services.ingestion.activity import stop_user_ingestions

logger = logging.getLogger(__name__)
settings = get_settings()

# Two routers: one for auth, one for gmail operations
auth_router = APIRouter(prefix="/auth/gmail", tags=["Gmail Auth"])
gmail_router = APIRouter(prefix="/gmail", tags=["Gmail"])

# OAuth state TTL
_OAUTH_STATE_TTL_MINUTES = 10
_GMAIL_ACCOUNT_CONFLICT_DETAIL = "This Gmail account cannot be connected to this workspace"
_GMAIL_ACCOUNT_MISMATCH_DETAIL = "A different Gmail account is already connected to this workspace"
_GMAIL_SCOPE_REQUIRED_DETAIL = "Gmail read-only permission was not granted"
_GMAIL_OAUTH_INVALIDATED_DETAIL = "This Gmail connection request is no longer valid"


class AutoSyncUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=86400)


def _serialize_auto_sync(account: GmailAccount) -> dict:
    return {
        "gmail_account_id": account.id,
        "connection_status": (
            "reauthorization_required"
            if account.auto_sync_status == "paused" and account.auto_sync_error
            else "connected"
        ),
        "enabled": bool(account.auto_sync_enabled),
        "interval_seconds": account.auto_sync_interval_seconds,
        "status": account.auto_sync_status,
        "error": account.auto_sync_error,
        "last_synced_at": account.last_synced_at.isoformat() if account.last_synced_at else None,
        "last_history_id": account.last_history_id,
    }


def _parse_token_expiry(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _revoke_unclaimed_google_grant(token_data: dict) -> None:
    token = token_data.get("refresh_token") or token_data.get("access_token")
    if not token:
        return
    try:
        await revoke_google_token(token)
    except Exception as exc:
        logger.warning(
            "Google grant from invalidated Gmail OAuth could not be revoked exception=%s",
            type(exc).__name__,
        )


def _gmail_redirect(*, error: str | None = None) -> RedirectResponse:
    """Return a safe browser redirect without reflecting provider input."""
    query = {"gmail_error": error} if error else {"gmail_auth": "success"}
    return RedirectResponse(
        url=f"/dashboard?{urlencode(query)}",
        status_code=303,
    )


def _provider_error_code(error: str) -> str:
    """Map Google's callback error to a stable, non-sensitive UI code."""
    return {
        "access_denied": "access_denied",
        "consent_required": "consent_required",
        "org_internal": "provider_rejected",
        "temporarily_unavailable": "provider_unavailable",
    }.get(error, "provider_rejected")


def _exception_error_code(exc: HTTPException) -> str:
    """Map recoverable callback exceptions to stable browser-facing codes."""
    if exc.detail == _GMAIL_SCOPE_REQUIRED_DETAIL:
        return "gmail_scope_required"
    if exc.detail == _GMAIL_ACCOUNT_CONFLICT_DETAIL:
        return "gmail_account_conflict"
    if exc.detail == _GMAIL_ACCOUNT_MISMATCH_DETAIL:
        return "gmail_account_mismatch"
    if exc.detail == _GMAIL_OAUTH_INVALIDATED_DETAIL:
        return "gmail_connection_invalidated"
    return {
        400: "gmail_transaction_invalid",
        401: "gmail_identity_invalid",
        403: "gmail_connection_forbidden",
        409: "gmail_account_conflict",
    }.get(exc.status_code, "gmail_connection_failed")


# ─── OAuth Flow ───


@auth_router.get("/connect")
async def gmail_connect(
    user_id: str = Query(..., description="User ID to connect Gmail for"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1: Redirect user to Google OAuth consent screen.
    After consent, Google redirects back to /callback.
    """
    user_id = resolve_user_scope(user_id, current_user)
    try:
        auth_url, state, code_verifier, nonce = get_authorization_url(
            redirect_uri=settings.GMAIL_OAUTH_REDIRECT_URI,
            scopes=GMAIL_SCOPES,
            offline=True,
        )
        browser_token = token_urlsafe(32)
        owner_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
        owner = owner_result.scalar_one_or_none()
        if owner is None or not owner.is_active or owner.deletion_started_at is not None:
            raise HTTPException(status_code=403, detail="User account is inactive")
        # Persist state in DB
        oauth_state = OAuthState(
            state=state,
            user_id=user_id,
            flow_type="gmail_connect",
            browser_token_hash=hash_session_token(browser_token),
            code_verifier_ref=encrypt_secret(code_verifier),
            nonce_ref=encrypt_secret(nonce),
            connection_generation=owner.gmail_connection_generation,
            expires_at=datetime.now(UTC) + timedelta(minutes=_OAUTH_STATE_TTL_MINUTES),
        )
        db.add(oauth_state)
        await db.commit()
        logger.info(f"OAuth flow started for user {user_id[:8]}...")
        redirect = RedirectResponse(url=auth_url)
        redirect.set_cookie(
            settings.OAUTH_COOKIE_NAME,
            browser_token,
            max_age=_OAUTH_STATE_TTL_MINUTES * 60,
            httponly=True,
            secure=settings.SESSION_COOKIE_SECURE,
            samesite="lax",
            path="/api/auth",
        )
        return redirect
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to start Gmail OAuth exception=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Gmail connection could not be started"
        ) from exc


@auth_router.get("/callback")
async def gmail_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2: Handle OAuth callback from Google.
    Exchange auth code for tokens and store them.
    """
    if not state:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    # Verify state from DB
    oauth_state_result = await db.execute(select(OAuthState).where(OAuthState.state == state))
    oauth_state = oauth_state_result.scalar_one_or_none()
    now_utc = datetime.now(UTC)
    expires = oauth_state.expires_at if oauth_state is not None else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    browser_token = request.cookies.get(settings.OAUTH_COOKIE_NAME)
    browser_matches = bool(
        oauth_state
        and browser_token
        and oauth_state.browser_token_hash
        and oauth_state.browser_token_hash == hash_session_token(browser_token)
    )
    if (
        not oauth_state
        or expires is None
        or expires < now_utc
        or oauth_state.flow_type != "gmail_connect"
        or not browser_matches
    ):
        if oauth_state:
            await db.delete(oauth_state)
            await db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    user_id = oauth_state.user_id
    connection_generation = oauth_state.connection_generation
    code_verifier_ref = oauth_state.code_verifier_ref
    nonce_ref = oauth_state.nonce_ref
    await db.delete(oauth_state)
    await db.commit()

    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state — missing user")

    if error:
        response = _gmail_redirect(error=_provider_error_code(error))
        response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
        return response

    if not code:
        response = _gmail_redirect(error="missing_code")
        response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
        return response

    try:
        # Exchange code for tokens
        token_data = exchange_code_for_tokens(
            code,
            redirect_uri=settings.GMAIL_OAUTH_REDIRECT_URI,
            scopes=GMAIL_SCOPES,
            code_verifier=decrypt_secret(code_verifier_ref),
        )
        if not has_gmail_readonly_scope(token_data):
            raise HTTPException(status_code=403, detail=_GMAIL_SCOPE_REQUIRED_DETAIL)

        profile = verify_google_identity(
            token_data,
            expected_nonce=decrypt_secret(nonce_ref),
        )
        owner_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
        owner = owner_result.scalar_one_or_none()
        if (
            owner is None
            or not owner.is_active
            or owner.deletion_started_at is not None
            or owner.gmail_connection_generation != connection_generation
        ):
            await _revoke_unclaimed_google_grant(token_data)
            raise HTTPException(status_code=409, detail=_GMAIL_OAUTH_INVALIDATED_DETAIL)
        token_expires_at = _parse_token_expiry(token_data.get("expiry"))
        google_account_id = profile["google_account_id"]

        # Resolve both ownership dimensions before writing any credentials. A user
        # may reconnect the same mailbox, but cannot silently replace a mailbox or
        # take over a Google subject already linked to another PFIS user.
        account_result = await db.execute(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        )
        existing = account_result.scalar_one_or_none()
        account_owner_result = await db.execute(
            select(GmailAccount).where(GmailAccount.google_account_id == google_account_id)
        )
        existing_owner = account_owner_result.scalar_one_or_none()

        if existing_owner is not None and existing_owner.user_id != user_id:
            raise HTTPException(status_code=409, detail=_GMAIL_ACCOUNT_CONFLICT_DETAIL)

        if existing is not None and existing.google_account_id != google_account_id:
            raise HTTPException(status_code=409, detail=_GMAIL_ACCOUNT_MISMATCH_DETAIL)

        if existing:
            if existing.auto_sync_status == "disconnecting":
                raise HTTPException(
                    status_code=409,
                    detail="Gmail disconnect is already in progress.",
                )
            new_refresh_token = token_data.get("refresh_token")
            needs_reauthorization = existing.auto_sync_status == "paused" and bool(
                existing.auto_sync_error
            )
            if needs_reauthorization and not new_refresh_token:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Google did not provide a new Gmail authorization. "
                        "Reconnect Gmail and approve read-only inbox access."
                    ),
                )
            # Update tokens
            existing.access_token_ref = encrypt_secret(token_data["access_token"])
            refresh_token = encrypt_secret(new_refresh_token)
            if refresh_token:
                existing.refresh_token_ref = refresh_token
            existing.token_expires_at = token_expires_at
            existing.google_account_id = profile["google_account_id"]
            existing.auto_sync_status = "idle" if existing.auto_sync_enabled else "paused"
            existing.auto_sync_error = None
            gmail_account_id = existing.id
            logger.info(f"Updated Gmail tokens for user {user_id[:8]}...")
        else:
            # Create new Gmail account link
            gmail_account = GmailAccount(
                user_id=user_id,
                google_account_id=google_account_id,
                access_token_ref=encrypt_secret(token_data["access_token"]),
                refresh_token_ref=encrypt_secret(token_data.get("refresh_token")),
                token_expires_at=token_expires_at,
            )
            db.add(gmail_account)
            await db.flush()
            gmail_account_id = gmail_account.id
            logger.info(f"Created Gmail account link for user {user_id[:8]}...")

        await db.commit()
        await _record_connector_audit(
            db,
            user_id,
            gmail_account_id,
            "connect",
            {"status": "connected"},
        )

        response = _gmail_redirect()
        response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
        return response

    except HTTPException as exc:
        await db.rollback()
        if exc.status_code in {400, 401, 403, 409}:
            response = _gmail_redirect(error=_exception_error_code(exc))
            response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
            return response
        raise
    except IntegrityError:
        await db.rollback()
        logger.warning("Gmail OAuth callback rejected by account ownership constraint")
        response = _gmail_redirect(error="gmail_account_conflict")
        response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
        return response
    except Exception as exc:
        await db.rollback()
        logger.error("Gmail OAuth callback failed exception=%s", type(exc).__name__)
        response = _gmail_redirect(error="gmail_connection_failed")
        response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
        return response


# ─── Gmail Operations ───


@gmail_router.post("/sync")
async def trigger_sync(
    user_id: str = Query(...),
    max_results: int = Query(500, ge=1, le=5000),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a Gmail sync for a user.
    Fetches new emails, filters financial ones, stores them.
    """
    user_id = resolve_user_scope(user_id, current_user)
    # Find Gmail account for user
    result = await db.execute(select(GmailAccount).where(GmailAccount.user_id == user_id))
    gmail_account = result.scalar_one_or_none()

    if not gmail_account:
        raise HTTPException(
            status_code=404, detail="No Gmail account connected. Use /api/auth/gmail/connect first."
        )
    if gmail_account.auto_sync_status == "disconnecting":
        raise HTTPException(status_code=409, detail="Gmail disconnect is already in progress.")

    try:
        stats = await sync_gmail_emails(
            db=db,
            user_id=user_id,
            gmail_account_id=gmail_account.id,
            max_results=max_results,
        )
        return {
            "status": "completed",
            "stats": stats,
        }
    except Exception as exc:
        logger.error("Gmail sync route failed exception=%s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Gmail synchronization failed") from exc


@gmail_router.get("/status")
async def get_sync_status(
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest sync run status for a user."""
    user_id = resolve_user_scope(user_id, current_user)
    result = await db.execute(
        select(SyncRun)
        .where(SyncRun.user_id == user_id)
        .order_by(SyncRun.start_time.desc())
        .limit(5)
    )
    runs = result.scalars().all()

    if not runs:
        return {"message": "No sync runs found", "runs": []}

    return {
        "latest_status": runs[0].status.value,
        "runs": [
            {
                "id": r.id,
                "status": r.status.value,
                "start_time": r.start_time.isoformat() if r.start_time else None,
                "end_time": r.end_time.isoformat() if r.end_time else None,
                "emails_fetched": r.emails_fetched,
                "emails_processed": r.emails_processed,
                "emails_failed": r.emails_failed,
                "coverage_complete": r.coverage_complete,
                "coverage_truncated": r.coverage_truncated,
                "coverage_pages": r.coverage_pages,
                "coverage_result_size_estimate": r.coverage_result_size_estimate,
            }
            for r in runs
        ],
    }


@gmail_router.get("/auto-sync")
async def get_auto_sync_status(
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Return automatic Gmail sync settings and runtime state."""
    user_id = resolve_user_scope(user_id, current_user)
    result = await db.execute(select(GmailAccount).where(GmailAccount.user_id == user_id))
    gmail_account = result.scalar_one_or_none()
    if not gmail_account:
        raise HTTPException(
            status_code=404, detail="No Gmail account connected. Use /api/auth/gmail/connect first."
        )
    return _serialize_auto_sync(gmail_account)


@gmail_router.patch("/auto-sync")
async def update_auto_sync_status(
    payload: AutoSyncUpdate,
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Enable/disable automatic Gmail sync or adjust its interval."""
    user_id = resolve_user_scope(user_id, current_user)
    result = await db.execute(select(GmailAccount).where(GmailAccount.user_id == user_id))
    gmail_account = result.scalar_one_or_none()
    if not gmail_account:
        raise HTTPException(
            status_code=404, detail="No Gmail account connected. Use /api/auth/gmail/connect first."
        )
    if gmail_account.auto_sync_status == "disconnecting":
        raise HTTPException(status_code=409, detail="Gmail disconnect is already in progress.")

    if payload.enabled is not None:
        gmail_account.auto_sync_enabled = payload.enabled
        has_credential_error = bool(gmail_account.auto_sync_error)
        if payload.enabled:
            if not (gmail_account.auto_sync_status == "paused" and has_credential_error):
                gmail_account.auto_sync_status = "idle"
                gmail_account.auto_sync_error = None
        elif not has_credential_error:
            gmail_account.auto_sync_status = "paused"
            gmail_account.auto_sync_error = None
    if payload.interval_seconds is not None:
        gmail_account.auto_sync_interval_seconds = payload.interval_seconds
    await db.commit()
    await db.refresh(gmail_account)
    return _serialize_auto_sync(gmail_account)


@gmail_router.delete("/connection")
async def disconnect_gmail(
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Stop future Gmail access while retaining already imported financial records."""
    user_id = resolve_user_scope(user_id, current_user)
    owner_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    owner = owner_result.scalar_one_or_none()
    if owner is None or not owner.is_active or owner.deletion_started_at is not None:
        raise HTTPException(status_code=404, detail="User account is not available.")
    result = await db.execute(
        select(GmailAccount).where(GmailAccount.user_id == user_id).with_for_update()
    )
    gmail_account = result.scalar_one_or_none()
    if not gmail_account:
        raise HTTPException(status_code=404, detail="No Gmail account is connected.")

    gmail_account.auto_sync_enabled = False
    gmail_account.auto_sync_status = "disconnecting"
    gmail_account.auto_sync_error = None
    owner.gmail_connection_generation += 1
    await db.execute(
        delete(OAuthState).where(
            OAuthState.user_id == user_id,
            OAuthState.flow_type == "gmail_connect",
        )
    )
    await db.commit()

    # Establish the local fence before revocation/deletion. This prevents an
    # already scheduled worker or in-flight ingestion from writing after the
    # connector grant is removed.
    await stop_auto_sync_for_account(gmail_account.id)
    await stop_user_ingestions(user_id)

    revocation_status = "unconfirmed"
    encrypted_token = gmail_account.refresh_token_ref or gmail_account.access_token_ref
    try:
        token = decrypt_secret(encrypted_token)
    except Exception as exc:
        token = None
        logger.warning(
            "Gmail credential could not be read during disconnect exception=%s",
            type(exc).__name__,
        )
    if not token:
        revocation_status = "token_unavailable"
    else:
        try:
            revocation_status = (
                "revoked" if await revoke_google_token(token) else "provider_rejected"
            )
        except Exception as exc:
            logger.warning(
                "Gmail provider revocation could not be confirmed exception=%s",
                type(exc).__name__,
            )

    raw_email_count = int(
        await db.scalar(select(func.count(RawEmail.id)).where(RawEmail.user_id == user_id)) or 0
    )
    gmail_account_id = gmail_account.id
    await db.delete(gmail_account)
    await _record_connector_audit(
        db,
        user_id,
        gmail_account_id,
        "disconnect",
        {
            "provider_revocation": revocation_status,
            "retained_raw_email_count": raw_email_count,
            "derived_records_retained": True,
        },
        commit=False,
    )
    await db.commit()
    return {
        "status": "disconnected",
        "provider_revocation": revocation_status,
        "retained_raw_email_count": raw_email_count,
        "derived_records_retained": True,
    }


@gmail_router.get("/emails")
async def list_raw_emails(
    user_id: str = Query(...),
    processed: bool = Query(None, description="Filter by processed flag"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """List stored raw emails for a user."""
    user_id = resolve_user_scope(user_id, current_user)
    base_query = select(RawEmail).where(RawEmail.user_id == user_id)
    query = base_query
    count_query = select(func.count(RawEmail.id)).where(RawEmail.user_id == user_id)

    if processed is not None:
        query = query.where(RawEmail.processed_flag == processed)
        count_query = count_query.where(RawEmail.processed_flag == processed)

    query = query.order_by(RawEmail.received_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    emails = result.scalars().all()

    # Get filtered count and overall processed/unprocessed totals.
    count_result = await db.execute(count_query)
    total = int(count_result.scalar() or 0)

    all_total_result = await db.execute(
        select(func.count(RawEmail.id)).where(RawEmail.user_id == user_id)
    )
    all_total = int(all_total_result.scalar() or 0)

    processed_total_result = await db.execute(
        select(func.count(RawEmail.id)).where(
            RawEmail.user_id == user_id,
            RawEmail.processed_flag.is_(True),
        )
    )
    processed_total = int(processed_total_result.scalar() or 0)

    unprocessed_total_result = await db.execute(
        select(func.count(RawEmail.id)).where(
            RawEmail.user_id == user_id,
            RawEmail.processed_flag.is_(False),
        )
    )
    unprocessed_total = int(unprocessed_total_result.scalar() or 0)

    return {
        "total": total,
        "all_total": all_total,
        "processed_total": processed_total,
        "unprocessed_total": unprocessed_total,
        "applied_filter": processed,
        "emails": [
            {
                "id": e.id,
                "gmail_message_id": e.gmail_message_id,
                "sender": e.sender,
                "subject": e.subject,
                "body_preview": (e.body or "")[:200],
                "received_at": e.received_at.isoformat() if e.received_at else None,
                "processed": e.processed_flag,
            }
            for e in emails
        ],
    }


# ─── Demo Mode (No OAuth Required) ───


@gmail_router.post("/demo-sync")
async def demo_sync(
    user_id: str = Query(...),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Simulate Gmail sync using sample bank emails.
    No OAuth required — perfect for testing the pipeline.
    Injects 15 realistic Indian bank emails into the system.
    """
    user_id = resolve_user_scope(user_id, current_user)
    stats = await demo_sync_gmail_emails(db, user_id)

    logger.info(
        f"Demo sync complete: {stats['emails_stored']} stored, "
        f"{stats['emails_skipped_otp']} OTP skipped, "
        f"{stats['emails_skipped_promo']} promo skipped"
    )

    return {
        "status": "completed",
        "mode": "demo",
        "stats": stats,
    }


async def _record_connector_audit(
    db: AsyncSession,
    user_id: str,
    gmail_account_id: str | None,
    event_type: str,
    payload: dict,
    *,
    commit: bool = True,
) -> None:
    import json

    db.add(
        ConnectorAuditEvent(
            user_id=user_id,
            connector_type="gmail",
            connector_account_id=gmail_account_id,
            event_type=event_type,
            payload_json=json.dumps(payload),
        )
    )
    if commit:
        await db.commit()
