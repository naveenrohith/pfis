"""Connector-driven ingestion regression tests."""

from __future__ import annotations

from datetime import UTC, datetime

from app.api.routes import gmail as gmail_routes
from app.models.email import GmailAccount
from app.models.sync import ConnectorAuditEvent, SyncRun, SyncStatus
from app.services.classification import ClassificationType, classify_source_record
from app.services.connectors.base import (
    ConnectorBatch,
    ConnectorCursor,
    ConnectorError,
    ConnectorErrorType,
)
from app.services.connectors.errors import classify_connector_exception
from app.services.connectors.gmail_connector import GmailConnector
from app.services.connectors.source_record import SourceType
from app.services.ingestion import IngestionCoordinator, IngestionMode
from sqlalchemy import select

from tests.pytest.helpers import create_user


def test_gmail_connector_converts_message_to_source_record():
    message = {
        "id": "gmail-1",
        "internalDate": str(int(datetime(2026, 5, 7, tzinfo=UTC).timestamp() * 1000)),
        "payload": {
            "headers": [
                {"name": "From", "value": "HDFC Bank <alerts@hdfcbank.net>"},
                {"name": "Subject", "value": "Payment alert"},
            ],
            "body": {"data": "UGF5bWVudCBvZiBScy43NTAuMDAgdG8gQk9PS01ZU0hPVyB2aWEgVVBJLg=="},
        },
    }

    record = GmailConnector._message_to_record("user-1", message)

    assert record.user_id == "user-1"
    assert record.source_type == SourceType.GMAIL
    assert record.source_message_id == "gmail-1"
    assert record.sender == "HDFC Bank <alerts@hdfcbank.net>"
    assert record.subject == "Payment alert"
    assert "BOOKMYSHOW" in record.body


def test_classification_engine_supports_enterprise_categories():
    samples = [
        (
            "salary credited",
            "Your salary of INR 100000 has been credited",
            ClassificationType.SALARY,
        ),
        (
            "refund processed",
            "Refund of INR 500 credited to your account",
            ClassificationType.REFUND,
        ),
        ("payment failed", "Your payment failed for INR 1200", ClassificationType.FAILED_PAYMENT),
        (
            "subscription charged",
            "Subscription auto-pay of INR 299 completed",
            ClassificationType.SUBSCRIPTION,
        ),
        (
            "SIP update",
            "Your mutual fund SIP of INR 5000 was processed",
            ClassificationType.INVESTMENT,
        ),
        ("loan EMI", "Your loan EMI of INR 12000 has been debited", ClassificationType.LOAN),
    ]

    for subject, body, expected in samples:
        result = classify_source_record("HDFC Bank <alerts@hdfcbank.net>", subject, body)
        assert result.classification == expected
        assert result.confidence > 0
        assert result.reason
        assert result.matched_signals


def test_unsubscribe_footer_does_not_hide_known_bank_money_movement():
    result = classify_source_record(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.net>",
        "View: Account update for your HDFC Bank A/c",
        (
            "Your salary of INR 43270 has been credited to your account. "
            "Manage preferences or unsubscribe."
        ),
    )
    assert result.classification == ClassificationType.SALARY


async def test_ingestion_coordinator_retries_transient_failure_and_audits(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "coordinator")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-test",
            access_token_ref="token",
            refresh_token_ref="refresh",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    attempts = {"count": 0}

    async def fake_fetch_backfill(self, user_id, options):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("temporary timeout")
        return ConnectorBatch(
            records=[],
            cursor=ConnectorCursor(history_id="history-2"),
            metrics={"fetched": 0, "records": 0, "fallback_used": False},
        )

    monkeypatch.setattr(GmailConnector, "fetch_backfill", fake_fetch_backfill)

    async with test_session_factory() as db:
        stats = await IngestionCoordinator(db).run_gmail(
            user["id"],
            account_id,
            IngestionMode.BACKFILL,
            max_results=10,
        )
        audits = await db.execute(
            select(ConnectorAuditEvent).where(
                ConnectorAuditEvent.connector_account_id == account_id
            )
        )
        event_types = [event.event_type for event in audits.scalars().all()]

    assert attempts["count"] == 2
    assert stats["emails_fetched"] == 0
    assert "sync_started" in event_types
    assert "sync_completed" in event_types


async def test_ingestion_completion_does_not_overwrite_a_concurrent_reconnect(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "gmail-reconnect-race")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-reconnect-race",
            access_token_ref="old-access-ref",
            refresh_token_ref="old-refresh-ref",
            last_history_id="cursor-before-sync",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async def fake_fetch(self, user_id, options):
        async with test_session_factory() as competing_db:
            competing_account = await competing_db.scalar(
                select(GmailAccount).where(GmailAccount.id == account_id)
            )
            assert competing_account is not None
            competing_account.access_token_ref = "reconnected-access-ref"
            competing_account.refresh_token_ref = "reconnected-refresh-ref"
            competing_account.auto_sync_status = "idle"
            competing_account.auto_sync_error = None
            await competing_db.commit()
        return ConnectorBatch(
            records=[],
            cursor=ConnectorCursor(history_id="stale-sync-cursor"),
            metrics={"fetched": 0, "records": 0, "fallback_used": False},
        )

    monkeypatch.setattr(GmailConnector, "fetch_backfill", fake_fetch)

    async with test_session_factory() as db:
        stats = await IngestionCoordinator(db).run_gmail(
            user["id"], account_id, IngestionMode.BACKFILL, max_results=10
        )

    assert stats["emails_fetched"] == 0
    async with test_session_factory() as db:
        stored = await db.scalar(select(GmailAccount).where(GmailAccount.id == account_id))
        assert stored is not None
        assert stored.access_token_ref == "reconnected-access-ref"
        assert stored.refresh_token_ref == "reconnected-refresh-ref"
        assert stored.last_history_id == "cursor-before-sync"
        assert stored.auto_sync_status == "idle"
        assert stored.auto_sync_error is None


async def test_ingestion_persists_refreshed_credentials_before_advancing_cursor(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "gmail-refresh-completion")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-refresh-completion",
            access_token_ref="old-access-ref",
            refresh_token_ref="old-refresh-ref",
            last_history_id="cursor-before-refresh",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async def fake_fetch(self, user_id, options):
        self.account.access_token_ref = "refreshed-access-ref"
        self.account.refresh_token_ref = "refreshed-refresh-ref"
        self.account.token_expires_at = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)
        return ConnectorBatch(
            records=[],
            cursor=ConnectorCursor(history_id="cursor-after-refresh"),
            metrics={
                "fetched": 0,
                "records": 0,
                "fallback_used": False,
                "credentials_refreshed": True,
            },
        )

    monkeypatch.setattr(GmailConnector, "fetch_backfill", fake_fetch)

    async with test_session_factory() as db:
        stats = await IngestionCoordinator(db).run_gmail(
            user["id"], account_id, IngestionMode.BACKFILL, max_results=10
        )

    assert stats["emails_fetched"] == 0
    async with test_session_factory() as db:
        stored = await db.scalar(select(GmailAccount).where(GmailAccount.id == account_id))
        assert stored is not None
        assert stored.access_token_ref == "refreshed-access-ref"
        assert stored.refresh_token_ref == "refreshed-refresh-ref"
        assert stored.last_history_id == "cursor-after-refresh"
        assert stored.auto_sync_status == "idle"
        assert stored.auto_sync_error is None


async def test_ingestion_refresh_race_completes_without_overwriting_reconnect(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "gmail-refresh-reconnect-race")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-refresh-reconnect-race",
            access_token_ref="old-race-access-ref",
            refresh_token_ref="old-race-refresh-ref",
            last_history_id="cursor-before-race-refresh",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async def fake_fetch(self, user_id, options):
        async with test_session_factory() as competing_db:
            competing_account = await competing_db.scalar(
                select(GmailAccount).where(GmailAccount.id == account_id)
            )
            assert competing_account is not None
            competing_account.access_token_ref = "reconnected-race-access-ref"
            competing_account.refresh_token_ref = "reconnected-race-refresh-ref"
            competing_account.auto_sync_status = "idle"
            competing_account.auto_sync_error = None
            await competing_db.commit()

        self.account.access_token_ref = "stale-refreshed-access-ref"
        self.account.refresh_token_ref = "stale-refreshed-refresh-ref"
        self.account.token_expires_at = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)
        return ConnectorBatch(
            records=[],
            cursor=ConnectorCursor(history_id="stale-refresh-cursor"),
            metrics={
                "fetched": 0,
                "records": 0,
                "fallback_used": False,
                "credentials_refreshed": True,
            },
        )

    monkeypatch.setattr(GmailConnector, "fetch_backfill", fake_fetch)

    async with test_session_factory() as db:
        stats = await IngestionCoordinator(db).run_gmail(
            user["id"], account_id, IngestionMode.BACKFILL, max_results=10
        )
        runs = await db.execute(select(SyncRun).where(SyncRun.user_id == user["id"]))
        sync_run = runs.scalar_one()

    assert stats["emails_fetched"] == 0
    assert sync_run.status == SyncStatus.COMPLETED
    async with test_session_factory() as db:
        stored = await db.scalar(select(GmailAccount).where(GmailAccount.id == account_id))
        assert stored is not None
        assert stored.access_token_ref == "reconnected-race-access-ref"
        assert stored.refresh_token_ref == "reconnected-race-refresh-ref"
        assert stored.last_history_id == "cursor-before-race-refresh"
        assert stored.auto_sync_status == "idle"
        assert stored.auto_sync_error is None


async def test_ingestion_failure_does_not_mark_a_reconnected_account_for_reauth(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "gmail-reconnect-failure")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-reconnect-failure",
            access_token_ref="old-failure-access-ref",
            refresh_token_ref="old-failure-refresh-ref",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async def fake_fetch(self, user_id, options):
        async with test_session_factory() as competing_db:
            competing_account = await competing_db.scalar(
                select(GmailAccount).where(GmailAccount.id == account_id)
            )
            assert competing_account is not None
            competing_account.access_token_ref = "reconnected-failure-access-ref"
            competing_account.refresh_token_ref = "reconnected-failure-refresh-ref"
            competing_account.auto_sync_status = "idle"
            competing_account.auto_sync_error = None
            await competing_db.commit()
        raise RuntimeError("invalid_grant provider detail must stay private")

    monkeypatch.setattr(GmailConnector, "fetch_backfill", fake_fetch)

    async with test_session_factory() as db:
        try:
            await IngestionCoordinator(db).run_gmail(
                user["id"], account_id, IngestionMode.BACKFILL, max_results=10
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("The simulated sync failure was not propagated")

    async with test_session_factory() as db:
        stored = await db.scalar(select(GmailAccount).where(GmailAccount.id == account_id))
        assert stored is not None
        assert stored.access_token_ref == "reconnected-failure-access-ref"
        assert stored.auto_sync_status == "idle"
        assert stored.auto_sync_error is None


def test_connector_error_classifier_marks_permanent_credentials():
    assert (
        classify_connector_exception(Exception("invalid_grant revoked"))
        == ConnectorErrorType.PERMANENT
    )


def test_connector_error_classifier_marks_dns_failures_transient():
    assert (
        classify_connector_exception(Exception("Unable to find the server at gmail.googleapis.com"))
        == ConnectorErrorType.TRANSIENT
    )


async def test_ingestion_rejects_another_users_gmail_account(client, test_session_factory):
    owner = await create_user(client, "gmail-owner")
    other = await create_user(client, "gmail-other")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=owner["id"],
            google_account_id="owned-gmail-account",
            access_token_ref="encrypted-access",
            refresh_token_ref="encrypted-refresh",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async with test_session_factory() as db:
        try:
            await IngestionCoordinator(db).run_gmail(
                other["id"], account_id, IngestionMode.BACKFILL
            )
        except LookupError as exc:
            assert str(exc) == "Gmail account not found"
        else:
            raise AssertionError("Cross-user Gmail account access was not rejected")

        sync_run = await db.scalar(select(SyncRun).where(SyncRun.user_id == other["id"]))
        audits = list(
            await db.scalars(
                select(ConnectorAuditEvent).where(ConnectorAuditEvent.user_id == other["id"])
            )
        )

    assert sync_run is not None
    assert sync_run.status == SyncStatus.FAILED
    assert "owned-gmail-account" not in sync_run.errors
    assert all(audit.connector_account_id is None for audit in audits)
    assert all(audit.event_type != "sync_started" for audit in audits)


async def test_ingestion_counts_sanitized_connector_record_failures(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "gmail-record-failure")
    async with test_session_factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id="gmail-record-failure",
            access_token_ref="access",
            refresh_token_ref="refresh",
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        account_id = account.id

    async def fake_fetch(self, user_id, options):
        return ConnectorBatch(
            records=[],
            cursor=ConnectorCursor(history_id="history-after-failure"),
            metrics={"fetched": 1, "records": 0, "message_failures": 1},
            errors=[
                ConnectorError(
                    ConnectorErrorType.UNKNOWN,
                    "Gmail message could not be decoded",
                    False,
                )
            ],
        )

    monkeypatch.setattr(GmailConnector, "fetch_backfill", fake_fetch)

    async with test_session_factory() as db:
        stats = await IngestionCoordinator(db).run_gmail(
            user["id"], account_id, IngestionMode.BACKFILL, max_results=10
        )

    assert stats["emails_fetched"] == 1
    assert stats["emails_failed"] == 1
    assert stats["errors"] == [
        {
            "error": "Gmail message could not be decoded",
            "error_type": "unknown",
        }
    ]


async def test_gmail_sync_route_does_not_expose_provider_exception(
    client, test_session_factory, monkeypatch
):
    user = await create_user(client, "gmail-route-private-error")
    secret = "refresh_token=provider-secret"
    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="gmail-route-private-error",
                access_token_ref="access",
                refresh_token_ref="refresh",
            )
        )
        await db.commit()

    async def fail_sync(**_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(gmail_routes, "sync_gmail_emails", fail_sync)

    response = await client.post(f"/api/gmail/sync?user_id={user['id']}")

    assert response.status_code == 500
    assert secret not in response.text
    assert response.json()["error"]["message"] == "Internal server error"
