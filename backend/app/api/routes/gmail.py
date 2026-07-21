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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
from app.services.gmail.oauth_service import (
    GMAIL_SCOPES,
    exchange_code_for_tokens,
    get_authorization_url,
    verify_google_identity,
)
from app.services.gmail.sync_service import demo_sync_gmail_emails, sync_gmail_emails

logger = logging.getLogger(__name__)
settings = get_settings()

# Two routers: one for auth, one for gmail operations
auth_router = APIRouter(prefix="/auth/gmail", tags=["Gmail Auth"])
gmail_router = APIRouter(prefix="/gmail", tags=["Gmail"])

# OAuth state TTL
_OAUTH_STATE_TTL_MINUTES = 10


class AutoSyncUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=86400)


def _serialize_auto_sync(account: GmailAccount) -> dict:
    return {
        "gmail_account_id": account.id,
        "enabled": bool(account.auto_sync_enabled),
        "interval_seconds": account.auto_sync_interval_seconds,
        "status": account.auto_sync_status,
        "error": account.auto_sync_error,
        "last_synced_at": account.last_synced_at.isoformat() if account.last_synced_at else None,
        "last_history_id": account.last_history_id,
    }


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
        # Persist state in DB
        oauth_state = OAuthState(
            state=state,
            user_id=user_id,
            flow_type="gmail_connect",
            browser_token_hash=hash_session_token(browser_token),
            code_verifier_ref=encrypt_secret(code_verifier),
            nonce_ref=encrypt_secret(nonce),
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
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2: Handle OAuth callback from Google.
    Exchange auth code for tokens and store them.
    """
    # Verify state from DB
    oauth_state_result = await db.execute(select(OAuthState).where(OAuthState.state == state))
    oauth_state = oauth_state_result.scalar_one_or_none()
    now_utc = datetime.now(UTC)
    expires = oauth_state.expires_at if oauth_state is not None else None
    if expires is not None and expires.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=None)
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
    code_verifier_ref = oauth_state.code_verifier_ref
    nonce_ref = oauth_state.nonce_ref
    await db.delete(oauth_state)
    await db.commit()

    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state — missing user")

    try:
        # Exchange code for tokens
        token_data = exchange_code_for_tokens(
            code,
            redirect_uri=settings.GMAIL_OAUTH_REDIRECT_URI,
            scopes=GMAIL_SCOPES,
            code_verifier=decrypt_secret(code_verifier_ref),
        )
        profile = verify_google_identity(
            token_data,
            expected_nonce=decrypt_secret(nonce_ref),
        )

        # Check if Gmail account already exists for this user
        account_result = await db.execute(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        )
        existing = account_result.scalar_one_or_none()

        if existing:
            # Update tokens
            existing.access_token_ref = encrypt_secret(token_data["access_token"])
            refresh_token = encrypt_secret(token_data.get("refresh_token"))
            if refresh_token:
                existing.refresh_token_ref = refresh_token
            existing.google_account_id = profile["google_account_id"]
            gmail_account_id = existing.id
            logger.info(f"Updated Gmail tokens for user {user_id[:8]}...")
        else:
            # Create new Gmail account link
            gmail_account = GmailAccount(
                user_id=user_id,
                google_account_id=profile["google_account_id"],
                access_token_ref=encrypt_secret(token_data["access_token"]),
                refresh_token_ref=encrypt_secret(token_data.get("refresh_token")),
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

        response = RedirectResponse(url="/dashboard?gmail_auth=success", status_code=303)
        response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")
        return response

    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error("Gmail OAuth callback failed exception=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500, detail="Gmail connection could not be completed"
        ) from exc


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
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}") from e


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

    if payload.enabled is not None:
        gmail_account.auto_sync_enabled = payload.enabled
        gmail_account.auto_sync_status = "idle" if payload.enabled else "paused"
    if payload.interval_seconds is not None:
        gmail_account.auto_sync_interval_seconds = payload.interval_seconds
    await db.commit()
    await db.refresh(gmail_account)
    return _serialize_auto_sync(gmail_account)


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
    await db.commit()
