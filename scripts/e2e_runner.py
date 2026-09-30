"""Isolated local and CI launcher for authenticated PFIS Playwright journeys."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import urlopen

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from scripts.e2e_safety import (
    E2E_DATABASE_PREFIX,
    E2EGuardError,
    e2e_database_name,
    parse_postgres_target,
    quote_identifier,
    quote_literal,
    validate_run_id,
)

FRONTEND = ROOT / "frontend"
FIXTURES = {
    "pipeline": "demo",
    "restart": "demo",
    "mock_demo": "demo",
    "quick_add": "auth",
    "owner": "auth",
    "other_user": "auth",
    "auth_flow": "auth",
    "planning": "auth",
    "privacy": "auth",
    "statement": "auth",
}
_CHILD_SECRET_KEYS = {
    "PFIS_E2E_ADMIN_DATABASE_URL",
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "POSTGRES_TEST_DATABASE_URL",
    "SECRET_KEY",
    "TOKEN_ENCRYPTION_KEY",
    "AUTH_REQUIRED",
    "ALLOW_DEMO_LOGIN",
    "DEBUG",
    "ENVIRONMENT",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "GMAIL_OAUTH_REDIRECT_URI",
    "GOOGLE_ALLOWED_EMAILS",
    "SESSION_COOKIE_SECURE",
    "SESSION_COOKIE_NAME",
    "CSRF_COOKIE_NAME",
}


@dataclass(frozen=True)
class DatabaseResources:
    run_id: str
    database: str
    marker: str
    migration_role: str
    runtime_role: str
    migration_password: str
    runtime_password: str
    admin_url: str

    @property
    def migration_url(self) -> str:
        return _role_url(
            self.admin_url, self.database, self.migration_role, self.migration_password
        )

    @property
    def runtime_url(self) -> str:
        return _role_url(self.admin_url, self.database, self.runtime_role, self.runtime_password)


class HarnessError(RuntimeError):
    """Raised when setup, readiness, execution, or cleanup cannot be proven."""


def _role_url(admin_url: str, database: str, role: str, password: str) -> str:
    parsed = urlsplit(admin_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.scheme == "postgres":
        parsed = parsed._replace(scheme="postgresql")
    host = parsed.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    auth = f"{quote(role, safe='')}:{quote(password, safe='')}@"
    netloc = f"{auth}{host}{port}"
    return urlunsplit(
        ("postgresql+asyncpg", netloc, f"/{quote(database, safe='')}", parsed.query, "")
    )


def _admin_database_url(admin_url: str, database: str) -> str:
    parsed = urlsplit(admin_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.scheme == "postgres":
        parsed = parsed._replace(scheme="postgresql")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{quote(database, safe='')}", parsed.query, "")
    )


def _admin_connection_url(admin_url: str) -> str:
    return admin_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def child_environment(
    source: dict[str, str], *, database_url: str, secret_key: str, port: int, run_id: str
) -> dict[str, str]:
    """Create the app/fixture environment without inheriting bootstrap credentials."""
    env = {key: value for key, value in source.items() if key not in _CHILD_SECRET_KEYS}
    origin = f"http://127.0.0.1:{port}"
    env.update(
        {
            "DATABASE_URL": database_url,
            "SECRET_KEY": secret_key,
            "TOKEN_ENCRYPTION_KEY": "",
            "AUTH_REQUIRED": "true",
            "ALLOW_DEMO_LOGIN": "false",
            "DEBUG": "false",
            "ENVIRONMENT": "test",
            "SESSION_COOKIE_SECURE": "false",
            "SESSION_COOKIE_NAME": "pfis_session",
            "CSRF_COOKIE_NAME": "pfis_csrf",
            "CORS_ORIGINS": origin,
            "GOOGLE_CLIENT_ID": "",
            "GOOGLE_CLIENT_SECRET": "",
            "GOOGLE_REDIRECT_URI": f"{origin}/api/auth/google/callback",
            "GMAIL_OAUTH_REDIRECT_URI": f"{origin}/api/auth/gmail/callback",
            "GOOGLE_ALLOWED_EMAILS": "",
            "PFIS_E2E": "1",
            "PFIS_E2E_RUN_ID": run_id,
            "PFIS_E2E_CONFIRM_DATABASE": database_url.rsplit("/", 1)[-1].split("?", 1)[0],
            "PFIS_E2E_PORT": str(port),
            "PFIS_E2E_BASE_URL": origin,
            "PFIS_HOST": "127.0.0.1",
            "PFIS_PORT": str(port),
            "CI": "true" if source.get("CI") == "true" else "false",
        }
    )
    return env


def _npm_command(*args: str) -> list[str]:
    executable = "npm.cmd" if os.name == "nt" else "npm"
    return [executable, *args]


def _run_checked(
    command: list[str], *, cwd: Path, env: dict[str, str], label: str, timeout: int = 600
) -> None:
    print(f"[e2e] {label}", flush=True)
    command_value: str | list[str] = (
        subprocess.list2cmdline(command) if os.name == "nt" else command
    )
    result = subprocess.run(
        command_value,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        shell=os.name == "nt",
    )
    if result.returncode == 0:
        return
    diagnostic = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-50:])
    raise HarnessError(f"{label} failed with exit code {result.returncode}:\n{diagnostic}")


def _database_resources(admin_url: str, run_id: str) -> DatabaseResources:
    return DatabaseResources(
        run_id=run_id,
        database=e2e_database_name(run_id),
        marker=f"pfis-e2e-run:{run_id}",
        migration_role=f"pfis_e2e_mig_{run_id}",
        runtime_role=f"pfis_e2e_app_{run_id}",
        migration_password=secrets.token_urlsafe(36),
        runtime_password=secrets.token_urlsafe(36),
        admin_url=admin_url,
    )


async def _cleanup_partial_database_setup(
    resources: DatabaseResources,
    *,
    database_created: bool,
    roles_created: set[str],
) -> None:
    """Compensate only resources this setup call successfully created."""
    connection = await asyncpg.connect(_admin_connection_url(resources.admin_url), timeout=10)
    try:
        if database_created:
            if resources.database != e2e_database_name(resources.run_id):
                raise HarnessError(
                    "Partial database cleanup identity mismatch; leaving resources intact"
                )
            row = await connection.fetchrow(
                "SELECT shobj_description(oid, 'pg_database') AS marker "
                "FROM pg_database WHERE datname = $1",
                resources.database,
            )
            if row is not None:
                if row["marker"] not in {None, resources.marker}:
                    raise HarnessError(
                        "Partial database marker mismatch; database and roles were left intact"
                    )
                await connection.execute(
                    f"DROP DATABASE {quote_identifier(resources.database)} WITH (FORCE)"
                )

        for role in (resources.runtime_role, resources.migration_role):
            if role not in roles_created:
                continue
            exists = await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            if exists:
                await connection.execute(f"DROP ROLE {quote_identifier(role)}")
    finally:
        await connection.close()


async def create_database(resources: DatabaseResources) -> None:
    database = resources.database
    marker = resources.marker
    admin_url = resources.admin_url
    _, admin_database = parse_postgres_target(admin_url)
    if admin_database.startswith(E2E_DATABASE_PREFIX):
        raise E2EGuardError("The bootstrap URL must connect outside the disposable E2E database")

    connection = await asyncpg.connect(_admin_connection_url(admin_url), timeout=10)
    database_created = False
    roles_created: set[str] = set()
    try:
        existing = await connection.fetchrow(
            "SELECT shobj_description(oid, 'pg_database') AS marker FROM pg_database WHERE datname = $1",
            database,
        )
        if existing is not None:
            raise HarnessError("A database with this run ID already exists; refusing to reuse it")
        existing_roles = await connection.fetch(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY($1::text[])",
            [resources.migration_role, resources.runtime_role],
        )
        if existing_roles:
            raise HarnessError("A role with this run ID already exists; refusing to reuse it")

        await connection.execute(
            f"CREATE ROLE {quote_identifier(resources.migration_role)} LOGIN "
            f"PASSWORD {quote_literal(resources.migration_password)} "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
        roles_created.add(resources.migration_role)
        await connection.execute(
            f"CREATE ROLE {quote_identifier(resources.runtime_role)} LOGIN "
            f"PASSWORD {quote_literal(resources.runtime_password)} "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
        )
        roles_created.add(resources.runtime_role)
        await connection.execute(f"CREATE DATABASE {quote_identifier(database)}")
        database_created = True
        await connection.execute(
            f"COMMENT ON DATABASE {quote_identifier(database)} IS {quote_literal(marker)}"
        )
        await connection.execute(
            f"REVOKE ALL PRIVILEGES ON DATABASE {quote_identifier(database)} FROM PUBLIC"
        )
        await connection.execute(
            f"GRANT CONNECT ON DATABASE {quote_identifier(database)} "
            f"TO {quote_identifier(resources.migration_role)}, {quote_identifier(resources.runtime_role)}"
        )
        target = await asyncpg.connect(_admin_database_url(admin_url, database), timeout=10)
        try:
            await target.execute("REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC")
            await target.execute(
                f"GRANT USAGE, CREATE ON SCHEMA public TO {quote_identifier(resources.migration_role)}"
            )
            await target.execute(
                f"GRANT USAGE ON SCHEMA public TO {quote_identifier(resources.runtime_role)}"
            )
        finally:
            await target.close()

        migration = await asyncpg.connect(
            _admin_connection_url(resources.migration_url), timeout=10
        )
        try:
            await migration.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES "
                f"TO {quote_identifier(resources.runtime_role)}"
            )
            await migration.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES "
                f"TO {quote_identifier(resources.runtime_role)}"
            )
            await migration.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE ON TYPES "
                f"TO {quote_identifier(resources.runtime_role)}"
            )
        finally:
            await migration.close()
    except Exception as setup_error:
        await connection.close()
        try:
            await _cleanup_partial_database_setup(
                resources,
                database_created=database_created,
                roles_created=roles_created,
            )
        except Exception as cleanup_error:
            raise HarnessError(
                f"Database setup failed ({setup_error}); partial cleanup failed "
                f"({cleanup_error}); inspect run {resources.run_id}"
            ) from setup_error
        raise
    else:
        await connection.close()
    return None


async def grant_runtime_access(resources: DatabaseResources) -> None:
    # Migrations create objects as the migration role; only that owner can grant
    # access on those objects to the runtime role.
    target = await asyncpg.connect(_admin_connection_url(resources.migration_url), timeout=10)
    try:
        await target.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            f"TO {quote_identifier(resources.runtime_role)}"
        )
        await target.execute(
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public "
            f"TO {quote_identifier(resources.runtime_role)}"
        )
        type_rows = await target.fetch(
            "SELECT typname FROM pg_type "
            "WHERE typnamespace = 'public'::regnamespace "
            "AND typtype IN ('b', 'c', 'd', 'e', 'r', 'm') AND typelem = 0"
        )
        for row in type_rows:
            await target.execute(
                "GRANT USAGE ON TYPE public."
                f"{quote_identifier(row['typname'])} "
                f"TO {quote_identifier(resources.runtime_role)}"
            )
    finally:
        await target.close()


async def verify_database_roles(resources: DatabaseResources) -> None:
    runtime = await asyncpg.connect(_admin_connection_url(resources.runtime_url), timeout=10)
    try:
        runtime_role = await runtime.fetchrow(
            "SELECT role.rolsuper, role.rolcreatedb, role.rolcreaterole, "
            "has_database_privilege(current_user, current_database(), 'CREATE') AS database_create, "
            "has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage, "
            "has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create, "
            "has_table_privilege(current_user, 'users', 'SELECT') AS user_read "
            "FROM pg_roles AS role WHERE role.rolname = current_user"
        )
        if runtime_role is None or any(
            runtime_role[key]
            for key in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "database_create",
                "schema_create",
            )
        ):
            raise HarnessError("E2E runtime role has privileges beyond the application contract")
        if not runtime_role["schema_usage"] or not runtime_role["user_read"]:
            raise HarnessError("E2E runtime role is missing schema or application read access")
    finally:
        await runtime.close()

    migration = await asyncpg.connect(_admin_connection_url(resources.migration_url), timeout=10)
    try:
        migration_role = await migration.fetchrow(
            "SELECT role.rolsuper, role.rolcreatedb, role.rolcreaterole, "
            "has_database_privilege(current_user, current_database(), 'CREATE') AS database_create, "
            "has_schema_privilege(current_user, 'public', 'USAGE') AS schema_usage, "
            "has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create "
            "FROM pg_roles AS role WHERE role.rolname = current_user"
        )
        if migration_role is None or any(
            migration_role[key]
            for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "database_create")
        ):
            raise HarnessError("E2E migration role has privileges beyond its schema contract")
        if not migration_role["schema_usage"] or not migration_role["schema_create"]:
            raise HarnessError("E2E migration role cannot manage the public schema objects")
    finally:
        await migration.close()


async def remove_database(resources: DatabaseResources) -> None:
    """Drop only resources bearing this run's exact name and ownership marker."""
    connection = await asyncpg.connect(_admin_connection_url(resources.admin_url), timeout=10)
    try:
        row = await connection.fetchrow(
            "SELECT shobj_description(oid, 'pg_database') AS marker FROM pg_database WHERE datname = $1",
            resources.database,
        )
        if row is not None:
            if (
                resources.database != e2e_database_name(resources.run_id)
                or row["marker"] != resources.marker
            ):
                raise HarnessError(
                    "Database cleanup marker mismatch; database and roles were left intact"
                )
            await connection.execute(
                f"DROP DATABASE {quote_identifier(resources.database)} WITH (FORCE)"
            )

        for role in (resources.runtime_role, resources.migration_role):
            row = await connection.fetchrow("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            if row is not None:
                if role not in {
                    f"pfis_e2e_app_{resources.run_id}",
                    f"pfis_e2e_mig_{resources.run_id}",
                }:
                    raise HarnessError("Role cleanup identity mismatch; leaving role intact")
                await connection.execute(f"DROP ROLE {quote_identifier(role)}")
    finally:
        await connection.close()


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_app(process: subprocess.Popen, base_url: str, log_path: Path) -> None:
    health_url = f"{base_url}/api/health"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise HarnessError(
                f"FastAPI exited before readiness (exit {process.returncode}); see {log_path}"
            )
        try:
            with urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise HarnessError(f"FastAPI readiness timed out; see {log_path}")


def _app_command(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--app-dir",
        str(ROOT / "backend"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def _start_app(port: int, env: dict[str, str], log_handle) -> subprocess.Popen:
    return subprocess.Popen(
        _app_command(port),
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def _terminate_owned_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _fixture_env(env: dict[str, str], run_id: str, database: str) -> dict[str, str]:
    result = dict(env)
    result.update(
        {
            "PFIS_E2E": "1",
            "PFIS_E2E_RUN_ID": run_id,
            "PFIS_E2E_CONFIRM_DATABASE": database,
        }
    )
    return result


def _run_directory(run_id: str) -> Path:
    path = ROOT / ".test-run" / f"e2e-{run_id}"
    path.mkdir(parents=True, exist_ok=False)
    (path / "storage").mkdir()
    (path / "logs").mkdir()
    return path


def _write_run_metadata(
    report_dir: Path,
    *,
    mode: str,
    database: str,
    run_id: str,
    exit_code: int,
    nightly_restart_requested: bool,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "run_id": run_id,
        "database": database,
        "mode": mode,
        "exit_code": exit_code,
        "nightly_restart_requested": nightly_restart_requested,
        "credential_artifacts_excluded": True,
    }
    (report_dir / "run-metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def _run_playwright(
    mode: str,
    env: dict[str, str],
    report_dir: Path,
    *,
    test_grep: str | None = None,
) -> int:
    if mode == "smoke":
        playwright_args = [
            "test",
            "--grep",
            "@smoke",
            "--retries=0",
            "--project=desktop",
            "--project=mobile-360",
        ]
    else:
        playwright_args = ["test", "--grep-invert", "@visual"]
        if test_grep:
            playwright_args.extend(("--grep", test_grep))
    output_file = report_dir
    test_env = dict(env)
    test_env.update(
        {
            "PFIS_E2E_MODE": mode,
            "PFIS_E2E_RUN_DIR": str(Path(env["PFIS_E2E_STATE_DIR"]).parent),
            "PFIS_E2E_REPORT_DIR": str(output_file),
            "PFIS_E2E_OUTPUT_DIR": str(report_dir.parent / "test-results"),
            "PLAYWRIGHT_HTML_OPEN": "never",
        }
    )
    playwright_cli = FRONTEND / "node_modules" / "@playwright" / "test" / "cli.js"
    if not playwright_cli.is_file():
        raise HarnessError("Playwright CLI is missing; run npm ci or omit --skip-install")
    node = shutil.which("node") or "node"
    command = [node, str(playwright_cli), *playwright_args]
    print(f"[e2e] Playwright {mode} selection: {' '.join(playwright_args)}", flush=True)
    completed = subprocess.run(command, cwd=FRONTEND, env=test_env, check=False)
    return int(completed.returncode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "full", "explore"), default="smoke")
    parser.add_argument(
        "--nightly-restart",
        action="store_true",
        help="prepare and recover one interrupted pipeline job across a harness-owned app restart",
    )
    parser.add_argument(
        "--test-grep",
        help="optional Playwright title pattern for focused full-mode feedback",
    )
    parser.add_argument(
        "--allow-disposable-database",
        action="store_true",
        help="confirm creation and owner-checked removal of one disposable PostgreSQL database",
    )
    parser.add_argument("--run-id", help="optional 12-hex run id; generated when omitted")
    parser.add_argument(
        "--skip-install", action="store_true", help="skip npm ci if dependencies are installed"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.nightly_restart and args.mode != "full":
        raise HarnessError("--nightly-restart requires --mode full")
    if args.test_grep and args.mode != "full":
        raise HarnessError("--test-grep requires --mode full")
    if args.nightly_restart and args.test_grep:
        raise HarnessError("--nightly-restart cannot be combined with --test-grep")
    if not args.allow_disposable_database:
        raise HarnessError(
            "Pass --allow-disposable-database to opt in to an isolated test database"
        )
    admin_url = os.environ.get("PFIS_E2E_ADMIN_DATABASE_URL", "")
    if not admin_url:
        raise HarnessError(
            "PFIS_E2E_ADMIN_DATABASE_URL must identify a loopback bootstrap database"
        )
    parse_postgres_target(admin_url)
    run_id = validate_run_id(args.run_id or secrets.token_hex(6))
    database = e2e_database_name(run_id)
    run_dir = _run_directory(run_id)
    report_dir = run_dir / "reports"
    report_dir.mkdir()
    resources: DatabaseResources | None = None
    database_created = False
    app_process: subprocess.Popen | None = None
    exit_code = 1
    started = time.monotonic()
    report_error: str | None = None
    try:
        print(f"[e2e] run id: {run_id}; isolated database: {database}", flush=True)
        resources = _database_resources(admin_url, run_id)
        asyncio.run(create_database(resources))
        database_created = True
        port = _free_tcp_port()
        secret_key = secrets.token_urlsafe(48)
        runtime_env = child_environment(
            os.environ,
            database_url=resources.runtime_url,
            secret_key=secret_key,
            port=port,
            run_id=run_id,
        )
        runtime_env["PFIS_E2E_STATE_DIR"] = str(run_dir / "storage")
        migration_env = child_environment(
            os.environ,
            database_url=resources.migration_url,
            secret_key=secret_key,
            port=port,
            run_id=run_id,
        )
        if not args.skip_install:
            _run_checked(
                _npm_command("ci"),
                cwd=FRONTEND,
                env=runtime_env,
                label="Install frontend dependencies",
            )
        elif not (FRONTEND / "node_modules").is_dir():
            raise HarnessError(
                "frontend/node_modules is missing; run npm ci or omit --skip-install"
            )
        _run_checked(
            _npm_command("run", "build"),
            cwd=FRONTEND,
            env=runtime_env,
            label="Build React application",
        )
        _run_checked(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "backend",
            env=migration_env,
            label="Apply Alembic migrations with migration-owner role",
            timeout=300,
        )
        asyncio.run(grant_runtime_access(resources))
        asyncio.run(verify_database_roles(resources))
        _run_checked(
            [
                sys.executable,
                str(ROOT / "scripts" / "check_migration_parity.py"),
                "--database",
                database,
                "--output",
                str(report_dir / "migration-parity.json"),
            ],
            cwd=ROOT,
            env=runtime_env,
            label="Verify migrated schema parity",
            timeout=300,
        )
        profiles = list(FIXTURES)
        fixture_command = [
            sys.executable,
            str(ROOT / "scripts" / "e2e_fixtures.py"),
            "seed",
            "--run-id",
            run_id,
            "--database-name",
            database,
            "--confirm-database",
            database,
            "--base-url",
            f"http://127.0.0.1:{port}",
            "--output-dir",
            str(run_dir / "storage"),
        ]
        for profile in profiles:
            fixture_command.extend(("--profile", profile))
        fixture_env = _fixture_env(runtime_env, run_id, database)
        _run_checked(
            fixture_command,
            cwd=ROOT,
            env=fixture_env,
            label="Create authenticated synthetic profiles",
        )

        app_log_path = run_dir / "logs" / "app.log"
        with app_log_path.open("w", encoding="utf-8") as app_log:
            app_process = _start_app(port, runtime_env, app_log)
            base_url = f"http://127.0.0.1:{port}"
            print("[e2e] Waiting for FastAPI readiness", flush=True)
            _wait_for_app(app_process, base_url, app_log_path)
            if args.mode == "explore":
                credentials = run_dir / "storage" / "credentials.json"
                print(f"[e2e] Ready for Brave exploration at {base_url}/dashboard", flush=True)
                print(
                    f"[e2e] Test-only credentials are in the ignored file: {credentials}",
                    flush=True,
                )
                print("[e2e] Press Ctrl+C here when exploration is complete.", flush=True)
                while app_process.poll() is None:
                    time.sleep(1)
                exit_code = 0 if app_process.returncode == 0 else int(app_process.returncode)
            else:
                if args.nightly_restart:
                    recovery_command = [
                        sys.executable,
                        str(ROOT / "scripts" / "e2e_fixtures.py"),
                        "prepare-restart-job",
                        "--run-id",
                        run_id,
                        "--database-name",
                        database,
                        "--confirm-database",
                        database,
                        "--output-dir",
                        str(run_dir / "storage"),
                    ]
                    _run_checked(
                        recovery_command,
                        cwd=ROOT,
                        env=fixture_env,
                        label="Prepare interrupted job for nightly restart recovery",
                    )
                exit_code = _run_playwright(
                    args.mode,
                    runtime_env,
                    report_dir,
                    test_grep=args.test_grep,
                )
                if args.nightly_restart:
                    print("[e2e] Restarting only the harness-owned FastAPI process", flush=True)
                    _terminate_owned_process(app_process)
                    app_process = _start_app(port, runtime_env, app_log)
                    print("[e2e] Waiting for restarted FastAPI readiness", flush=True)
                    _wait_for_app(app_process, base_url, app_log_path)
                pipeline_selected = not args.test_grep or "pipeline" in args.test_grep.lower()
                if pipeline_selected:
                    try:
                        report_command = [
                            sys.executable,
                            str(ROOT / "scripts" / "e2e_report.py"),
                            "--run-id",
                            run_id,
                            "--database-name",
                            database,
                            "--manifest",
                            str(run_dir / "storage" / "manifest.json"),
                            "--output",
                            str(report_dir / "financial-pipeline.json"),
                        ]
                        if args.nightly_restart:
                            report_command.append("--check-restart-recovery")
                        _run_checked(
                            report_command,
                            cwd=ROOT,
                            env=runtime_env,
                            label=(
                                "Verify financial pipeline persistence and nightly restart recovery"
                                if args.nightly_restart
                                else "Verify persisted sources, dedup outcome, and ledger total"
                            ),
                            timeout=180,
                        )
                    except Exception as exc:
                        print(
                            f"[e2e] Financial pipeline report failed: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                        if exit_code == 0:
                            exit_code = 1
                else:
                    print(
                        "[e2e] Skipping pipeline-wide persistence report because the focused selection excludes @pipeline",
                        flush=True,
                    )
    except KeyboardInterrupt:
        print("[e2e] Exploration interrupted; stopping harness-owned app", flush=True)
        exit_code = 0
    except Exception as exc:
        report_error = str(exc)
        print(f"[e2e] {report_error}", file=sys.stderr, flush=True)
    finally:
        _terminate_owned_process(app_process)
        if resources is not None and database_created:
            try:
                asyncio.run(remove_database(resources))
                print(
                    f"[e2e] Removed only marked run database {resources.database} and its ephemeral roles",
                    flush=True,
                )
            except Exception as exc:
                report_error = f"owner-checked cleanup could not complete: {exc}"
                print(
                    f"[e2e] {report_error}; leaving uncertain resources intact",
                    file=sys.stderr,
                    flush=True,
                )
                exit_code = 1
        _write_run_metadata(
            report_dir,
            mode=args.mode,
            database=database,
            run_id=run_id,
            exit_code=exit_code,
            nightly_restart_requested=args.nightly_restart,
        )
        metadata = json.loads((report_dir / "run-metadata.json").read_text(encoding="utf-8"))
        metadata.update({"duration_seconds": round(time.monotonic() - started, 2)})
        if report_error:
            metadata["error"] = report_error
        (report_dir / "run-metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        sanitize_result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "sanitize_e2e_artifacts.py"),
                "--run-dir",
                str(run_dir),
                "--report-dir",
                str(report_dir),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if sanitize_result.returncode == 0:
            (report_dir / "SAFE_TO_UPLOAD").write_text(
                "Ephemeral browser session cookies and fixture passwords were removed.\n",
                encoding="utf-8",
            )
            storage_dir = run_dir / "storage"
            for secret_file in storage_dir.iterdir():
                if secret_file.name == "credentials.json" or secret_file.name.endswith(
                    ".storage-state.json"
                ):
                    secret_file.unlink()
        else:
            print(
                "[e2e] Playwright reports were withheld because credential redaction failed. "
                f"Sanitizer output: {sanitize_result.stderr.strip() or sanitize_result.stdout.strip()}",
                file=sys.stderr,
                flush=True,
            )
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HarnessError as exc:
        print(f"[e2e] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
