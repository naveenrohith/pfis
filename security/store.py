"""Private SQLite evidence store for local security assessments."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from security.parsers import ParsedFinding, sanitize_evidence

RUN_STATES = {"queued", "running", "completed", "failed", "cancelled", "interrupted"}
FINDING_STATES = {"candidate", "confirmed", "false_positive", "fixed_pending_rescan", "resolved"}
_ACTIVE_STATES = ("queued", "running")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SecurityStore:
    def __init__(self, path: Path, retention_days: int = 30) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = max(1, min(int(retention_days), 365))
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level="IMMEDIATE")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    generation TEXT NOT NULL,
                    commit_sha TEXT NOT NULL,
                    profile TEXT NOT NULL,
                    state TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS ix_security_runs_created ON runs(created_at DESC);
                CREATE INDEX IF NOT EXISTS ix_security_runs_state ON runs(state);
                CREATE TABLE IF NOT EXISTS findings (
                    fingerprint TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    reproduction TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    control INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_security_findings_severity ON findings(severity);
                CREATE TABLE IF NOT EXISTS run_findings (
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    fingerprint TEXT NOT NULL REFERENCES findings(fingerprint) ON DELETE CASCADE,
                    PRIMARY KEY (run_id, fingerprint)
                );
                CREATE TABLE IF NOT EXISTS finding_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL REFERENCES findings(fingerprint) ON DELETE CASCADE,
                    old_status TEXT NOT NULL,
                    new_status TEXT NOT NULL,
                    note TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    body_json TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row["name"]) for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "cancel_requested" not in columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0"
                )
            cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
            connection.execute("DELETE FROM reports WHERE created_at < ?", (cutoff,))

    def interrupt_active_runs(self) -> list[dict[str, Any]]:
        """Mark abandoned work interrupted after the coordinator owns the process lock."""
        with self._lock, self._connect() as connection:
            run_ids = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM runs WHERE state IN ('queued','running')"
                ).fetchall()
            ]
        for run_id in run_ids:
            self.set_run_state(
                run_id,
                "interrupted",
                summary={
                    "coverage_complete": False,
                    "coverage": [],
                    "stop_reason": "controller stopped while this assessment was active",
                },
            )
        return [record for run_id in run_ids if (record := self.get_run(run_id)) is not None]

    def create_run(
        self, run_id: str, generation: str, commit_sha: str, profile: str
    ) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM runs WHERE state IN ('queued','running') LIMIT 1"
            ).fetchone()
            if existing:
                raise RuntimeError("an assessment is already queued or running")
            connection.execute(
                "INSERT INTO runs(id,generation,commit_sha,profile,state,created_at) VALUES(?,?,?,?,?,?)",
                (run_id, generation, commit_sha, profile, "queued", now),
            )
        return self.get_run(run_id) or {}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            return dict(row) if row else None

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def set_run_state(
        self,
        run_id: str,
        state: str,
        *,
        summary: dict[str, Any] | None = None,
    ) -> None:
        if state not in RUN_STATES:
            raise ValueError("unknown run state")
        now = utc_now()
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError("assessment run was not found")
            old = str(row["state"])
            allowed = {
                "queued": {"running", "cancelled", "interrupted", "failed"},
                "running": {"completed", "failed", "cancelled", "interrupted"},
            }
            if state != old and state not in allowed.get(old, set()):
                raise ValueError(f"invalid run-state transition: {old} -> {state}")
            started_at = now if state == "running" and old == "queued" else None
            finished_at = (
                now if state in {"completed", "failed", "cancelled", "interrupted"} else None
            )
            connection.execute(
                "UPDATE runs SET state=?, started_at=COALESCE(?,started_at), "
                "finished_at=COALESCE(?,finished_at), summary=COALESCE(?,summary) WHERE id=?",
                (
                    state,
                    started_at,
                    finished_at,
                    json.dumps(summary, ensure_ascii=True) if summary is not None else None,
                    run_id,
                ),
            )
            if finished_at:
                self._save_report(connection, run_id)

    def request_cancel(self, run_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET cancel_requested=1 WHERE id=? AND state IN ('queued','running')",
                (run_id,),
            )
            if cursor.rowcount == 0:
                row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                if row is None:
                    raise KeyError("assessment run was not found")
                return dict(row)
        return self.get_run(run_id) or {}

    def add_findings(self, run_id: str, findings: list[ParsedFinding]) -> None:
        now = utc_now()
        with self._lock, self._connect() as connection:
            for finding in findings:
                row = connection.execute(
                    "SELECT evidence_json FROM findings WHERE fingerprint=?", (finding.fingerprint,)
                ).fetchone()
                if row:
                    evidence = json.loads(row["evidence_json"])
                    evidence.append(
                        {
                            "tool": finding.tool,
                            "value": sanitize_evidence(finding.evidence),
                            "observed_at": now,
                        }
                    )
                    evidence = evidence[-20:]
                    connection.execute(
                        "UPDATE findings SET evidence_json=?, last_seen=? WHERE fingerprint=?",
                        (json.dumps(evidence, ensure_ascii=True), now, finding.fingerprint),
                    )
                else:
                    evidence = [
                        {
                            "tool": finding.tool,
                            "value": sanitize_evidence(finding.evidence),
                            "observed_at": now,
                        }
                    ]
                    connection.execute(
                        "INSERT INTO findings(fingerprint,title,severity,confidence,target_id,endpoint,tool,"
                        "evidence_json,reproduction,control,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?, ?,?)",
                        (
                            finding.fingerprint,
                            sanitize_evidence(finding.title),
                            finding.severity,
                            finding.confidence,
                            finding.target_id,
                            sanitize_evidence(finding.endpoint),
                            finding.tool,
                            json.dumps(evidence, ensure_ascii=True),
                            sanitize_evidence(finding.reproduction),
                            int(finding.control),
                            "candidate",
                            now,
                            now,
                        ),
                    )
                connection.execute(
                    "INSERT OR IGNORE INTO run_findings(run_id,fingerprint) VALUES(?,?)",
                    (run_id, finding.fingerprint),
                )

    def list_findings(self, include_controls: bool = False) -> list[dict[str, Any]]:
        predicate = "" if include_controls else "WHERE control=0"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM findings {predicate} ORDER BY "
                "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 "
                "WHEN 'low' THEN 3 ELSE 4 END, last_seen DESC"
            ).fetchall()
            return [self._finding_dict(row) for row in rows]

    def update_finding(self, fingerprint: str, status: str, note: str) -> dict[str, Any]:
        if status not in FINDING_STATES:
            raise ValueError("unknown finding state")
        note = sanitize_evidence(note)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM findings WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if row is None:
                raise KeyError("finding was not found")
            old_status = str(row["status"])
            if old_status != status:
                connection.execute(
                    "UPDATE findings SET status=? WHERE fingerprint=?", (status, fingerprint)
                )
                connection.execute(
                    "INSERT INTO finding_history(fingerprint,old_status,new_status,note,changed_at) "
                    "VALUES(?,?,?,?,?)",
                    (fingerprint, old_status, status, note, utc_now()),
                )
            result = connection.execute(
                "SELECT * FROM findings WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            return self._finding_dict(result)

    def triage_history(self, fingerprint: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT old_status,new_status,note,changed_at FROM finding_history "
                "WHERE fingerprint=? ORDER BY id",
                (fingerprint,),
            ).fetchall()
            return [dict(row) for row in rows]

    def report(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT body_json FROM reports WHERE run_id=? ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            return json.loads(row["body_json"]) if row else None

    def _save_report(self, connection: sqlite3.Connection, run_id: str) -> None:
        run = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        findings = connection.execute(
            "SELECT f.* FROM findings f JOIN run_findings rf USING(fingerprint) WHERE rf.run_id=?",
            (run_id,),
        ).fetchall()
        body = {
            "run": dict(run) if run else {},
            "findings": [self._finding_dict(row) for row in findings],
            "coverage": json.loads(run["summary"] or "{}") if run else {},
        }
        body_text = json.dumps(body, ensure_ascii=True, separators=(",", ":"))
        connection.execute(
            "INSERT INTO reports(id,run_id,created_at,body_json) VALUES(?,?,?,?)",
            (run_id, run_id, utc_now(), body_text),
        )
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
        connection.execute("DELETE FROM reports WHERE created_at < ?", (cutoff,))

    @staticmethod
    def _finding_dict(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["evidence"] = json.loads(item.pop("evidence_json"))
        item["control"] = bool(item["control"])
        return item
