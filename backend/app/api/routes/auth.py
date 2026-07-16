"""Authentication routes for PFIS."""

import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.email import GmailAccount
from app.models.sync import OAuthState
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.auth import AuthMeResponse, AuthTokenResponse, LoginRequest, RegisterRequest
from app.security import (
    create_access_token,
    encrypt_secret,
    get_current_user,
    hash_password,
    verify_password,
)
from app.services.gmail import oauth_service

router = APIRouter(prefix="/auth", tags=["Auth"])
settings = get_settings()

# OAuth state TTL
_OAUTH_STATE_TTL_MINUTES = 10


@router.post("/register", response_model=AuthTokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register(
    request: Request,
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user and return a bearer token."""
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User with this email already exists")

    user = User(
        email=data.email,
        name=data.name,
        currency=data.currency,
        password_hash=hash_password(data.password),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return AuthTokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user,
    )


@router.post("/login", response_model=AuthTokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a user and return a bearer token."""
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    return AuthTokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user,
    )


@router.get("/me", response_model=AuthMeResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user profile."""
    return current_user


@router.get("/google/login")
async def google_login(db: AsyncSession = Depends(get_db)):
    """Start Google OAuth sign-in."""
    try:
        auth_url, state = oauth_service.get_authorization_url(
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )
        # Persist state in DB
        oauth_state = OAuthState(
            state=state,
            user_id=None,
            flow_type="google_login",
            expires_at=datetime.now(UTC) + timedelta(minutes=_OAUTH_STATE_TTL_MINUTES),
        )
        db.add(oauth_state)
        await db.commit()
        return RedirectResponse(url=auth_url)
    except HTTPException as exc:
        query = urlencode({"oauth_error": str(exc.detail)})
        return RedirectResponse(url=f"/dashboard?{query}", status_code=303)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Google sign-in failed to start: {exc}"
        ) from exc


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """Complete Google OAuth sign-in and hand the dashboard a PFIS session."""
    # Verify state from DB
    result = await db.execute(select(OAuthState).where(OAuthState.state == state))
    oauth_state = result.scalar_one_or_none()
    now_utc = datetime.now(UTC)
    expires = oauth_state.expires_at if oauth_state else None
    if expires and expires.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=None)
    if not oauth_state or expires < now_utc:
        if oauth_state:
            await db.delete(oauth_state)
            await db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    await db.delete(oauth_state)
    await db.flush()

    try:
        token_data = oauth_service.exchange_code_for_tokens(
            code,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
        )
        profile = oauth_service.verify_google_identity(token_data)

        allowed_emails = {email.lower() for email in settings.GOOGLE_ALLOWED_EMAILS}
        if allowed_emails and profile["email"] not in allowed_emails:
            raise HTTPException(status_code=403, detail="This Google account is not allowed")

        user = await _get_or_create_google_user(db, profile)
        await _upsert_gmail_account(db, user.id, profile["google_account_id"], token_data)
        await db.commit()
        await db.refresh(user)

        payload = AuthTokenResponse(
            access_token=create_access_token(user.id),
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user,
        ).model_dump(mode="json")

        return _oauth_complete_html(payload)
    except HTTPException as exc:
        await db.rollback()
        query = urlencode({"oauth_error": str(exc.detail)})
        return RedirectResponse(url=f"/dashboard?{query}", status_code=303)
    except Exception as exc:
        await db.rollback()
        query = urlencode({"oauth_error": f"Google sign-in callback failed: {exc}"})
        return RedirectResponse(url=f"/dashboard?{query}", status_code=303)


async def _get_or_create_google_user(db: AsyncSession, profile: dict) -> User:
    result = await db.execute(select(User).where(User.email == profile["email"]))
    user = result.scalar_one_or_none()
    if user:
        updated = False
        if user.name != profile["name"]:
            user.name = profile["name"]
            updated = True
        if not user.is_active:
            user.is_active = True
            updated = True
        if updated:
            await db.flush()
        return user

    user = User(
        email=profile["email"],
        name=profile["name"],
        currency="INR",
        password_hash=None,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _upsert_gmail_account(
    db: AsyncSession,
    user_id: str,
    google_account_id: str,
    token_data: dict,
) -> None:
    result = await db.execute(select(GmailAccount).where(GmailAccount.user_id == user_id))
    existing = result.scalar_one_or_none()

    access_token = encrypt_secret(token_data.get("access_token"))
    refresh_token = encrypt_secret(token_data.get("refresh_token"))

    if existing:
        existing.google_account_id = google_account_id or existing.google_account_id
        existing.access_token_ref = access_token
        if refresh_token:
            existing.refresh_token_ref = refresh_token
        await db.flush()
        return

    db.add(
        GmailAccount(
            user_id=user_id,
            google_account_id=google_account_id or f"gmail_{user_id[:8]}",
            access_token_ref=access_token,
            refresh_token_ref=refresh_token,
        )
    )
    await db.flush()


def _oauth_complete_html(payload: dict) -> HTMLResponse:
    session_payload = {
        "mode": "auth",
        "token": payload["access_token"],
        "expiresAt": "__EXPIRES_AT__",
        "user": payload["user"],
    }
    safe_session = json.dumps(session_payload).replace('"__EXPIRES_AT__"', "Date.now() + expiresIn")
    expires_in = int(payload["expires_in"])
    nonce = secrets.token_urlsafe(16)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Signing in...</title>
</head>
<body>
  <script nonce="{nonce}">
    const expiresIn = {expires_in} * 1000;
    const session = {safe_session};
    localStorage.setItem('pfis.session.v3', JSON.stringify(session));
    window.location.replace('/dashboard?google_auth=success');
  </script>
</body>
</html>"""
    return HTMLResponse(html)
