"""Generation-scoped disposable lab lifecycle with fail-closed Docker checks."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security.executor import _safe_process_environment
from security.registry import TARGETS, TOOLS

GENERATION_RE = re.compile(r"^[0-9a-f]{12}$")
CONTEXT_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
LAB_LABEL = "com.pfis.security.lab-generation"
RUN_LABEL = "com.pfis.security.run-id"
MANAGED_LABEL = "com.pfis.security.managed"
COMPOSE_IMAGES = (
    "database",
    "proxy",
    "metasploit-fixture",
    "nmap",
    "metasploit",
    "vulnerability-tests",
    "notus-data",
    "scap-data",
    "cert-bund-data",
    "dfn-cert-data",
    "data-objects",
    "report-formats",
    "gpg-data",
    "redis-server",
    "pg-gvm",
    "pg-gvm-migrator",
    "gvmd",
    "configure-openvas",
    "openvas",
    "openvasd",
    "ospd-openvas",
)
BUILD_SERVICES = (
    "app",
    "sqli-fixture",
    "sqlmap",
    "nuclei",
    "greenbone-control",
    "zap-api",
    "isolation-probe",
    "testssl",
)
LIGHT_PULL_SERVICES = ("database", "proxy")
LIGHT_BUILD_SERVICES = ("app", "sqli-fixture", "zap-api", "isolation-probe")
EXTENDED_PULL_SERVICES = (*LIGHT_PULL_SERVICES, "nmap")
EXTENDED_BUILD_SERVICES = (
    *LIGHT_BUILD_SERVICES[:2],
    "nuclei",
    *LIGHT_BUILD_SERVICES[2:],
    "testssl",
)
CORE_SERVICES = ("database", "app", "proxy")
FIXTURE_SERVICES = ("sqli-fixture", "metasploit-fixture")
FEED_SERVICES = (
    "vulnerability-tests",
    "notus-data",
    "scap-data",
    "cert-bund-data",
    "dfn-cert-data",
    "data-objects",
    "report-formats",
)
GREENBONE_RUN_SERVICES = (
    "redis-server",
    "pg-gvm-migrator",
    "pg-gvm",
    "gvmd",
    "configure-openvas",
    "openvas",
    "openvasd",
    "ospd-openvas",
)
FEED_NETWORK = "pfis-security-{generation}-feed-egress"
SCANNER_SERVICES = frozenset(
    {
        "zap",
        "zap-api",
        "nuclei",
        "nmap",
        "testssl",
        "sqlmap",
        "metasploit",
        "greenbone-tools",
        "isolation-probe",
    }
)
GREENBONE_INTERNAL_SERVICES = frozenset(
    {
        "gpg-data",
        "redis-server",
        "pg-gvm",
        "pg-gvm-migrator",
        "gvmd",
        "configure-openvas",
        "openvas",
        "openvasd",
        "ospd-openvas",
    }
)


class LabError(RuntimeError):
    """A requested lab operation failed closed."""


class LabCancelled(LabError):
    """A cancellable lab readiness operation was stopped by the operator."""


@dataclass(frozen=True)
class LabConfig:
    generation: str
    docker_context: str
    https_port: int
    values: dict[str, str]

    @property
    def project(self) -> str:
        return f"pfis-security-{self.generation}"


class LabManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.metadata = self.root / ".security-local"
        self.env_file = self.metadata / "lab.env"
        self.credentials_file = self.metadata / "lab-credentials.json"
        self.compose_file = self.root / "security" / "lab.compose.yml"

    def prepare_config(self) -> LabConfig:
        self.metadata.mkdir(parents=True, exist_ok=True)
        if self.env_file.exists():
            self._ensure_lab_secrets()
            return self.config()
        docker_context = self._validate_docker_context()
        generation = secrets.token_hex(6)
        values = {
            "LAB_GENERATION": generation,
            "LAB_HTTPS_PORT": "8443",
            "LAB_DATABASE_PASSWORD": secrets.token_urlsafe(32),
            "LAB_SECRET_KEY": secrets.token_urlsafe(48),
            "LAB_TOKEN_ENCRYPTION_KEY": secrets.token_urlsafe(48),
            "LAB_GREENBONE_PASSWORD": secrets.token_urlsafe(36),
            "LAB_DEMO_PASSWORD": secrets.token_urlsafe(32),
            "LAB_OWNER_EMAIL": "owner@pfis.example.com",
            "LAB_OWNER_PASSWORD": secrets.token_urlsafe(24),
            "LAB_MEMBER_EMAIL": "member@pfis.example.com",
            "LAB_MEMBER_PASSWORD": secrets.token_urlsafe(24),
            "LAB_VIEWER_EMAIL": "viewer@pfis.example.com",
            "LAB_VIEWER_PASSWORD": secrets.token_urlsafe(24),
        }
        self._write_env(values, self.env_file)
        credentials = {
            "generation": generation,
            "owner": {"email": values["LAB_OWNER_EMAIL"], "password": values["LAB_OWNER_PASSWORD"]},
            "member": {
                "email": values["LAB_MEMBER_EMAIL"],
                "password": values["LAB_MEMBER_PASSWORD"],
            },
            "viewer": {
                "email": values["LAB_VIEWER_EMAIL"],
                "password": values["LAB_VIEWER_PASSWORD"],
            },
            "household_roles": ["owner", "member", "viewer"],
        }
        self._write_private(self.credentials_file, json.dumps(credentials, indent=2) + "\n")
        # Keep only the Docker context name in the ignored environment file.
        values["LAB_DOCKER_CONTEXT"] = docker_context
        with self.env_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"LAB_DOCKER_CONTEXT={docker_context}\n")
        return LabConfig(generation, docker_context, 8443, values)

    def _ensure_lab_secrets(self) -> None:
        lines = self.env_file.read_text(encoding="utf-8").splitlines()
        keys = {
            line.split("=", maxsplit=1)[0]
            for line in lines
            if line and not line.lstrip().startswith("#") and "=" in line
        }
        additions = {
            "LAB_GREENBONE_PASSWORD": secrets.token_urlsafe(36),
            "LAB_DEMO_PASSWORD": secrets.token_urlsafe(32),
        }
        missing = [(key, value) for key, value in additions.items() if key not in keys]
        if not missing:
            return
        with self.env_file.open("a", encoding="utf-8", newline="\n") as handle:
            for key, value in missing:
                handle.write(f"{key}={value}\n")
        with suppress(OSError):
            os.chmod(self.env_file, 0o600)

    def config(self) -> LabConfig:
        if not self.env_file.is_file():
            raise LabError("lab is not prepared; run `python scripts/security.py prepare` first")
        self._ensure_lab_secrets()
        values: dict[str, str] = {}
        for line in self.env_file.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", maxsplit=1)
            if key in values:
                raise LabError(f"duplicate lab setting: {key}")
            values[key] = value
        generation = values.get("LAB_GENERATION", "")
        context = values.get("LAB_DOCKER_CONTEXT", "")
        if not GENERATION_RE.fullmatch(generation) or not CONTEXT_RE.fullmatch(context):
            raise LabError("local lab identity is invalid; refusing Docker operations")
        try:
            port = int(values["LAB_HTTPS_PORT"])
        except (ValueError, KeyError) as exc:
            raise LabError("local lab port is invalid") from exc
        if not 1024 <= port <= 65535:
            raise LabError("local lab port is outside the permitted range")
        required = {
            "LAB_DATABASE_PASSWORD",
            "LAB_SECRET_KEY",
            "LAB_TOKEN_ENCRYPTION_KEY",
            "LAB_GREENBONE_PASSWORD",
            "LAB_DEMO_PASSWORD",
            "LAB_OWNER_EMAIL",
            "LAB_OWNER_PASSWORD",
            "LAB_MEMBER_EMAIL",
            "LAB_MEMBER_PASSWORD",
            "LAB_VIEWER_EMAIL",
            "LAB_VIEWER_PASSWORD",
        }
        if not required.issubset(values):
            raise LabError("local lab credentials are incomplete")
        return LabConfig(generation, context, port, values)

    def compose_prefix(self, config: LabConfig | None = None) -> list[str]:
        config = config or self.config()
        return [
            "docker",
            "--context",
            config.docker_context,
            "compose",
            "--env-file",
            str(self.env_file),
            "-f",
            str(self.compose_file),
            "--project-name",
            config.project,
        ]

    def run_compose(
        self,
        args: list[str],
        *,
        timeout: int = 600,
        check: bool = True,
        profile: str | None = None,
    ) -> str:
        config = self.config()
        self._validate_docker_context(expected=config.docker_context)
        if profile not in {None, "greenbone", "scanners"}:
            raise LabError("Compose profile is not registered")
        if not args or args[0] not in {
            "config",
            "pull",
            "build",
            "up",
            "ps",
            "run",
            "down",
            "logs",
            "restart",
            "stop",
        }:
            raise LabError("Compose operation is not registered")
        command = [*self.compose_prefix(config)]
        if profile:
            command.extend(("--profile", profile))
        command.extend(args)
        result = subprocess.run(
            command,
            cwd=self.root,
            env=_safe_process_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            shell=False,
        )
        output = result.stdout.decode("utf-8", errors="replace")
        if check and result.returncode != 0:
            raise LabError(
                f"Docker Compose {args[0]} failed (exit {result.returncode}): {output[-1500:]}"
            )
        return output

    def validate_compose(self) -> str:
        return self.run_compose(["config", "--quiet"], timeout=60)

    def prepare_images(
        self, *, lightweight: bool = False, extended: bool = False
    ) -> dict[str, str]:
        if lightweight and extended:
            raise LabError("lightweight and extended preparation modes cannot be combined")
        config = self.prepare_config()
        self.validate_compose()
        pull_services: tuple[str, ...]
        build_services: tuple[str, ...]
        prepared_tool_ids: set[str]
        if lightweight:
            pull_services = LIGHT_PULL_SERVICES
            build_services = LIGHT_BUILD_SERVICES
            prepared_tool_ids = {"zap"}
        elif extended:
            pull_services = EXTENDED_PULL_SERVICES
            build_services = EXTENDED_BUILD_SERVICES
            prepared_tool_ids = {"zap", "nuclei", "nmap", "testssl"}
        else:
            pull_services = COMPOSE_IMAGES
            build_services = BUILD_SERVICES
            prepared_tool_ids = set(TOOLS)
        pulled = self.run_compose(["pull", *pull_services], timeout=7200)
        built = self.run_compose(["build", *build_services], timeout=1800)
        feed_receipt = None if lightweight or extended else self._prepare_greenbone_feeds(config)
        images = {
            tool.id: self.image_info(tool.runtime_image or tool.image, config)
            for tool in TOOLS.values()
            if tool.id in prepared_tool_ids
        }
        receipt = {
            "schema_version": 1,
            "generation": config.generation,
            "commit_sha": self._git_commit(),
            "images": images,
            "tools": {
                tool.id: {
                    "version": tool.version,
                    "source_image": tool.image,
                    "runtime_image": tool.runtime_image or tool.image,
                    "source_revision": tool.source_revision,
                    "capabilities": list(tool.capabilities),
                }
                for tool in TOOLS.values()
            },
            "nuclei_templates_sha256": self._file_sha256(
                self.root / "security" / "nuclei_templates" / "pfis-security-headers.yaml"
            ),
            "preparation_mode": (
                "lightweight" if lightweight else "extended" if extended else "full"
            ),
            "greenbone_feed_receipt": feed_receipt,
        }
        receipt_path = self.metadata / "image-receipt.json"
        temporary_receipt = receipt_path.with_suffix(".json.tmp")
        temporary_receipt.write_text(
            json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
        with suppress(OSError):
            os.chmod(temporary_receipt, 0o600)
        os.replace(temporary_receipt, receipt_path)
        return {
            "pulled": pulled[-1200:],
            "built": built[-1200:],
            "receipt": str(receipt_path),
        }

    def _prepare_greenbone_feeds(self, config: LabConfig) -> dict[str, Any]:
        self.run_compose(
            ["up", "-d", *FEED_SERVICES],
            timeout=7200,
            profile="greenbone",
        )
        for service in FEED_SERVICES:
            self._wait_for_service(service, 3600)
        self._disconnect_feed_updates(config)
        if not self._feed_updates_disconnected(config):
            raise LabError("Greenbone feed updater egress could not be disconnected")
        receipt: dict[str, Any] = {
            "schema_version": 1,
            "generation": config.generation,
            "commit_sha": self._git_commit(),
            "services_healthy": list(FEED_SERVICES),
            "feed_network_disconnected": True,
            "compose_sha256": self._file_sha256(self.compose_file),
            "prepared_at": datetime.now(UTC).isoformat(),
        }
        path = self.metadata / "greenbone-feed-receipt.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
        with suppress(OSError):
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return receipt

    def _disconnect_feed_updates(self, config: LabConfig) -> None:
        network_name = FEED_NETWORK.format(generation=config.generation)
        network = self._inspect_network(network_name, config)
        if network is None:
            raise LabError("Greenbone temporary feed network is missing")
        if (network.get("Labels") or {}).get(LAB_LABEL) != config.generation:
            raise LabError("Greenbone feed network identity mismatch; egress was not changed")
        containers = network.get("Containers") or {}
        if not isinstance(containers, dict):
            raise LabError("Greenbone feed network endpoint list is invalid")
        for container_id, endpoint in containers.items():
            inspected = subprocess.run(
                [
                    "docker",
                    "--context",
                    config.docker_context,
                    "inspect",
                    "--format",
                    "{{json .Config.Labels}}",
                    str(container_id),
                ],
                cwd=self.root,
                env=_safe_process_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                shell=False,
            )
            try:
                labels = json.loads(inspected.stdout.decode("utf-8", errors="replace") or "{}")
            except json.JSONDecodeError as exc:
                raise LabError("Greenbone feed container labels could not be verified") from exc
            if not isinstance(labels, dict):
                raise LabError("Greenbone feed container labels are invalid")
            service = labels.get("com.docker.compose.service") if isinstance(labels, dict) else None
            if (
                inspected.returncode
                or labels.get(LAB_LABEL) != config.generation
                or labels.get(MANAGED_LABEL) != "true"
                or service not in FEED_SERVICES
            ):
                raise LabError("unexpected resource is connected to the Greenbone feed network")
            name = endpoint.get("Name") if isinstance(endpoint, dict) else None
            disconnect = subprocess.run(
                [
                    "docker",
                    "--context",
                    config.docker_context,
                    "network",
                    "disconnect",
                    network_name,
                    str(name or container_id),
                ],
                cwd=self.root,
                env=_safe_process_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=15,
                check=False,
                shell=False,
            )
            if disconnect.returncode:
                raise LabError("could not disconnect a Greenbone feed updater from egress")
        if not self._feed_updates_disconnected(config):
            raise LabError("Greenbone feed network still has connected containers")

    def _feed_updates_disconnected(self, config: LabConfig) -> bool:
        network_name = FEED_NETWORK.format(generation=config.generation)
        listed = subprocess.run(
            [
                "docker",
                "--context",
                config.docker_context,
                "network",
                "ls",
                "--filter",
                f"name=^{re.escape(network_name)}$",
                "--format",
                "{{.Name}}",
            ],
            cwd=self.root,
            env=_safe_process_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            shell=False,
        )
        if listed.returncode:
            return False
        if not listed.stdout.decode("utf-8", errors="replace").strip():
            return True
        network = self._inspect_network(network_name, config)
        if network is None or (network.get("Labels") or {}).get(LAB_LABEL) != config.generation:
            return False
        return not bool(network.get("Containers"))

    def _inspect_network(self, name: str, config: LabConfig) -> dict[str, Any] | None:
        result = subprocess.run(
            [
                "docker",
                "--context",
                config.docker_context,
                "network",
                "inspect",
                name,
                "--format",
                "{{json .}}",
            ],
            cwd=self.root,
            env=_safe_process_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            shell=False,
        )
        if result.returncode:
            return None
        try:
            value = json.loads(result.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def _greenbone_feed_receipt_ready(self, config: LabConfig) -> bool:
        try:
            receipt = json.loads(
                (self.metadata / "greenbone-feed-receipt.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return False
        return (
            isinstance(receipt, dict)
            and receipt.get("schema_version") == 1
            and receipt.get("generation") == config.generation
            and receipt.get("services_healthy") == list(FEED_SERVICES)
            and receipt.get("feed_network_disconnected") is True
            and self._feed_updates_disconnected(config)
        )

    def image_info(self, image: str, config: LabConfig | None = None) -> dict[str, Any]:
        config = config or self.config()
        if not image or len(image) > 512 or any(char in image for char in " \t\r\n;`$|&"):
            raise LabError("scanner image reference is invalid")
        result = subprocess.run(
            [
                "docker",
                "--context",
                config.docker_context,
                "image",
                "inspect",
                "--format",
                "{{json .}}",
                image,
            ],
            cwd=self.root,
            env=_safe_process_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=20,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise LabError(f"required pinned scanner image is missing: {image}")
        try:
            info = json.loads(result.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise LabError("Docker returned invalid image metadata") from exc
        return {
            "image_id": str(info.get("Id", "")),
            "repo_digests": list(info.get("RepoDigests") or []),
            "runtime_image": image,
        }

    def tool_readiness(self) -> list[dict[str, Any]]:
        config = self.config()
        receipt_path = self.metadata / "image-receipt.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            receipt = {}
        ready: list[dict[str, Any]] = []
        for tool in TOOLS.values():
            image_ref = tool.runtime_image or tool.image
            source_digest = tool.image.rsplit("@sha256:", maxsplit=1)[-1]
            digest_pinned = len(source_digest) == 64 and all(
                char in "0123456789abcdef" for char in source_digest
            )
            expected = (
                receipt.get("images", {}).get(tool.id, {}) if isinstance(receipt, dict) else {}
            )
            try:
                actual = self.image_info(image_ref, config)
                image_present = (
                    bool(expected.get("image_id")) and actual["image_id"] == expected["image_id"]
                )
            except LabError:
                actual = {}
                image_present = False
            greenbone_ready = tool.id != "greenbone" or self._greenbone_feed_receipt_ready(config)
            is_ready = digest_pinned and image_present and greenbone_ready
            detail = ""
            if not digest_pinned:
                detail = "No pinned source digest is registered."
            elif not image_present:
                detail = "Run the preparation command and verify the image receipt."
            elif tool.id == "greenbone" and not greenbone_ready:
                detail = "Greenbone feeds are not ready or feed updater egress is still connected."
            ready.append(
                {
                    "id": tool.id,
                    "version": tool.version,
                    "image": image_ref,
                    "source_image": tool.image,
                    "runtime_image_id": actual.get("image_id", ""),
                    "capabilities": list(tool.capabilities),
                    "digest_pinned": digest_pinned,
                    "ready": is_ready,
                    "status": "ready" if is_ready else "not_ready",
                    "detail": detail,
                }
            )
        return ready

    def start(self, *, lightweight: bool = False) -> None:
        self.validate_compose()
        config = self.config()
        self._validate_docker_context(expected=config.docker_context)
        self.run_compose(["up", "-d", "database"], timeout=180)
        self._wait_for_service("database", 180)
        self.run_compose(
            ["run", "--rm", "--no-deps", "app", "alembic", "upgrade", "head"], timeout=900
        )
        self.run_compose(
            ["run", "--rm", "--no-deps", "app", "python", "-m", "security.lab_seed"], timeout=180
        )
        services = ["app", "proxy", "sqli-fixture"]
        if not lightweight:
            services.append("metasploit-fixture")
        self.run_compose(["up", "-d", *services], timeout=180)
        self.run_compose(["restart", "proxy"], timeout=90)
        self._wait_for_service("proxy", 180)
        self.export_proxy_ca()
        self._wait_for_https_ready(180)
        start_targets = ("sqli-fixture",) if lightweight else FIXTURE_SERVICES
        self.verify_identity(required_targets=start_targets)

    def start_greenbone(self, cancel: threading.Event | None = None) -> None:
        config = self.config()
        if cancel is not None and cancel.is_set():
            raise LabCancelled("Greenbone startup was cancelled")
        self.verify_identity()
        if not self._greenbone_feed_receipt_ready(config):
            raise LabError(
                "Greenbone feed preparation is incomplete; refusing an infrastructure scan"
            )
        self.run_compose(
            ["up", "-d", *GREENBONE_RUN_SERVICES],
            timeout=1800,
            profile="greenbone",
        )
        if cancel is not None and cancel.is_set():
            raise LabCancelled("Greenbone startup was cancelled")
        self._disconnect_feed_updates(config)
        if not self._feed_updates_disconnected(config):
            raise LabError("Greenbone feed updater reconnected to egress; refusing the scan")
        self.verify_network_isolation()
        for service in ("gvmd", "ospd-openvas"):
            self._wait_for_service(service, 900, cancel=cancel)
        if cancel is not None and cancel.is_set():
            raise LabCancelled("Greenbone startup was cancelled")
        readiness = self.run_compose(
            ["run", "--rm", "--no-deps", "greenbone-control", "ready"],
            timeout=300,
            profile="greenbone",
        )
        try:
            result = json.loads(readiness.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            raise LabError("Greenbone manager readiness response is invalid") from exc
        if result.get("status") != "ready" or result.get("target_id") != "pfis-web":
            raise LabError("Greenbone manager, scanner, and configuration are not ready")

    def stop_greenbone(self) -> None:
        self.run_compose(
            ["stop", *GREENBONE_RUN_SERVICES],
            timeout=180,
            profile="greenbone",
        )

    def registered_target_hosts(self, target_id: str) -> set[str]:
        if target_id not in TARGETS:
            raise LabError("scanner requested an unregistered target")
        if target_id != "pfis-web":
            return set()
        config = self.config()
        result = subprocess.run(
            [
                "docker",
                "--context",
                config.docker_context,
                "inspect",
                "--format",
                "{{json .NetworkSettings.Networks}}",
                f"{config.project}-proxy-1",
            ],
            cwd=self.root,
            env=_safe_process_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            shell=False,
        )
        if result.returncode:
            raise LabError("registered PFIS target address is unavailable")
        try:
            networks = json.loads(result.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise LabError("registered PFIS target network metadata is invalid") from exc
        scanner_network = f"pfis-security-{config.generation}-scanner"
        details = networks.get(scanner_network) if isinstance(networks, dict) else None
        address = details.get("IPAddress") if isinstance(details, dict) else None
        if not address:
            raise LabError("registered PFIS target is not attached to the scanner network")
        return {str(address)}

    def status(self) -> dict[str, Any]:
        config = self.config()
        containers = self._list_resources("container")
        networks = self._list_resources("network")
        volumes = self._list_resources("volume")
        labeled = [
            item for item in containers if self._labels(item).get(LAB_LABEL) == config.generation
        ]
        return {
            "generation": config.generation,
            "project": config.project,
            "https_url": f"https://localhost:{config.https_port}",
            "synthetic_data": True,
            "docker_context": config.docker_context,
            "containers": labeled,
            "networks": [
                item for item in networks if self._labels(item).get(LAB_LABEL) == config.generation
            ],
            "volumes": [
                item for item in volumes if self._labels(item).get(LAB_LABEL) == config.generation
            ],
            "scanner_network_internal": self._scanner_network_internal(config),
            "feed_updates_disconnected": self._feed_updates_disconnected(config),
        }

    def verify_identity(self, *, required_targets: tuple[str, ...] = ()) -> dict[str, Any]:
        config = self.config()
        self._validate_docker_context(expected=config.docker_context)
        status = self.status()
        names = {self._resource_name(item) for item in status["containers"]}
        expected_services = set(CORE_SERVICES)
        if "sqli-fixture" in required_targets:
            expected_services.add("sqli-fixture")
        if "metasploit-fixture" in required_targets:
            expected_services.add("metasploit-fixture")
        if any(target not in {"pfis-web", *FIXTURE_SERVICES} for target in required_targets):
            raise LabError("lab identity request contains an unregistered target")
        expected = {f"{config.project}-{service}-1" for service in expected_services}
        missing = sorted(expected - names)
        if missing:
            raise LabError(
                f"lab identity verification failed; missing services: {', '.join(missing)}"
            )
        if status["scanner_network_internal"] is not True:
            raise LabError("scanner network is not internal; refusing active scans")
        if status["feed_updates_disconnected"] is not True:
            raise LabError("Greenbone feed updater still has egress; refusing active scans")
        for item in status["containers"]:
            labels = self._labels(item)
            if labels.get(MANAGED_LABEL) != "true":
                raise LabError("unmanaged container shares the PFIS security generation label")
        return status

    def verify_network_isolation(self, *, required_targets: tuple[str, ...] = ()) -> dict[str, Any]:
        """Verify lab network membership and actively test host and public egress."""
        status = self.verify_identity(required_targets=required_targets)
        config = self.config()
        self._verify_container_networks(config)

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", 0))
            listener.listen(1)
            listener.settimeout(0.25)
            host_port = int(listener.getsockname()[1])
        except OSError as exc:
            listener.close()
            raise LabError("could not open a temporary host isolation sentinel") from exc

        sentinel_hit = threading.Event()
        stop_listener = threading.Event()

        def accept_once() -> None:
            while not stop_listener.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                sentinel_hit.set()
                connection.close()
                return

        accept_thread = threading.Thread(
            target=accept_once, name="pfis-host-isolation-sentinel", daemon=True
        )
        accept_thread.start()
        run_id = secrets.token_hex(16)
        try:
            output = self.run_compose(
                [
                    "run",
                    "--rm",
                    "--no-deps",
                    "--pull",
                    "never",
                    "--label",
                    f"{RUN_LABEL}={run_id}",
                    "--label",
                    f"{LAB_LABEL}={config.generation}",
                    "isolation-probe",
                    "--host-port",
                    str(host_port),
                ],
                timeout=30,
                profile="scanners",
            )
        except (OSError, subprocess.SubprocessError, LabError) as exc:
            raise LabError("scanner isolation probe could not complete") from exc
        finally:
            stop_listener.set()
            listener.close()
            accept_thread.join(timeout=1)

        try:
            result = next(
                json.loads(line)
                for line in reversed(output.splitlines())
                if line.lstrip().startswith("{")
            )
        except (json.JSONDecodeError, StopIteration) as exc:
            raise LabError("scanner isolation probe returned no valid receipt") from exc
        if sentinel_hit.is_set():
            result["host_listener_accessible"] = True
            result["status"] = "failed"
        if result.get("status") != "passed":
            raise LabError(
                "scanner isolation probe failed or was incomplete; no assessment was started"
            )

        receipt = {
            "schema_version": 1,
            "generation": config.generation,
            "commit_sha": self._git_commit(),
            "network_internal": status["scanner_network_internal"],
            "feed_updates_disconnected": status["feed_updates_disconnected"],
            "topology_verified": True,
            "probe": result,
            "verified_at": datetime.now(UTC).isoformat(),
        }
        path = self.metadata / "isolation-receipt.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
        )
        with suppress(OSError):
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return receipt

    def _verify_container_networks(self, config: LabConfig) -> None:
        listed = subprocess.run(
            [
                "docker",
                "--context",
                config.docker_context,
                "ps",
                "-aq",
                "--filter",
                f"label={LAB_LABEL}={config.generation}",
            ],
            cwd=self.root,
            env=_safe_process_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            shell=False,
        )
        if listed.returncode:
            raise LabError("could not inspect labelled lab containers for network isolation")

        app_network = f"{config.project}_app-data"
        default_network = f"{config.project}_default"
        scanner_network = f"pfis-security-{config.generation}-scanner"
        operator_network = f"pfis-security-{config.generation}-operator"
        feed_network = FEED_NETWORK.format(generation=config.generation)
        expected_by_service: dict[str, set[str]] = {
            "database": {app_network},
            "app": {app_network},
            "proxy": {app_network, scanner_network, operator_network},
            "sqli-fixture": {scanner_network},
            "metasploit-fixture": {scanner_network},
            **{service: {scanner_network} for service in SCANNER_SERVICES},
            "greenbone-control": {default_network, scanner_network},
            **{
                service: {default_network}
                for service in (*GREENBONE_INTERNAL_SERVICES, *FEED_SERVICES)
                if service != "ospd-openvas"
            },
            "ospd-openvas": {default_network, scanner_network},
        }
        allowed_network_names = {
            app_network,
            default_network,
            scanner_network,
            operator_network,
            feed_network,
        }
        for container_id in listed.stdout.decode("ascii", errors="ignore").splitlines()[:128]:
            inspected = subprocess.run(
                [
                    "docker",
                    "--context",
                    config.docker_context,
                    "inspect",
                    "--format",
                    "{{json .Config.Labels}}{{println}}{{json .NetworkSettings.Networks}}{{println}}{{json .Mounts}}",
                    container_id,
                ],
                cwd=self.root,
                env=_safe_process_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=12,
                check=False,
                shell=False,
            )
            lines = inspected.stdout.decode("utf-8", errors="replace").splitlines()
            if inspected.returncode or len(lines) != 3:
                raise LabError("lab container network metadata could not be verified")
            try:
                labels, attached, mounts = (json.loads(line) for line in lines)
            except json.JSONDecodeError as exc:
                raise LabError("lab container network metadata is invalid") from exc
            if not isinstance(labels, dict) or labels.get(LAB_LABEL) != config.generation:
                raise LabError("lab container generation identity changed during isolation check")
            service = labels.get("com.docker.compose.service")
            networks = set(attached) if isinstance(attached, dict) else set()
            if networks & allowed_network_names and service not in expected_by_service:
                raise LabError("unregistered service is attached to a PFIS lab network")
            if service in expected_by_service and networks != expected_by_service[service]:
                raise LabError(f"lab service {service} has an unexpected network attachment")
            if feed_network in networks:
                raise LabError(
                    "a lab service remains attached to the temporary feed egress network"
                )
            if networks - allowed_network_names:
                raise LabError("a lab container has an unregistered network attachment")
            scanner_container = service in SCANNER_SERVICES or service in {
                "greenbone-control",
                "ospd-openvas",
                "sqli-fixture",
                "metasploit-fixture",
            }
            if scanner_container and not isinstance(mounts, list):
                raise LabError("scanner container has a host bind mount or invalid mount metadata")
            if scanner_container and any(
                isinstance(mount, dict) and mount.get("Type") == "bind" for mount in mounts
            ):
                raise LabError("scanner container has access to a host filesystem path")

    def reset(self) -> None:
        config = self.config()
        self._validate_docker_context(expected=config.docker_context)
        resources: dict[str, list[dict[str, Any]]] = {
            kind: self._list_resources(kind) for kind in ("container", "network", "volume")
        }
        project_resources = [
            item
            for group in resources.values()
            for item in group
            if config.project in self._resource_name(item)
        ]
        for item in project_resources:
            labels = self._labels(item)
            if labels.get(LAB_LABEL) != config.generation or labels.get(MANAGED_LABEL) != "true":
                raise LabError("resource identity mismatch; no lab cleanup was performed")
        if not project_resources:
            (self.metadata / "greenbone-feed-receipt.json").unlink(missing_ok=True)
            return
        self.run_compose(
            ["down", "--volumes", "--remove-orphans"], timeout=180, profile="greenbone"
        )
        remaining = [
            item
            for kind in resources
            for item in self._list_resources(kind)
            if config.project in self._resource_name(item)
        ]
        if remaining:
            raise LabError("lab cleanup left generation resources; inspect the lab status")
        (self.metadata / "greenbone-feed-receipt.json").unlink(missing_ok=True)

    def reset_generation(self) -> None:
        """Reset, then invalidate the old generation and secrets."""
        self.reset()
        for path in (self.env_file, self.credentials_file, self.metadata / "caddy-root.crt"):
            if path.exists() and path.parent.resolve() == self.metadata.resolve():
                path.unlink()
        for path in self.metadata.glob("security.sqlite3*"):
            if path.is_file() and path.parent.resolve() == self.metadata.resolve():
                path.unlink()

    def export_proxy_ca(self) -> Path:
        config = self.config()
        container = f"{config.project}-proxy-1"
        destination = self.metadata / "caddy-root.crt"
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "docker",
                "--context",
                config.docker_context,
                "cp",
                f"{container}:/data/caddy/pki/authorities/local/root.crt",
                str(destination),
            ],
            cwd=self.root,
            env=_safe_process_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
            shell=False,
        )
        if result.returncode != 0 or not destination.is_file():
            raise LabError("could not export the lab CA; HTTPS trust cannot be verified")
        certificate = destination.read_bytes()
        if (
            len(certificate) > 16_384
            or not certificate.startswith(b"-----BEGIN CERTIFICATE-----")
            or b"-----END CERTIFICATE-----" not in certificate
        ):
            raise LabError("exported lab CA is not a valid bounded PEM certificate")
        self._set_env_value("LAB_CADDY_ROOT_CA_B64", base64.b64encode(certificate).decode("ascii"))
        return destination

    def _set_env_value(self, key: str, value: str) -> None:
        """Atomically update one generated Docker Compose setting in the private env file."""
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or any(char in value for char in "\r\n"):
            raise LabError("generated lab setting is invalid")
        lines = self.env_file.read_text(encoding="utf-8").splitlines()
        output: list[str] = []
        found = False
        for line in lines:
            if line.startswith(f"{key}="):
                if found:
                    raise LabError(f"duplicate lab setting: {key}")
                output.append(f"{key}={value}")
                found = True
            else:
                output.append(line)
        if not found:
            output.append(f"{key}={value}")
        temporary = self.env_file.with_suffix(".env.tmp")
        temporary.write_text("\n".join(output) + "\n", encoding="utf-8", newline="\n")
        with suppress(OSError):
            os.chmod(temporary, 0o600)
        temporary.replace(self.env_file)

    def _wait_for_https_ready(self, timeout_seconds: int) -> None:
        import ssl
        from urllib.error import URLError
        from urllib.request import urlopen

        config = self.config()
        ca_path = self.metadata / "caddy-root.crt"
        if not ca_path.is_file():
            raise LabError("lab CA is missing; HTTPS identity cannot be checked")
        ssl_context = ssl.create_default_context(cafile=str(ca_path))
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                with urlopen(
                    f"https://localhost:{config.https_port}/api/health",
                    context=ssl_context,
                    timeout=3,
                ) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                time.sleep(2)
        raise LabError("PFIS HTTPS health endpoint did not become ready")

    def _wait_for_service(
        self,
        service: str,
        timeout_seconds: int,
        *,
        cancel: threading.Event | None = None,
    ) -> None:
        config = self.config()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise LabCancelled("Greenbone readiness was cancelled")
            result = subprocess.run(
                [
                    "docker",
                    "--context",
                    config.docker_context,
                    "inspect",
                    "--format",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                    f"{config.project}-{service}-1",
                ],
                cwd=self.root,
                env=_safe_process_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
                shell=False,
            )
            state = result.stdout.decode("ascii", errors="ignore").strip()
            if state in {"healthy", "running"}:
                return
            time.sleep(2)
        raise LabError(f"lab service {service} did not become ready")

    def _validate_docker_context(self, expected: str | None = None) -> str:
        try:
            shown = subprocess.run(
                ["docker", "context", "show"],
                cwd=self.root,
                env=_safe_process_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
                check=False,
                shell=False,
            )
            context = shown.stdout.decode("utf-8", errors="replace").strip()
            if (
                shown.returncode
                or not CONTEXT_RE.fullmatch(context)
                or (expected and context != expected)
            ):
                raise LabError(
                    "Docker context is unavailable or changed; lab operations are disabled"
                )
            inspected = subprocess.run(
                ["docker", "context", "inspect", context, "--format", "{{json .Endpoints.docker}}"],
                cwd=self.root,
                env=_safe_process_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=10,
                check=False,
                shell=False,
            )
            endpoint = json.loads(inspected.stdout.decode("utf-8", errors="replace"))
            host = str(endpoint.get("Host", ""))
            if inspected.returncode or not host.lower().startswith(
                ("npipe://", "unix://", "tcp://127.0.0.1", "tcp://localhost")
            ):
                raise LabError(
                    "Docker context is remote; scanner operations require a local daemon"
                )
            return context
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, LabError):
                raise
            raise LabError("could not verify a local Docker context") from exc

    def _git_commit(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            shell=False,
        )
        commit = result.stdout.decode("ascii", errors="ignore").strip()
        return commit if result.returncode == 0 and len(commit) == 40 else "unknown"

    @staticmethod
    def _file_sha256(path: Path) -> str:
        import hashlib

        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _scanner_network_internal(self, config: LabConfig) -> bool | None:
        result = subprocess.run(
            [
                "docker",
                "--context",
                config.docker_context,
                "network",
                "inspect",
                f"{config.project}-scanner",
                "--format",
                "{{json .}}",
            ],
            cwd=self.root,
            env=_safe_process_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            shell=False,
        )
        if result.returncode:
            return None
        try:
            network = json.loads(result.stdout.decode("utf-8"))
            if isinstance(network, list):
                network = network[0] if network else None
            if not isinstance(network, dict):
                return None
            labels = network.get("Labels") or {}
            if labels.get(LAB_LABEL) != config.generation:
                return None
            return bool(network.get("Internal"))
        except (ValueError, IndexError, TypeError):
            return None

    def _list_resources(self, kind: str) -> list[dict[str, Any]]:
        config = self.config()
        if kind not in {"container", "network", "volume"}:
            raise LabError("unsupported Docker resource kind")
        flags = {
            "container": ["ps", "-a", "--format", "{{json .}}"],
            "network": ["network", "ls", "--format", "{{json .}}"],
            "volume": ["volume", "ls", "--format", "{{json .}}"],
        }[kind]
        result = subprocess.run(
            ["docker", "--context", config.docker_context, *flags],
            cwd=self.root,
            env=_safe_process_environment(),
            capture_output=True,
            timeout=15,
            check=False,
            shell=False,
        )
        if result.returncode:
            raise LabError("Docker resource inspection failed")
        rows: list[dict[str, Any]] = []
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = item.get("Names") or item.get("Name") or ""
            if kind == "container" and name:
                inspected = subprocess.run(
                    [
                        "docker",
                        "--context",
                        config.docker_context,
                        "inspect",
                        "--format",
                        "{{json .Config.Labels}}",
                        str(item.get("ID", "")),
                    ],
                    cwd=self.root,
                    env=_safe_process_environment(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    shell=False,
                )
                try:
                    item["_labels"] = json.loads(inspected.stdout.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    item["_labels"] = {}
            elif kind in {"network", "volume"}:
                subcmd = "network" if kind == "network" else "volume"
                inspect_flag = "--format"
                inspect_result = subprocess.run(
                    [
                        "docker",
                        "--context",
                        config.docker_context,
                        subcmd,
                        "inspect",
                        str(name),
                        inspect_flag,
                        "{{json .Labels}}",
                    ],
                    cwd=self.root,
                    env=_safe_process_environment(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    shell=False,
                )
                try:
                    item["_labels"] = json.loads(inspect_result.stdout.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    item["_labels"] = {}
            rows.append(item)
        return rows

    @staticmethod
    def _labels(resource: dict[str, Any]) -> dict[str, str]:
        labels = resource.get("_labels") or {}
        return labels if isinstance(labels, dict) else {}

    @staticmethod
    def _resource_name(resource: dict[str, Any]) -> str:
        return str(resource.get("Names") or resource.get("Name") or "")

    @staticmethod
    def _write_env(values: dict[str, str], path: Path) -> None:
        output = path
        lines = [f"{key}={value}" for key, value in values.items()]
        LabManager._write_private(output, "\n".join(lines) + "\n")

    @staticmethod
    def _write_private(path: Path, contents: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
        with suppress(OSError):
            os.chmod(path, 0o600)
