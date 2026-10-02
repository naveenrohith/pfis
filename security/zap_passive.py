"""Bounded ZAP baseline adapter with an ephemeral report workspace."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

TARGETS = {"pfis-web": "https://pfis.test"}
FRONTEND_TARGETS = {"pfis-web": "https://pfis.test/dashboard"}
REPORT_FILE = Path("/zap/wrk/pfis-zap-baseline.json")
MAX_REPORT_BYTES = 2_000_000
ZAP_OPTIONS = (
    "-silent -Xmx1024m -dir /tmp/zap-data "
    "-config autoupdate.checkOnStart=false "
    "-config autoupdate.installAddonUpdates=false "
    "-config autoupdate.downloadNewRelease=false"
)


def run(target_id: str, *, frontend: bool = False) -> int:
    target = (FRONTEND_TARGETS if frontend else TARGETS).get(target_id)
    executable = shutil.which("zap-baseline.py")
    if target is None or executable is None:
        print("registered ZAP target or baseline adapter is unavailable", file=sys.stderr)
        return 2
    REPORT_FILE.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            [
                executable,
                "-t",
                target,
                "-J",
                REPORT_FILE.name,
                "-T",
                "2",
                "-I",
                "-s",
                "-z",
                ZAP_OPTIONS,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=150,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        print("ZAP baseline process did not complete", file=sys.stderr)
        return 1
    if result.returncode not in {0, 1, 2}:
        print("ZAP baseline exited before producing a complete report", file=sys.stderr)
        return 1
    try:
        if not REPORT_FILE.is_file() or REPORT_FILE.stat().st_size > MAX_REPORT_BYTES:
            raise ValueError
        report = json.loads(REPORT_FILE.read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("site"), list):
            raise ValueError
    except (OSError, json.JSONDecodeError, ValueError):
        print("ZAP baseline report is missing or has an unexpected schema", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
    sys.stdout.write("\n")
    REPORT_FILE.unlink(missing_ok=True)
    return 0


def main() -> int:
    arguments = sys.argv[1:]
    if arguments == ["passive", "--target-id", "pfis-web"]:
        return run("pfis-web")
    if arguments == ["frontend", "--target-id", "pfis-web"]:
        return run("pfis-web", frontend=True)
    else:
        print("ZAP accepts only the registered passive PFIS target.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
