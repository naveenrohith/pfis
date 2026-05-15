"""Regression tests for application settings parsing."""

from pathlib import Path

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


def test_settings_resolve_relative_sqlite_database_url_from_backend(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./pfis.db")

    settings = Settings(_env_file=None)
    expected_path = (Path(__file__).resolve().parents[2] / "backend" / "pfis.db").resolve().as_posix()

    assert settings.DATABASE_URL == f"sqlite+aiosqlite:///{expected_path}"
