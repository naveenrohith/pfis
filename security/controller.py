"""Loopback-only operator API for local PFIS security assessments."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.responses import Response as RawResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from security.assessment import AssessmentCoordinator
from security.lab import LabManager
from security.parsers import sanitize_evidence
from security.registry import ALL_PROFILE_IDS, PROFILE_TARGETS
from security.scope import ScopeViolation
from security.store import FINDING_STATES, SecurityStore

PAIRING_WINDOW_SECONDS = 300
SESSION_TTL_SECONDS = 3600
COOKIE_NAME = "__Host-pfis-security"
CSRF_HEADER = "X-CSRF-Token"
ALLOWED_FINDING_STATES = FINDING_STATES


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class RunRequest(BaseModel):
    profile_id: str = Field(min_length=1, max_length=32)
    target_ids: list[str] = Field(default_factory=list, max_length=8)


class TriageRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    note: str = Field(default="", max_length=2000)


@dataclass
class Session:
    expires_at: float


class PairingAuth:
    def __init__(self, port: int) -> None:
        self.port = port
        self.code = f"{secrets.randbelow(1_000_000):06d}"
        self.code_expires_at = time.monotonic() + PAIRING_WINDOW_SECONDS
        self.code_hash = hashlib.sha256(self.code.encode()).digest()
        self.csrf_key = secrets.token_bytes(32)
        self.sessions: dict[str, Session] = {}
        self.failed_attempts = 0
        self.lock_until = 0.0

    @property
    def origin(self) -> str:
        return f"http://localhost:{self.port}"

    @property
    def host(self) -> str:
        return f"localhost:{self.port}"

    def validate_host(self, request: Request) -> None:
        if request.headers.get("host", "").lower() != self.host:
            raise HTTPException(status_code=421, detail="Host is not allowed")

    def validate_origin(self, request: Request) -> None:
        if request.headers.get("origin") != self.origin:
            raise HTTPException(status_code=403, detail="Exact local Origin is required")

    def pair(self, code: str) -> tuple[str, str]:
        now = time.monotonic()
        if now < self.lock_until:
            raise HTTPException(status_code=429, detail="Pairing is temporarily rate limited")
        supplied = hashlib.sha256(code.encode()).digest()
        if now > self.code_expires_at or not hmac.compare_digest(supplied, self.code_hash):
            self.failed_attempts += 1
            if self.failed_attempts >= 5:
                self.lock_until = now + 60
                self.failed_attempts = 0
            raise HTTPException(status_code=403, detail="Pairing code is invalid or expired")
        self.code_expires_at = 0
        session_id = secrets.token_urlsafe(32)
        self.sessions[hashlib.sha256(session_id.encode()).hexdigest()] = Session(
            expires_at=now + SESSION_TTL_SECONDS
        )
        return session_id, self.csrf_token(session_id)

    def validate_session(self, session_id: str | None) -> str:
        if not session_id:
            raise HTTPException(status_code=401, detail="Operator pairing is required")
        key = hashlib.sha256(session_id.encode()).hexdigest()
        session = self.sessions.get(key)
        if session is None or session.expires_at <= time.monotonic():
            self.sessions.pop(key, None)
            raise HTTPException(status_code=401, detail="Operator session expired")
        return session_id

    def csrf_token(self, session_id: str) -> str:
        return hmac.new(self.csrf_key, session_id.encode(), hashlib.sha256).hexdigest()

    def validate_csrf(self, session_id: str, supplied: str | None) -> None:
        if not supplied or not hmac.compare_digest(self.csrf_token(session_id), supplied):
            raise HTTPException(status_code=403, detail="CSRF validation failed")


def create_controller(
    root: Path,
    *,
    port: int,
    store: SecurityStore | None = None,
    lab: LabManager | None = None,
) -> FastAPI:
    root = root.resolve()
    metadata = root / ".security-local"
    store = store or SecurityStore(metadata / "security.sqlite3")
    lab = lab or LabManager(root)
    coordinator = AssessmentCoordinator(root, store, lab)
    pairing = PairingAuth(port)

    app = FastAPI(
        title="PFIS Local Security Console",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.security_store = store
    app.state.security_lab = lab
    app.state.security_coordinator = coordinator
    app.state.pairing = pairing

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        try:
            pairing.validate_host(request)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                pairing.validate_origin(request)
        except HTTPException as exc:
            return JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
            )
        return await call_next(request)

    def require_session(request: Request) -> str:
        return pairing.validate_session(request.cookies.get(COOKIE_NAME))

    def require_mutation(request: Request, session_id: str = Depends(require_session)) -> str:
        pairing.validate_csrf(session_id, request.headers.get(CSRF_HEADER))
        return session_id

    @app.post("/security-api/pair")
    def pair_operator(data: PairRequest, request: Request, response: Response) -> dict[str, str]:
        pairing.validate_origin(request)
        session_id, csrf = pairing.pair(data.code)
        response.set_cookie(
            COOKIE_NAME,
            session_id,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="strict",
            path="/",
        )
        return {"csrf_token": csrf, "expires_in": str(SESSION_TTL_SECONDS)}

    @app.get("/security-api/session")
    def current_session(session_id: str = Depends(require_session)) -> dict[str, str]:
        return {
            "csrf_token": pairing.csrf_token(session_id),
            "expires_in": str(SESSION_TTL_SECONDS),
        }

    @app.post("/security-api/logout")
    def logout_operator(
        response: Response, session_id: str = Depends(require_mutation)
    ) -> dict[str, str]:
        pairing.sessions.pop(hashlib.sha256(session_id.encode()).hexdigest(), None)
        response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
        return {"status": "logged_out"}

    @app.get("/security-api/lab")
    def lab_status(_session_id: str = Depends(require_session)) -> dict[str, Any]:
        try:
            return lab.status()
        except Exception as exc:
            return {"ready": False, "detail": sanitize_evidence(str(exc))}

    @app.get("/security-api/tools")
    def tool_readiness(_session_id: str = Depends(require_session)) -> dict[str, Any]:
        try:
            lab.verify_identity()
            lab_ready = True
        except Exception as exc:
            lab_ready = False
            lab_error = sanitize_evidence(str(exc))
        tools = lab.tool_readiness()
        if not lab_ready:
            for tool in tools:
                tool["ready"] = False
                tool["status"] = "not_ready"
                tool["detail"] = lab_error
        return {"tools": tools, "lab_ready": lab_ready}

    @app.get("/security-api/runs")
    def list_runs(
        limit: int = 100, _session_id: str = Depends(require_session)
    ) -> list[dict[str, Any]]:
        return store.list_runs(limit)

    @app.post("/security-api/runs", status_code=status.HTTP_202_ACCEPTED)
    def create_run(
        data: RunRequest,
        _session_id: str = Depends(require_mutation),
    ) -> dict[str, Any]:
        if data.profile_id not in ALL_PROFILE_IDS:
            raise HTTPException(status_code=422, detail="Unknown assessment profile")
        try:
            targets = data.target_ids or list(PROFILE_TARGETS[data.profile_id])
            return coordinator.enqueue(data.profile_id, targets)
        except ScopeViolation as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=sanitize_evidence(str(exc))) from exc

    @app.get("/security-api/runs/{run_id}")
    def get_run(run_id: str, _session_id: str = Depends(require_session)) -> dict[str, Any]:
        record = store.get_run(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Assessment run not found")
        return record

    @app.post("/security-api/runs/{run_id}/cancel")
    def cancel_run(
        run_id: str,
        _session_id: str = Depends(require_mutation),
    ) -> dict[str, Any]:
        try:
            return coordinator.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/security-api/findings")
    def list_findings(_session_id: str = Depends(require_session)) -> list[dict[str, Any]]:
        return store.list_findings()

    @app.patch("/security-api/findings/{fingerprint}")
    def triage_finding(
        fingerprint: str,
        data: TriageRequest,
        _session_id: str = Depends(require_mutation),
    ) -> dict[str, Any]:
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise HTTPException(status_code=404, detail="Finding not found")
        try:
            return store.update_finding(fingerprint, data.status, data.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/security-api/findings/{fingerprint}/history")
    def finding_history(
        fingerprint: str,
        _session_id: str = Depends(require_session),
    ) -> list[dict[str, Any]]:
        return store.triage_history(fingerprint)

    @app.post("/security-api/findings/{fingerprint}/rescan", status_code=status.HTTP_202_ACCEPTED)
    def rescan_finding(
        fingerprint: str,
        _session_id: str = Depends(require_mutation),
    ) -> dict[str, Any]:
        finding = next(
            (item for item in store.list_findings() if item["fingerprint"] == fingerprint), None
        )
        if finding is None:
            raise HTTPException(status_code=404, detail="Finding not found")
        profile = "baseline" if finding["target_id"] == "pfis-web" else "exploit-validation"
        try:
            return coordinator.enqueue(profile, list(PROFILE_TARGETS[profile]))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/security-api/reports")
    def reports(_session_id: str = Depends(require_session)) -> list[dict[str, Any]]:
        return [
            {
                "id": item["id"],
                "profile": item["profile"],
                "state": item["state"],
                "created_at": item["created_at"],
                "finished_at": item["finished_at"],
            }
            for item in store.list_runs()
            if item["state"] in {"completed", "failed", "cancelled", "interrupted"}
        ]

    @app.get("/security-api/reports/{run_id}")
    def report_attachment(run_id: str, _session_id: str = Depends(require_session)) -> RawResponse:
        body = store.report(run_id)
        if body is None:
            raise HTTPException(status_code=404, detail="Report has expired or does not exist")
        content = json.dumps(body, ensure_ascii=True, separators=(",", ":"))
        return RawResponse(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="pfis-security-{run_id}.json"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @app.post("/security-api/lab/reset")
    def reset_lab(_session_id: str = Depends(require_mutation)) -> dict[str, str]:
        try:
            with coordinator.lab_maintenance():
                lab.reset()
                lab.start()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=sanitize_evidence(str(exc))) from exc
        return {"status": "reset", "generation": lab.config().generation}

    static_dir = root / "frontend" / "security-dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="security-console")
    else:

        @app.get("/")
        def missing_console() -> JSONResponse:
            return JSONResponse(
                {
                    "detail": "Security console is not built. Run npm --prefix frontend run security:build."
                },
                status_code=503,
            )

    return app
