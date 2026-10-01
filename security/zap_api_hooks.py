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
    if state not in HOOK_STATES and not re.fullmatch(
        r"csrf_(?:denial|validation)_status_[0-9]{3}_observed[01]_auth[01]_session[01]_cookie[01]_token[01]_origin[01]_host[01]_path[01]",
        state,
    ):
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

    denial_response = zap.core.send_request(denial_probe, followredirects=False)
    _record_hook_state("csrf_probe_sent")
    messages = _latest_message(zap, REGISTERED_ORIGIN)
    status_code = _response_status_code(denial_response)
    if status_code != "403" and not _has_csrf_probe_status(messages, 403):
        _record_probe_failure("denial", messages, status_code, denial_probe)
        raise RuntimeError("PFIS did not reject the CSRF probe without its CSRF cookie")
    _record_hook_state("csrf_denial_verified")

    accepted_response = zap.core.send_request(accepted_probe, followredirects=False)
    _record_hook_state("csrf_probe_sent")
    messages = _latest_message(zap, REGISTERED_ORIGIN)
    status_code = _response_status_code(accepted_response)
    if status_code != "422" and not _has_csrf_probe_status(messages, 422):
        _record_probe_failure("validation", messages, status_code, accepted_probe)
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
        f"POST {REGISTERED_ORIGIN}{CSRF_PROBE_PATH} HTTP/1.1\r\n"
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
        response = str(message.get("responseHeader", ""))
        request_line = request.splitlines()[0] if request else ""
        request_parts = request_line.split()
        cookies: dict[str, str] = {}
        if len(request_parts) == 3 and request_parts[0] in {"GET", "POST", "PATCH", "PUT"}:
            cookie_line = re.search(r"(?im)^Cookie:\s*([^\r\n]+)", request)
            if cookie_line is not None:
                cookies.update(_parse_cookie_header(cookie_line.group(1)))
        for name, value in re.findall(
            r"(?im)^Set-Cookie:\s*(__Host-pfis-(?:session|csrf))=([^;\r\n]*)", response
        ):
            cookies[name] = value
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


def _record_probe_failure(
    phase: str,
    messages: list[dict[str, Any]],
    status_code: str = "",
    sent_request: str = "",
) -> None:
    """Persist only the probe phase, status and bounded request-shape booleans."""
    if phase not in {"denial", "validation"}:
        return
    message = next(
        (item for item in messages if _is_csrf_probe_request(str(item.get("requestHeader", "")))),
        messages[0] if messages else {},
    )
    observed_request = str(message.get("requestHeader", ""))
    observed = _is_csrf_probe_request(observed_request)
    request = observed_request if observed else sent_request
    cookie_line = re.search(r"(?im)^Cookie:\s*([^\r\n]+)", request)
    cookies = _parse_cookie_header(cookie_line.group(1)) if cookie_line else {}
    authorization_present = re.search(r"(?im)^Authorization:", request) is not None
    csrf_header_present = re.search(r"(?im)^X-CSRF-Token:", request) is not None
    status = status_code or _response_status_code(message) or "000"
    flags = (
        int(authorization_present),
        int(SESSION_COOKIE_NAME in cookies),
        int(CSRF_COOKIE_NAME in cookies),
        int(csrf_header_present),
        int("origin" in _headers(request)),
        int("host" in _headers(request)),
        int(_is_csrf_probe_request(request)),
    )
    auth, session, csrf_cookie, token, origin, host, path = flags
    _record_hook_state(
        f"csrf_{phase}_status_{status}_observed{int(observed)}_auth{auth}_session{session}_cookie{csrf_cookie}"
        f"_token{token}_origin{origin}_host{host}_path{path}"
    )


def _headers(request: str) -> dict[str, str]:
    """Parse header names only; values are never retained in diagnostics."""
    result: dict[str, str] = {}
    for line in request.splitlines()[1:]:
        if not line:
            break
        name, separator, _ = line.partition(":")
        if separator:
            result[name.strip().lower()] = ""
    return result


def _response_status_code(message: object) -> str:
    if isinstance(message, dict):
        response = str(message.get("responseHeader", message.get("response", "")))
    elif isinstance(message, str):
        response = message
    else:
        return ""
    matches = re.findall(r"(?im)^HTTP/\S+\s+([0-9]{3})\b", response)
    return matches[-1] if matches else ""


def _latest_message(zap: Any, target: str) -> list[dict[str, Any]]:
    try:
        message_count = int(zap.core.number_of_messages(target))
    except (TypeError, ValueError):
        return []
    if message_count < 1:
        return []
    messages = zap.core.messages(target, message_count - 1, 1)
    return messages if isinstance(messages, list) else []
