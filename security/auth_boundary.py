"""Run bounded authentication and ownership checks against the local PFIS lab."""

from __future__ import annotations

import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from security.parsers import ParsedFinding

USER_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
MAX_BODY_BYTES = 256_000


@dataclass(frozen=True)
class BoundaryCheck:
    check_id: str
    status: str
    endpoint: str


@dataclass
class LabIdentity:
    user_id: str
    client: LabHTTPClient
    csrf_cookie_name: str
    csrf_token: str


@dataclass
class LabHTTPClient:
    base_url: str
    context: ssl.SSLContext
    cookies: http.cookiejar.CookieJar = field(default_factory=http.cookiejar.CookieJar)
    opener: urllib.request.OpenerDirector = field(init=False)

    def __post_init__(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=self.context),
            _NoRedirect(),
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        csrf_token: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, bytes, Any]:
        if not path.startswith("/") or "\r" in path or "\n" in path:
            raise ValueError("invalid registered PFIS API path")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            headers["Origin"] = origin or self.base_url
        if csrf_token is not None:
            headers["X-CSRF-Token"] = csrf_token
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8") if body else None
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            headers=headers,
            method=method,
        )
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            data = response.read(MAX_BODY_BYTES + 1)
            if len(data) > MAX_BODY_BYTES:
                raise ValueError("PFIS security response exceeded its size limit")
            return response.status, data, response.headers


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run_auth_boundary_checks(
    root: Path, *, https_port: int, ca_path: Path, expected_generation: str
) -> tuple[list[BoundaryCheck], list[ParsedFinding]]:
    """Exercise synthetic identities, transaction ownership, CSRF, and household roles."""
    checks: list[BoundaryCheck] = []

    def record(check_id: str, passed: bool, endpoint: str) -> None:
        checks.append(BoundaryCheck(check_id, "passed" if passed else "failed", endpoint))

    base_url = f"https://localhost:{https_port}"
    try:
        if not 1 <= https_port <= 65535 or not ca_path.is_file():
            raise ValueError
        credentials_path = root.resolve() / ".security-local" / "lab-credentials.json"
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        if (
            not isinstance(credentials, dict)
            or credentials.get("generation") != expected_generation
        ):
            raise ValueError
        tls_context = ssl.create_default_context(cafile=str(ca_path))
        identities: dict[str, LabIdentity] = {}
        set_cookie_headers: list[str] = []
        for role in ("owner", "member", "viewer"):
            identity_data = credentials.get(role)
            if not isinstance(identity_data, dict):
                raise ValueError
            email = identity_data.get("email")
            password = identity_data.get("password")
            if not isinstance(email, str) or not isinstance(password, str) or len(password) < 24:
                raise ValueError
            client = LabHTTPClient(base_url, tls_context)
            status, body, headers = client.request(
                "POST", "/api/auth/login", body={"email": email, "password": password}
            )
            parsed = json.loads(body) if status == 200 else {}
            user = parsed.get("user", {}) if isinstance(parsed, dict) else {}
            user_id = str(user.get("id", "")) if isinstance(user, dict) else ""
            csrf_name = str(parsed.get("csrf_cookie_name", "")) if isinstance(parsed, dict) else ""
            csrf_cookie = next(
                (cookie for cookie in client.cookies if cookie.name == csrf_name), None
            )
            record(
                f"{role}-synthetic-login",
                status == 200 and bool(USER_ID_RE.fullmatch(user_id)),
                "/api/auth/login",
            )
            if (
                status != 200
                or not USER_ID_RE.fullmatch(user_id)
                or csrf_cookie is None
                or csrf_cookie.value is None
            ):
                return checks, _findings_for_failed_checks(checks)
            set_cookie_headers.extend(headers.get_all("Set-Cookie") or [])
            identities[role] = LabIdentity(user_id, client, csrf_name, csrf_cookie.value)

        session_cookies = [
            line for line in set_cookie_headers if line.startswith("__Host-pfis-session=")
        ]
        csrf_cookies = [line for line in set_cookie_headers if line.startswith("__Host-pfis-csrf=")]
        secure_session = bool(session_cookies) and all(
            "httponly" in line.lower()
            and "secure" in line.lower()
            and "samesite=lax" in line.lower()
            and "path=/" in line.lower()
            and "domain=" not in line.lower()
            for line in session_cookies
        )
        secure_csrf = bool(csrf_cookies) and all(
            "secure" in line.lower() and "samesite=lax" in line.lower() and "path=/" in line.lower()
            for line in csrf_cookies
        )
        record("secure-host-session-cookie", secure_session, "/api/auth/login")
        record("secure-csrf-cookie", secure_csrf, "/api/auth/login")

        owner, member, viewer = (identities[name] for name in ("owner", "member", "viewer"))

        def transactions_path(user_id: str) -> str:
            return "/api/transactions/?" + urllib.parse.urlencode(
                {"user_id": user_id, "limit": 200}
            )

        anonymous = LabHTTPClient(base_url, tls_context)
        anonymous_status, _, _ = anonymous.request("GET", transactions_path(owner.user_id))
        record(
            "anonymous-financial-data-denied", anonymous_status in {401, 403}, "/api/transactions/"
        )

        owner_status, owner_body, _ = owner.client.request("GET", transactions_path(owner.user_id))
        member_status, member_body, _ = member.client.request(
            "GET", transactions_path(member.user_id)
        )
        viewer_status, viewer_body, _ = viewer.client.request(
            "GET", transactions_path(viewer.user_id)
        )
        owner_text = owner_body.decode("utf-8", errors="replace")
        member_text = member_body.decode("utf-8", errors="replace")
        viewer_text = viewer_body.decode("utf-8", errors="replace")
        record(
            "owner-sees-own-synthetic-record",
            owner_status == 200 and "Synthetic Market 1" in owner_text,
            "/api/transactions/",
        )
        record(
            "member-private-record-isolation",
            member_status == 200 and "Synthetic Market 1" not in member_text,
            "/api/transactions/",
        )
        record(
            "viewer-private-record-isolation",
            viewer_status == 200 and "Synthetic Market 1" not in viewer_text,
            "/api/transactions/",
        )

        spoofed_status, spoofed_body, _ = owner.client.request(
            "GET", transactions_path(member.user_id)
        )
        spoofed_text = spoofed_body.decode("utf-8", errors="replace")
        record(
            "authenticated-user-id-cannot-be-spoofed",
            spoofed_status in {200, 403}
            and "Synthetic Market 2" not in spoofed_text
            and (spoofed_status == 403 or "Synthetic Market 1" in spoofed_text),
            "/api/transactions/",
        )

        member_query = urllib.parse.urlencode({"user_id": member.user_id})
        accounts_status, _, _ = owner.client.request("GET", f"/api/accounts?{member_query}")
        record("owner-cannot-read-member-accounts", accounts_status == 403, "/api/accounts")

        export_query = urllib.parse.urlencode({"user_id": member.user_id, "month": 9, "year": 2026})
        export_status, _, _ = owner.client.request("GET", f"/api/reports/export/csv?{export_query}")
        record(
            "owner-cannot-export-member-transactions",
            export_status == 403,
            "/api/reports/export/csv",
        )

        statement_query = urllib.parse.urlencode({"user_id": member.user_id})
        statement_status, _, _ = owner.client.request(
            "POST",
            f"/api/statements/import/text?{statement_query}",
            body={
                "financial_account_id": "00000000-0000-4000-8000-000000000001",
                "document_fingerprint": "a" * 64,
                "statement_text": "Synthetic statement row with a bounded, fictitious test amount.",
            },
            csrf_token=owner.csrf_token,
        )
        record(
            "owner-cannot-import-statement-for-member",
            statement_status == 403,
            "/api/statements/import/text",
        )

        job_status, _, _ = owner.client.request(
            "POST",
            f"/api/jobs/demo-sync-pipeline?{member_query}",
            csrf_token=owner.csrf_token,
        )
        record(
            "owner-cannot-enqueue-member-job",
            job_status == 403,
            "/api/jobs/demo-sync-pipeline",
        )

        gmail_status, _, _ = owner.client.request("GET", f"/api/gmail/status?{member_query}")
        record(
            "owner-cannot-read-member-gmail-status",
            gmail_status == 403,
            "/api/gmail/status",
        )

        statement_record_status, _, _ = owner.client.request(
            "GET",
            f"/api/statements/00000000-0000-4000-8000-000000000001?{member_query}",
        )
        record(
            "owner-cannot-read-member-statement",
            statement_record_status == 403,
            "/api/statements/{statement_id}",
        )

        owner_households_status, households_body, _ = owner.client.request(
            "GET", f"/api/households?user_id={urllib.parse.quote(owner.user_id)}"
        )
        households = json.loads(households_body) if owner_households_status == 200 else []
        household = (
            next(
                (
                    item
                    for item in households
                    if isinstance(item, dict) and item.get("owner_user_id") == owner.user_id
                ),
                None,
            )
            if isinstance(households, list)
            else None
        )
        household_id = str(household.get("id", "")) if isinstance(household, dict) else ""
        if not USER_ID_RE.fullmatch(household_id):
            record("synthetic-household-fixture-ready", False, "/api/households")
            return checks, _findings_for_failed_checks(checks)
        member_path = (
            f"/api/households/{household_id}/members?user_id={urllib.parse.quote(viewer.user_id)}"
        )
        members_status, members_body, _ = viewer.client.request("GET", member_path)
        members = json.loads(members_body) if members_status == 200 else []
        viewer_is_read_only_member = isinstance(members, list) and any(
            isinstance(item, dict)
            and item.get("user_id") == viewer.user_id
            and item.get("role") == "viewer"
            for item in members
        )
        record(
            "viewer-household-read-scope",
            members_status == 200 and viewer_is_read_only_member,
            "/api/households/{id}/members",
        )

        delete_path = (
            f"/api/households/{household_id}/members/{urllib.parse.quote(member.user_id)}"
            f"?user_id={urllib.parse.quote(viewer.user_id)}"
        )
        delete_status, _, _ = viewer.client.request(
            "DELETE", delete_path, csrf_token=viewer.csrf_token
        )
        record(
            "viewer-cannot-remove-household-member",
            delete_status == 403,
            "/api/households/{id}/members/{user_id}",
        )

        empty_payload = {"user_id": owner.user_id}
        mutation_path = "/api/transactions/?" + urllib.parse.urlencode(empty_payload)
        no_csrf_status, _, _ = owner.client.request("POST", mutation_path, body={}, csrf_token=None)
        record("cookie-mutation-requires-csrf", no_csrf_status == 403, "/api/transactions/")
        cross_origin_status, _, _ = owner.client.request(
            "POST",
            mutation_path,
            body={},
            csrf_token=owner.csrf_token,
            origin="https://security-test.invalid",
        )
        record("cross-origin-mutation-denied", cross_origin_status == 403, "/api/transactions/")
        valid_csrf_status, _, _ = owner.client.request(
            "POST", mutation_path, body={}, csrf_token=owner.csrf_token
        )
        record("same-origin-csrf-token-accepted", valid_csrf_status == 422, "/api/transactions/")

        logout_status, _, _ = owner.client.request(
            "POST", "/api/auth/logout", body={}, csrf_token=owner.csrf_token
        )
        revoked_status, _, _ = owner.client.request("GET", "/api/auth/me")
        record(
            "session-revocation-effective",
            logout_status == 200 and revoked_status in {401, 403},
            "/api/auth/logout",
        )
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, urllib.error.URLError):
        checks.append(BoundaryCheck("security-regression-fixture-ready", "failed", "/api/health"))

    return checks, _findings_for_failed_checks(checks)


def _findings_for_failed_checks(checks: list[BoundaryCheck]) -> list[ParsedFinding]:
    return [
        ParsedFinding(
            title=f"Application security regression: {check.check_id}",
            severity="high",
            confidence="high",
            target_id="pfis-web",
            endpoint=f"https://pfis.test{check.endpoint}",
            tool="auth-boundary",
            evidence=f"Fixed synthetic security check failed: {check.check_id}",
            reproduction=check.endpoint,
        )
        for check in checks
        if check.status == "failed" and "fixture-ready" not in check.check_id
    ]
