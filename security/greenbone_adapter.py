"""Narrow Greenbone Community adapter; accepts only the registered PFIS target."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

GVM_SOCKET = "/run/gvmd/gvmd.sock"
GVM_USER = "admin"
REGISTERED_TARGET = "pfis-web"
REGISTERED_HOST = "pfis.test"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ACTIVE_TASK_ID: str | None = None
GVM_CONFIG: Path | None = None


class AdapterError(RuntimeError):
    """A fixed Greenbone operation failed or exceeded its scope."""


def _write_config(password: str) -> Path:
    path = Path(tempfile.gettempdir()) / "pfis-gvm-tools.conf"
    content = (
        "[main]\ntimeout=60\n\n"
        f"[gmp]\nusername={GVM_USER}\npassword={password}\n\n"
        f"[unixsocket]\nsocketpath={GVM_SOCKET}\n"
    )
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def _safe_cli_error(result: subprocess.CompletedProcess[str]) -> str:
    """Keep only one bounded, redacted gvm-cli diagnostic line."""
    raw = f"{result.stderr or ''}\n{result.stdout or ''}"
    raw = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw)
    for secret in (os.environ.get("PFIS_GVM_PASSWORD", ""),):
        if secret:
            raw = raw.replace(secret, "[redacted]")
    raw = re.sub(
        r"(?i)\b(password|passphrase|secret|token)(\s*[:=]\s*|\s+)[^\s,;]+",
        r"\1\2[redacted]",
        raw,
    )
    lines = raw.splitlines()
    frames = [line.strip() for line in lines if re.match(r"\s*File \"[^\"]+\", line \d+", line)]
    for line in reversed(lines):
        candidate = line.strip()
        if (
            candidate
            and not candidate.startswith(("Traceback ", "File "))
            and "<" not in candidate
            and ">" not in candidate
        ):
            if frames:
                return f"{frames[-1][:100]}: {candidate[:120]}"
            return candidate[:160]
    return "unclassified gvm-cli error"


def _send(command: str) -> ET.Element:
    if len(command) > 16_000 or not command.startswith("<"):
        raise AdapterError("invalid registered Greenbone request")
    if GVM_CONFIG is None:
        raise AdapterError("Greenbone credentials are unavailable")
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="pfis-gvm-request-",
        suffix=".xml",
        dir=tempfile.gettempdir(),
        delete=False,
    ) as request_file:
        request_file.write(command)
        request_path = Path(request_file.name)
    try:
        request_path.chmod(0o600)
        result = subprocess.run(
            [
                "gvm-cli",
                "--config",
                str(GVM_CONFIG),
                "--timeout",
                "60",
                "socket",
                "--socketpath",
                GVM_SOCKET,
                str(request_path),
            ],
            capture_output=True,
            text=True,
            timeout=70,
            check=False,
            shell=False,
        )
    finally:
        request_path.unlink(missing_ok=True)
    if result.returncode:
        # Expose only a bounded category; command output can contain secrets.
        diagnostic = f"{result.stdout}\n{result.stderr}".casefold()
        if "must not be run as root" in diagnostic:
            reason = "gvm-tools requires an unprivileged user"
        elif "permission denied" in diagnostic:
            reason = "Greenbone management socket permission denied"
        elif "authentication" in diagnostic or "unauthorized" in diagnostic:
            reason = "Greenbone credentials were rejected"
        elif "enter username" in diagnostic or "eof when reading a line" in diagnostic:
            reason = "Greenbone credentials were not supplied to gvm-tools"
        elif any(term in diagnostic for term in ("no such file", "connection refused")):
            reason = "Greenbone management socket is unavailable"
        elif "timed out" in diagnostic or "timeout" in diagnostic:
            reason = "Greenbone management request timed out"
        else:
            reason = f"Greenbone management request failed: {_safe_cli_error(result)}"
        raise AdapterError(reason)
    try:
        response = ET.fromstring(result.stdout)
    except ET.ParseError as exc:
        raise AdapterError("Greenbone returned invalid management XML") from exc
    status = response.get("status", "")
    if status and status[0] not in {"2", "3"}:
        request_name = response.tag.removesuffix("_response")
        if not re.fullmatch(r"[a-z_]{1,48}", request_name):
            request_name = "management"
        response_code = status if re.fullmatch(r"\d{3}", status) else "unknown"
        raise AdapterError(f"Greenbone rejected {request_name} request (status {response_code})")
    return response


def _authenticate() -> None:
    global GVM_CONFIG
    password = os.environ.get("PFIS_GVM_PASSWORD", "")
    if len(password) < 24 or any(char in password for char in "\r\n"):
        raise AdapterError("generated Greenbone credentials are unavailable")
    GVM_CONFIG = _write_config(password)
    try:
        _send("<get_version/>")
        return
    except AdapterError:
        # A new lab generation starts with the official image's default
        # account. The first authenticated operation immediately replaces it.
        GVM_CONFIG = _write_config("admin")
        users = _send('<get_users filter="name=admin"/>')
        user = users.find(".//user")
        user_id = user.get("id") if user is not None else None
        if not user_id or not UUID_RE.fullmatch(user_id):
            raise AdapterError("Greenbone initial administrator is unavailable") from None
        _send(
            f'<modify_user user_id="{user_id}"><name>{GVM_USER}</name>'
            f"<password>{password}</password></modify_user>"
        )
        GVM_CONFIG = _write_config(password)
        _send("<get_version/>")


def _registered_address() -> str:
    if os.environ.get("LAB_SECURITY_TARGET_ID") != REGISTERED_TARGET:
        raise AdapterError("Greenbone target is not registered for this profile")
    resolved = {
        item[4][0] for item in socket.getaddrinfo(REGISTERED_HOST, None, type=socket.SOCK_STREAM)
    }
    addresses = {str(ipaddress.ip_address(value)) for value in resolved}
    if len(addresses) != 1:
        raise AdapterError("PFIS lab target did not resolve to one address")
    address = next(iter(addresses))
    parsed = ipaddress.ip_address(address)
    if not parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_multicast:
        raise AdapterError("PFIS lab target resolved outside the private lab range")
    return address


def _find_id(response: ET.Element, element: str, name: str | None = None) -> str:
    for item in response.findall(f".//{element}"):
        item_name = (item.findtext("name") or "").strip().casefold()
        if name is None or item_name == name.casefold():
            item_id = item.get("id")
            if item_id:
                return item_id
    raise AdapterError(f"required Greenbone {element} is not ready")


def _signal_handler(_signum: int, _frame: object) -> None:
    if ACTIVE_TASK_ID:
        with suppress(AdapterError, subprocess.SubprocessError):
            _send(f'<stop_task task_id="{ACTIVE_TASK_ID}"/>')
    raise SystemExit(143)


def scan(target_id: str) -> ET.Element:
    global ACTIVE_TASK_ID
    if target_id != REGISTERED_TARGET:
        raise AdapterError("Greenbone target is not registered for this profile")
    generation = os.environ.get("LAB_GENERATION", "")
    if len(generation) != 12 or any(char not in "0123456789abcdef" for char in generation):
        raise AdapterError("Greenbone lab generation is invalid")
    host = _registered_address()
    config_id = _find_id(_send("<get_configs/>"), "config", "Full and fast")
    scanner_id = _find_id(_send("<get_scanners/>"), "scanner", "OpenVAS Default")
    task_name = f"PFIS {generation}"
    target_response = _send(
        f"<create_target><name>{task_name}</name><hosts>{host}</hosts></create_target>"
    )
    target_uuid = target_response.get("id")
    if not target_uuid or not UUID_RE.fullmatch(target_uuid):
        raise AdapterError("Greenbone could not register the PFIS lab target")
    task_response = _send(
        f'<create_task><name>{task_name}</name><target id="{target_uuid}"/>'
        f'<config id="{config_id}"/><scanner id="{scanner_id}"/></create_task>'
    )
    ACTIVE_TASK_ID = task_response.get("id")
    if not ACTIVE_TASK_ID or not UUID_RE.fullmatch(ACTIVE_TASK_ID):
        raise AdapterError("Greenbone could not create the PFIS scan task")
    started = _send(f'<start_task task_id="{ACTIVE_TASK_ID}"/>')
    report_id = (started.findtext("report_id") or "").strip()
    if not UUID_RE.fullmatch(report_id):
        raise AdapterError("Greenbone did not start the PFIS scan task")

    deadline = time.monotonic() + 3600
    while time.monotonic() < deadline:
        current = _send(f'<get_tasks task_id="{ACTIVE_TASK_ID}"/>')
        task = current.find(".//task")
        task_state = (task.findtext("status") if task is not None else "") or ""
        if task_state.casefold() in {"done", "completed"}:
            report = _send(f'<get_reports report_id="{report_id}"/>')
            ACTIVE_TASK_ID = None
            return report
        if task_state.casefold() in {"stopped", "interrupted"}:
            raise AdapterError("Greenbone scan did not complete")
        time.sleep(10)
    _send(f'<stop_task task_id="{ACTIVE_TASK_ID}"/>')
    raise AdapterError("Greenbone scan exceeded its one-hour limit")


def readiness() -> dict[str, str]:
    _authenticate()
    version = _send("<get_version/>").findtext("version") or "unknown"
    _find_id(_send("<get_configs/>"), "config", "Full and fast")
    _find_id(_send("<get_scanners/>"), "scanner", "OpenVAS Default")
    return {"status": "ready", "version": version, "target_id": REGISTERED_TARGET}


def main() -> int:
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    if sys.argv[1:] == ["ready"]:
        try:
            print(json.dumps(readiness(), sort_keys=True))
            return 0
        except (AdapterError, OSError, subprocess.SubprocessError, ET.ParseError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        finally:
            if GVM_CONFIG is not None:
                with suppress(OSError):
                    GVM_CONFIG.unlink(missing_ok=True)
    if sys.argv[1:] != ["scan", "--target-id", REGISTERED_TARGET]:
        print("Greenbone adapter accepts only the registered PFIS target.", file=sys.stderr)
        return 2
    try:
        _authenticate()
        report = scan(REGISTERED_TARGET)
        sys.stdout.write(ET.tostring(report, encoding="unicode"))
        sys.stdout.write("\n")
        return 0
    except (AdapterError, OSError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if GVM_CONFIG is not None:
            with suppress(OSError):
                GVM_CONFIG.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
