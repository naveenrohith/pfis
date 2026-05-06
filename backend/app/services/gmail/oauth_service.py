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
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Gmail read-only scope — minimum access needed
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def create_oauth_flow(redirect_uri: str = None) -> Flow:
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
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri or settings.GOOGLE_REDIRECT_URI,
    )

    return flow


def get_authorization_url() -> tuple[str, str]:
    """
    Generate the Google OAuth authorization URL.
    Returns (auth_url, state) tuple.
    """
    flow = create_oauth_flow()

    auth_url, state = flow.authorization_url(
        access_type="offline",       # Get refresh token
        include_granted_scopes="true",
        prompt="consent",            # Always show consent (ensures refresh token)
    )

    logger.info(f"Generated OAuth URL (state={state[:8]}...)")
    return auth_url, state


def exchange_code_for_tokens(code: str) -> dict:
    """
    Exchange the authorization code for access and refresh tokens.
    Returns dict with access_token, refresh_token, expiry.
    """
    flow = create_oauth_flow()
    flow.fetch_token(code=code)

    credentials = flow.credentials

    token_data = {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "expiry": credentials.expiry.isoformat() if credentials.expiry else None,
        "scopes": list(credentials.scopes) if credentials.scopes else SCOPES,
    }

    logger.info("Successfully exchanged auth code for tokens")
    return token_data


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
