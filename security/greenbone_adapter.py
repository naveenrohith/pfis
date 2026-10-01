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
import uuid
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

GVM_SOCKET = "/run/gvmd/gvmd.sock"
GVM_USER = "pfis_security"
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


def _safe_gmp_status_reason(response: ET.Element) -> str:
    status_text = response.get("status_text", "")[:256].casefold()
    if "invalid characters in user name" in status_text:
        return "invalid user name"
    if "user" in status_text and any(term in status_text for term in ("not found", "not exist")):
        return "user not found"
    if "not found" in status_text or "not exist" in status_text:
        return "resource not found"
    if "permission denied" in status_text or "not authorized" in status_text:
        return "permission denied"
    return ""


def _safe_gmp_status_detail(response: ET.Element) -> str:
    status_text = response.get("status_text", "")[:256]
    if not status_text:
        return ""
    detail = _safe_cli_error(
        subprocess.CompletedProcess(["gvm-cli"], 1, stdout="", stderr=status_text)
    )
    detail = re.sub(r"[^A-Za-z0-9 .,;:_()/-\[\]]", "", detail)[:100]
    return "" if detail == "unclassified gvm-cli error" else detail


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
        reason = _safe_gmp_status_reason(response) or _safe_gmp_status_detail(response)
        detail = f", {reason}" if reason else ""
        raise AdapterError(
            f"Greenbone rejected {request_name} request (status {response_code}{detail})"
        )
    return response


def _authenticate() -> None:
    global GVM_CONFIG
    password = os.environ.get("PFIS_GVM_PASSWORD", "")
    if len(password) < 24 or any(char in password for char in "\r\n"):
        raise AdapterError("generated Greenbone credentials are unavailable")
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


def _find_resource(response: ET.Element, element: str, resource_id: str) -> ET.Element | None:
    return next(
        (item for item in response.findall(f".//{element}") if item.get("id") == resource_id),
        None,
    )


def _resolve_target(
    target_name: str,
    host: str,
    port_list_id: str,
) -> tuple[str, ET.Element | None]:
    response = _send('<get_targets details="1" tasks="1"/>')
    targets = [
        item
        for item in response.findall("./target")
        if (item.findtext("name") or "").strip() == target_name
    ]
    if len(targets) > 1:
        raise AdapterError("multiple Greenbone targets match the PFIS lab generation")
    if not targets:
        created = _send(
            f"<create_target><name>{target_name}</name><hosts>{host}</hosts>"
            f'<port_list id="{port_list_id}"/></create_target>'
        )
        target_id = created.get("id", "")
        if not UUID_RE.fullmatch(target_id):
            raise AdapterError("Greenbone could not register the PFIS lab target")
        return target_id, None

    target = targets[0]
    target_id = target.get("id", "")
    hosts = [
        value.strip() for value in (target.findtext("hosts") or "").split(",") if value.strip()
    ]
    port_list = target.find("port_list")
    excluded_hosts = (target.findtext("exclude_hosts") or "").strip()
    if (
        not UUID_RE.fullmatch(target_id)
        or hosts != [host]
        or excluded_hosts
        or port_list is None
        or port_list.get("id") != port_list_id
    ):
        raise AdapterError("existing Greenbone target does not match the registered PFIS lab scope")
    return target_id, target


def _resolve_task(
    target: ET.Element | None,
    target_id: str,
    target_name: str,
    config_id: str,
    scanner_id: str,
) -> str:
    reusable: list[str] = []
    has_owned_task_name = False
    for reference in target.findall("./tasks/task") if target is not None else ():
        task_id = reference.get("id", "")
        task_name = (reference.findtext("name") or "").strip()
        if not UUID_RE.fullmatch(task_id):
            raise AdapterError("Greenbone returned an invalid task reference for the PFIS target")
        details = _send(f'<get_tasks task_id="{task_id}" details="1"/>')
        task = _find_resource(details, "task", task_id)
        if task is None:
            raise AdapterError("Greenbone target references a missing scan task")
        status = (task.findtext("status") or "").strip().casefold()
        if status in {"requested", "queued", "running", "processing", "stopping"}:
            raise AdapterError("Greenbone already has an active task for the PFIS lab target")

        if task_name == target_name or task_name.startswith(f"{target_name} assessment "):
            has_owned_task_name = True
            task_target = task.find("target")
            task_config = task.find("config")
            task_scanner = task.find("scanner")
            if (
                status in {"done", "completed"}
                and task_target is not None
                and task_target.get("id") == target_id
                and task_config is not None
                and task_config.get("id") == config_id
                and task_scanner is not None
                and task_scanner.get("id") == scanner_id
            ):
                reusable.append(task_id)

    if len(reusable) > 1:
        raise AdapterError("multiple completed Greenbone tasks match the PFIS lab scope")
    if reusable:
        return reusable[0]

    task_name = (
        f"{target_name} assessment {uuid.uuid4().hex[:12]}" if has_owned_task_name else target_name
    )
    created = _send(
        f'<create_task><name>{task_name}</name><target id="{target_id}"/>'
        f'<config id="{config_id}"/><scanner id="{scanner_id}"/></create_task>'
    )
    task_id = created.get("id", "")
    if not UUID_RE.fullmatch(task_id):
        raise AdapterError("Greenbone could not create the PFIS scan task")
    return task_id


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
    port_list_id = _find_id(_send("<get_port_lists/>"), "port_list", "All IANA assigned TCP")
    if not all(UUID_RE.fullmatch(value) for value in (config_id, scanner_id, port_list_id)):
        raise AdapterError("Greenbone returned invalid scanner configuration identifiers")
    target_name = f"PFIS {generation}"
    target_uuid, existing_target = _resolve_target(target_name, host, port_list_id)
    ACTIVE_TASK_ID = _resolve_task(
        existing_target,
        target_uuid,
        target_name,
        config_id,
        scanner_id,
    )
    if ACTIVE_TASK_ID is None:
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
