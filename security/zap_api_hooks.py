"""Fixed ZAP API scan hooks for PFIS's cookie-bound CSRF contract."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REGISTERED_ORIGIN = "https://pfis.test"
CSRF_SCRIPT_NAME = "pfis-lab-csrf-cookie-header"
CSRF_SCRIPT_PATH = "/opt/pfis/zap_csrf_cookie_header.js"
CSRF_COOKIE_NAME = "__Host-pfis-csrf"
SESSION_COOKIE_NAME = "__Host-pfis-session"
CSRF_PROBE_PATH = "/api/transactions/?user_id=00000000-0000-4000-8000-000000000001"


def zap_started(zap: Any, target: str) -> None:
    """Load the reviewed sender script into only the fixed PFIS scan target."""
    parsed = urlsplit(target)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "pfis.test"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError("PFIS CSRF sender hook received an unregistered target")
    if not Path(CSRF_SCRIPT_PATH).is_file():
        raise RuntimeError("the pinned PFIS CSRF sender script is missing")
    engines = zap.script.list_engines
    if not any(str(engine).endswith(" : Graal.js") for engine in engines):
        raise RuntimeError("the pinned ZAP image does not provide the Graal.js engine")
    zap.script.load(
        CSRF_SCRIPT_NAME,
        "httpsender",
        "Graal.js",
        CSRF_SCRIPT_PATH,
        "Copies the registered PFIS CSRF cookie into the request header.",
    )
    zap.script.enable(CSRF_SCRIPT_NAME)


def zap_pre_shutdown(zap: Any) -> None:
    """Prove an in-scope cookie mutation passes CSRF and reaches validation."""
    messages = zap.core.messages(REGISTERED_ORIGIN, 0, 10_000)
    cookie_header = _authenticated_cookie_header(messages)
    request = (
        f"POST {CSRF_PROBE_PATH} HTTP/1.1\r\n"
        "Host: pfis.test\r\n"
        f"Origin: {REGISTERED_ORIGIN}\r\n"
        "Content-Type: application/json\r\n"
        f"Cookie: {cookie_header}\r\n"
        "Content-Length: 2\r\n"
        "Connection: close\r\n\r\n{}"
    )
    zap.core.send_request(request, followredirects=False)
    messages = zap.core.messages(REGISTERED_ORIGIN, 0, 10_000)
    if not _has_csrf_validation_response(messages):
        raise RuntimeError("authenticated ZAP did not pass its CSRF probe to PFIS validation")


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


def _has_csrf_validation_response(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        request = str(message.get("requestHeader", ""))
        if not request.startswith(f"POST {CSRF_PROBE_PATH} "):
            continue
        cookie_line = re.search(r"(?im)^Cookie:\s*([^\r\n]+)", request)
        token_line = re.search(r"(?im)^X-CSRF-Token:\s*([^\r\n]+)", request)
        if cookie_line is None or token_line is None:
            continue
        cookies = _parse_cookie_header(cookie_line.group(1))
        if cookies.get(CSRF_COOKIE_NAME) != token_line.group(1).strip():
            continue
        response = str(message.get("responseHeader", ""))
        if re.search(r"(?m)^HTTP/\S+\s+422\b", response):
            return True
    return False
