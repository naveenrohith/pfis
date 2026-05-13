"""Regression tests for application settings parsing."""

from app.config import Settings


def test_settings_accept_csv_cors_origins(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:8000, http://127.0.0.1:8000",
    )

    settings = Settings(_env_file=None)

    assert settings.CORS_ORIGINS == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
