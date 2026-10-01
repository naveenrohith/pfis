"""Create an ephemeral ZAP JSON-auth context and scan only the PFIS OpenAPI target."""

from __future__ import annotations

import base64
import binascii
import importlib.util
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import ModuleType

ZAP_API = "http://127.0.0.1:18080/JSON"
TARGET_ID = "pfis-web"
TARGET_URL = "https://pfis.test"
OPENAPI_URL = f"{TARGET_URL}/openapi.json"
OPENAPI_PROFILE_FILE = Path("/tmp/pfis-zap-application-openapi.json")
MAX_OPENAPI_BYTES = 2_000_000
ACTIVE_SCAN_OPERATIONS = {
    "/api/transactions/": ("get", "post"),
    "/api/accounts": ("get",),
    "/api/statements/import/text": ("post",),
    "/api/reports/export/csv": ("get",),
    "/api/gmail/status": ("get",),
}
CONTEXT_INCLUDE_REGEX = r"^https://pfis\.test(?:/.*)?$"
CONTEXT_NAME = "PFIS authenticated API"
LOGGED_OUT_INDICATOR = (
    r'"detail"\s*:\s*"(?:Authentication required|Invalid or expired session|'
    r'Invalid access token|User not found)"'
)
CONTEXT_FILE = Path("/tmp/pfis-zap-context.xml")
REPORT_FILE = Path("/zap/wrk/pfis-zap-report.json")
ZAP_LOG_FILE = Path("/tmp/zap.out")
ZAP_DATA_DIRECTORY = Path("/tmp/zap-data")
HOOK_STATE_FILE = Path("/tmp/pfis-zap-hook-state.txt")
API_MINIMAL_POLICY_SOURCE = Path("/home/zap/.ZAP/policies/API-Minimal.policy")
ROOT_CA_FILE = Path("/tmp/pfis-lab-root.crt")
TRUSTSTORE_FILE = Path("/tmp/pfis-truststore.p12")
TRUSTSTORE_PASSWORD = "changeit"
ZAP_HEAP_SIZE = "1536m"
MAX_RAW_REPORT_BYTES = 64_000_000
MAX_NORMALIZED_REPORT_BYTES = 8_000_000
MAX_ZAP_INSTANCES = 5_000
MAX_ZAP_TEXT_CHARS = 1_024
JAVA_TRUSTSTORE_OPTIONS = (
    f"-Xmx{ZAP_HEAP_SIZE} "
    f"-Djavax.net.ssl.trustStore={TRUSTSTORE_FILE} "
    "-Djavax.net.ssl.trustStoreType=PKCS12 "
    f"-Djavax.net.ssl.trustStorePassword={TRUSTSTORE_PASSWORD}"
)


class ZapError(RuntimeError):
    """An authenticated local ZAP setup or scan failed closed."""


def _prepare_truststore() -> None:
    encoded = os.environ.get("LAB_CADDY_ROOT_CA_B64", "")
    if not encoded or len(encoded) > 22_000:
        raise ZapError("verified lab CA is unavailable to authenticated ZAP")
    try:
        certificate = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ZapError("verified lab CA encoding is invalid") from exc
    if (
        not certificate
        or len(certificate) > 16_384
        or not certificate.startswith(b"-----BEGIN CERTIFICATE-----")
        or b"-----END CERTIFICATE-----" not in certificate
    ):
        raise ZapError("verified lab CA is not a bounded PEM certificate")
    ROOT_CA_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROOT_CA_FILE.write_bytes(certificate)
    ROOT_CA_FILE.chmod(0o600)
    result = subprocess.run(
        [
            "keytool",
            "-importcert",
            "-noprompt",
            "-trustcacerts",
            "-alias",
            "pfis-lab-ca",
            "-file",
            str(ROOT_CA_FILE),
            "-keystore",
            str(TRUSTSTORE_FILE),
            "-storetype",
            "PKCS12",
            "-storepass",
            TRUSTSTORE_PASSWORD,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
        check=False,
        shell=False,
    )
    if result.returncode != 0 or not TRUSTSTORE_FILE.is_file():
        raise ZapError("could not create the authenticated ZAP lab truststore")
    if TRUSTSTORE_FILE.stat().st_size > 65_536:
        raise ZapError("authenticated ZAP lab truststore exceeds its size limit")
    TRUSTSTORE_FILE.chmod(0o600)


def _java_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["JAVA_TOOL_OPTIONS"] = JAVA_TRUSTSTORE_OPTIONS
    return environment


def _prepare_scan_policy(
    source: Path = API_MINIMAL_POLICY_SOURCE,
    data_directory: Path = ZAP_DATA_DIRECTORY,
) -> None:
    """Install the pinned image's API-Minimal policy into the isolated ZAP data dir."""
    try:
        source_info = source.lstat()
        if not stat.S_ISREG(source_info.st_mode) or source_info.st_size > 256_000:
            raise ZapError("bundled ZAP API-Minimal scan policy is unavailable")
        destination = data_directory / "policies" / "API-Minimal.policy"
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o600)
        if destination.stat().st_size != source_info.st_size:
            raise ZapError("temporary ZAP API-Minimal policy copy is incomplete")
    except OSError as exc:
        raise ZapError("could not prepare the bundled ZAP API-Minimal scan policy") from exc


def _has_external_reference(value: object) -> bool:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and not reference.startswith("#/"):
            return True
        return any(_has_external_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_external_reference(item) for item in value)
    return False


def _filter_openapi_spec(document: object) -> dict[str, object]:
    """Keep reviewed PFIS operations and pin all requests to the lab endpoint."""
    if not isinstance(document, dict):
        raise ZapError("PFIS OpenAPI document has an unexpected schema")
    paths = document.get("paths")
    if not isinstance(paths, dict) or _has_external_reference(document):
        raise ZapError("PFIS OpenAPI document has invalid paths or external references")
    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        raise ZapError("PFIS OpenAPI version is unsupported")

    filtered_paths: dict[str, object] = {}
    for path, methods in ACTIVE_SCAN_OPERATIONS.items():
        path_item = paths.get(path)
        if not isinstance(path_item, dict):
            raise ZapError("a required PFIS application scan path is missing")
        filtered_item: dict[str, object] = {}
        path_parameters = path_item.get("parameters")
        if path_parameters is not None:
            filtered_item["parameters"] = path_parameters
        for method in methods:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                raise ZapError("a required PFIS application scan operation is missing")
            # Operation-level servers could override the fixed lab host.
            filtered_item[method] = {
                key: value for key, value in operation.items() if key != "servers"
            }
        filtered_paths[path] = filtered_item

    result: dict[str, object] = {
        key: document[key]
        for key in ("openapi", "info", "components", "security", "tags")
        if key in document
    }
    result["servers"] = [{"url": TARGET_URL}]
    result["paths"] = filtered_paths
    return result


def _prepare_openapi_profile(
    destination: Path = OPENAPI_PROFILE_FILE,
    source_url: str = OPENAPI_URL,
    ca_file: Path = ROOT_CA_FILE,
) -> None:
    """Fetch OpenAPI from the lab and write the bounded registered scan profile."""
    if destination != OPENAPI_PROFILE_FILE or source_url != OPENAPI_URL or not ca_file.is_file():
        raise ZapError("verified PFIS OpenAPI source or lab CA is unavailable")
    try:
        context = ssl.create_default_context(cafile=str(ca_file))
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context), _NoRedirectHandler()
        )
        with opener.open(source_url, timeout=15) as response:
            if response.geturl() != OPENAPI_URL or response.status != 200:
                raise ZapError("PFIS OpenAPI request left the registered HTTPS endpoint")
            raw_document = response.read(MAX_OPENAPI_BYTES + 1)
        if len(raw_document) > MAX_OPENAPI_BYTES:
            raise ZapError("PFIS OpenAPI document exceeded its size limit")
        document = json.loads(raw_document.decode("utf-8"))
        profile = _filter_openapi_spec(document)
        destination.write_text(
            json.dumps(profile, ensure_ascii=True, separators=(",", ":")), encoding="utf-8"
        )
        destination.chmod(0o600)
        if destination.stat().st_size > MAX_OPENAPI_BYTES:
            raise ZapError("filtered PFIS application scan profile exceeded its size limit")
    except ZapError:
        destination.unlink(missing_ok=True)
        raise
    except (
        OSError,
        urllib.error.URLError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        TimeoutError,
    ) as exc:
        destination.unlink(missing_ok=True)
        raise ZapError("could not prepare the bounded PFIS OpenAPI scan profile") from exc


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _safe_scan_diagnostic(output: str) -> str:
    matches = re.findall(
        r"<class '([A-Za-z0-9_.]+)'>|\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception))\b",
        output,
    )
    names = [
        next(value for value in match if value).rsplit(".", maxsplit=1)[-1] for match in matches
    ]
    names = list(dict.fromkeys(names))[-3:]
    exception_details: list[str] = []
    details: list[str] = []
    for line in output.splitlines():
        if not re.search(
            r"(?i)\b(error|warn|fail|exception|ssl|certificate|spider|openapi|"
            r"severe|fatal|authentication|context|scope|api.?exception|bad request|"
            r"not found|not in context|scanAsUser|url_not_found)",
            line,
        ):
            continue
        if "check the log/output for more details" in line.lower():
            continue
        for key in ("LAB_OWNER_EMAIL", "LAB_OWNER_PASSWORD"):
            secret = os.environ.get(key, "")
            if secret:
                line = line.replace(secret, "[redacted]")
        line = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", line)
        if re.search(r"(?i)\b(authorization|cookie|set-cookie|csrf|session)\b", line):
            continue
        line = re.sub(
            r"(?i)(authorization|proxy-authorization|cookie|set-cookie|password|passwd|"
            r"client_secret|access_token|refresh_token|id_token|api[_-]?key|csrf[_-]?token)"
            r"(\s*[=:]\s*)[^\s,;]+",
            r"\1\2[redacted]",
            line,
        )
        line = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", line)
        line = re.sub(
            r"(?i)(https?://[^\s\"'<>]+)",
            lambda match: _safe_diagnostic_url(match.group(1)),
            line,
        )
        safe_line = line.strip()[:240]
        if re.search(
            r"(?i)(?:\b[A-Za-z0-9_.$]*(?:Error|Exception)\s*:|\bCaused by\s*:) ",
            safe_line,
        ):
            exception_details.append(safe_line)
        else:
            details.append(safe_line)
    fragments = names + list(dict.fromkeys(exception_details[-3:] + details[-2:]))
    return "; ".join(fragments)[:700] or "scanner reported an incomplete result"


def _hook_state_diagnostic(path: Path = HOOK_STATE_FILE) -> str:
    """Read the hook's bounded phase marker without exposing requests or credentials."""
    try:
        if path.stat().st_size > 128:
            return ""
        state = path.read_text(encoding="ascii").strip()
    except OSError:
        return ""
    return state if re.fullmatch(r"[a-z_0-9]{1,128}", state) else ""


def _safe_diagnostic_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        if not parsed.hostname:
            return "[redacted-url]"
        host = parsed.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        return urllib.parse.urlunsplit(
            (
                parsed.scheme,
                host + port,
                parsed.path[:256],
                "[redacted]" if parsed.query else "",
                "",
            )
        )
    except ValueError:
        return "[redacted-url]"


def _safe_authentication_state(
    authentication_response: dict[str, object], state_response: dict[str, object]
) -> str:
    """Expose only response shapes and non-secret login-state fields for debugging."""
    auth_payload = authentication_response.get("authenticateAsUser", authentication_response)
    state_payload = state_response.get("getAuthenticationState", state_response)
    if not isinstance(auth_payload, dict):
        auth_payload = {}
    if not isinstance(state_payload, dict):
        state_payload = {}
    auth_successful = auth_payload.get("authSuccessful")
    if isinstance(auth_successful, str) and auth_successful.lower() in {"true", "false"}:
        auth_successful = auth_successful.lower() == "true"
    elif not isinstance(auth_successful, bool):
        auth_successful = None
    safe_state: dict[str, object] = {}
    state = state_payload.get("state")
    if isinstance(state, str) and len(state) <= 32 and re.fullmatch(r"[A-Za-z _-]*", state):
        safe_state["state"] = state
    for key in ("loggedIn", "authenticated", "isLoggedIn", "lastAuthFailure"):
        value = state_payload.get(key)
        if isinstance(value, bool):
            safe_state[key] = value
    last_success = state_payload.get("lastSuccessfulAuthTimeInMs")
    if isinstance(last_success, int) and not isinstance(last_success, bool):
        safe_state["lastSuccessfulAuthTimeInMs"] = last_success
    response_header = auth_payload.get("responseHeader")
    response_status_match = (
        re.search(r"(?m)^HTTP/\S+\s+([0-9]{3})\b", response_header)
        if isinstance(response_header, str)
        else None
    )
    return json.dumps(
        {
            "authSuccessful": auth_successful,
            "state": safe_state,
            "login_response_status": (
                response_status_match.group(1) if response_status_match else None
            ),
        },
        ensure_ascii=True,
        separators=(",", ":"),
    )


def _auth_preflight_succeeded(authentication_response: dict[str, object]) -> bool:
    result = authentication_response.get("authenticateAsUser", authentication_response)
    if not isinstance(result, dict):
        return False
    successful = result.get("authSuccessful")
    return successful is True or (isinstance(successful, str) and successful.lower() == "true")


def _compact_zap_report(document: dict[str, object]) -> dict[str, object]:
    """Keep bounded alert evidence, dropping the scanner's raw requests and responses."""
    source_sites = document.get("site")
    if not isinstance(source_sites, list):
        raise ZapError("authenticated ZAP report has an unexpected schema")
    sites: list[dict[str, object]] = []
    finding_instances = 0
    alert_fields = ("name", "alert", "riskdesc", "confidence", "desc")
    instance_fields = ("uri", "method", "evidence", "attack")
    limits = {"uri": 2_048, "method": 16, "evidence": 512, "attack": 512}
    for source_site in source_sites:
        if not isinstance(source_site, dict):
            continue
        source_alerts = source_site.get("alerts", [])
        if not isinstance(source_alerts, list):
            continue
        alerts: list[dict[str, object]] = []
        for source_alert in source_alerts:
            if not isinstance(source_alert, dict):
                continue
            source_instances = source_alert.get("instances") or [{}]
            if not isinstance(source_instances, list):
                source_instances = [{}]
            instances: list[dict[str, str]] = []
            for source_instance in source_instances:
                if finding_instances >= MAX_ZAP_INSTANCES:
                    raise ZapError("authenticated ZAP report exceeded the finding limit")
                if not isinstance(source_instance, dict):
                    continue
                instance = {
                    key: value[: limits[key]]
                    for key in instance_fields
                    if isinstance((value := source_instance.get(key)), str)
                }
                instances.append(instance)
                finding_instances += 1
            alert: dict[str, object] = {
                key: value[:MAX_ZAP_TEXT_CHARS]
                for key in alert_fields
                if isinstance((value := source_alert.get(key)), str)
            }
            alert["instances"] = instances or [{}]
            alerts.append(alert)
        site: dict[str, object] = {"alerts": alerts}
        site_name = source_site.get("@name")
        if isinstance(site_name, str):
            site["@name"] = site_name[:512]
        sites.append(site)
    return {"site": sites}


def _api(path: str, parameters: dict[str, str] | None = None) -> dict[str, object]:
    if not path.startswith("/") or ".." in path:
        raise ZapError("invalid ZAP API operation")
    url = f"{ZAP_API}{path}"
    body = urllib.parse.urlencode(parameters or {}).encode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read(128_000))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise ZapError("ZAP authentication context setup failed") from exc
    if not isinstance(payload, dict) or "code" in payload:
        raise ZapError("ZAP rejected the registered authentication setup")
    return payload


def _first_nested_list(value: object) -> list[object] | None:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for nested in value.values():
            result = _first_nested_list(nested)
            if result is not None:
                return result
    return None


def _first_nested_count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    if isinstance(value, dict):
        for nested in value.values():
            result = _first_nested_count(nested)
            if result is not None:
                return result
    return None


def _first_http_response(value: object) -> str:
    if isinstance(value, str):
        return value if re.search(r"(?im)^HTTP/\S+\s+[0-9]{3}\b", value) else ""
    if isinstance(value, dict):
        preferred = value.get("response")
        if isinstance(preferred, str) and re.search(r"(?im)^HTTP/\S+\s+[0-9]{3}\b", preferred):
            return preferred
        for nested in value.values():
            result = _first_http_response(nested)
            if result:
                return result
    elif isinstance(value, list):
        for nested in value:
            result = _first_http_response(nested)
            if result:
                return result
    return ""


class _ZapScriptAPI:
    @property
    def list_engines(self) -> list[object]:
        engines = _first_nested_list(_api("/script/view/listEngines/"))
        if engines is None:
            raise ZapError("ZAP did not return its registered script engines")
        return engines

    def load(
        self,
        name: str,
        script_type: str,
        engine: str,
        filename: str,
        description: str,
    ) -> None:
        _api(
            "/script/action/load/",
            {
                "scriptName": name,
                "scriptType": script_type,
                "scriptEngine": engine,
                "fileName": filename,
                "scriptDescription": description,
            },
        )

    def enable(self, name: str) -> None:
        _api("/script/action/enable/", {"scriptName": name})


class _ZapCoreAPI:
    def messages(self, baseurl: str, start: int, count: int) -> list[dict[str, object]]:
        payload = _api(
            "/core/view/messages/",
            {"baseurl": baseurl, "start": str(start), "count": str(count)},
        )
        messages = _first_nested_list(payload)
        if messages is None:
            return []
        return [message for message in messages if isinstance(message, dict)]

    def number_of_messages(self, baseurl: str) -> int:
        payload = _api("/core/view/numberOfMessages/", {"baseurl": baseurl})
        count = _first_nested_count(payload)
        return count if count is not None else 0

    def send_request(self, request: str, *, followredirects: bool) -> str:
        payload = _api(
            "/core/action/sendRequest/",
            {"request": request, "followRedirects": str(followredirects).lower()},
        )
        return _first_http_response(payload)


class _ZapAPIFacade:
    def __init__(self) -> None:
        self.script = _ZapScriptAPI()
        self.core = _ZapCoreAPI()


def _run_csrf_probe_only() -> int:
    hook_path = Path("/opt/pfis/zap_api_hooks.py")
    spec = importlib.util.spec_from_file_location("pfis_lab_zap_api_hooks", hook_path)
    if spec is None or spec.loader is None:
        raise ZapError("registered PFIS ZAP CSRF hook is unavailable")
    hooks: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hooks)
    zap = _ZapAPIFacade()
    try:
        hooks.zap_started(zap, TARGET_URL)
        hooks.zap_pre_shutdown(zap)
    except RuntimeError as exc:
        hook_state = _hook_state_diagnostic()
        suffix = f"; hook_state={hook_state}" if hook_state else ""
        raise ZapError(f"registered PFIS CSRF probe failed{suffix}") from exc
    sys.stdout.write(
        json.dumps(
            {
                "status": "completed",
                "coverage_complete": True,
                "checks": ["cookie-omission-rejected", "csrf-cookie-mirrored-by-zap"],
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


def _start_daemon() -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [
            "/zap/zap.sh",
            "-daemon",
            "-silent",
            "-host",
            "127.0.0.1",
            "-port",
            "18080",
            "-dir",
            str(ZAP_DATA_DIRECTORY),
            f"-Xmx{ZAP_HEAP_SIZE}",
            "-config",
            "api.disablekey=true",
            "-config",
            "autoupdate.checkOnStart=false",
            "-config",
            "autoupdate.installAddonUpdates=false",
            "-config",
            "autoupdate.downloadNewRelease=false",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_java_environment(),
        shell=False,
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ZapError("ZAP bootstrap process stopped before readiness")
        try:
            _api("/core/view/version/")
            return process
        except ZapError:
            time.sleep(1)
    process.terminate()
    raise ZapError("ZAP bootstrap process did not become ready")


def _configure_authenticated_context() -> str:
    username = os.environ.get("LAB_OWNER_EMAIL", "")
    password = os.environ.get("LAB_OWNER_PASSWORD", "")
    if not username or len(password) < 24 or any(char in password for char in "\r\n"):
        raise ZapError("generated synthetic ZAP credentials are unavailable")
    context_response = _api("/context/action/newContext/", {"contextName": CONTEXT_NAME})
    context_id = str(context_response.get("contextId", ""))
    if not context_id.isdigit():
        raise ZapError("ZAP did not create the registered PFIS context")
    _api(
        "/context/action/includeInContext/",
        {"contextName": CONTEXT_NAME, "regex": CONTEXT_INCLUDE_REGEX},
    )
    _api("/ascan/action/setOptionDelayInMs/", {"Integer": "200"})
    _api("/ascan/action/setOptionThreadPerHost/", {"Integer": "1"})
    auth_configuration = urllib.parse.urlencode(
        {
            "loginUrl": f"{TARGET_URL}/api/auth/login",
            "loginRequestData": json.dumps(
                {"email": "{%username%}", "password": "{%password%}"},
                separators=(",", ":"),
            ),
            "loginRequestHeaders": "Content-Type: application/json",
        }
    )
    _api(
        "/authentication/action/setAuthenticationMethod/",
        {
            "contextId": context_id,
            "authMethodName": "jsonBasedAuthentication",
            "authMethodConfigParams": auth_configuration,
        },
    )
    _api(
        "/sessionManagement/action/setSessionManagementMethod/",
        {
            "contextId": context_id,
            "methodName": "cookieBasedSessionManagement",
            "methodConfigParams": "",
        },
    )
    _api(
        "/authentication/action/setLoggedOutIndicator/",
        {"contextId": context_id, "loggedOutIndicatorRegex": LOGGED_OUT_INDICATOR},
    )
    user = _api("/users/action/newUser/", {"contextId": context_id, "name": "pfis-owner"})
    user_id = str(user.get("userId", ""))
    if not user_id.isdigit():
        raise ZapError("ZAP did not register the synthetic PFIS user")
    credentials = urllib.parse.urlencode({"username": username, "password": password})
    _api(
        "/users/action/setAuthenticationCredentials/",
        {
            "contextId": context_id,
            "userId": user_id,
            "authCredentialsConfigParams": credentials,
        },
    )
    _api(
        "/users/action/setUserEnabled/",
        {"contextId": context_id, "userId": user_id, "enabled": "true"},
    )
    authentication_response = _api(
        "/users/action/authenticateAsUser/",
        {"contextId": context_id, "userId": user_id},
    )
    authentication_state = _api(
        "/users/view/getAuthenticationState/",
        {"contextId": context_id, "userId": user_id},
    )
    preflight_diagnostic = (
        "PFIS ZAP synthetic authentication preflight: "
        + _safe_authentication_state(authentication_response, authentication_state)
    )
    if not _auth_preflight_succeeded(authentication_response):
        raise ZapError(
            "synthetic PFIS user failed ZAP authentication preflight; " + preflight_diagnostic
        )
    exported = _api(
        "/context/action/exportContext/",
        {"contextName": CONTEXT_NAME, "contextFile": str(CONTEXT_FILE)},
    )
    if exported.get("Result") not in {"OK", "Context exported"} or not CONTEXT_FILE.is_file():
        raise ZapError("ZAP could not export the ephemeral synthetic-user context")
    if CONTEXT_FILE.stat().st_size > 64_000:
        raise ZapError("ZAP exported an unexpectedly large context")
    CONTEXT_FILE.chmod(0o600)
    return preflight_diagnostic


def _stop_daemon(process: subprocess.Popen[bytes]) -> None:
    try:
        _api("/core/action/shutdown/")
    except ZapError:
        process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_scan(preflight_diagnostic: str) -> int:
    if (
        not OPENAPI_PROFILE_FILE.is_file()
        or OPENAPI_PROFILE_FILE.stat().st_size > MAX_OPENAPI_BYTES
    ):
        raise ZapError("bounded PFIS OpenAPI scan profile is unavailable")
    scan = subprocess.run(
        [
            "zap-api-scan.py",
            "-t",
            str(OPENAPI_PROFILE_FILE),
            "-f",
            "openapi",
            "-n",
            str(CONTEXT_FILE),
            "-U",
            "pfis-owner",
            "--hook",
            "/opt/pfis/zap_api_hooks.py",
            "-J",
            REPORT_FILE.name,
            "-T",
            "180",
            "-I",
            "-z",
            f"-Xmx{ZAP_HEAP_SIZE} -silent -dir {ZAP_DATA_DIRECTORY} "
            "-config autoupdate.checkOnStart=false -config autoupdate.installAddonUpdates=false "
            "-config autoupdate.downloadNewRelease=false",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_java_environment(),
        timeout=1_800,
        check=False,
        shell=False,
    )
    if scan.returncode not in {0, 1, 2}:
        output = (scan.stdout or b"").decode("utf-8", errors="replace")
        if ZAP_LOG_FILE.is_file() and ZAP_LOG_FILE.stat().st_size <= 2_000_000:
            output += "\n" + ZAP_LOG_FILE.read_text(encoding="utf-8", errors="replace")
        for name in ("LAB_OWNER_EMAIL", "LAB_OWNER_PASSWORD"):
            secret = os.environ.get(name, "")
            if secret:
                output = output.replace(secret, "[redacted]")
        diagnostic = _safe_scan_diagnostic(output)
        hook_state = _hook_state_diagnostic()
        if hook_state:
            diagnostic = f"{diagnostic}; hook_state={hook_state}"
        suffix = f"; {diagnostic}; {preflight_diagnostic}" if diagnostic else ""
        raise ZapError(f"authenticated ZAP API scan exited with code {scan.returncode}{suffix}")
    if len(scan.stdout or b"") > MAX_NORMALIZED_REPORT_BYTES:
        raise ZapError("authenticated ZAP API scan output exceeded its size limit")
    if not REPORT_FILE.is_file():
        raise ZapError("authenticated ZAP report is missing")
    if REPORT_FILE.stat().st_size > MAX_RAW_REPORT_BYTES:
        raise ZapError("authenticated ZAP report exceeded the raw report size limit")
    raw_report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw_report, dict):
        raise ZapError("authenticated ZAP report has an unexpected schema")
    report = _compact_zap_report(raw_report)
    normalized_report = json.dumps(report, ensure_ascii=True, separators=(",", ":"))
    if len(normalized_report.encode("utf-8")) > MAX_NORMALIZED_REPORT_BYTES:
        raise ZapError("authenticated ZAP findings exceeded the normalized report size limit")
    sys.stdout.write(normalized_report)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    arguments = sys.argv[1:]
    normal_command = ["authenticated-api", "--target-id", TARGET_ID]
    probe_command = ["csrf-probe", "--target-id", TARGET_ID]
    if arguments not in (normal_command, probe_command):
        print("ZAP accepts only fixed PFIS application or CSRF probe profiles.", file=sys.stderr)
        return 2
    probe_only = arguments == probe_command
    context_path = re.compile(r"^/tmp/pfis-zap-context\.xml$")
    if not context_path.fullmatch(str(CONTEXT_FILE)):
        return 2
    daemon: subprocess.Popen[bytes] | None = None
    try:
        _prepare_truststore()
        if not probe_only:
            _prepare_scan_policy()
            _prepare_openapi_profile()
        daemon = _start_daemon()
        preflight_diagnostic = _configure_authenticated_context()
        if probe_only:
            return _run_csrf_probe_only()
        _stop_daemon(daemon)
        daemon = None
        return _run_scan(preflight_diagnostic)
    except (
        ZapError,
        OSError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
        TimeoutError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if daemon is not None:
            _stop_daemon(daemon)
        HOOK_STATE_FILE.unlink(missing_ok=True)
        CONTEXT_FILE.unlink(missing_ok=True)
        REPORT_FILE.unlink(missing_ok=True)
        OPENAPI_PROFILE_FILE.unlink(missing_ok=True)
        ZAP_LOG_FILE.unlink(missing_ok=True)
        ROOT_CA_FILE.unlink(missing_ok=True)
        TRUSTSTORE_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
