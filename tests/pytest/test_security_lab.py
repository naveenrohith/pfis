"""Security controller, scope, parser, and evidence-store regression tests."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from security import zap_api_hooks, zap_passive
from security.assessment import AssessmentCoordinator, ToolCoverage
from security.auth_boundary import (
    BoundaryCheck,
    _findings_for_failed_checks,
    run_auth_boundary_checks,
)
from security.controller import COOKIE_NAME, create_controller
from security.executor import (
    ComposeToolExecutor,
    _is_authentication_failure,
    _is_missing_image_error,
    _safe_process_environment,
)
from security.isolation_probe import run as run_isolation_probe
from security.lab import FEED_SERVICES, LabConfig, LabManager
from security.parsers import (
    ParsedFinding,
    parse_greenbone_xml,
    parse_metasploit_output,
    parse_nmap_xml,
    parse_nuclei_jsonl,
    parse_sqlmap_output,
    parse_testssl_json,
    parse_zap_json,
    sanitize_evidence,
)
from security.process_lock import ProcessLock
from security.registry import PROFILE_TOOL_IDS
from security.scope import ScopeViolation, resolve_targets, resolve_url, validate_redirect
from security.store import SecurityStore
from security.tools import NMAP_SCRIPT_ALLOWLIST, build_tool_command, commands_for_profile
from security.zap_api_hooks import (
    _build_csrf_probe_request,
    _has_csrf_header_mirroring,
    _has_csrf_validation_response,
    _response_status_code,
)
from security.zap_authenticated import (
    ACTIVE_SCAN_OPERATIONS,
    CONTEXT_INCLUDE_REGEX,
    LOGGED_OUT_INDICATOR,
    ZapError,
    _auth_preflight_succeeded,
    _compact_zap_report,
    _filter_openapi_spec,
    _hook_state_diagnostic,
    _java_environment,
    _prepare_scan_policy,
    _prepare_truststore,
    _safe_authentication_state,
    _safe_scan_diagnostic,
)


def test_target_registry_rejects_arbitrary_urls_and_redirects() -> None:
    assert resolve_targets("baseline") == ("pfis-web",)
    with pytest.raises(ScopeViolation):
        resolve_targets("baseline", ["https://example.com"])
    with pytest.raises(ScopeViolation):
        resolve_url("pfis-web", "https://example.com/path")
    with pytest.raises(ScopeViolation):
        resolve_url("pfis-web", "https://user:password@pfis.test/")
    with pytest.raises(ScopeViolation):
        validate_redirect("pfis-web", "https://pfis.test/", "https://example.com/")


def test_zap_informational_risk_maps_to_non_failing_info() -> None:
    raw_report = json.dumps(
        {
            "site": [
                {
                    "@name": "https://pfis.test",
                    "alerts": [
                        {
                            "name": "A Client Error response code was returned by the server",
                            "riskdesc": "Informational",
                            "confidence": "Medium",
                            "instances": [
                                {
                                    "uri": "https://pfis.test/api/accounts",
                                    "method": "GET",
                                    "evidence": "404",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )

    findings = parse_zap_json(
        raw_report,
        target_id="pfis-web",
        allowed_hosts={"pfis.test"},
    )

    assert len(findings) == 1
    assert findings[0].severity == "info"


def test_zap_csrf_hook_is_fixed_to_registered_host_and_sender_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_path = tmp_path / "csrf-header.js"
    script_path.write_text("function sendingRequest() {}", encoding="utf-8")
    monkeypatch.setattr(zap_api_hooks, "CSRF_SCRIPT_PATH", str(script_path))

    class _ScriptApi:
        list_engines = ["ECMAScript : Graal.js"]

        def __init__(self) -> None:
            self.loaded: tuple[object, ...] | None = None
            self.enabled: str | None = None

        def load(self, *args: object) -> None:
            self.loaded = args

        def enable(self, name: str) -> None:
            self.enabled = name

    class _Zap:
        def __init__(self) -> None:
            self.script = _ScriptApi()

    zap = _Zap()
    zap_api_hooks.zap_started(zap, "https://pfis.test/")
    assert zap.script.loaded is not None
    assert zap.script.loaded[:3] == (
        "pfis-lab-csrf-cookie-header",
        "httpsender",
        "Graal.js",
    )
    assert zap.script.enabled == "pfis-lab-csrf-cookie-header"

    profile_path = tmp_path / "pfis-zap-application-openapi.json"
    profile_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(zap_api_hooks, "OPENAPI_PROFILE_PATH", profile_path)
    zap_api_hooks.zap_started(zap, str(profile_path))

    with pytest.raises(RuntimeError, match="unregistered target"):
        zap_api_hooks.zap_started(zap, "https://pfis.test.attacker.invalid/")
    with pytest.raises(RuntimeError, match="unregistered target"):
        zap_api_hooks.zap_started(zap, str(tmp_path / "different-openapi.json"))


def test_zap_csrf_probe_requires_cookie_mirroring_and_validation_response() -> None:
    probe_request = _build_csrf_probe_request(
        "__Host-pfis-session=session-value; __Host-pfis-csrf=csrf-value"
    )
    assert "X-CSRF-Token: csrf-value\r\n" in probe_request

    request = (
        "POST /api/transactions/?user_id=00000000-0000-4000-8000-000000000001 HTTP/1.1\r\n"
        "Host: pfis.test\r\n"
        "Origin: https://pfis.test\r\n"
        "Cookie: __Host-pfis-session=session-value; __Host-pfis-csrf=csrf-value\r\n"
        "X-CSRF-Token: csrf-value\r\n"
    )
    assert _has_csrf_validation_response(
        [{"requestHeader": request, "responseHeader": "HTTP/1.1 422 Unprocessable Entity\r\n"}]
    )
    assert _has_csrf_header_mirroring([{"requestHeader": request}])
    absolute_request = request.replace(
        "POST /api/transactions/", "POST https://pfis.test/api/transactions/"
    )
    assert _has_csrf_validation_response(
        [
            {
                "requestHeader": absolute_request,
                "responseHeader": "HTTP/1.1 422 Unprocessable Entity\r\n",
            }
        ]
    )
    assert not _has_csrf_validation_response(
        [
            {
                "requestHeader": absolute_request.replace(
                    "https://pfis.test/", "https://other.invalid/"
                ),
                "responseHeader": "HTTP/1.1 422 Unprocessable Entity\r\n",
            }
        ]
    )
    assert not _has_csrf_validation_response(
        [
            {
                "requestHeader": absolute_request.replace(
                    "Origin: https://pfis.test", "Origin: https://other.invalid"
                ),
                "responseHeader": "HTTP/1.1 422 Unprocessable Entity\r\n",
            }
        ]
    )
    assert not _has_csrf_validation_response(
        [{"requestHeader": request, "responseHeader": "HTTP/1.1 403 Forbidden\r\n"}]
    )
    assert not _has_csrf_validation_response(
        [
            {
                "requestHeader": request.replace(
                    "X-CSRF-Token: csrf-value", "X-CSRF-Token: different-token"
                ),
                "responseHeader": "HTTP/1.1 422 Unprocessable Entity\r\n",
            }
        ]
    )
    assert not _has_csrf_header_mirroring(
        [{"requestHeader": request.replace("X-CSRF-Token: csrf-value", "X-CSRF-Token: other")}]
    )
    with pytest.raises(RuntimeError, match="valid PFIS CSRF cookie"):
        _build_csrf_probe_request("__Host-pfis-session=session-value")
    assert (
        _response_status_code({"responseHeader": "HTTP/1.1 422 Unprocessable Entity\r\n"}) == "422"
    )
    assert _response_status_code({"responseHeader": "not-an-http-response"}) == ""


def test_zap_pre_shutdown_reads_the_latest_csrf_probe_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook_state = tmp_path / "hook-state.txt"
    monkeypatch.setattr(zap_api_hooks, "HOOK_STATE_PATH", hook_state)
    scanned_request = (
        "POST /api/transactions/ HTTP/1.1\r\n"
        "Host: pfis.test\r\n"
        "Origin: https://pfis.test\r\n"
        "Cookie: __Host-pfis-session=session-value; __Host-pfis-csrf=csrf-value\r\n"
        "X-CSRF-Token: csrf-value\r\n"
    )
    probe_message: dict[str, str] = {}

    class _CoreApi:
        def messages(self, _target: str, start: int, count: int) -> list[dict[str, str]]:
            if start == 9_001:
                assert count == 1_000
                return [{"requestHeader": scanned_request}]
            if start == 20_001:
                assert count == 1
                return [probe_message]
            assert count == 1_000
            assert start >= 10_001
            return []

        def number_of_messages(self, _target: str) -> int:
            return 20_002 if probe_message else 20_001

        def send_request(self, request: str, *, followredirects: bool) -> str:
            assert followredirects is False
            assert "X-CSRF-Token: csrf-value\r\n" in request
            probe_message.update(
                {
                    "requestHeader": request,
                    "responseHeader": "HTTP/1.1 422 Unprocessable Entity\r\n",
                }
            )
            return "request and response text"

    class _Zap:
        core = _CoreApi()

    zap_api_hooks.zap_pre_shutdown(_Zap())
    assert hook_state.read_text(encoding="ascii") == "csrf_validation_verified"


def test_zap_authenticated_scan_cookie_header_distinguishes_missing_mirroring() -> None:
    scanned_request = (
        "POST /api/transactions/ HTTP/1.1\r\n"
        "Host: pfis.test\r\n"
        "Origin: https://pfis.test\r\n"
        "Cookie: __Host-pfis-session=session-value; __Host-pfis-csrf=csrf-value\r\n"
    )

    class _CoreApi:
        def number_of_messages(self, _target: str) -> int:
            return 1

        def messages(self, _target: str, _start: int, _count: int) -> list[dict[str, str]]:
            return [{"requestHeader": scanned_request}]

    class _Zap:
        core = _CoreApi()

    with pytest.raises(zap_api_hooks.ZapHookEvidenceError) as error:
        zap_api_hooks._authenticated_scan_cookie_header(_Zap())
    assert error.value.state == "csrf_sender_missing"


def test_scanner_commands_are_registry_bound_and_nmap_scripts_allowlisted() -> None:
    nmap = build_tool_command("nmap", "pfis-web", "baseline")
    assert "--script" in nmap.argv
    assert nmap.argv[nmap.argv.index("--script") + 1].split(",") == list(NMAP_SCRIPT_ALLOWLIST)
    assert all(";" not in argument and "|" not in argument for argument in nmap.argv)
    assert {command.tool_id for command in commands_for_profile("baseline")} == {
        "nmap",
        "testssl",
        "zap",
        "nuclei",
    }
    tls = build_tool_command("testssl", "pfis-web", "baseline")
    assert tls.argv == ("pfis.test:443",)
    assert tls.timeout_seconds == 300
    api_zap = build_tool_command("zap", "pfis-web", "application")
    assert api_zap.service == "zap-api"
    assert api_zap.timeout_seconds == 2_100
    assert api_zap.argv == ("authenticated-api", "--target-id", "pfis-web")
    passive = commands_for_profile("passive")
    assert len(passive) == 1
    assert passive[0].tool_id == "zap"
    assert passive[0].service == "zap"
    with pytest.raises(ValueError):
        build_tool_command("nmap", "https://example.com", "baseline")
    with pytest.raises(ValueError):
        build_tool_command("sqlmap", "pfis-web", "exploit-validation")
    with pytest.raises(ValueError):
        build_tool_command("metasploit", "pfis-web", "exploit-validation")
    assert "auth-boundary" in PROFILE_TOOL_IDS["application"]
    frontend = commands_for_profile("frontend")
    assert len(frontend) == 1
    assert frontend[0].tool_id == "zap"
    assert frontend[0].service == "zap"
    assert frontend[0].argv == ("frontend", "--target-id", "pfis-web")
    assert frontend[0] in commands_for_profile("full")
    sqlmap = build_tool_command("sqlmap", "sqli-fixture", "exploit-validation")
    assert "--delay=0.2" in sqlmap.argv
    metasploit = build_tool_command("metasploit", "metasploit-fixture", "exploit-validation")
    assert metasploit.argv[:3] == ("./msfconsole", "-q", "-x")
    assert "metasploit-fixture" in metasploit.argv[3]


def test_zap_report_projection_discards_raw_requests_and_bounds_evidence() -> None:
    projected = _compact_zap_report(
        {
            "site": [
                {
                    "@name": "https://pfis.test",
                    "alerts": [
                        {
                            "name": "Example finding",
                            "riskdesc": "High (3)",
                            "requestHeader": "Authorization: synthetic-secret",
                            "instances": [
                                {
                                    "uri": "https://pfis.test/api/records",
                                    "method": "GET",
                                    "evidence": "E" * 700,
                                    "attack": "A" * 700,
                                    "requestHeader": "Cookie: session-secret",
                                    "responseBody": "financial-data",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    serialized = json.dumps(projected)
    assert "Authorization" not in serialized
    assert "Cookie" not in serialized
    assert "session-secret" not in serialized
    instance = projected["site"][0]["alerts"][0]["instances"][0]
    assert len(instance["evidence"]) == 512
    assert len(instance["attack"]) == 512


def test_authenticated_zap_openapi_profile_is_fixed_and_pinned_to_the_lab() -> None:
    document = {
        "openapi": "3.1.0",
        "info": {"title": "PFIS", "version": "1"},
        "servers": [{"url": "https://external.invalid"}],
        "components": {"schemas": {}},
        "paths": {
            path: {
                method: {
                    "responses": {"200": {"description": "OK"}},
                    "servers": [{"url": "https://external.invalid"}],
                }
                for method in methods
            }
            for path, methods in ACTIVE_SCAN_OPERATIONS.items()
        }
        | {"/api/unreviewed": {"get": {"responses": {}}}},
    }

    profile = _filter_openapi_spec(document)

    assert profile["servers"] == [{"url": "https://pfis.test"}]
    assert set(profile["paths"]) == set(ACTIVE_SCAN_OPERATIONS)
    for path, methods in ACTIVE_SCAN_OPERATIONS.items():
        operation = profile["paths"][path]
        assert set(operation) == set(methods)
        assert all("servers" not in operation[method] for method in methods)


def test_authenticated_zap_rejects_external_openapi_refs_and_missing_operations() -> None:
    document = {
        "openapi": "3.1.0",
        "info": {"title": "PFIS", "version": "1"},
        "components": {"schemas": {"Bad": {"$ref": "https://example.invalid/schema"}}},
        "paths": {},
    }
    with pytest.raises(ZapError, match="external references"):
        _filter_openapi_spec(document)

    document["components"] = {"schemas": {}}
    with pytest.raises(ZapError, match="required PFIS application scan path"):
        _filter_openapi_spec(document)


def test_auth_boundary_failures_are_high_findings_without_response_data() -> None:
    checks = [BoundaryCheck("member-private-record-isolation", "failed", "/api/transactions/")]
    findings = _findings_for_failed_checks(checks)
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].target_id == "pfis-web"
    assert "member-private-record-isolation" in findings[0].evidence
    assert "owner@pfis.example.com" not in findings[0].evidence


def test_zap_failure_diagnostic_keeps_exception_class_and_discards_response_data() -> None:
    diagnostic = _safe_scan_diagnostic(
        "Traceback (most recent call last):\n"
        "Caused by: java.nio.file.AccessDeniedException: /tmp/zap-data/context.xml\n"
        "ERROR <class 'zapv2.errors.FileNotFoundError'> owner@pfis.example.com "
        "password=synthetic-secret"
    )
    assert "FileNotFoundError" in diagnostic
    assert "AccessDeniedException: /tmp/zap-data/context.xml" in diagnostic
    assert "owner@pfis.example.com" not in diagnostic
    assert "synthetic-secret" not in diagnostic


def test_scanner_log_mentions_do_not_become_authentication_failures() -> None:
    assert not _is_authentication_failure("Authentication Request Identified; authSuccessful=true")
    assert _is_authentication_failure("HTTP/1.1 401 Unauthorized")
    assert _is_authentication_failure("synthetic PFIS user failed ZAP authentication preflight")


def test_scanner_module_errors_are_not_misreported_as_missing_images() -> None:
    assert not _is_missing_image_error('exec: "msfconsole": executable file not found in $PATH')
    assert not _is_missing_image_error("Exploit module not found")
    assert _is_missing_image_error("Error response from daemon: no such image: example:tag")


def test_zap_hook_diagnostics_accept_only_bounded_safe_stage_markers(tmp_path: Path) -> None:
    marker = tmp_path / "hook-state"
    marker.write_text("graal_engine_verified", encoding="ascii")
    assert _hook_state_diagnostic(marker) == "graal_engine_verified"
    marker.write_text("csrf_token=synthetic-secret", encoding="ascii")
    assert _hook_state_diagnostic(marker) == ""
    marker.write_text("x" * 65, encoding="ascii")
    assert _hook_state_diagnostic(marker) == ""


def test_authenticated_zap_installs_bounded_bundled_scan_policy(tmp_path: Path) -> None:
    source = tmp_path / "image-policy"
    data_directory = tmp_path / "zap-data"
    source.write_text("pinned policy", encoding="utf-8")

    _prepare_scan_policy(source, data_directory)

    destination = data_directory / "policies" / "API-Minimal.policy"
    assert destination.read_text(encoding="utf-8") == "pinned policy"
    with pytest.raises(ZapError, match="could not prepare"):
        _prepare_scan_policy(tmp_path / "missing-policy", data_directory)


def test_zap_authentication_diagnostic_keeps_state_but_discards_responses() -> None:
    diagnostic = _safe_authentication_state(
        {
            "authSuccessful": True,
            "requestBody": "password=synthetic-secret",
            "responseHeader": "HTTP/1.1 200 OK\nSet-Cookie: session-secret",
            "responseBody": "private-session-token",
        },
        {
            "state": "loggedIn",
            "loggedIn": True,
            "token": "private-session-token",
        },
    )
    assert '"state":"loggedIn"' in diagnostic
    assert '"loggedIn":true' in diagnostic
    assert '"authSuccessful":true' in diagnostic
    assert '"login_response_status":"200"' in diagnostic
    assert "synthetic-secret" not in diagnostic
    assert "session-secret" not in diagnostic
    assert "private-session-token" not in diagnostic
    assert _auth_preflight_succeeded({"authSuccessful": True})
    assert _auth_preflight_succeeded({"authSuccessful": "true"})
    assert not _auth_preflight_succeeded({"authSuccessful": False})


def test_zap_logged_out_indicator_matches_only_registered_auth_failures() -> None:
    assert re.search(LOGGED_OUT_INDICATOR, '{"detail":"Authentication required"}')
    assert re.search(LOGGED_OUT_INDICATOR, '{"detail":"Invalid or expired session"}')
    assert not re.search(LOGGED_OUT_INDICATOR, '{"detail":"Invalid transaction"}')


def test_authenticated_zap_context_includes_only_the_registered_pfis_host() -> None:
    assert re.fullmatch(CONTEXT_INCLUDE_REGEX, "https://pfis.test")
    assert re.fullmatch(CONTEXT_INCLUDE_REGEX, "https://pfis.test/")
    assert re.fullmatch(CONTEXT_INCLUDE_REGEX, "https://pfis.test/api/transactions/")
    assert not re.fullmatch(CONTEXT_INCLUDE_REGEX, "https://other.pfis.test/")
    assert not re.fullmatch(CONTEXT_INCLUDE_REGEX, "https://example.com/")
    assert not re.fullmatch(CONTEXT_INCLUDE_REGEX, "http://pfis.test/")


def test_auth_boundary_fixture_generation_mismatch_fails_closed(tmp_path: Path) -> None:
    metadata = tmp_path / ".security-local"
    metadata.mkdir()
    (metadata / "lab-credentials.json").write_text('{"generation":"different"}', encoding="utf-8")
    checks, findings = run_auth_boundary_checks(
        tmp_path,
        https_port=8443,
        ca_path=metadata / "missing-ca.crt",
        expected_generation="expected",
    )
    assert [check.check_id for check in checks] == ["security-regression-fixture-ready"]
    assert findings == []


def test_scanner_executor_suppresses_compose_progress_before_machine_output(
    tmp_path: Path,
) -> None:
    (tmp_path / "security").mkdir()
    (tmp_path / "security" / "lab.compose.yml").write_text("services: {}", encoding="utf-8")
    (tmp_path / ".security-local").mkdir()
    (tmp_path / ".security-local" / "lab.env").write_text("LAB_GENERATION=abc\n", encoding="utf-8")
    executor = ComposeToolExecutor(tmp_path, "abc", "0" * 32, docker_context="desktop-linux")
    command = executor.command("zap", ("passive", "--target-id", "pfis-web"))
    assert command[3:6] == ["compose", "--progress", "quiet"]
    assert command[-4:] == ["zap", "passive", "--target-id", "pfis-web"]


def test_lab_compose_keeps_scanners_and_greenbone_managers_internal() -> None:
    compose = yaml.safe_load(Path("security/lab.compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    networks = compose["networks"]
    assert networks["scanner"]["internal"] is True
    assert networks["app-data"]["internal"] is True
    assert networks["default"]["internal"] is True
    assert networks["operator"].get("internal", False) is False
    assert (
        networks["operator"]["driver_opts"]["com.docker.network.bridge.enable_ip_masquerade"]
        == "false"
    )
    assert networks["feed-egress"].get("internal", False) is False
    assert services["zap-api"]["healthcheck"] == {"disable": True}
    assert "entrypoint" not in services["metasploit"]
    assert services["metasploit"]["command"] == ["./msfconsole", "--version"]
    for service_name, service in services.items():
        attached = service.get("networks", [])
        if isinstance(attached, dict):
            attached = list(attached)
        if service_name in FEED_SERVICES:
            assert "feed-egress" in attached
        else:
            assert "feed-egress" not in attached
    assert set(services["greenbone-control"]["networks"]) == {"default", "scanner"}
    assert set(services["proxy"]["networks"]) == {"app-data", "scanner", "operator"}
    for scanner in (
        "zap",
        "zap-api",
        "nuclei",
        "nmap",
        "testssl",
        "sqlmap",
        "metasploit",
        "isolation-probe",
    ):
        assert services[scanner]["networks"] == ["scanner"]
        assert services[scanner].get("volumes", []) == []
        assert services[scanner].get("read_only") is True
        if scanner in {"zap", "zap-api"}:
            assert services[scanner]["working_dir"] == "/tmp"


def test_isolation_probe_fails_closed_on_host_or_public_connectivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("socket.gethostbyname", lambda _: "192.0.2.1")
    calls = iter(((False, "blocked"), (False, "blocked"), (False, "blocked")))
    monkeypatch.setattr("security.isolation_probe._reachable", lambda *_: next(calls))
    assert run_isolation_probe(45678, 1)["status"] == "passed"

    monkeypatch.setattr("socket.gethostbyname", lambda _: "192.0.2.1")
    calls = iter(((True, "connected"), (False, "blocked"), (False, "blocked")))
    monkeypatch.setattr("security.isolation_probe._reachable", lambda *_: next(calls))
    assert run_isolation_probe(45678, 1)["status"] == "failed"


def test_zap_passive_accepts_warning_exit_only_with_a_valid_bounded_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "zap.json"
    monkeypatch.setattr(zap_passive, "REPORT_FILE", report)
    monkeypatch.setattr(zap_passive.shutil, "which", lambda _: "/zap/zap-baseline.py")
    targets: list[str] = []

    def fake_scan(argv: list[str], **kwargs: object):
        targets.append(argv[argv.index("-t") + 1])
        output_name = Path(argv[argv.index("-J") + 1])
        assert output_name == Path("zap.json")
        output_path = report.parent / output_name
        options = argv[argv.index("-z") + 1]
        assert "-silent" in options
        assert "-Xmx1024m" in options
        assert "-dir /tmp/zap-data" in options
        output_path.write_text('{"site":[]}', encoding="utf-8")
        return type("Completed", (), {"returncode": 2})()

    monkeypatch.setattr(zap_passive.subprocess, "run", fake_scan)
    assert zap_passive.run("pfis-web") == 0
    assert json.loads(capsys.readouterr().out) == {"site": []}
    assert not report.exists()
    assert zap_passive.run("pfis-web", frontend=True) == 0
    assert json.loads(capsys.readouterr().out) == {"site": []}
    assert targets == ["https://pfis.test", "https://pfis.test/dashboard"]
    assert zap_passive.run("https://example.com") == 2


def test_safe_docker_environment_keeps_windows_cli_plugin_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    monkeypatch.setenv("PFIS_TEST_SECRET", "must-not-propagate")
    safe = _safe_process_environment()
    assert (
        next(value for name, value in safe.items() if name.upper() == "PROGRAMFILES")
        == "C:\\Program Files"
    )
    assert "PFIS_TEST_SECRET" not in safe


def test_lab_demo_password_is_random_private_and_demo_route_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = LabManager(tmp_path)
    monkeypatch.setattr(lab, "_validate_docker_context", lambda expected=None: "desktop-linux")
    config = lab.prepare_config()
    assert config.values["LAB_DEMO_PASSWORD"] != "demo12345"
    assert len(config.values["LAB_DEMO_PASSWORD"]) >= 32
    credentials = lab.credentials_file.read_text(encoding="utf-8")
    assert config.values["LAB_DEMO_PASSWORD"] not in credentials
    compose = Path("security/lab.compose.yml").read_text(encoding="utf-8")
    assert "ALLOW_DEMO_LOGIN: 'false'" in compose
    assert "DEMO_USER_PASSWORD: ${LAB_DEMO_PASSWORD" in compose


def test_lab_setting_update_replaces_existing_value_without_duplicate(tmp_path: Path) -> None:
    lab = LabManager(tmp_path)
    lab.metadata.mkdir()
    lab.env_file.write_text("LAB_GENERATION=abc\nOTHER=value\n", encoding="utf-8")

    lab._set_env_value("LAB_CADDY_ROOT_CA_B64", "Y2VydA==")
    lab._set_env_value("LAB_CADDY_ROOT_CA_B64", "bmV3")

    contents = lab.env_file.read_text(encoding="utf-8")
    assert contents.count("LAB_CADDY_ROOT_CA_B64=") == 1
    assert "LAB_CADDY_ROOT_CA_B64=bmV3" in contents
    assert "OTHER=value" in contents


def test_extended_preparation_pins_only_requested_active_scan_tool_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = LabManager(tmp_path)
    lab.metadata.mkdir()
    config = LabConfig("0123456789ab", "desktop-linux", 8443, {})
    calls: list[list[str]] = []
    monkeypatch.setattr(lab, "prepare_config", lambda: config)
    monkeypatch.setattr(lab, "validate_compose", lambda: "")

    def run_compose(args: list[str], **_kwargs: object) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(lab, "run_compose", run_compose)
    monkeypatch.setattr(
        lab, "image_info", lambda image, _config=None: {"image_id": image, "runtime_image": image}
    )
    monkeypatch.setattr(lab, "_git_commit", lambda: "a" * 40)
    monkeypatch.setattr(lab, "_file_sha256", lambda _path: "b" * 64)
    monkeypatch.setattr(
        lab,
        "_prepare_greenbone_feeds",
        lambda _config: (_ for _ in ()).throw(AssertionError("Greenbone feeds are out of scope")),
    )

    lab.prepare_images(extended=True)
    receipt = json.loads((tmp_path / ".security-local" / "image-receipt.json").read_text())

    assert calls == [
        ["pull", "database", "proxy", "nmap"],
        ["build", "app", "sqli-fixture", "nuclei", "zap-api", "isolation-probe", "testssl"],
    ]
    assert set(receipt["images"]) == {"zap", "nuclei", "nmap", "testssl"}
    assert receipt["preparation_mode"] == "extended"
    assert receipt["greenbone_feed_receipt"] is None


def test_authenticated_zap_requires_private_lab_ca_and_builds_temp_truststore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64
    import subprocess

    import security.zap_authenticated as zap_authenticated

    root_ca = tmp_path / "lab-root.crt"
    truststore = tmp_path / "truststore.p12"
    monkeypatch.setattr(zap_authenticated, "ROOT_CA_FILE", root_ca)
    monkeypatch.setattr(zap_authenticated, "TRUSTSTORE_FILE", truststore)
    certificate = b"-----BEGIN CERTIFICATE-----\nZm9v\n-----END CERTIFICATE-----\n"
    monkeypatch.setenv("LAB_CADDY_ROOT_CA_B64", base64.b64encode(certificate).decode("ascii"))
    observed: list[list[str]] = []

    def fake_keytool(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed.append(argv)
        truststore.write_bytes(b"truststore")
        assert kwargs["shell"] is False
        assert kwargs["stdin"] == subprocess.DEVNULL
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(zap_authenticated.subprocess, "run", fake_keytool)
    _prepare_truststore()
    assert root_ca.read_bytes() == certificate
    assert truststore.read_bytes() == b"truststore"
    assert observed[0][0] == "keytool"
    assert "-storetype" in observed[0]
    assert "PKCS12" in observed[0]
    java_environment = _java_environment()
    assert "-Djavax.net.ssl.trustStore=" in java_environment["JAVA_TOOL_OPTIONS"]
    assert "-Xmx1536m" in java_environment["JAVA_TOOL_OPTIONS"]
    assert "connection.httpsAcceptUntrusted" not in java_environment["JAVA_TOOL_OPTIONS"]

    monkeypatch.delenv("LAB_CADDY_ROOT_CA_B64")
    with pytest.raises(ZapError, match="CA is unavailable"):
        _prepare_truststore()


def test_parsers_reject_out_of_scope_hosts_and_store_redacted_evidence(tmp_path: Path) -> None:
    out_of_scope = (
        '{"template-id":"test","matched-at":"https://example.com/",'
        '"info":{"name":"Unexpected","severity":"high"}}'
    )
    with pytest.raises(ValueError, match="out-of-scope"):
        parse_nuclei_jsonl(out_of_scope, target_id="pfis-web", allowed_hosts={"pfis.test"})

    finding = ParsedFinding(
        title="Unexpected token exposure",
        severity="high",
        confidence="high",
        target_id="pfis-web",
        endpoint="https://pfis.test/account",
        tool="zap",
        evidence="Authorization: Bearer abc.def.ghi\npassword=hunter2",
    )
    store = SecurityStore(tmp_path / "security.sqlite3")
    run = store.create_run("a" * 32, "b" * 12, "c" * 40, "baseline")
    store.add_findings(run["id"], [finding])
    evidence = store.list_findings()[0]["evidence"][0]["value"]
    assert "hunter2" not in evidence
    assert "abc.def.ghi" not in evidence


def test_evidence_redaction_handles_quoted_json_and_spaced_secret_values() -> None:
    source = (
        '{"password":"hunter2","access_token":"abc123",'
        '"client_secret": "multi word secret", "csrf-token":"csrf-value"}'
    )
    sanitized = sanitize_evidence(source)
    for secret in ("hunter2", "abc123", "multi word secret", "csrf-value"):
        assert secret not in sanitized
    assert '"password":"[redacted]"' in sanitized


def test_greenbone_cvss_severity_reaches_critical_high_assessment_gate() -> None:
    report = """<get_reports_response><report><results><result>
      <host>pfis.test</host><severity>9.8</severity>
      <nvt><name>Critical sample</name></nvt>
      <description>Bounded synthetic evidence.</description>
    </result></results></report></get_reports_response>"""
    findings = parse_greenbone_xml(report, target_id="pfis-web", allowed_hosts={"pfis.test"})
    assert findings[0].severity == "critical"
    coverage = ToolCoverage(
        tool="greenbone",
        target_id="pfis-web",
        status="completed",
        finding_count=len(findings),
        critical_high_count=sum(finding.severity in {"critical", "high"} for finding in findings),
    )
    assert (
        AssessmentCoordinator._summary("infrastructure", [coverage], "")["critical_high_count"] == 1
    )


def test_nmap_parser_accepts_only_its_inert_doctype() -> None:
    normal = """<?xml version="1.0"?>
<!DOCTYPE nmaprun>
<nmaprun><host><hostnames><hostname name="pfis.test"/></hostnames>
<address addr="192.0.2.1"/><ports><port protocol="tcp" portid="443">
<state state="open"/><service name="https" product="Caddy"/></port></ports>
</host></nmaprun>"""
    findings = parse_nmap_xml(normal, target_id="pfis-web", allowed_hosts={"pfis.test"})
    assert len(findings) == 1
    assert findings[0].endpoint == "tcp://pfis.test:443"

    hostile = normal.replace(
        "<!DOCTYPE nmaprun>",
        '<!DOCTYPE nmaprun [<!ENTITY x SYSTEM "file:///etc/passwd">]>',
    )
    with pytest.raises(ValueError, match="DTD and entity"):
        parse_nmap_xml(hostile, target_id="pfis-web", allowed_hosts={"pfis.test"})


def test_testssl_parser_requires_clean_complete_json_report() -> None:
    report = json.dumps(
        [
            {
                "id": "HSTS",
                "severity": "low",
                "targetHost": "pfis.test",
                "finding": "Missing HSTS",
            }
        ]
    )
    findings = parse_testssl_json(report, target_id="pfis-web", allowed_hosts={"pfis.test"})
    assert len(findings) == 1
    assert findings[0].endpoint == "https://pfis.test"
    assert findings[0].title == "HSTS"

    with pytest.raises(ValueError, match="no complete JSON report"):
        parse_testssl_json('[{"id":', target_id="pfis-web", allowed_hosts={"pfis.test"})
    with pytest.raises(ValueError, match="no complete JSON report"):
        parse_testssl_json(
            report + "\ntestssl.sh human-readable summary",
            target_id="pfis-web",
            allowed_hosts={"pfis.test"},
        )


def test_testssl_contextualizes_only_registered_private_ca_observations() -> None:
    report = json.dumps(
        [
            {
                "id": "cert_chain_of_trust",
                "severity": "critical",
                "targetHost": "pfis.test",
                "ip": "pfis.test/172.20.0.3",
                "finding": "failed (chain incomplete).",
            },
            {
                "id": "TLS_RSA_vulnerability",
                "severity": "critical",
                "targetHost": "pfis.test",
                "finding": "A real TLS issue remains critical.",
            },
        ]
    )
    lab_findings = parse_testssl_json(
        report,
        target_id="pfis-web",
        allowed_hosts={"pfis.test", "172.20.0.3"},
        private_ca=True,
    )
    by_title = {finding.title: finding for finding in lab_findings}
    assert by_title["cert_chain_of_trust"].severity == "info"
    assert "Expected local private-CA observation" in by_title["cert_chain_of_trust"].evidence
    assert by_title["TLS_RSA_vulnerability"].severity == "critical"

    production_findings = parse_testssl_json(
        report,
        target_id="pfis-web",
        allowed_hosts={"pfis.test", "172.20.0.3"},
        private_ca=False,
    )
    assert (
        next(f for f in production_findings if f.title == "cert_chain_of_trust").severity
        == "critical"
    )


def test_findings_deduplicate_across_tools_and_fixture_controls_stay_separate(
    tmp_path: Path,
) -> None:
    store = SecurityStore(tmp_path / "security.sqlite3")
    run = store.create_run("a" * 32, "b" * 12, "c" * 40, "full")
    observations = [
        ParsedFinding(
            "Missing secure cookie flag",
            "medium",
            "high",
            "pfis-web",
            "https://pfis.test/api/login",
            tool,
            f"Observed by {tool}",
        )
        for tool in ("zap", "nuclei")
    ]
    control = parse_sqlmap_output("parameter id appears to be injectable")[0]
    store.add_findings(run["id"], [*observations, control])

    findings = store.list_findings()
    assert len(findings) == 1
    assert {item["tool"] for item in findings[0]["evidence"]} == {"zap", "nuclei"}
    controls = store.list_findings(include_controls=True)
    assert len(controls) == 2
    by_control = {finding["control"]: finding for finding in controls}
    assert set(by_control) == {False, True}


def test_exploit_validators_require_positive_fixture_evidence() -> None:
    assert parse_sqlmap_output("all tested parameters do not appear to be injectable") == []
    assert parse_metasploit_output("Exploit completed, but no session was created.") == []

    sqlmap_control = parse_sqlmap_output("Parameter 'id' appears to be injectable.")[0]
    metasploit_control = parse_metasploit_output("Command shell session 1 opened.")[0]
    assert sqlmap_control.control is True
    assert sqlmap_control.target_id == "sqli-fixture"
    assert metasploit_control.control is True
    assert metasploit_control.target_id == "metasploit-fixture"


def test_assessment_process_lock_and_store_reads_preserve_live_run(tmp_path: Path) -> None:
    lock_path = tmp_path / "assessment.lock"
    first_lock = ProcessLock(lock_path)
    second_lock = ProcessLock(lock_path)
    store_path = tmp_path / "security.sqlite3"
    store = SecurityStore(store_path)
    run = store.create_run("e" * 32, "f" * 12, "a" * 40, "baseline")
    store.set_run_state(run["id"], "running")

    assert first_lock.try_acquire()
    assert not second_lock.try_acquire()
    reopened = SecurityStore(store_path)
    assert reopened.get_run(run["id"])["state"] == "running"

    first_lock.release()
    assert second_lock.try_acquire()
    second_lock.release()
    interrupted = reopened.interrupt_active_runs()
    assert interrupted[0]["state"] == "interrupted"
    assert interrupted[0]["summary"]


class _LabStub:
    def __init__(self, root: Path) -> None:
        self.root = root


def test_controller_requires_host_origin_pairing_csrf_and_attaches_reports(tmp_path: Path) -> None:
    store = SecurityStore(tmp_path / "security.sqlite3")
    app = create_controller(tmp_path, port=43127, store=store, lab=_LabStub(tmp_path))  # type: ignore[arg-type]
    client = TestClient(app, base_url="https://localhost:43127")
    origin = {"Origin": "http://localhost:43127"}

    assert client.get("/security-api/session").status_code == 401
    assert (
        client.get("/security-api/session", headers={"Host": "attacker.test:43127"}).status_code
        == 421
    )
    assert (
        client.post("/security-api/pair", headers=origin, json={"code": "000000"}).status_code
        == 403
    )

    pairing = app.state.pairing
    wrong_code = "999999" if pairing.code != "999999" else "000000"
    assert (
        client.post("/security-api/pair", headers=origin, json={"code": wrong_code}).status_code
        == 403
    )
    response = client.post("/security-api/pair", headers=origin, json={"code": pairing.code})
    assert response.status_code == 200
    assert COOKIE_NAME in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    csrf = response.json()["csrf_token"]
    assert client.get("/security-api/session").status_code == 200

    run = store.create_run("d" * 32, "b" * 12, "c" * 40, "baseline")
    store.set_run_state(run["id"], "running")
    store.set_run_state(run["id"], "completed", summary={"coverage_complete": True})
    report = client.get(f"/security-api/reports/{run['id']}")
    assert report.status_code == 200
    assert report.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in report.headers["content-disposition"]

    coordinator = app.state.security_coordinator
    coordinator._active_run_id = "active-test-run"
    reset = client.post(
        "/security-api/lab/reset",
        headers=origin | {"X-CSRF-Token": csrf},
    )
    assert reset.status_code == 409
    coordinator._active_run_id = None

    assert client.post("/security-api/logout", headers=origin).status_code == 403
    assert (
        client.post("/security-api/logout", headers=origin | {"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert (
        client.post("/security-api/logout", headers=origin | {"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert client.get("/security-api/session").status_code == 401
