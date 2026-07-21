"""Authentication routes for PFIS browser and API clients."""

import logging
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.auth import AuthIdentity
from app.models.email import GmailAccount
from app.models.sync import OAuthState
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.auth import (
    AuthMeResponse,
    AuthSessionResponse,
    LoginRequest,
    LogoutResponse,
    RegisterRequest,
)
from app.schemas.user import UserResponse
from app.security import (
    create_auth_session,
    decrypt_secret,
    encrypt_secret,
    get_active_auth_session,
    get_current_user,
    hash_password,
    hash_session_token,
    normalize_email,
    revoke_auth_session,
    verify_password_and_update,
)
from app.services.gmail import oauth_service

router = APIRouter(prefix="/auth", tags=["Auth"])
settings = get_settings()
logger = logging.getLogger(__name__)

_OAUTH_STATE_TTL_MINUTES = 10


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps returned by SQLite to timezone-aware UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _set_session_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
) -> None:
    max_age = settings.SESSION_ABSOLUTE_HOURS * 60 * 60
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
        max_age=max_age,
    )
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
        max_age=max_age,
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(settings.CSRF_COOKIE_NAME, path="/")


def _set_oauth_cookie(response: Response, browser_token: str) -> None:
    response.set_cookie(
        settings.OAUTH_COOKIE_NAME,
        browser_token,
        max_age=_OAUTH_STATE_TTL_MINUTES * 60,
        httponly=True,
        secure=settings.SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/api/auth",
    )


def _clear_oauth_cookie(response: Response) -> None:
    response.delete_cookie(settings.OAUTH_COOKIE_NAME, path="/api/auth")


async def _commit_browser_session(
    response: Response,
    db: AsyncSession,
    user: User,
    *,
    mode: str = "auth",
) -> AuthSessionResponse:
    session_token, csrf_token, session = await create_auth_session(db, user.id, mode=mode)
    await db.commit()
    _set_session_cookies(response, session_token, csrf_token)
    expires_in = max(
        0,
        int((_as_utc(session.expires_at) - datetime.now(UTC)).total_seconds()),
    )
    return AuthSessionResponse(
        expires_in=expires_in,
        mode=mode,
        csrf_cookie_name=settings.CSRF_COOKIE_NAME,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=AuthSessionResponse, status_code=201)
@limiter.limit("5/minute")
async def register(
    request: Request,
    response: Response,
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a user and establish a revocable browser session."""
    email = normalize_email(str(data.email))
    if len(data.password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )

    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        email=email,
        name=data.name.strip(),
        currency=data.currency.upper(),
        password_hash=hash_password(data.password),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return await _commit_browser_session(response, db, user)


@router.post("/login", response_model=AuthSessionResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a password user and establish a revocable browser session."""
    email = normalize_email(str(data.email))
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    valid, replacement_hash = verify_password_and_update(
        data.password,
        user.password_hash if user else None,
    )
    if user is None or not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")
    if replacement_hash:
        user.password_hash = replacement_hash
        await db.flush()

    return await _commit_browser_session(response, db, user)


@router.post("/demo", response_model=AuthSessionResponse)
@limiter.limit("10/minute")
async def demo_login(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Open the isolated seeded demo workspace in non-production environments."""
    if not settings.ALLOW_DEMO_LOGIN:
        raise HTTPException(status_code=404, detail="Demo workspace is not available")
    result = await db.execute(select(User).where(User.email == "demo@pfis.app"))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="Demo workspace is not available")
    return await _commit_browser_session(response, db, user, mode="demo")


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current browser session and clear its cookies."""
    await revoke_auth_session(request.cookies.get(settings.SESSION_COOKIE_NAME), db)
    _clear_session_cookies(response)
    return LogoutResponse()


@router.get("/me", response_model=AuthMeResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user profile."""
    return current_user


@router.get("/session", response_model=AuthSessionResponse)
async def browser_session(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return browser-safe session metadata without exposing credentials."""
    raw_session = request.cookies.get(settings.SESSION_COOKIE_NAME)
    session = await get_active_auth_session(raw_session, db) if raw_session else None
    mode = session.mode if session else "auth"
    expires_in = (
        max(0, int((_as_utc(session.expires_at) - datetime.now(UTC)).total_seconds()))
        if session
        else settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return AuthSessionResponse(
        expires_in=expires_in,
        mode=mode,
        csrf_cookie_name=settings.CSRF_COOKIE_NAME,
        user=UserResponse.model_validate(current_user),
    )


@router.get("/google/login")
async def google_login(db: AsyncSession = Depends(get_db)):
    """Start identity-only Google OpenID Connect sign-in."""
    try:
        auth_url, state, code_verifier, nonce = oauth_service.get_authorization_url(
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
            scopes=oauth_service.IDENTITY_SCOPES,
            offline=False,
        )
        browser_token = token_urlsafe(32)
        db.add(
            OAuthState(
                state=state,
                user_id=None,
                flow_type="google_login",
                browser_token_hash=hash_session_token(browser_token),
                code_verifier_ref=encrypt_secret(code_verifier),
                nonce_ref=encrypt_secret(nonce),
                expires_at=datetime.now(UTC) + timedelta(minutes=_OAUTH_STATE_TTL_MINUTES),
            )
        )
        await db.commit()
        redirect = RedirectResponse(url=auth_url)
        _set_oauth_cookie(redirect, browser_token)
        return redirect
    except HTTPException:
        return RedirectResponse(url="/dashboard?auth_error=google_not_configured", status_code=303)
    except Exception:
        return RedirectResponse(url="/dashboard?auth_error=google_start_failed", status_code=303)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Complete Google identity sign-in and establish a PFIS browser session."""
    oauth_state = await _consume_oauth_state(request, db, state, "google_login")
    try:
        token_data = oauth_service.exchange_code_for_tokens(
            code,
            redirect_uri=settings.GOOGLE_REDIRECT_URI,
            scopes=oauth_service.IDENTITY_SCOPES,
            code_verifier=decrypt_secret(oauth_state.code_verifier_ref),
        )
        profile = oauth_service.verify_google_identity(
            token_data,
            expected_nonce=decrypt_secret(oauth_state.nonce_ref),
        )

        allowed_emails = {normalize_email(email) for email in settings.GOOGLE_ALLOWED_EMAILS}
        if allowed_emails and profile["email"] not in allowed_emails:
            raise HTTPException(status_code=403, detail="Google account is not allowed")

        user = await _resolve_google_user(db, profile)
        await db.flush()
        session_token, csrf_token, _ = await create_auth_session(db, user.id)
        await db.commit()

        redirect = RedirectResponse(url="/dashboard?google_auth=success", status_code=303)
        _clear_oauth_cookie(redirect)
        _set_session_cookies(redirect, session_token, csrf_token)
        return redirect
    except HTTPException as exc:
        await db.rollback()
        error_code = {
            401: "google_identity_invalid",
            403: "google_account_not_allowed",
            409: "account_link_required",
        }.get(exc.status_code, "google_signin_failed")
        logger.warning(
            "Google sign-in rejected (status=%s, category=%s)",
            exc.status_code,
            error_code,
        )
        redirect = RedirectResponse(
            url=f"/dashboard?{urlencode({'auth_error': error_code})}", status_code=303
        )
        _clear_oauth_cookie(redirect)
        return redirect
    except Exception:
        await db.rollback()
        logger.exception("Google sign-in callback failed")
        redirect = RedirectResponse(
            url="/dashboard?auth_error=google_signin_failed", status_code=303
        )
        _clear_oauth_cookie(redirect)
        return redirect


async def _consume_oauth_state(
    request: Request,
    db: AsyncSession,
    state: str,
    expected_flow: str,
) -> OAuthState:
    result = await db.execute(select(OAuthState).where(OAuthState.state == state))
    oauth_state = result.scalar_one_or_none()
    now = datetime.now(UTC)
    expires = oauth_state.expires_at if oauth_state else None
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    browser_token = request.cookies.get(settings.OAUTH_COOKIE_NAME)
    browser_matches = bool(
        oauth_state
        and browser_token
        and oauth_state.browser_token_hash
        and oauth_state.browser_token_hash == hash_session_token(browser_token)
    )
    if (
        oauth_state is None
        or expires is None
        or expires <= now
        or oauth_state.flow_type != expected_flow
        or not browser_matches
    ):
        if oauth_state is not None:
            await db.delete(oauth_state)
            await db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth transaction")

    await db.delete(oauth_state)
    await db.commit()
    return oauth_state


async def _resolve_google_user(db: AsyncSession, profile: dict) -> User:
    subject = profile["google_account_id"]
    if not subject:
        raise HTTPException(status_code=401, detail="Google account identifier is missing")

    identity_result = await db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google",
            AuthIdentity.provider_subject == subject,
        )
    )
    identity = identity_result.scalar_one_or_none()
    if identity:
        user = await db.get(User, identity.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=403, detail="User account is inactive")
        return user

    email = normalize_email(profile["email"])
    user_result = await db.execute(select(User).where(User.email == email))
    user = user_result.scalar_one_or_none()
    if user:
        gmail_result = await db.execute(
            select(GmailAccount).where(
                GmailAccount.user_id == user.id,
                GmailAccount.google_account_id == subject,
            )
        )
        safe_legacy_identity = gmail_result.scalar_one_or_none() is not None
        if user.password_hash is not None or not safe_legacy_identity:
            raise HTTPException(status_code=409, detail="Existing account must link Google first")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User account is inactive")
        user.name = profile["name"] or user.name
    else:
        user = User(
            email=email,
            name=profile["name"],
            currency="INR",
            password_hash=None,
            is_active=True,
        )
        db.add(user)
        await db.flush()

    db.add(
        AuthIdentity(
            user_id=user.id,
            provider="google",
            provider_subject=subject,
            email_at_link=email,
        )
    )
    return user
