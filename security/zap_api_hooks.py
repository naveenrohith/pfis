"""Fixed ZAP API scan hooks for PFIS's cookie-bound CSRF contract."""

from __future__ import annotations

import re
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REGISTERED_ORIGIN = "https://pfis.test"
OPENAPI_PROFILE_PATH = Path("/tmp/pfis-zap-application-openapi.json")
CSRF_SCRIPT_NAME = "pfis-lab-csrf-cookie-header"
CSRF_SCRIPT_PATH = "/opt/pfis/zap_csrf_cookie_header.js"
CSRF_COOKIE_NAME = "__Host-pfis-csrf"
SESSION_COOKIE_NAME = "__Host-pfis-session"
CSRF_PROBE_PATH = "/api/transactions/?user_id=00000000-0000-4000-8000-000000000001"
HOOK_STATE_PATH = Path("/tmp/pfis-zap-hook-state.txt")
HOOK_STATES = frozenset(
    {
        "zap_started",
        "target_verified",
        "script_available",
        "graal_engine_verified",
        "sender_enabled",
        "pre_shutdown_started",
        "auth_cookies_observed",
        "csrf_sender_missing",
        "csrf_probe_sent",
        "csrf_validation_verified",
        "auth_cookies_missing",
        "csrf_denial_verified",
        "csrf_validation_missing",
        "csrf_response_missing",
    }
)


def _record_hook_state(state: str) -> None:
    """Keep only a fixed, credential-free lifecycle marker for scanner diagnostics."""
    if state not in HOOK_STATES and not re.fullmatch(r"csrf_status_[0-9]{3}", state):
        return
    with suppress(OSError):
        HOOK_STATE_PATH.write_text(state, encoding="ascii")


def _is_registered_scan_target(target: str) -> bool:
    """Accept PFIS HTTPS or the one prevalidated OpenAPI file used by API Scan."""
    parsed = urlsplit(target)
    if "://" in target:
        return (
            parsed.scheme == "https"
            and parsed.hostname == "pfis.test"
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
        )
    try:
        supplied_path = Path(target)
        return supplied_path.resolve() == OPENAPI_PROFILE_PATH.resolve() and supplied_path.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def zap_started(zap: Any, target: str) -> None:
    """Load the reviewed sender script into only the fixed PFIS scan target."""
    _record_hook_state("zap_started")
    if not _is_registered_scan_target(target):
        raise RuntimeError("PFIS CSRF sender hook received an unregistered target")
    _record_hook_state("target_verified")
    if not Path(CSRF_SCRIPT_PATH).is_file():
        raise RuntimeError("the pinned PFIS CSRF sender script is missing")
    _record_hook_state("script_available")
    engines = zap.script.list_engines
    if not any(str(engine).endswith(" : Graal.js") for engine in engines):
        raise RuntimeError("the pinned ZAP image does not provide the Graal.js engine")
    _record_hook_state("graal_engine_verified")
    zap.script.load(
        CSRF_SCRIPT_NAME,
        "httpsender",
        "Graal.js",
        CSRF_SCRIPT_PATH,
        "Copies the registered PFIS CSRF cookie into the request header.",
    )
    zap.script.enable(CSRF_SCRIPT_NAME)
    _record_hook_state("sender_enabled")


def zap_pre_shutdown(zap: Any) -> None:
    """Prove an in-scope cookie mutation passes CSRF and reaches validation."""
    _record_hook_state("pre_shutdown_started")
    messages = zap.core.messages(REGISTERED_ORIGIN, 0, 10_000)
    try:
        cookie_header = _authenticated_cookie_header(messages)
    except RuntimeError:
        _record_hook_state("auth_cookies_missing")
        raise
    _record_hook_state("auth_cookies_observed")
    try:
        denial_probe = _build_csrf_probe_request(
            cookie_header, include_csrf_cookie=False, include_csrf_header=False
        )
        accepted_probe = _build_csrf_probe_request(cookie_header, include_csrf_header=False)
    except RuntimeError:
        _record_hook_state("auth_cookies_missing")
        raise

    zap.core.send_request(denial_probe, followredirects=False)
    _record_hook_state("csrf_probe_sent")
    messages = _latest_message(zap, REGISTERED_ORIGIN)
    if not _has_csrf_probe_status(messages, 403):
        status_code = _response_status_code(messages[0] if messages else None)
        _record_hook_state(f"csrf_status_{status_code}" if status_code else "csrf_response_missing")
        raise RuntimeError("PFIS did not reject the CSRF probe without its CSRF cookie")
    _record_hook_state("csrf_denial_verified")

    zap.core.send_request(accepted_probe, followredirects=False)
    _record_hook_state("csrf_probe_sent")
    messages = _latest_message(zap, REGISTERED_ORIGIN)
    if not _has_csrf_probe_status(messages, 422):
        status_code = _response_status_code(messages[0] if messages else None)
        _record_hook_state(f"csrf_status_{status_code}" if status_code else "csrf_response_missing")
        raise RuntimeError("authenticated ZAP CSRF sender did not reach PFIS validation")
    _record_hook_state("csrf_validation_verified")


def _build_csrf_probe_request(
    cookie_header: str, *, include_csrf_cookie: bool = True, include_csrf_header: bool = True
) -> str:
    cookies = _parse_cookie_header(cookie_header)
    session_token = cookies.get(SESSION_COOKIE_NAME, "")
    csrf_token = cookies.get(CSRF_COOKIE_NAME, "")
    if not session_token or re.search(r"[\r\n;]", session_token):
        raise RuntimeError("authenticated ZAP did not observe a valid PFIS session cookie")
    if include_csrf_cookie and (not csrf_token or re.search(r"[\r\n;]", csrf_token)):
        raise RuntimeError("authenticated ZAP did not observe a valid PFIS CSRF cookie")
    csrf_header = f"X-CSRF-Token: {csrf_token}\r\n" if include_csrf_header else ""
    probe_cookie_header = f"{SESSION_COOKIE_NAME}={session_token}"
    if include_csrf_cookie:
        probe_cookie_header += f"; {CSRF_COOKIE_NAME}={csrf_token}"
    return (
        f"POST {CSRF_PROBE_PATH} HTTP/1.1\r\n"
        "Host: pfis.test\r\n"
        f"Origin: {REGISTERED_ORIGIN}\r\n"
        "Content-Type: application/json\r\n"
        f"Cookie: {probe_cookie_header}\r\n"
        f"{csrf_header}"
        "Content-Length: 2\r\n"
        "Connection: close\r\n\r\n{}"
    )


def _authenticated_cookie_header(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        request = str(message.get("requestHeader", ""))
        if not request.startswith("POST "):
            continue
        cookie_line = re.search(r"(?im)^Cookie:\s*([^\r\n]+)", request)
        if cookie_line is None:
            continue
        cookies = _parse_cookie_header(cookie_line.group(1))
        if CSRF_COOKIE_NAME in cookies and SESSION_COOKIE_NAME in cookies:
            values = (cookies[SESSION_COOKIE_NAME], cookies[CSRF_COOKIE_NAME])
            if any(not value or re.search(r"[\r\n;]", value) for value in values):
                continue
            return f"{SESSION_COOKIE_NAME}={values[0]}; " f"{CSRF_COOKIE_NAME}={values[1]}"
    raise RuntimeError("authenticated ZAP did not observe both PFIS lab cookies")


def _parse_cookie_header(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in value.split(";"):
        name, separator, cookie_value = item.strip().partition("=")
        if separator:
            cookies[name] = cookie_value
    return cookies


def _has_csrf_probe_status(messages: list[dict[str, Any]], expected_status: int) -> bool:
    for message in messages:
        request = str(message.get("requestHeader", ""))
        if not _is_csrf_probe_request(request) or not _has_registered_host_and_origin(request):
            continue
        if _response_status_code(message) == str(expected_status):
            return True
    return False


def _is_csrf_probe_request(request: str) -> bool:
    request_line = request.splitlines()[0] if request else ""
    parts = request_line.split()
    if len(parts) != 3 or parts[0] != "POST" or not parts[2].startswith("HTTP/"):
        return False
    target = parts[1]
    if target.startswith("/"):
        return target == CSRF_PROBE_PATH
    try:
        parsed = urlsplit(target)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return (
            parsed.scheme == "https"
            and parsed.hostname == "pfis.test"
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and path == CSRF_PROBE_PATH
        )
    except ValueError:
        return False


def _has_registered_host_and_origin(request: str) -> bool:
    host_line = re.search(r"(?im)^Host:\s*([^\r\n]+)", request)
    origin_line = re.search(r"(?im)^Origin:\s*([^\r\n]+)", request)
    return (
        host_line is not None
        and host_line.group(1).strip().lower() in {"pfis.test", "pfis.test:443"}
        and origin_line is not None
        and origin_line.group(1).strip() == REGISTERED_ORIGIN
    )


def _response_status_code(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    response = str(message.get("responseHeader", ""))
    match = re.search(r"(?im)^HTTP/\S+\s+([0-9]{3})\b", response)
    return match.group(1) if match else ""


def _latest_message(zap: Any, target: str) -> list[dict[str, Any]]:
    try:
        message_count = int(zap.core.number_of_messages(target))
    except (TypeError, ValueError):
        return []
    if message_count < 1:
        return []
    messages = zap.core.messages(target, message_count - 1, 1)
    return messages if isinstance(messages, list) else []
