"""Regression tests for application settings parsing."""

import warnings
from pathlib import Path

import pytest
from app.config import DEFAULT_SECRET_KEY, EXAMPLE_SECRET_KEY, Settings


def test_settings_accept_csv_cors_origins(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-unique-secret-key-value-123456789")
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:8000, http://127.0.0.1:8000",
    )

    settings = Settings(_env_file=None)

    assert settings.CORS_ORIGINS == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def test_settings_resolve_relative_sqlite_database_url_from_backend(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-unique-secret-key-value-123456789")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./pfis.db")

    settings = Settings(_env_file=None)
    expected_path = (
        (Path(__file__).resolve().parents[2] / "backend" / "pfis.db").resolve().as_posix()
    )

    assert f"sqlite+aiosqlite:///{expected_path}" == settings.DATABASE_URL


def test_default_secret_key_warns_for_local_use():
    with pytest.warns(UserWarning, match="development placeholder"):
        Settings(_env_file=None, SECRET_KEY=DEFAULT_SECRET_KEY, AUTH_REQUIRED=False)


def test_default_secret_key_with_auth_required_warns_strongly():
    with pytest.warns(UserWarning, match="AUTH_REQUIRED"):
        Settings(_env_file=None, SECRET_KEY=DEFAULT_SECRET_KEY, AUTH_REQUIRED=True)


def test_example_secret_key_with_auth_required_warns_strongly():
    with pytest.warns(UserWarning, match="known development placeholder"):
        Settings(_env_file=None, SECRET_KEY=EXAMPLE_SECRET_KEY, AUTH_REQUIRED=True)


def test_custom_secret_key_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Settings(_env_file=None, SECRET_KEY="a-unique-strong-secret-key-value-123456")


def test_production_requires_unique_secret_key():
    with pytest.raises(ValueError, match="unique SECRET_KEY"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY=DEFAULT_SECRET_KEY,
            AUTH_REQUIRED=True,
            DATABASE_URL="postgresql+asyncpg://user:pass@db/pfis",
            CORS_ORIGINS="https://pfis.example.com",
        )


def test_production_rejects_example_secret_key():
    with pytest.raises(ValueError, match="unique SECRET_KEY"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY=EXAMPLE_SECRET_KEY,
            AUTH_REQUIRED=True,
            DATABASE_URL="postgresql+asyncpg://user:pass@db/pfis",
            CORS_ORIGINS="https://pfis.example.com",
        )


def test_production_requires_auth_required():
    with pytest.raises(ValueError, match="AUTH_REQUIRED"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a-unique-strong-secret-key-value-123456",
            AUTH_REQUIRED=False,
            DATABASE_URL="postgresql+asyncpg://user:pass@db/pfis",
            CORS_ORIGINS="https://pfis.example.com",
        )


def test_production_rejects_sqlite_database():
    with pytest.raises(ValueError, match="non-SQLite"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            SECRET_KEY="a-unique-strong-secret-key-value-123456",
            AUTH_REQUIRED=True,
            DATABASE_URL="sqlite+aiosqlite:///./pfis.db",
            CORS_ORIGINS="https://pfis.example.com",
        )


def test_production_accepts_safe_minimum_configuration():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="production",
        SECRET_KEY="a-unique-strong-secret-key-value-123456",
        AUTH_REQUIRED=True,
        DATABASE_URL="postgresql+asyncpg://user:pass@db/pfis",
        CORS_ORIGINS="https://pfis.example.com",
    )

    assert settings.is_production is True
