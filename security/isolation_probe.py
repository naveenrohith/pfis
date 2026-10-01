"""One-shot scanner-network egress and host-gateway probe."""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
from typing import Any


def _reachable(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "connected"
    except OSError as exc:
        return False, f"blocked:{exc.__class__.__name__}"


def discover_host_gateway() -> str:
    """Return the Docker-provided host gateway address for a scoped sentinel."""
    address = ipaddress.ip_address(socket.gethostbyname("host.docker.internal"))
    if not address.is_private or address.is_loopback or address.is_link_local:
        raise ValueError("host gateway is outside the private lab range")
    return str(address)


def run(host_port: int, timeout: float) -> dict[str, Any]:
    if not 1 <= host_port <= 65535 or not 0.2 <= timeout <= 3:
        raise ValueError("probe parameters are outside the fixed range")

    external = {
        "cloudflare_https": _reachable("1.1.1.1", 443, timeout),
        "google_dns": _reachable("8.8.8.8", 53, timeout),
    }
    try:
        host_address = discover_host_gateway()
    except (OSError, ValueError) as exc:
        return {
            "status": "incomplete",
            "detail": f"host gateway did not resolve: {exc.__class__.__name__}",
            "external": external,
        }
    host_accessible, host_result = _reachable(host_address, host_port, timeout)
    external_accessible = any(result[0] for result in external.values())
    result = {
        "status": "failed" if external_accessible or host_accessible else "passed",
        "external": {name: value[1] for name, value in external.items()},
        "host_gateway": {"address": host_address, "result": host_result},
        "external_accessible": external_accessible,
        "host_listener_accessible": host_accessible,
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--host-port", type=int)
    mode.add_argument("--discover-host-gateway", action="store_true")
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.discover_host_gateway:
        try:
            result = {"host_gateway": discover_host_gateway()}
        except (OSError, ValueError):
            print(json.dumps({"status": "incomplete", "detail": "host gateway unavailable"}))
            return 2
        print(json.dumps(result, separators=(",", ":")))
        return 0
    if args.host_port is None:
        parser.error("--host-port is required")
    try:
        result = run(args.host_port, args.timeout)
    except ValueError as exc:
        print(json.dumps({"status": "incomplete", "detail": str(exc)}))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
