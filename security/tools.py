"""Fixed, reviewed scanner argv builders. Callers may select IDs, never argv."""

from __future__ import annotations

from dataclasses import dataclass

from security.registry import PROFILE_TARGETS, PROFILE_TOOL_IDS, TARGETS


@dataclass(frozen=True)
class ToolCommand:
    tool_id: str
    target_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    service: str | None = None


NMAP_SCRIPT_ALLOWLIST = ("banner", "http-title", "http-headers", "ssl-cert")
NUCLEI_TEMPLATE_DIR = "/opt/pfis/nuclei-templates"


def build_tool_command(tool_id: str, target_id: str, profile_id: str) -> ToolCommand:
    """Build arguments only from the immutable target/profile/tool registries."""
    allowed_tools = PROFILE_TOOL_IDS.get(profile_id)
    allowed_targets = PROFILE_TARGETS.get(profile_id)
    if allowed_tools is None or allowed_targets is None:
        raise ValueError("unknown assessment profile")
    if tool_id not in allowed_tools or target_id not in allowed_targets:
        raise ValueError("tool or target is not registered for this profile")
    target = TARGETS[target_id]

    if tool_id == "nmap" and target_id == "pfis-web":
        argv = (
            "-Pn",
            "-n",
            "-sT",
            "-sV",
            "--version-light",
            "--top-ports",
            "1000",
            "--reason",
            "--script",
            ",".join(NMAP_SCRIPT_ALLOWLIST),
            "-oX",
            "-",
            target.host,
        )
        return ToolCommand(tool_id, target_id, argv, 180)

    if tool_id == "testssl" and target_id == "pfis-web":
        return ToolCommand(
            tool_id,
            target_id,
            (f"{target.host}:{target.port}",),
            300,
        )

    if tool_id == "zap" and target_id == "pfis-web":
        if profile_id == "frontend":
            return ToolCommand(
                tool_id,
                target_id,
                ("frontend", "--target-id", target_id),
                180,
                "zap",
            )
        if profile_id in {"baseline", "passive"}:
            return ToolCommand(
                tool_id,
                target_id,
                ("passive", "--target-id", target_id),
                180,
                "zap",
            )
        if profile_id == "application":
            return ToolCommand(
                tool_id,
                target_id,
                ("authenticated-api", "--target-id", "pfis-web"),
                2_100,
                "zap-api",
            )

    if tool_id == "nuclei" and target_id == "pfis-web":
        return ToolCommand(
            tool_id,
            target_id,
            (
                "-u",
                target.url,
                "-t",
                NUCLEI_TEMPLATE_DIR,
                "-duc",
                "-disable-update-check",
                "-no-interactsh",
                "-rl",
                "5",
                "-timeout",
                "5",
                "-retries",
                "0",
                "-jsonl",
                "-silent",
            ),
            180,
        )

    if tool_id == "sqlmap" and target_id == "sqli-fixture":
        return ToolCommand(
            tool_id,
            target_id,
            (
                "-u",
                f"{target.url}/item?id=1",
                "--batch",
                "--disable-coloring",
                "--flush-session",
                "--smart",
                "--technique=BEUSTQ",
                "--risk=1",
                "--level=1",
                "--threads=1",
                "--timeout=5",
                "--retries=0",
                "--delay=0.2",
                "--output-dir=/tmp/sqlmap-output",
            ),
            240,
        )

    if tool_id == "metasploit" and target_id == "metasploit-fixture":
        resource_commands = (
            "use exploit/unix/ftp/vsftpd_234_backdoor; "
            "set TARGET 1; set PAYLOAD cmd/unix/interact; "
            f"set RHOSTS {target.host}; set RPORT {target.port}; "
            "set WfsDelay 1; exploit -j; sleep 2; sessions -K; exit -y"
        )
        # Target and module are fixed; the derived image clears Rapid7's
        # writable account-setup entrypoint and runs this command directly.
        return ToolCommand(tool_id, target_id, ("./msfconsole", "-q", "-x", resource_commands), 180)

    if tool_id == "greenbone" and target_id == "pfis-web":
        return ToolCommand(tool_id, target_id, ("scan", "--target-id", "pfis-web"), 3600)

    raise ValueError("no reviewed command is registered for this profile")


def commands_for_profile(profile_id: str) -> tuple[ToolCommand, ...]:
    """Resolve a profile to its fixed ordered target/tool commands."""
    if profile_id == "full":
        command_groups = (
            *(
                commands_for_profile(name)
                for name in ("baseline", "application", "frontend", "infrastructure")
            ),
            commands_for_profile("exploit-validation"),
        )
        return tuple(command for group in command_groups for command in group)

    tools = PROFILE_TOOL_IDS.get(profile_id)
    targets = PROFILE_TARGETS.get(profile_id)
    if tools is None or targets is None:
        raise ValueError("unknown assessment profile")
    result: list[ToolCommand] = []
    if profile_id in {"passive", "frontend"}:
        result.append(build_tool_command("zap", "pfis-web", profile_id))
    elif profile_id == "baseline":
        for tool in ("nmap", "testssl", "zap", "nuclei"):
            result.append(build_tool_command(tool, "pfis-web", profile_id))
    elif profile_id == "application":
        result.extend(
            (
                build_tool_command("zap", "pfis-web", profile_id),
                build_tool_command("nuclei", "pfis-web", profile_id),
            )
        )
    elif profile_id == "infrastructure":
        result.append(build_tool_command("greenbone", "pfis-web", profile_id))
    elif profile_id == "exploit-validation":
        result.extend(
            (
                build_tool_command("sqlmap", "sqli-fixture", profile_id),
                build_tool_command("metasploit", "metasploit-fixture", profile_id),
            )
        )
    else:
        raise ValueError("unknown assessment profile")
    return tuple(result)
