"""Fail-closed safety tests for the disposable E2E database harness."""

from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from scripts.e2e_runner import child_environment
from scripts.e2e_safety import (
    E2EGuardError,
    e2e_database_name,
    parse_postgres_target,
    quote_identifier,
    validate_fixture_write,
)
from scripts.sanitize_e2e_artifacts import sanitize

RUN_ID = "a1b2c3d4e5f6"
DATABASE = e2e_database_name(RUN_ID)
DATABASE_URL = f"postgresql+asyncpg://pfis_e2e_app_{RUN_ID}:secret@127.0.0.1:5432/{DATABASE}"
DATABASE_COMMENT = f"pfis-e2e-run:{RUN_ID}"
SAFE_ENV = {
    "PFIS_E2E": "1",
    "PFIS_E2E_RUN_ID": RUN_ID,
    "PFIS_E2E_CONFIRM_DATABASE": DATABASE,
}


def _validate(*, env: dict[str, str] | None = None, **overrides) -> None:
    values = {
        "env": dict(SAFE_ENV if env is None else env),
        "database_url": DATABASE_URL,
        "database_name": DATABASE,
        "run_id": RUN_ID,
        "database_comment": DATABASE_COMMENT,
    }
    values.update(overrides)
    validate_fixture_write(**values)


def test_fixture_write_requires_every_exact_run_identity() -> None:
    _validate()


@pytest.mark.parametrize(
    "env_update",
    [
        {"PFIS_E2E": "0"},
        {"PFIS_E2E_RUN_ID": "ffffffffffff"},
        {"PFIS_E2E_CONFIRM_DATABASE": "postgres"},
    ],
)
def test_fixture_write_refuses_missing_or_mismatched_confirmation(
    env_update: dict[str, str],
) -> None:
    env = dict(SAFE_ENV)
    env.update(env_update)
    with pytest.raises(E2EGuardError):
        _validate(env=env)


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_name": "postgres"},
        {"run_id": "bad-id"},
        {"database_comment": "pfis-e2e-run:ffffffffffff"},
        {"database_url": "postgresql+asyncpg://u:p@db.example.test/pfis_e2e_a1b2c3d4e5f6"},
        {"database_url": "postgresql+asyncpg://u:p@127.0.0.1:5432/postgres"},
    ],
)
def test_fixture_write_refuses_unsafe_database_identity(overrides: dict[str, str]) -> None:
    with pytest.raises(E2EGuardError):
        _validate(**overrides)


def test_postgres_url_parser_accepts_only_the_expected_local_database() -> None:
    assert parse_postgres_target(DATABASE_URL, expected_database=DATABASE) == (
        "127.0.0.1",
        DATABASE,
    )
    with pytest.raises(E2EGuardError):
        parse_postgres_target("postgresql://u:p@localhost/postgres", expected_database=DATABASE)


def test_generated_sql_identifier_cannot_escape_the_identifier_alphabet() -> None:
    assert quote_identifier("pfis_e2e_app_a1b2c3d4e5f6") == '"pfis_e2e_app_a1b2c3d4e5f6"'
    with pytest.raises(E2EGuardError):
        quote_identifier('pfis"; drop database postgres; --')


def test_child_environment_never_receives_bootstrap_credentials_or_optional_auth() -> None:
    child = child_environment(
        {
            "PFIS_E2E_ADMIN_DATABASE_URL": "postgresql://admin:secret@127.0.0.1/postgres",
            "AUTH_REQUIRED": "false",
            "ALLOW_DEMO_LOGIN": "true",
            "SECRET_KEY": "old-secret",
        },
        database_url=DATABASE_URL,
        secret_key="fresh-test-secret",
        port=8123,
        run_id=RUN_ID,
    )
    assert "PFIS_E2E_ADMIN_DATABASE_URL" not in child
    assert child["AUTH_REQUIRED"] == "true"
    assert child["ALLOW_DEMO_LOGIN"] == "false"
    assert child["SECRET_KEY"] == "fresh-test-secret"
    assert child["DATABASE_URL"] == DATABASE_URL


def test_playwright_reports_redact_session_cookies_and_fixture_passwords(tmp_path) -> None:
    run_dir = tmp_path / "e2e-a1b2c3d4e5f6"
    storage_dir = run_dir / "storage"
    report_dir = run_dir / "reports"
    storage_dir.mkdir(parents=True)
    report_dir.mkdir()
    session = "one-time-session-cookie-value"
    csrf = "one-time-csrf-cookie-value"
    password = "fixture-password-value"
    (storage_dir / "credentials.json").write_text(
        json.dumps({"pipeline": {"email": "fixture@example.test", "password": password}}),
        encoding="utf-8",
    )
    (storage_dir / "pipeline.storage-state.json").write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "pfis_session", "value": session},
                    {"name": "pfis_csrf", "value": csrf},
                ]
            }
        ),
        encoding="utf-8",
    )
    (report_dir / "junit.xml").write_text(f"{session} {csrf} {password}", encoding="utf-8")
    with ZipFile(report_dir / "trace.zip", "w") as trace:
        trace.writestr("trace.network", f"{session} {csrf} {password}")

    sanitized_files = sanitize(report_dir, run_dir)

    assert sanitized_files == 2
    assert session.encode() not in (report_dir / "junit.xml").read_bytes()
    assert csrf.encode() not in (report_dir / "junit.xml").read_bytes()
    assert password.encode() not in (report_dir / "junit.xml").read_bytes()
    with ZipFile(report_dir / "trace.zip") as trace:
        contents = trace.read("trace.network")
    assert session.encode() not in contents
    assert csrf.encode() not in contents
    assert password.encode() not in contents
