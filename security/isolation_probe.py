"""One-shot scanner-network egress and host-gateway probe."""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any


def _reachable(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "connected"
    except OSError as exc:
        return False, f"blocked:{exc.__class__.__name__}"


def run(host_port: int, timeout: float) -> dict[str, Any]:
    if not 1 <= host_port <= 65535 or not 0.2 <= timeout <= 3:
        raise ValueError("probe parameters are outside the fixed range")

    external = {
        "cloudflare_https": _reachable("1.1.1.1", 443, timeout),
        "google_dns": _reachable("8.8.8.8", 53, timeout),
    }
    try:
        host_address = socket.gethostbyname("host.docker.internal")
    except OSError as exc:
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
    parser.add_argument("--host-port", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args(argv)
    try:
        result = run(args.host_port, args.timeout)
    except ValueError as exc:
        print(json.dumps({"status": "incomplete", "detail": str(exc)}))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
