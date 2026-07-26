"""One-command local startup for PFIS.

This script prepares the local backend and frontend, then starts FastAPI.
FastAPI serves the built React dashboard at /dashboard, so only one long-lived
server process is needed for the normal local workflow.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
VENV_DIR = ROOT_DIR / ".venv"
ENV_FILE = BACKEND_DIR / ".env"
ENV_EXAMPLE = BACKEND_DIR / ".env.example"
ROOT_ENV_FILE = ROOT_DIR / ".env"
FRONTEND_DIST_INDEX = FRONTEND_DIR / "dist" / "index.html"
BACKEND_INSTALL_STAMP = VENV_DIR / ".pfis-backend-installed"
EXAMPLE_SECRET_KEY = "change-me-in-production-with-at-least-32-characters"
DEFAULT_SECRET_KEY = "pfis-dev-secret-change-me-please-32bytes"
KNOWN_PLACEHOLDER_SECRETS = {EXAMPLE_SECRET_KEY, DEFAULT_SECRET_KEY}
SECRET_KEY_PATTERN = re.compile(r"^(SECRET_KEY=)([^\r\n#]+)(\s*)$", re.MULTILINE)

FRONTEND_BUILD_INPUTS = (
    "index.html",
    "package.json",
    "package-lock.json",
    "postcss.config.js",
    "tailwind.config.js",
    "tsconfig.json",
    "tsconfig.app.json",
    "tsconfig.node.json",
    "vite.config.ts",
    "src",
)
SUPABASE_DATABASE_ONLY_EXCLUDES = (
    "edge-runtime",
    "gotrue",
    "imgproxy",
    "kong",
    "logflare",
    "mailpit",
    "postgres-meta",
    "postgrest",
    "realtime",
    "storage-api",
    "studio",
    "supavisor",
    "vector",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and start PFIS locally.")
    parser.add_argument("--host", default=os.environ.get("PFIS_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=os.environ.get("PFIS_PORT", "8000"))
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Start uvicorn without auto-reload.",
    )
    parser.add_argument(
        "--force-build",
        action="store_true",
        help="Always rebuild the React dashboard before starting.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip dependency installation checks.",
    )
    parser.add_argument(
        "--skip-migrations",
        action="store_true",
        help="Skip the local Alembic migration step.",
    )
    parser.add_argument(
        "--skip-supabase",
        action="store_true",
        help="Do not start the local Supabase stack.",
    )
    return parser.parse_args()


def run(command: list[str], cwd: Path | None = None) -> None:
    label = " ".join(command)
    print(f"\n[PFIS] {label}")
    completed = subprocess.run(command, cwd=cwd or ROOT_DIR, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def ensure_virtualenv() -> Path:
    python_path = venv_python()
    if python_path.exists():
        return python_path

    print("[PFIS] Creating local Python virtual environment in .venv ...")
    run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if not python_path.exists():
        raise SystemExit("Unable to create .venv. Install Python 3.13+ and try again.")
    return python_path


def requirement_files() -> list[Path]:
    return [BACKEND_DIR / "requirements.txt", BACKEND_DIR / "requirements-dev.txt"]


def backend_dependencies_stale() -> bool:
    if not BACKEND_INSTALL_STAMP.exists():
        return True
    stamp_mtime = BACKEND_INSTALL_STAMP.stat().st_mtime
    return any(path.exists() and path.stat().st_mtime > stamp_mtime for path in requirement_files())


def ensure_backend_dependencies(python_path: Path, skip_install: bool) -> None:
    if skip_install or not backend_dependencies_stale():
        return

    print("[PFIS] Installing backend dependencies ...")
    run([str(python_path), "-m", "pip", "install", "-r", "backend/requirements-dev.txt"])
    BACKEND_INSTALL_STAMP.write_text("installed\n", encoding="utf-8")


def ensure_env_file() -> None:
    if ENV_FILE.exists():
        rotate_placeholder_secret(ENV_FILE)
        rotate_placeholder_secret(ROOT_ENV_FILE)
        return
    if not ENV_EXAMPLE.exists():
        rotate_placeholder_secret(ROOT_ENV_FILE)
        return
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    env_text = SECRET_KEY_PATTERN.sub(
        lambda match: replace_placeholder_secret_match(match),
        env_text,
    )
    ENV_FILE.write_text(env_text, encoding="utf-8")
    print("[PFIS] Created backend/.env with a generated local SECRET_KEY.")
    rotate_placeholder_secret(ROOT_ENV_FILE)


def replace_placeholder_secret_match(match: re.Match[str]) -> str:
    """Replace a known placeholder SECRET_KEY assignment with a generated value."""
    current_value = match.group(2).strip().strip("\"'")
    if current_value not in KNOWN_PLACEHOLDER_SECRETS:
        return match.group(0)
    return f"{match.group(1)}{secrets.token_urlsafe(48)}{match.group(3)}"


def rotate_placeholder_secret(env_path: Path) -> None:
    """Rotate placeholder SECRET_KEY values in an existing env file, if present."""
    if not env_path.exists():
        return

    original_text = env_path.read_text(encoding="utf-8")
    updated_text = SECRET_KEY_PATTERN.sub(
        lambda match: replace_placeholder_secret_match(match),
        original_text,
    )
    if updated_text == original_text:
        return

    env_path.write_text(updated_text, encoding="utf-8")
    relative_path = (
        env_path.relative_to(ROOT_DIR) if env_path.is_relative_to(ROOT_DIR) else env_path
    )
    print(f"[PFIS] Replaced placeholder SECRET_KEY in {relative_path}.")


def ensure_node_available() -> None:
    missing = [command for command in ("node", "npm") if not command_exists(command)]
    if missing:
        raise SystemExit(
            "Missing Node.js tooling: "
            + ", ".join(missing)
            + ". Install Node.js 22+ and rerun this command."
        )


def configured_database_url() -> str:
    """Read the effective database URL without loading application secrets."""
    if database_url := os.environ.get("DATABASE_URL"):
        return database_url
    for env_path in (ENV_FILE, ROOT_ENV_FILE):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.partition("=")[2].strip().strip("\"'")
    return ""


def ensure_local_supabase(skip_supabase: bool) -> None:
    """Start Supabase when PFIS targets its standard local PostgreSQL port."""
    if skip_supabase:
        return
    database_url = configured_database_url()
    if not any(
        local_address in database_url for local_address in ("127.0.0.1:54322", "localhost:54322")
    ):
        return

    ensure_node_available()
    npx_command = "npx.cmd" if os.name == "nt" else "npx"
    print("[PFIS] Starting local Supabase PostgreSQL ...")
    run(
        [
            npx_command,
            "supabase",
            "start",
            "--exclude",
            ",".join(SUPABASE_DATABASE_ONLY_EXCLUDES),
        ]
    )


def frontend_dependencies_stale() -> bool:
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        return True

    package_lock = FRONTEND_DIR / "package-lock.json"
    package_json = FRONTEND_DIR / "package.json"
    marker = node_modules / ".package-lock.json"
    reference = marker if marker.exists() else node_modules
    reference_mtime = reference.stat().st_mtime
    return any(
        path.exists() and path.stat().st_mtime > reference_mtime
        for path in (package_lock, package_json)
    )


def ensure_frontend_dependencies(skip_install: bool) -> None:
    ensure_node_available()
    if skip_install or not frontend_dependencies_stale():
        return

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    install_command = "ci" if (FRONTEND_DIR / "package-lock.json").exists() else "install"
    print("[PFIS] Installing frontend dependencies ...")
    run([npm_command, install_command, "--no-audit", "--no-fund"], cwd=FRONTEND_DIR)


def newest_frontend_input_mtime() -> float:
    newest = 0.0
    for relative in FRONTEND_BUILD_INPUTS:
        path = FRONTEND_DIR / relative
        if not path.exists():
            continue
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
            continue
        for child in path.rglob("*"):
            if child.is_file():
                newest = max(newest, child.stat().st_mtime)
    return newest


def frontend_build_stale(force_build: bool) -> bool:
    if force_build or not FRONTEND_DIST_INDEX.exists():
        return True
    return newest_frontend_input_mtime() > FRONTEND_DIST_INDEX.stat().st_mtime


def build_frontend_if_needed(force_build: bool) -> None:
    if not frontend_build_stale(force_build):
        print("[PFIS] React dashboard build is up to date.")
        return

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    print("[PFIS] Building React dashboard for FastAPI to serve at /dashboard ...")
    run([npm_command, "run", "build"], cwd=FRONTEND_DIR)


def run_migrations(python_path: Path, skip_migrations: bool) -> None:
    if skip_migrations:
        return
    print("[PFIS] Applying local database migrations ...")
    run([str(python_path), "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR)


def _is_port_free(host: str, port: int) -> bool:
    """Return True when the TCP port is available to bind.

    Note: SO_REUSEADDR is intentionally omitted because on Windows it allows
    concurrent binds, which would produce false positives.
    """
    bind_host = "127.0.0.1" if host in {"0.0.0.0", ""} else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((bind_host, port))
            return True
        except OSError:
            return False


def _find_free_port(host: str, start: int, attempts: int = 20) -> int | None:
    """Return the first free port at or above *start*, or None if none found."""
    for port in range(start, start + attempts):
        if _is_port_free(host, port):
            return port
    return None


def check_port(host: str, port: int) -> int:
    """Verify the port is available and return it, auto-advancing if blocked."""
    if _is_port_free(host, port):
        return port

    print(f"[PFIS] Port {port} is already in use.")
    free = _find_free_port(host, port + 1)
    if free is None:
        raise SystemExit(
            f"[PFIS] Could not find a free port near {port}. "
            "Stop other services or pass --port <number>."
        )
    print(f"[PFIS] Switching to port {free} automatically.")
    return free


def start_backend(python_path: Path, host: str, port: str, reload: bool) -> int:
    dashboard_url = f"http://{host}:{port}/dashboard"
    docs_url = f"http://{host}:{port}/docs"
    print("\n[PFIS] Starting PFIS ...")
    print(f"[PFIS] Dashboard: {dashboard_url}")
    print(f"[PFIS] API docs:  {docs_url}")
    print("[PFIS] Press Ctrl+C to stop.\n")

    command = [
        str(python_path),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        port,
    ]
    if reload:
        command.append("--reload")

    env = os.environ.copy()
    env["PFIS_HOST"] = host
    env["PFIS_PORT"] = port
    return subprocess.call(command, cwd=BACKEND_DIR, env=env)


def main() -> int:
    args = parse_args()
    python_path = ensure_virtualenv()
    ensure_env_file()
    ensure_backend_dependencies(python_path, args.skip_install)
    ensure_frontend_dependencies(args.skip_install)
    build_frontend_if_needed(args.force_build)
    ensure_local_supabase(args.skip_supabase)
    run_migrations(python_path, args.skip_migrations)
    port = check_port(args.host, int(args.port))
    return start_backend(
        python_path=python_path,
        host=args.host,
        port=str(port),
        reload=not args.no_reload,
    )


if __name__ == "__main__":
    raise SystemExit(main())
