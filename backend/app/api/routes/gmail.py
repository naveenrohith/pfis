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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.email import RawEmail, GmailAccount
from app.models.sync import SyncRun
from app.models.user import User
from app.security import encrypt_secret
from app.security import get_current_user_optional, resolve_user_scope
from app.services.gmail.oauth_service import (
    get_authorization_url,
    exchange_code_for_tokens,
)
from app.services.gmail.sync_service import sync_gmail_emails, demo_sync_gmail_emails

logger = logging.getLogger(__name__)
settings = get_settings()

# Two routers: one for auth, one for gmail operations
auth_router = APIRouter(prefix="/auth/gmail", tags=["Gmail Auth"])
gmail_router = APIRouter(prefix="/gmail", tags=["Gmail"])

# In-memory state store (use Redis in production)
_oauth_states: dict[str, str] = {}


# ─── OAuth Flow ───

@auth_router.get("/connect")
async def gmail_connect(
    user_id: str = Query(..., description="User ID to connect Gmail for"),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Step 1: Redirect user to Google OAuth consent screen.
    After consent, Google redirects back to /callback.
    """
    user_id = resolve_user_scope(user_id, current_user)
    try:
        auth_url, state = get_authorization_url(redirect_uri=settings.GMAIL_OAUTH_REDIRECT_URI)
        _oauth_states[state] = user_id
        logger.info(f"OAuth flow started for user {user_id[:8]}...")
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Failed to start OAuth: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth initialization failed: {str(e)}")


@auth_router.get("/callback")
async def gmail_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2: Handle OAuth callback from Google.
    Exchange auth code for tokens and store them.
    """
    # Verify state
    user_id = _oauth_states.pop(state, None)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        # Exchange code for tokens
        token_data = exchange_code_for_tokens(code, redirect_uri=settings.GMAIL_OAUTH_REDIRECT_URI)

        # Check if Gmail account already exists for this user
        result = await db.execute(
            select(GmailAccount).where(GmailAccount.user_id == user_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update tokens
            existing.access_token_ref = encrypt_secret(token_data["access_token"])
            existing.refresh_token_ref = encrypt_secret(token_data["refresh_token"])
            gmail_account_id = existing.id
            logger.info(f"Updated Gmail tokens for user {user_id[:8]}...")
        else:
            # Create new Gmail account link
            gmail_account = GmailAccount(
                user_id=user_id,
                google_account_id=f"gmail_{user_id[:8]}",
                access_token_ref=encrypt_secret(token_data["access_token"]),
                refresh_token_ref=encrypt_secret(token_data["refresh_token"]),
            )
            db.add(gmail_account)
            await db.flush()
            gmail_account_id = gmail_account.id
            logger.info(f"Created Gmail account link for user {user_id[:8]}...")

        await db.commit()

        return {
            "status": "connected",
            "message": "Gmail account connected successfully",
            "gmail_account_id": gmail_account_id,
            "user_id": user_id,
        }

    except Exception as e:
        logger.error(f"OAuth callback failed: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth callback failed: {str(e)}")


# ─── Gmail Operations ───

@gmail_router.post("/sync")
async def trigger_sync(
    user_id: str = Query(...),
    max_results: int = Query(50, ge=1, le=200),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a Gmail sync for a user.
    Fetches new emails, filters financial ones, stores them.
    """
    user_id = resolve_user_scope(user_id, current_user)
    # Find Gmail account for user
    result = await db.execute(
        select(GmailAccount).where(GmailAccount.user_id == user_id)
    )
    gmail_account = result.scalar_one_or_none()

    if not gmail_account:
        raise HTTPException(
            status_code=404,
            detail="No Gmail account connected. Use /api/auth/gmail/connect first."
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
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


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
