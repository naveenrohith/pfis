"""Serial assessment orchestration with explicit per-tool coverage states."""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from security.auth_boundary import run_auth_boundary_checks
from security.executor import ComposeToolExecutor, ProcessOutcome
from security.lab import LabManager
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
from security.registry import PROFILE_TARGETS, PROFILE_TOOL_IDS, TARGETS, TOOLS
from security.scope import ScopeViolation, resolve_targets
from security.store import SecurityStore
from security.tools import commands_for_profile


@dataclass(frozen=True)
class ToolCoverage:
    tool: str
    target_id: str
    status: str
    finding_count: int = 0
    critical_high_count: int = 0
    duration_seconds: float = 0
    detail: str = ""


class AssessmentCoordinator:
    def __init__(self, root: Path, store: SecurityStore, lab: LabManager) -> None:
        self.root = root.resolve()
        self.store = store
        self.lab = lab
        self._lock = threading.RLock()
        self._active_run_id: str | None = None
        self._cancel_event: threading.Event | None = None
        self._executor: ComposeToolExecutor | None = None
        self._thread: threading.Thread | None = None
        self._maintenance = False
        self._run_lock = ProcessLock(self.root / ".security-local" / "assessment.lock")
        self._recover()

    def enqueue(self, profile_id: str, target_ids: list[str] | None = None) -> dict[str, Any]:
        try:
            expected_targets = resolve_targets(profile_id, target_ids)
        except ScopeViolation as exc:
            raise ValueError(str(exc)) from exc
        # Resolve all arguments before placing work in the queue. There is no
        # user-supplied target URL, module, script, template, or Docker option.
        commands_for_profile(profile_id)
        with self._lock:
            if self._maintenance:
                raise RuntimeError("lab maintenance is in progress")
            if self._active_run_id is not None:
                raise RuntimeError("an assessment is already running")
            if not self._run_lock.try_acquire():
                raise RuntimeError("an assessment is already running in another process")
            try:
                lab_state = self.lab.verify_network_isolation(required_targets=expected_targets)
                generation = str(lab_state["generation"])
                commit = self._branch_commit()
                run_id = secrets.token_hex(16)
                record = self.store.create_run(run_id, generation, commit, profile_id)
                cancel_event = threading.Event()
                executor = ComposeToolExecutor(
                    self.root,
                    generation,
                    run_id,
                    docker_context=self.lab.config().docker_context,
                )
                self._active_run_id = run_id
                self._cancel_event = cancel_event
                self._executor = executor
                self._thread = threading.Thread(
                    target=self._execute,
                    args=(run_id, profile_id, expected_targets, executor, cancel_event),
                    name=f"pfis-security-{run_id[:8]}",
                    daemon=True,
                )
                self._thread.start()
            except BaseException:
                self._run_lock.release()
                raise
        return record

    def cancel(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            if self._active_run_id != run_id or self._cancel_event is None:
                record = self.store.get_run(run_id)
                if record is None:
                    raise KeyError("assessment run was not found")
                if record["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                    return record
                return self.store.request_cancel(run_id)
            self.store.request_cancel(run_id)
            self._cancel_event.set()
            if self._executor:
                self._executor.cancel()
        return self.store.get_run(run_id) or {}

    def active_run_id(self) -> str | None:
        with self._lock:
            return self._active_run_id

    @contextmanager
    def lab_maintenance(self) -> Iterator[None]:
        """Exclude assessment starts while a reset changes the disposable lab."""
        with self._lock:
            if self._maintenance or self._active_run_id is not None:
                raise RuntimeError("lab reset requires the assessment queue to be idle")
            if not self._run_lock.try_acquire():
                raise RuntimeError("lab reset is blocked by an assessment in another process")
            self._maintenance = True
        try:
            yield
        finally:
            with self._lock:
                self._maintenance = False
                self._run_lock.release()

    def wait(self, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _execute(
        self,
        run_id: str,
        profile_id: str,
        target_ids: tuple[str, ...],
        executor: ComposeToolExecutor,
        cancel: threading.Event,
    ) -> None:
        coverage: list[ToolCoverage] = []
        overall_state = "completed"
        stop_reason = ""
        monitor_stop = threading.Event()
        cancel_monitor = threading.Thread(
            target=self._watch_cancel,
            args=(run_id, cancel, monitor_stop, executor),
            name=f"pfis-security-cancel-{run_id[:8]}",
            daemon=True,
        )
        cancel_monitor.start()
        try:
            self.store.set_run_state(run_id, "running")
            commands = commands_for_profile(profile_id)
            if profile_id in {"application", "full"}:
                config = self.lab.config()
                boundary_checks, boundary_findings = run_auth_boundary_checks(
                    self.root,
                    https_port=config.https_port,
                    ca_path=self.root / ".security-local" / "caddy-root.crt",
                    expected_generation=config.generation,
                )
                failed_checks = [
                    check.check_id for check in boundary_checks if check.status != "passed"
                ]
                coverage.append(
                    ToolCoverage(
                        tool="auth-boundary",
                        target_id="pfis-web",
                        status="failed" if failed_checks else "completed",
                        finding_count=len(boundary_findings),
                        critical_high_count=len(boundary_findings),
                        detail=(
                            "failed synthetic checks: " + ", ".join(failed_checks)
                            if failed_checks
                            else f"{len(boundary_checks)} fixed checks passed"
                        ),
                    )
                )
                self.store.add_findings(run_id, boundary_findings)
                if failed_checks:
                    overall_state = "failed"
            if profile_id == "full":
                for service in ("sqli-fixture", "metasploit-fixture"):
                    self.lab.run_compose(["restart", service], timeout=90)
            for command in commands:
                if cancel.is_set():
                    overall_state = "cancelled"
                    stop_reason = "operator cancellation requested"
                    break
                self.lab.verify_identity(required_targets=(command.target_id,))
                if command.target_id not in target_ids:
                    raise ScopeViolation("resolved command target is outside the requested profile")
                spec = TOOLS[command.tool_id]
                run_command = command
                if command.tool_id == "greenbone":
                    try:
                        self.lab.start_greenbone()
                        outcome = executor.execute(
                            command.service or spec.service,
                            run_command.argv,
                            timeout_seconds=run_command.timeout_seconds,
                            cancel=cancel,
                        )
                    finally:
                        self.lab.stop_greenbone()
                else:
                    outcome = executor.execute(
                        command.service or spec.service,
                        run_command.argv,
                        timeout_seconds=run_command.timeout_seconds,
                        cancel=cancel,
                    )
                status, findings, detail = self._parse_outcome(
                    command.tool_id, command.target_id, outcome
                )
                coverage.append(
                    ToolCoverage(
                        tool=command.tool_id,
                        target_id=command.target_id,
                        status=status,
                        finding_count=len(findings),
                        critical_high_count=sum(
                            finding.severity in {"critical", "high"}
                            for finding in findings
                            if finding.target_id == "pfis-web"
                        ),
                        duration_seconds=round(outcome.duration_seconds, 3),
                        detail=detail,
                    )
                )
                self.store.add_findings(run_id, findings)
                if status in {
                    "failed",
                    "timeout",
                    "authentication_failure",
                    "incomplete",
                    "cancelled",
                }:
                    overall_state = "failed" if status != "cancelled" else "cancelled"
                    if status == "cancelled":
                        stop_reason = "operator cancellation requested"
                        break
                    if "scope" in detail.lower() or "identity" in detail.lower():
                        stop_reason = detail
                        break
                if profile_id == "full" and command.target_id in {
                    "sqli-fixture",
                    "metasploit-fixture",
                }:
                    fixture = (
                        "sqli-fixture"
                        if command.target_id == "sqli-fixture"
                        else "metasploit-fixture"
                    )
                    self.lab.run_compose(["restart", fixture], timeout=90)
            if cancel.is_set():
                overall_state = "cancelled"
                stop_reason = stop_reason or "operator cancellation requested"
            # Every expected tool is explicit in the coverage receipt; absence
            # is never interpreted as a clean scan.
            by_tool = {entry.tool for entry in coverage}
            for tool_id in PROFILE_TOOL_IDS[profile_id]:
                if tool_id not in by_tool:
                    target_id = PROFILE_TARGETS[profile_id][0]
                    coverage.append(
                        ToolCoverage(
                            tool_id,
                            target_id,
                            "cancelled" if cancel.is_set() else "failed",
                            detail="Tool was not executed because assessment stopped before it completed.",
                        )
                    )
                    if not cancel.is_set():
                        overall_state = "failed"
            summary = self._summary(profile_id, coverage, stop_reason)
            self.store.set_run_state(run_id, overall_state, summary=summary)
        except ScopeViolation as exc:
            self.store.set_run_state(
                run_id,
                "failed",
                summary=self._summary(profile_id, coverage, f"scope violation: {exc}"),
            )
        except Exception as exc:  # Fail closed and preserve the sanitized reason.
            self.store.set_run_state(
                run_id,
                "failed",
                summary=self._summary(profile_id, coverage, sanitize_evidence(str(exc))),
            )
        finally:
            monitor_stop.set()
            cancel_monitor.join(timeout=1)
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = None
                    self._cancel_event = None
                    self._executor = None
                    self._thread = None
                self._run_lock.release()

    def _parse_outcome(
        self, tool_id: str, target_id: str, outcome: ProcessOutcome
    ) -> tuple[str, list[ParsedFinding], str]:
        if outcome.status != "completed":
            return outcome.status, [], outcome.error or sanitize_evidence(outcome.output[-500:])
        target = TARGETS[target_id]
        allowed_hosts = {target.host, *self.lab.registered_target_hosts(target_id)}
        try:
            if tool_id == "nmap":
                findings = parse_nmap_xml(
                    outcome.output, target_id=target_id, allowed_hosts=allowed_hosts
                )
            elif tool_id == "testssl":
                findings = parse_testssl_json(
                    outcome.output,
                    target_id=target_id,
                    allowed_hosts=allowed_hosts,
                    private_ca=target.private_ca,
                )
            elif tool_id == "zap":
                findings = parse_zap_json(
                    outcome.output, target_id=target_id, allowed_hosts=allowed_hosts
                )
            elif tool_id == "nuclei":
                findings = parse_nuclei_jsonl(
                    outcome.output, target_id=target_id, allowed_hosts=allowed_hosts
                )
            elif tool_id == "greenbone":
                findings = parse_greenbone_xml(
                    outcome.output, target_id=target_id, allowed_hosts=allowed_hosts
                )
            elif tool_id == "sqlmap":
                findings = parse_sqlmap_output(outcome.output, target_id=target_id)
                if not findings:
                    return "incomplete", [], "positive SQLi control was not detected"
            elif tool_id == "metasploit":
                findings = parse_metasploit_output(outcome.output)
                if not findings:
                    return "incomplete", [], "known-vulnerable Metasploit control did not execute"
            else:
                return "not_applicable", [], "no parser is registered for this scanner"
        except (ValueError, json.JSONDecodeError) as exc:
            detail = sanitize_evidence(str(exc))
            status = (
                "failed"
                if "out-of-scope" in detail.lower() or "outside" in detail.lower()
                else "incomplete"
            )
            return status, [], detail
        status = "completed" if findings else "no_findings"
        return status, findings, ""

    @staticmethod
    def _summary(profile_id: str, coverage: list[ToolCoverage], stop_reason: str) -> dict[str, Any]:
        # The persisted finding store contains the canonical evidence list;
        # this report keeps controls and PFIS targets distinct by target ID.
        return {
            "profile": profile_id,
            "coverage": [asdict(item) for item in coverage],
            "coverage_complete": all(
                item.status in {"completed", "no_findings", "not_applicable"} for item in coverage
            ),
            "critical_high_count": sum(item.critical_high_count for item in coverage),
            "fixture_controls": [
                item.tool
                for item in coverage
                if item.target_id != "pfis-web" and item.finding_count
            ],
            "stop_reason": stop_reason,
        }

    def _branch_commit(self) -> str:
        result = __import__("subprocess").run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            stdin=__import__("subprocess").DEVNULL,
            stdout=__import__("subprocess").PIPE,
            stderr=__import__("subprocess").DEVNULL,
            timeout=5,
            check=False,
            shell=False,
        )
        commit = result.stdout.decode("ascii", errors="ignore").strip()
        return commit if result.returncode == 0 and len(commit) == 40 else "unknown"

    def _recover(self) -> None:
        if not self._run_lock.try_acquire():
            return
        try:
            interrupted = self.store.interrupt_active_runs()
            try:
                config = self.lab.config()
            except Exception:
                return
            for record in interrupted:
                if record["generation"] == config.generation:
                    executor = ComposeToolExecutor(
                        self.root,
                        config.generation,
                        str(record["id"]),
                        docker_context=config.docker_context,
                    )
                    executor._cleanup_run_container()
        finally:
            self._run_lock.release()

    def _watch_cancel(
        self,
        run_id: str,
        cancel: threading.Event,
        stop: threading.Event,
        executor: ComposeToolExecutor,
    ) -> None:
        while not stop.wait(0.25):
            record = self.store.get_run(run_id)
            if record is None or record.get("cancel_requested"):
                cancel.set()
                executor.cancel()
                return
