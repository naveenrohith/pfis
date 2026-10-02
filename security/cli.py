"""Developer CLI for preparing and operating the isolated PFIS security lab."""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from pathlib import Path
from typing import Any

import uvicorn

from security.assessment import AssessmentCoordinator
from security.auth_boundary import run_auth_boundary_checks
from security.controller import create_controller
from security.lab import LabError, LabManager
from security.process_lock import ProcessLock
from security.registry import ALL_PROFILE_IDS
from security.scope import resolve_targets
from security.store import SecurityStore

ROOT = Path(__file__).resolve().parents[1]
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=True, indent=2, default=str))


def _store() -> SecurityStore:
    return SecurityStore(ROOT / ".security-local" / "security.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/security.py",
        description="Prepare and run the local, synthetic PFIS security assessment lab.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare", help="generate local credentials and prepare pinned images"
    )
    preparation_mode = prepare.add_mutually_exclusive_group()
    preparation_mode.add_argument(
        "--lightweight",
        action="store_true",
        help="prepare only PFIS, fixture, and passive ZAP images (for ephemeral CI labs)",
    )
    preparation_mode.add_argument(
        "--extended",
        action="store_true",
        help="prepare PFIS, ZAP, Nuclei, Nmap, and testssl without Greenbone feeds",
    )

    lab = commands.add_parser("lab", help="manage the disposable PFIS lab")
    lab_actions = lab.add_subparsers(dest="lab_action", required=True)
    start = lab_actions.add_parser(
        "start", help="apply migrations, seed synthetic users, and start HTTPS lab"
    )
    start.add_argument(
        "--lightweight",
        action="store_true",
        help="omit the Metasploitable fixture (for bounded passive CI assessments)",
    )
    lab_actions.add_parser("status", help="inspect only resources labelled for this lab generation")
    lab_actions.add_parser(
        "reset", help="stop and remove only resources labelled for this generation"
    )

    commands.add_parser(
        "console", help="start the loopback-only operator console and show pairing code"
    )

    run = commands.add_parser("run", help="start one registered assessment profile")
    run.add_argument("--profile", required=True, choices=sorted(ALL_PROFILE_IDS))
    run.add_argument(
        "--target",
        action="append",
        dest="target_ids",
        help="registered target ID; repeat to match profile scope",
    )

    status = commands.add_parser("status", help="show assessment runs or one run")
    status.add_argument("--run-id")

    cancel = commands.add_parser(
        "cancel", help="request cancellation of a queued or running assessment"
    )
    cancel.add_argument("run_id")

    report = commands.add_parser(
        "report", help="export one sanitized JSON report under .security-local/reports"
    )
    report.add_argument("run_id")

    commands.add_parser("findings", help="list local PFIS findings without fixture controls")
    commands.add_parser(
        "verify-boundaries", help="run the registered synthetic-user application boundary checks"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lab = LabManager(ROOT)
    try:
        if args.command == "prepare":
            config = lab.prepare_config()
            receipt = lab.prepare_images(lightweight=args.lightweight, extended=args.extended)
            _json(
                {
                    "status": "prepared",
                    "generation": config.generation,
                    "branch_commit": _branch_commit(),
                    "https_url": f"https://localhost:{config.https_port}",
                    "synthetic_credentials_file": str(lab.credentials_file),
                    "image_receipt": receipt,
                    "preparation_mode": (
                        "lightweight"
                        if args.lightweight
                        else "extended" if args.extended else "full"
                    ),
                    "network_policy": "scanner network is internal; feed egress is temporary and disconnected before scans",
                }
            )
            return 0

        if args.command == "lab":
            if args.lab_action == "start":
                lab.start(lightweight=args.lightweight)
                _json({"status": "running", **lab.status()})
            elif args.lab_action == "status":
                _json(lab.status())
            elif args.lab_action == "reset":
                lock = ProcessLock(lab.metadata / "assessment.lock")
                if not lock.try_acquire():
                    raise LabError("lab reset is blocked by a running assessment")
                try:
                    lab.reset()
                    _json({"status": "stopped", "generation": lab.config().generation})
                finally:
                    lock.release()
            return 0

        if args.command == "console":
            port = _available_port()
            app = create_controller(ROOT, port=port, store=_store(), lab=lab)
            print(f"Security console: http://localhost:{port}")
            print(f"One-time pairing code (valid for five minutes): {app.state.pairing.code}")
            print("The controller is bound to 127.0.0.1 and does not accept remote clients.")
            uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")
            return 0

        if args.command == "run":
            targets = resolve_targets(args.profile, args.target_ids)
            store = _store()
            coordinator = AssessmentCoordinator(ROOT, store, lab)
            record = coordinator.enqueue(args.profile, list(targets))
            try:
                coordinator.wait()
            except KeyboardInterrupt:
                # A one-shot process owns the worker thread. Request cancellation and
                # let executor and fixture cleanup finish before allowing Python to exit.
                coordinator.cancel(record["id"])
                coordinator.wait()
                raise
            finished_record = store.get_run(record["id"])
            if finished_record is not None:
                record = finished_record
            _json(record)
            return 0 if record["state"] == "completed" else 1

        if args.command == "status":
            store = _store()
            if args.run_id:
                run_status = store.get_run(args.run_id)
                if run_status is None:
                    raise LabError("assessment run was not found")
                _json(run_status)
            else:
                _json(store.list_runs())
            return 0

        if args.command == "cancel":
            if not RUN_ID_RE.fullmatch(args.run_id):
                raise LabError("run ID is invalid")
            _json(_store().request_cancel(args.run_id))
            return 0

        if args.command == "report":
            if not RUN_ID_RE.fullmatch(args.run_id):
                raise LabError("run ID is invalid")
            store = _store()
            report_body = store.report(args.run_id)
            if report_body is None:
                raise LabError("report has expired or does not exist")
            destination_dir = ROOT / ".security-local" / "reports"
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / f"{args.run_id}.json"
            destination.write_text(
                json.dumps(report_body, ensure_ascii=True, indent=2) + "\n", encoding="utf-8"
            )
            _json({"status": "exported", "path": str(destination)})
            return 0

        if args.command == "findings":
            _json(_store().list_findings())
            return 0

        if args.command == "verify-boundaries":
            config = lab.config()
            lab.verify_identity(required_targets=("sqli-fixture",))
            checks, findings = run_auth_boundary_checks(
                ROOT,
                https_port=config.https_port,
                ca_path=lab.metadata / "caddy-root.crt",
                expected_generation=config.generation,
            )
            failed = [check.check_id for check in checks if check.status != "passed"]
            _json(
                {
                    "generation": config.generation,
                    "synthetic_data": True,
                    "check_count": len(checks),
                    "passed_count": len(checks) - len(failed),
                    "failed_checks": failed,
                    "critical_high_count": len(findings),
                }
            )
            return 1 if failed else 0
    except (LabError, ValueError, RuntimeError) as exc:
        print(f"Security operation failed: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Security operation cancelled.", file=sys.stderr)
        return 130
    return 2


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _branch_commit() -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
        shell=False,
    )
    return (
        result.stdout.decode("ascii", errors="ignore").strip()
        if result.returncode == 0
        else "unknown"
    )


if __name__ == "__main__":
    raise SystemExit(main())
