"""Coverage for user-scoped Gmail operations and OAuth helper boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.api.routes import gmail as gmail_routes
from app.models.email import GmailAccount, RawEmail
from app.models.sync import SyncRun, SyncStatus
from app.models.user import User
from app.services.gmail import oauth_service
from fastapi import HTTPException

from tests.pytest.helpers import create_user


async def test_gmail_status_and_email_listing_report_counts_and_filters(
    client, test_session_factory
):
    user = await create_user(client, "gmail-route-status")
    received_at = datetime(2026, 8, 20, 12, tzinfo=UTC)
    async with test_session_factory() as db:
        db.add_all(
            [
                RawEmail(
                    user_id=user["id"],
                    gmail_message_id="status-processed",
                    sender="bank@example.com",
                    subject="Processed",
                    body="processed body",
                    received_at=received_at,
                    processed_flag=True,
                ),
                RawEmail(
                    user_id=user["id"],
                    gmail_message_id="status-pending",
                    sender="bank@example.com",
                    subject="Pending",
                    body="pending body",
                    received_at=received_at - timedelta(hours=1),
                    processed_flag=False,
                ),
                SyncRun(
                    user_id=user["id"],
                    status=SyncStatus.COMPLETED,
                    start_time=received_at - timedelta(minutes=5),
                    end_time=received_at,
                    emails_fetched=2,
                    emails_processed=1,
                    emails_failed=0,
                    coverage_complete=False,
                    coverage_truncated=True,
                    coverage_pages=2,
                    coverage_result_size_estimate=500,
                ),
            ]
        )
        await db.commit()

    status = await client.get(f"/api/gmail/status?user_id={user['id']}")
    status.raise_for_status()
    assert status.json() == {
        "latest_status": "completed",
        "runs": [
            {
                "id": status.json()["runs"][0]["id"],
                "status": "completed",
                "start_time": (received_at - timedelta(minutes=5)).isoformat(),
                "end_time": received_at.isoformat(),
                "emails_fetched": 2,
                "emails_processed": 1,
                "emails_failed": 0,
                "coverage_complete": False,
                "coverage_truncated": True,
                "coverage_pages": 2,
                "coverage_result_size_estimate": 500,
            }
        ],
    }

    all_emails = await client.get(f"/api/gmail/emails?user_id={user['id']}&limit=1")
    all_emails.raise_for_status()
    assert all_emails.json()["total"] == 2
    assert all_emails.json()["all_total"] == 2
    assert all_emails.json()["processed_total"] == 1
    assert all_emails.json()["unprocessed_total"] == 1
    assert all_emails.json()["applied_filter"] is None
    assert len(all_emails.json()["emails"]) == 1
    assert all_emails.json()["emails"][0]["body_preview"] == "processed body"

    pending = await client.get(f"/api/gmail/emails?user_id={user['id']}&processed=false")
    pending.raise_for_status()
    assert pending.json()["total"] == 1
    assert pending.json()["applied_filter"] is False
    assert pending.json()["emails"][0]["gmail_message_id"] == "status-pending"


async def test_gmail_sync_route_returns_provider_stats_on_success(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "gmail-route-sync-success")
    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="sync-success-account",
                access_token_ref="access",
                refresh_token_ref="refresh",
            )
        )
        await db.commit()

    captured: dict[str, object] = {}

    async def fake_sync(**kwargs):
        captured.update(kwargs)
        return {"emails_fetched": 3, "emails_processed": 2}

    monkeypatch.setattr(gmail_routes, "sync_gmail_emails", fake_sync)
    response = await client.post(f"/api/gmail/sync?user_id={user['id']}&max_results=42")

    response.raise_for_status()
    assert response.json() == {
        "status": "completed",
        "stats": {"emails_fetched": 3, "emails_processed": 2},
    }
    assert captured["user_id"] == user["id"]
    assert captured["max_results"] == 42


@pytest.mark.parametrize(
    ("provider_error", "expected"),
    [
        (None, "/dashboard?gmail_auth=success"),
        ("access_denied", "/dashboard?gmail_error=access_denied"),
        ("consent_required", "/dashboard?gmail_error=consent_required"),
        ("org_internal", "/dashboard?gmail_error=provider_rejected"),
        ("temporarily_unavailable", "/dashboard?gmail_error=provider_unavailable"),
        ("unexpected", "/dashboard?gmail_error=provider_rejected"),
    ],
)
def test_gmail_redirect_helpers_use_stable_browser_error_codes(provider_error, expected):
    mapped = gmail_routes._provider_error_code(provider_error) if provider_error else None
    response = gmail_routes._gmail_redirect(error=mapped)
    assert response.status_code == 303
    assert response.headers["location"] == expected


def test_gmail_exception_error_codes_are_stable_and_non_sensitive():
    assert (
        gmail_routes._exception_error_code(HTTPException(status_code=400, detail="transaction"))
        == "gmail_transaction_invalid"
    )
    assert (
        gmail_routes._exception_error_code(HTTPException(status_code=401, detail="identity"))
        == "gmail_identity_invalid"
    )
    assert (
        gmail_routes._exception_error_code(HTTPException(status_code=403, detail="forbidden"))
        == "gmail_connection_forbidden"
    )
    assert (
        gmail_routes._exception_error_code(HTTPException(status_code=409, detail="conflict"))
        == "gmail_account_conflict"
    )
    assert (
        gmail_routes._exception_error_code(HTTPException(status_code=500, detail="provider secret"))
        == "gmail_connection_failed"
    )
    assert (
        gmail_routes._exception_error_code(
            HTTPException(status_code=403, detail="Gmail read-only permission was not granted")
        )
        == "gmail_scope_required"
    )


async def test_gmail_disconnect_reports_unavailable_and_rejected_provider_grants(
    client, test_session_factory, monkeypatch
):
    unavailable = await create_user(client, "gmail-disconnect-no-token")
    rejected = await create_user(client, "gmail-disconnect-rejected")
    async with test_session_factory() as db:
        db.add_all(
            [
                GmailAccount(
                    user_id=unavailable["id"],
                    google_account_id="disconnect-no-token",
                ),
                GmailAccount(
                    user_id=rejected["id"],
                    google_account_id="disconnect-rejected",
                    access_token_ref="access-token",
                ),
            ]
        )
        await db.commit()

    monkeypatch.setattr(gmail_routes, "revoke_google_token", lambda _token: False)
    missing = await client.delete(f"/api/gmail/connection?user_id={unavailable['id']}")
    missing.raise_for_status()
    assert missing.json()["provider_revocation"] == "token_unavailable"

    async def fake_revoke(_token: str) -> bool:
        return False

    monkeypatch.setattr(gmail_routes, "revoke_google_token", fake_revoke)
    rejected_response = await client.delete(f"/api/gmail/connection?user_id={rejected['id']}")
    rejected_response.raise_for_status()
    assert rejected_response.json()["provider_revocation"] == "provider_rejected"


async def test_gmail_connect_rejects_inactive_users_and_hides_startup_failures(
    client, test_session_factory, monkeypatch
):
    inactive = await create_user(client, "gmail-connect-inactive")
    async with test_session_factory() as db:
        owner = await db.get(User, inactive["id"])
        assert owner is not None
        owner.is_active = False
        await db.commit()

    monkeypatch.setattr(
        gmail_routes,
        "get_authorization_url",
        lambda **_kwargs: ("https://accounts.google.test/gmail", "inactive-state", "v", "n"),
    )
    inactive_response = await client.get(
        f"/api/auth/gmail/connect?user_id={inactive['id']}",
        follow_redirects=False,
    )
    assert inactive_response.status_code == 403

    active = await create_user(client, "gmail-connect-failure")

    def fail_authorization(**_kwargs):
        raise RuntimeError("client secret must not be exposed")

    monkeypatch.setattr(gmail_routes, "get_authorization_url", fail_authorization)
    failed = await client.get(
        f"/api/auth/gmail/connect?user_id={active['id']}",
        follow_redirects=False,
    )
    assert failed.status_code == 500
    assert failed.json()["error"]["message"] == "Internal server error"


def test_gmail_token_expiry_normalizes_supported_values():
    assert gmail_routes._parse_token_expiry(None) is None
    assert gmail_routes._parse_token_expiry("") is None
    assert gmail_routes._parse_token_expiry("2026-08-20T12:00:00Z") == datetime(
        2026, 8, 20, 12, tzinfo=UTC
    )
    assert gmail_routes._parse_token_expiry("2026-08-20T12:00:00") == datetime(
        2026, 8, 20, 12, tzinfo=UTC
    )


def test_google_identity_verification_normalizes_profile_and_rejects_bad_claims(monkeypatch):
    payload = {
        "sub": "google-subject",
        "email": " Person@Example.COM ",
        "email_verified": True,
        "nonce": "nonce-1",
        "name": "Person",
        "picture": "https://example.test/avatar",
    }
    monkeypatch.setattr(oauth_service.id_token, "verify_oauth2_token", lambda *_args: payload)
    assert oauth_service.verify_google_identity(
        {"id_token": "id-token"}, expected_nonce="nonce-1"
    ) == {
        "google_account_id": "google-subject",
        "email": "person@example.com",
        "name": "Person",
        "picture": "https://example.test/avatar",
    }

    for token_data, detail in (
        ({}, "Google did not return an ID token"),
        ({"id_token": "id-token"}, "Google account email is missing"),
    ):
        bad_payload = {} if not token_data else {"email_verified": True}
        monkeypatch.setattr(
            oauth_service.id_token,
            "verify_oauth2_token",
            lambda *_args, bad_payload=bad_payload: bad_payload,
        )
        with pytest.raises(HTTPException, match=detail):
            oauth_service.verify_google_identity(token_data)

    invalid = {"email": "person@example.com", "email_verified": False, "sub": "subject"}
    monkeypatch.setattr(oauth_service.id_token, "verify_oauth2_token", lambda *_args: invalid)
    with pytest.raises(HTTPException, match="not verified"):
        oauth_service.verify_google_identity({"id_token": "id-token"})

    nonce_mismatch = {"email": "person@example.com", "email_verified": True, "sub": "subject"}
    monkeypatch.setattr(
        oauth_service.id_token, "verify_oauth2_token", lambda *_args: nonce_mismatch
    )
    with pytest.raises(HTTPException, match="nonce"):
        oauth_service.verify_google_identity({"id_token": "id-token"}, expected_nonce="expected")

    missing_subject = {
        "email": "person@example.com",
        "email_verified": True,
    }
    monkeypatch.setattr(
        oauth_service.id_token, "verify_oauth2_token", lambda *_args: missing_subject
    )
    with pytest.raises(HTTPException, match="identifier"):
        oauth_service.verify_google_identity({"id_token": "id-token"})


def test_google_identity_verification_translates_provider_validation_failure(monkeypatch):
    def fail_verification(*_args):
        raise ValueError("invalid token")

    monkeypatch.setattr(oauth_service.id_token, "verify_oauth2_token", fail_verification)
    with pytest.raises(HTTPException, match="Invalid Google identity token"):
        oauth_service.verify_google_identity({"id_token": "bad-token"})


def test_google_oauth_settings_reject_missing_and_malformed_client_ids(monkeypatch):
    monkeypatch.setattr(oauth_service.settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(oauth_service.settings, "GOOGLE_CLIENT_SECRET", "secret")
    with pytest.raises(HTTPException, match="not configured"):
        oauth_service.validate_google_oauth_settings()

    monkeypatch.setattr(oauth_service.settings, "GOOGLE_CLIENT_ID", "not-a-client-id")
    with pytest.raises(HTTPException, match="valid Google OAuth client ID"):
        oauth_service.validate_google_oauth_settings()


async def test_google_token_revocation_and_refresh_cover_provider_outcomes(monkeypatch):
    assert await oauth_service.revoke_google_token("") is False

    class FakeCredentials:
        token = "new-access"
        refresh_token = None
        expiry = datetime(2026, 8, 20, 12, tzinfo=UTC)

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def refresh(self, _request):
            return None

    monkeypatch.setattr(oauth_service, "Credentials", FakeCredentials)
    refreshed = oauth_service.refresh_access_token("old-refresh")
    assert refreshed == {
        "access_token": "new-access",
        "refresh_token": "old-refresh",
        "expiry": "2026-08-20T12:00:00+00:00",
    }
