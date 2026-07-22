"""
Gmail OAuth Service
Handles Google OAuth 2.0 flow for Gmail read-only access.

Flow:
1. User hits /api/auth/gmail/connect → redirected to Google consent screen
2. Google redirects back to /api/auth/gmail/callback with auth code
3. We exchange code for access+refresh tokens
4. Tokens stored in gmail_accounts table
"""

import base64
import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_GOOGLE_CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$")

# Gmail read-only scope — minimum access needed
IDENTITY_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GMAIL_SCOPES = [
    *IDENTITY_SCOPES,
    "https://www.googleapis.com/auth/gmail.readonly",
]

SCOPES = GMAIL_SCOPES


def create_oauth_flow(
    redirect_uri: str | None = None,
    scopes: list[str] | None = None,
) -> Flow:
    """
    Create a Google OAuth flow instance.
    Uses client ID/secret from environment (no credentials.json file needed).
    """
    client_config = {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                settings.GOOGLE_REDIRECT_URI,
                settings.GMAIL_OAUTH_REDIRECT_URI,
            ],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=scopes or GMAIL_SCOPES,
        redirect_uri=redirect_uri or settings.GOOGLE_REDIRECT_URI,
    )

    return flow


def validate_google_oauth_settings() -> None:
    """Fail locally when Google OAuth credentials are missing or malformed."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env.",
        )

    if not _GOOGLE_CLIENT_ID_PATTERN.fullmatch(settings.GOOGLE_CLIENT_ID.strip()):
        raise HTTPException(
            status_code=500,
            detail=(
                "GOOGLE_CLIENT_ID in backend/.env is not a valid Google OAuth client ID. "
                "Use the full Web application client ID ending with .apps.googleusercontent.com."
            ),
        )


def get_authorization_url(
    redirect_uri: str | None = None,
    *,
    scopes: list[str] | None = None,
    offline: bool = True,
) -> tuple[str, str, str, str]:
    """
    Generate the Google OAuth authorization URL.
    Returns (auth_url, state) tuple.
    """
    validate_google_oauth_settings()

    flow = create_oauth_flow(redirect_uri=redirect_uri, scopes=scopes or GMAIL_SCOPES)
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    nonce = secrets.token_urlsafe(32)

    auth_url, state = flow.authorization_url(
        access_type="offline" if offline else "online",
        # Identity sign-in must not inherit an older Gmail grant. Besides
        # preserving consent separation, this prevents OAuthLib from rejecting
        # the callback when Google returns a broader, previously granted scope.
        include_granted_scopes="true" if offline else "false",
        prompt="consent" if offline else "select_account",
        code_challenge=code_challenge,
        code_challenge_method="S256",
        nonce=nonce,
    )

    logger.info("Generated Google OAuth authorization URL")
    return auth_url, state, code_verifier, nonce


def exchange_code_for_tokens(
    code: str,
    redirect_uri: str | None = None,
    *,
    scopes: list[str] | None = None,
    code_verifier: str | None = None,
) -> dict:
    """
    Exchange the authorization code for access and refresh tokens.
    Returns dict with access_token, refresh_token, expiry.
    """
    requested_scopes = scopes or GMAIL_SCOPES
    flow = create_oauth_flow(redirect_uri=redirect_uri, scopes=requested_scopes)
    flow.fetch_token(code=code, code_verifier=code_verifier)

    credentials = flow.credentials

    token_data = {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "id_token": credentials.id_token,
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        "scopes": list(credentials.scopes) if credentials.scopes else requested_scopes,
    }

    logger.info("Successfully exchanged auth code for tokens")
    return token_data


def verify_google_identity(
    token_data: dict[str, Any],
    *,
    expected_nonce: str | None = None,
) -> dict[str, Any]:
    """
    Verify Google's ID token and return normalized profile fields.
    """
    raw_id_token = token_data.get("id_token")
    if not raw_id_token:
        raise HTTPException(status_code=401, detail="Google did not return an ID token")

    try:
        payload = id_token.verify_oauth2_token(
            raw_id_token,
            Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Google identity token") from exc

    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Google account email is missing")
    if payload.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="Google account email is not verified")
    if expected_nonce and payload.get("nonce") != expected_nonce:
        raise HTTPException(status_code=401, detail="Invalid Google identity nonce")

    subject = str(payload.get("sub") or "")
    if not subject:
        raise HTTPException(status_code=401, detail="Google account identifier is missing")

    return {
        "google_account_id": subject,
        "email": email,
        "name": str(payload.get("name") or email.split("@")[0]),
        "picture": payload.get("picture"),
    }


def refresh_access_token(refresh_token: str) -> dict:
    """
    Refresh an expired access token using the refresh token.
    Returns updated token data.
    """
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )

    credentials.refresh(Request())

    return {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token or refresh_token,
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
    }


def build_credentials(
    access_token: str,
    refresh_token: str,
    expiry: datetime | None = None,
) -> Credentials:
    """
    Build a Credentials object from stored tokens.
    Used to authenticate Gmail API calls.
    """
    google_expiry = expiry
    if google_expiry is not None and google_expiry.tzinfo is not None:
        google_expiry = google_expiry.astimezone(UTC).replace(tzinfo=None)
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
        expiry=google_expiry,
    )
