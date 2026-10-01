"""Immutable target, tool, and assessment profile registries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Target:
    id: str
    host: str
    port: int
    scheme: str
    synthetic: bool
    destructive: bool = False
    private_ca: bool = False

    @property
    def url(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        suffix = "" if self.port == default_port else f":{self.port}"
        return f"{self.scheme}://{self.host}{suffix}"


@dataclass(frozen=True)
class Tool:
    id: str
    service: str
    version: str
    image: str
    capabilities: tuple[str, ...]
    runtime_image: str | None = None
    source_revision: str | None = None


@dataclass(frozen=True)
class Profile:
    id: str
    title: str
    tools: tuple[str, ...]
    destructive: bool = False
    description: str = ""


TARGETS: Final[dict[str, Target]] = {
    "pfis-web": Target("pfis-web", "pfis.test", 443, "https", True, private_ca=True),
    "sqli-fixture": Target("sqli-fixture", "sqli-fixture", 8080, "http", True, True),
    "metasploit-fixture": Target(
        "metasploit-fixture", "metasploit-fixture", 2121, "tcp", True, True
    ),
}

# Image references are content-addressed; the display version is independently
# checked by the preparation command before a tool can be marked ready.
TOOLS: Final[dict[str, Tool]] = {
    "zap": Tool(
        "zap",
        "zap",
        "2.17.0",
        "ghcr.io/zaproxy/zaproxy:stable@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef",
        ("passive", "frontend-passive", "openapi", "authenticated-api"),
        runtime_image="pfis-security-zap:2.17.0",
    ),
    "nuclei": Tool(
        "nuclei",
        "nuclei",
        "3.11.1",
        "projectdiscovery/nuclei:v3.11.1@sha256:582d5546902e67052097cb2d07296c642d50a1afc5e44623cb038845df9a32eb",
        ("http", "tls"),
        runtime_image="pfis-security-nuclei:3.11.1",
    ),
    "nmap": Tool(
        "nmap",
        "nmap",
        "7.97",
        "instrumentisto/nmap:7.97@sha256:14f6a358dde31433690efe3b636472983fa99df1ced025ed04c6e39f0ad37355",
        ("ports", "service-versions"),
    ),
    "testssl": Tool(
        "testssl",
        "testssl",
        "3.2.4",
        "ghcr.io/testssl/testssl.sh:latest@sha256:d02d3b2e03f61c20838d788b7c5102e1c5bdcf85ead96a1bc9aa8c2657d9282b",
        ("tls",),
        runtime_image="pfis-security-testssl:3.2.4",
    ),
    "greenbone": Tool(
        "greenbone",
        "greenbone-control",
        "community-feed",
        "registry.community.greenbone.net/community/gvm-tools:latest@sha256:a3ec2b8d2281e1a0bea147f1a6fbe00d22eab26db1c114bebf7bb2beed0a5619",
        ("infrastructure-vulnerability-management",),
        runtime_image="pfis-security-greenbone-control:community",
    ),
    "sqlmap": Tool(
        "sqlmap",
        "sqlmap",
        "1.10",
        "python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d",
        ("bounded-sqli-detection",),
        runtime_image="pfis-security-sqlmap:1.10",
        source_revision="sqlmap@ea8c6bdb63a3b2da1584f328836eb0d28116f7c4",
    ),
    "metasploit": Tool(
        "metasploit",
        "metasploit",
        "framework-locked-by-image-digest",
        "metasploitframework/metasploit-framework:latest@sha256:a05bb5cac4c4d95b2ebeb972813ce17b2da022d7647c4f17e9537bffa2906ed6",
        ("registered-module-validation",),
    ),
}

PROFILES: Final[dict[str, Profile]] = {
    "passive": Profile(
        "passive",
        "Passive ZAP",
        ("zap-passive",),
        description="A bounded passive ZAP scan for an ephemeral CI lab.",
    ),
    "frontend": Profile(
        "frontend",
        "Frontend coverage",
        ("zap-frontend",),
        description="A passive ZAP crawl starting from the registered PFIS dashboard route.",
    ),
    "baseline": Profile(
        "baseline",
        "Baseline",
        ("nmap", "testssl", "zap-passive", "nuclei"),
        description="Port inventory, TLS posture, passive ZAP, and reviewed HTTP/TLS templates.",
    ),
    "application": Profile(
        "application",
        "Application",
        ("zap-api", "auth-boundary-tests", "nuclei"),
        description="Authenticated API and application-boundary checks using synthetic identities.",
    ),
    "infrastructure": Profile(
        "infrastructure",
        "Infrastructure",
        ("greenbone",),
        description="Greenbone Community assessment of registered lab services.",
    ),
    "exploit-validation": Profile(
        "exploit-validation",
        "Exploit validation",
        ("sqlmap-fixture", "metasploit-fixture"),
        destructive=True,
        description="Known-vulnerable disposable fixtures only; no arbitrary module selection.",
    ),
}

PROFILE_TOOL_IDS: Final[dict[str, tuple[str, ...]]] = {
    "passive": ("zap",),
    "frontend": ("zap",),
    "baseline": ("nmap", "testssl", "zap", "nuclei"),
    "application": ("zap", "auth-boundary", "nuclei"),
    "infrastructure": ("greenbone",),
    "exploit-validation": ("sqlmap", "metasploit"),
    "full": (
        "nmap",
        "testssl",
        "zap",
        "auth-boundary",
        "nuclei",
        "greenbone",
        "sqlmap",
        "metasploit",
    ),
}

PROFILE_TARGETS: Final[dict[str, tuple[str, ...]]] = {
    "passive": ("pfis-web",),
    "frontend": ("pfis-web",),
    "baseline": ("pfis-web",),
    "application": ("pfis-web",),
    "infrastructure": ("pfis-web",),
    "exploit-validation": ("sqli-fixture", "metasploit-fixture"),
    "full": ("pfis-web", "sqli-fixture", "metasploit-fixture"),
}

ALL_PROFILE_IDS: Final[frozenset[str]] = frozenset((*PROFILES.keys(), "full"))
ALLOWED_SERVICES: Final[frozenset[str]] = frozenset(
    {tool.service for tool in TOOLS.values()} | {"zap-api"}
)
