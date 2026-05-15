"""
PFIS Configuration Module
Loads settings from .env file with Pydantic validation.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
ROOT_DIR = BACKEND_DIR.parent
DEFAULT_SQLITE_DB = BACKEND_DIR / "pfis.db"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    APP_NAME: str = "PFIS"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite+aiosqlite:///./pfis.db"
    SECRET_KEY: str = "pfis-dev-secret-change-me-please-32bytes"
    TOKEN_ENCRYPTION_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    AUTH_REQUIRED: bool = False
    CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    DEMO_USER_PASSWORD: str = "demo12345"

    # Gmail OAuth (Phase 1)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    GMAIL_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/auth/gmail/callback"
    GOOGLE_ALLOWED_EMAILS: Annotated[list[str], NoDecode] = []

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def resolve_database_url(cls, value: Any) -> str:
        """Resolve relative SQLite paths against the backend directory."""
        if value is None or value == "":
            return f"sqlite+aiosqlite:///{DEFAULT_SQLITE_DB.as_posix()}"
        if not isinstance(value, str):
            raise ValueError("Invalid DATABASE_URL value")

        prefix = "sqlite+aiosqlite:///"
        if not value.startswith(prefix):
            return value

        raw_path = value[len(prefix):]
        if raw_path in {":memory:", "/:memory:"}:
            return value

        candidate = Path(raw_path)
        if candidate.is_absolute() or (len(raw_path) >= 3 and raw_path[1:3] in {":\\", ":/"}):
            return f"{prefix}{candidate.as_posix()}"

        resolved = (BACKEND_DIR / candidate).resolve()
        return f"{prefix}{resolved.as_posix()}"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> bool:
        """Accept common deployment labels for DEBUG."""
        if isinstance(value, str) and value.strip().lower() in {"release", "production", "prod"}:
            return False
        return value

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        """Allow CORS origins to be provided as CSV or JSON-like strings."""
        if value is None or value == "":
            return ["http://localhost:8000", "http://127.0.0.1:8000"]
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        raise ValueError("Invalid CORS_ORIGINS value")

    @field_validator("GOOGLE_ALLOWED_EMAILS", mode="before")
    @classmethod
    def parse_google_allowed_emails(cls, value: Any) -> list[str]:
        """Allow Google sign-in allowlist to be provided as CSV."""
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        raise ValueError("Invalid GOOGLE_ALLOWED_EMAILS value")

    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), str(ROOT_DIR / ".env")),
        env_file_encoding="utf-8",
    )


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
