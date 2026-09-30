"""Remove ephemeral session and password values from Playwright artifacts."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote


def _collect_secrets(run_dir: Path) -> set[bytes]:
    storage_dir = run_dir / "storage"
    secrets_found: set[bytes] = set()
    credentials_path = storage_dir / "credentials.json"
    if credentials_path.exists():
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        for profile in credentials.values():
            password = str(profile.get("password", ""))
            if password:
                secrets_found.add(password.encode("utf-8"))
                secrets_found.add(quote(password, safe="").encode("utf-8"))

    for storage_state in storage_dir.glob("*.storage-state.json"):
        payload = json.loads(storage_state.read_text(encoding="utf-8"))
        for cookie in payload.get("cookies", []):
            if cookie.get("name") in {"pfis_session", "pfis_csrf"}:
                value = str(cookie.get("value", ""))
                if value:
                    secrets_found.add(value.encode("utf-8"))
                    secrets_found.add(quote(value, safe="").encode("utf-8"))
                    secrets_found.add(base64.b64encode(value.encode("utf-8")))
    return {value for value in secrets_found if value}


def _scrub_zip(path: Path, secrets_found: set[bytes]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix="pfis-e2e-trace-", suffix=".zip")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temporary, "w") as output:
            for entry in source.infolist():
                payload = source.read(entry.filename)
                for secret in secrets_found:
                    payload = payload.replace(secret, b"[REDACTED-E2E-SECRET]")
                output.writestr(entry, payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sanitize(report_dir: Path, run_dir: Path) -> int:
    report_dir = report_dir.resolve()
    run_dir = run_dir.resolve()
    if (
        not report_dir.is_relative_to(run_dir)
        or not (run_dir / "storage").is_dir()
        or not (run_dir / "test-results").is_relative_to(run_dir)
    ):
        raise ValueError("Report and credential paths must belong to the same E2E run directory")
    secrets_found = _collect_secrets(run_dir)
    sanitized = 0
    artifact_roots = (report_dir, run_dir / "test-results")
    for artifact_root in artifact_roots:
        for path in artifact_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".zip":
                _scrub_zip(path, secrets_found)
                content = path.read_bytes()
            else:
                content = path.read_bytes()
                for secret in secrets_found:
                    content = content.replace(secret, b"[REDACTED-E2E-SECRET]")
                path.write_bytes(content)
            if any(secret in content for secret in secrets_found):
                raise ValueError(f"An ephemeral credential remains in report artifact {path.name}")
            sanitized += 1
    return sanitized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    count = sanitize(args.report_dir, args.run_dir)
    print(f"Sanitized {count} report artifacts; no session cookie or fixture password remains.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"E2E artifact sanitization failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
