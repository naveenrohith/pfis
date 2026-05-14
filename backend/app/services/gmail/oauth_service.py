"""
Gmail OAuth Service
Handles Google OAuth 2.0 flow for Gmail read-only access.

Flow:
1. User hits /api/auth/gmail/connect → redirected to Google consent screen
2. Google redirects back to /api/auth/gmail/callback with auth code
3. We exchange code for access+refresh tokens
4. Tokens stored in gmail_accounts table
"""

import logging
from typing import Any

from fastapi import HTTPException
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Gmail read-only scope — minimum access needed
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def create_oauth_flow(redirect_uri: str | None = None) -> Flow:
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
        scopes=SCOPES,
        redirect_uri=redirect_uri or settings.GOOGLE_REDIRECT_URI,
    )

    return flow


def get_authorization_url(redirect_uri: str | None = None) -> tuple[str, str]:
    """
    Generate the Google OAuth authorization URL.
    Returns (auth_url, state) tuple.
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )

    flow = create_oauth_flow(redirect_uri=redirect_uri)

    auth_url, state = flow.authorization_url(
        access_type="offline",       # Get refresh token
        include_granted_scopes="true",
        prompt="consent",            # Always show consent (ensures refresh token)
    )

    logger.info(f"Generated OAuth URL (state={state[:8]}...)")
    return auth_url, state


def exchange_code_for_tokens(code: str, redirect_uri: str | None = None) -> dict:
    """
    Exchange the authorization code for access and refresh tokens.
    Returns dict with access_token, refresh_token, expiry.
    """
    flow = create_oauth_flow(redirect_uri=redirect_uri)
    flow.fetch_token(code=code)

    credentials = flow.credentials

    token_data = {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "id_token": credentials.id_token,
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        "scopes": list(credentials.scopes) if credentials.scopes else SCOPES,
    }

    logger.info("Successfully exchanged auth code for tokens")
    return token_data


def verify_google_identity(token_data: dict[str, Any]) -> dict[str, Any]:
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
    if payload.get("email_verified") is False:
        raise HTTPException(status_code=401, detail="Google account email is not verified")

    return {
        "google_account_id": str(payload.get("sub") or ""),
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


def build_credentials(access_token: str, refresh_token: str) -> Credentials:
    """
    Build a Credentials object from stored tokens.
    Used to authenticate Gmail API calls.
    """
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
