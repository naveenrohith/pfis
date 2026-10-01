"""Host-side fixed-argv executor for generation-labelled Compose services."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from security.registry import ALLOWED_SERVICES

MAX_PROCESS_OUTPUT = 8_000_000
CONTEXT_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class ProcessOutcome:
    status: str
    exit_code: int | None
    output: str
    duration_seconds: float
    error: str = ""


def _safe_process_environment() -> dict[str, str]:
    """Preserve only platform and Docker credential paths; never inherit Docker overrides."""
    allow = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "DOCKER_CONFIG",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allow}


class ComposeToolExecutor:
    def __init__(self, root: Path, generation: str, run_id: str, *, docker_context: str) -> None:
        self.root = root.resolve()
        self.generation = generation
        self.run_id = run_id
        if not CONTEXT_RE.fullmatch(docker_context):
            raise ValueError("Docker context name is invalid")
        self.docker_context = docker_context
        self.env_file = (self.root / ".security-local" / "lab.env").resolve()
        self.compose_file = (self.root / "security" / "lab.compose.yml").resolve()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    def command(self, service: str, argv: tuple[str, ...]) -> list[str]:
        if service not in ALLOWED_SERVICES:
            raise ValueError("scanner service is not in the registry")
        if not self.env_file.is_file() or not self.compose_file.is_file():
            raise RuntimeError("prepared lab configuration is missing")
        # Docker and Compose receive only the generation-specific project,
        # compose file, and registry-derived service arguments.
        return [
            "docker",
            "--context",
            self.docker_context,
            "compose",
            "--progress",
            "quiet",
            "--env-file",
            str(self.env_file),
            "-f",
            str(self.compose_file),
            "--project-name",
            f"pfis-security-{self.generation}",
            "run",
            "--rm",
            "--no-deps",
            "--pull",
            "never",
            "--label",
            f"com.pfis.security.run-id={self.run_id}",
            "--label",
            f"com.pfis.security.lab-generation={self.generation}",
            service,
            *argv,
        ]

    def execute(
        self,
        service: str,
        argv: tuple[str, ...],
        *,
        timeout_seconds: int,
        cancel: threading.Event,
    ) -> ProcessOutcome:
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                self.command(service, argv),
                cwd=self.root,
                env=_safe_process_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
            )
        except (OSError, ValueError) as exc:
            return ProcessOutcome("failed", None, "", 0, str(exc))

        with self._process_lock:
            self._process = process
        chunks: queue.Queue[bytes | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            try:
                while chunk := process.stdout.read(64 * 1024):
                    chunks.put(chunk)
            finally:
                chunks.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        captured = bytearray()
        reader_done = False
        status = "completed"
        deadline = started + timeout_seconds
        try:
            while process.poll() is None or not reader_done or not chunks.empty():
                if cancel.is_set():
                    status = "cancelled"
                    process.terminate()
                elif time.monotonic() >= deadline:
                    status = "timeout"
                    process.terminate()
                try:
                    chunk = chunks.get(timeout=0.2)
                except queue.Empty:
                    chunk = b""
                if chunk is None:
                    reader_done = True
                elif chunk:
                    if len(captured) + len(chunk) > MAX_PROCESS_OUTPUT:
                        status = "incomplete"
                        process.kill()
                        captured.extend(chunk[: MAX_PROCESS_OUTPUT - len(captured)])
                        break
                    captured.extend(chunk)
                if status in {"cancelled", "timeout"}:
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    break
            try:
                exit_code = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait(timeout=2)
            if status == "completed" and exit_code != 0:
                status = "failed"
            if status in {"cancelled", "timeout", "incomplete"}:
                self._cleanup_run_container()
        finally:
            reader.join(timeout=2)
            with self._process_lock:
                self._process = None

        output = captured.decode("utf-8", errors="replace")
        error = ""
        if status == "failed" and ("401" in output or "authentication" in output.lower()):
            status = "authentication_failure"
        elif status == "failed" and (
            "not found" in output.lower() or "pull access denied" in output.lower()
        ):
            error = "required scanner image is unavailable; assessment did not pass"
        return ProcessOutcome(status, exit_code, output, time.monotonic() - started, error)

    def cancel(self) -> None:
        with self._process_lock:
            process = self._process
        if process is not None:
            process.terminate()
            self._cleanup_run_container()

    def _cleanup_run_container(self) -> None:
        env = _safe_process_environment()
        base = [
            "docker",
            "--context",
            self.docker_context,
            "ps",
            "-aq",
            "--filter",
            f"label=com.pfis.security.run-id={self.run_id}",
        ]
        try:
            found = subprocess.run(
                base,
                cwd=self.root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
                shell=False,
            )
            container_ids = found.stdout.decode("ascii", errors="ignore").split()
            for container_id in container_ids[:16]:
                inspected = subprocess.run(
                    [
                        "docker",
                        "--context",
                        self.docker_context,
                        "inspect",
                        "--format",
                        "{{json .Config.Labels}}",
                        container_id,
                    ],
                    cwd=self.root,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    check=False,
                    shell=False,
                )
                labels = json.loads(inspected.stdout.decode("utf-8", errors="replace") or "{}")
                if not isinstance(labels, dict):
                    continue
                if (
                    labels.get("com.pfis.security.lab-generation") == self.generation
                    and labels.get("com.pfis.security.run-id") == self.run_id
                ):
                    subprocess.run(
                        ["docker", "--context", self.docker_context, "rm", "-f", container_id],
                        cwd=self.root,
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=12,
                        check=False,
                        shell=False,
                    )
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            # An incomplete cleanup is surfaced by the run record and can be
            # repaired by the generation-checked `lab reset` command.
            return
