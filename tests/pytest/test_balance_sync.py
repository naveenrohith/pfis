"""Focused coverage for provider-neutral balance refresh orchestration."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models.account import AccountBalanceSnapshot, AccountBalanceSource, FinancialAccount
from app.models.financial_position import CardPositionObservation
from app.services.balance_provider_connection_service import BalanceProviderConnectionService
from app.services.balance_sync_service import BalanceSyncService
from app.services.connectors.balance_registry import balance_connector_registry
from app.services.connectors.base import (
    BalanceObservation,
    BalanceObservationBatch,
    ConnectorCursor,
)
from app.services.connectors.base import (
    CardPositionObservation as CardPositionObservationContract,
)
from app.services.job_service import _handle_balance_refresh
from sqlalchemy import select

from tests.pytest.helpers import create_user


class _FakeBalanceConnector:
    source_type = "fake_bank"

    def __init__(self):
        self.seen_cursors: list[str | None] = []

    async def fetch_balance_observations(self, user_id, account_ids, cursor):
        self.seen_cursors.append(cursor.opaque_token)
        observed_at = datetime.now(UTC)
        return BalanceObservationBatch(
            source="connector",
            observations=[
                BalanceObservation(
                    financial_account_id=account_ids[0],
                    amount=Decimal("42000.00"),
                    currency="INR",
                    as_of=observed_at.date(),
                    source_record_id="fake-balance-1",
                    source_account_id="provider-account-1",
                    observed_at=observed_at,
                    effective_at=observed_at,
                    expected_cadence_minutes=60,
                    coverage_start=observed_at,
                    coverage_end=observed_at,
                )
            ],
            cursor=ConnectorCursor(opaque_token="cursor-1"),
            coverage_complete=True,
        )


class _FakeCardBalanceConnector:
    source_type = "fake_card"

    async def fetch_balance_observations(self, user_id, account_ids, cursor):
        observed_at = datetime.now(UTC)
        return BalanceObservationBatch(
            source="connector",
            observations=[
                BalanceObservation(
                    financial_account_id=account_ids[0],
                    amount=Decimal("12500.00"),
                    currency="INR",
                    as_of=observed_at.date(),
                    source_record_id="fake-card-position-1",
                    source_account_id="provider-card-1",
                    observed_at=observed_at,
                    effective_at=observed_at,
                    expected_cadence_minutes=60,
                    coverage_start=observed_at,
                    coverage_end=observed_at,
                )
            ],
            card_observations=[
                CardPositionObservationContract(
                    financial_account_id=account_ids[0],
                    currency="INR",
                    current_outstanding=Decimal("12500.00"),
                    billed_due=Decimal("9000.00"),
                    pending_amount=Decimal("700.00"),
                    credit_limit=Decimal("50000.00"),
                    available_credit=Decimal("36800.00"),
                    as_of=observed_at.date(),
                    source_record_id="fake-card-position-1",
                    source_account_id="provider-card-1",
                    observed_at=observed_at,
                    effective_at=observed_at,
                    expected_cadence_minutes=60,
                    coverage_start=observed_at,
                    coverage_end=observed_at,
                )
            ],
            cursor=ConnectorCursor(opaque_token="card-cursor-1"),
            coverage_complete=True,
        )


class _DuplicateBalanceConnector:
    source_type = "duplicate_bank"

    async def fetch_balance_observations(self, user_id, account_ids, cursor):
        observed_at = datetime.now(UTC)
        observations = [
            BalanceObservation(
                financial_account_id=account_ids[0],
                amount=Decimal("100.00"),
                currency="INR",
                as_of=observed_at.date(),
                source_record_id="duplicate-record",
                source_account_id="provider-duplicate",
                observed_at=observed_at,
                effective_at=observed_at,
                coverage_start=observed_at,
                coverage_end=observed_at,
            ),
            BalanceObservation(
                financial_account_id=account_ids[0],
                amount=Decimal("200.00"),
                currency="INR",
                as_of=observed_at.date(),
                source_record_id="duplicate-record",
                source_account_id="provider-duplicate",
                observed_at=observed_at,
                effective_at=observed_at,
                coverage_start=observed_at,
                coverage_end=observed_at,
            ),
        ]
        return BalanceObservationBatch(
            source="connector",
            observations=observations,
            cursor=ConnectorCursor(opaque_token="duplicate-cursor"),
        )


async def _fake_balance_factory(db, user_id, connection):
    return _FakeBalanceConnector()


async def test_balance_sync_runner_ingests_observation_and_resumes_cursor(
    client, test_session_factory
):
    user = await create_user(client, "balance-sync-runner")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Provider Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "****7788",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account_id = account_response.json()["id"]

    async with test_session_factory() as db:
        account = await db.get(FinancialAccount, account_id)
        assert account is not None
        account.connector_account_id = "provider-account-1"
        await db.commit()

        connector = _FakeBalanceConnector()
        result = await BalanceSyncService(db).run(
            user["id"],
            connector,
            [account_id],
        )
        assert result.observations_ingested == 1
        assert result.coverage_complete is True
        assert result.cursor_advanced is True

        repeated = await BalanceSyncService(db).run(
            user["id"],
            connector,
            [account_id],
        )
        assert repeated.observations_ingested == 1
        assert connector.seen_cursors == [None, "cursor-1"]

        snapshot = await db.scalar(
            select(AccountBalanceSnapshot).where(
                AccountBalanceSnapshot.financial_account_id == account_id,
                AccountBalanceSnapshot.source_record_id == "fake-balance-1",
            )
        )
        source = await db.scalar(
            select(AccountBalanceSource).where(
                AccountBalanceSource.financial_account_id == account_id,
                AccountBalanceSource.source == "connector",
            )
        )

    assert snapshot is not None
    assert snapshot.amount == Decimal("42000.00")
    assert source is not None
    assert source.cursor_token == "cursor-1"


async def test_balance_sync_marks_omitted_requested_accounts_incomplete(
    client, test_session_factory
):
    user = await create_user(client, "balance-sync-partial")
    account_ids = []
    async with test_session_factory() as db:
        for suffix in ("1111", "2222"):
            account_response = await client.post(
                f"/api/accounts?user_id={user['id']}",
                json={
                    "institution_name": f"Provider Bank {suffix}",
                    "account_type": "bank",
                    "balance_kind": "asset",
                    "masked_number": f"****{suffix}",
                    "currency": "INR",
                },
            )
            account_response.raise_for_status()
            account_ids.append(account_response.json()["id"])
            account = await db.get(FinancialAccount, account_ids[-1])
            assert account is not None
            account.connector_account_id = (
                "provider-account-1" if suffix == "1111" else f"provider-account-{suffix}"
            )
        await db.commit()

        result = await BalanceSyncService(db).run(
            user["id"],
            _FakeBalanceConnector(),
            account_ids,
        )
        assert result.observations_ingested == 1
        assert result.coverage_complete is False

        missing_source = await db.scalar(
            select(AccountBalanceSource).where(
                AccountBalanceSource.financial_account_id == account_ids[1],
                AccountBalanceSource.source == "connector",
            )
        )

    assert missing_source is not None
    assert missing_source.coverage_complete is False
    assert missing_source.last_error_code == "connector_batch_incomplete"


async def test_balance_provider_status_is_explicit_before_consent_and_transport(
    client,
):
    user = await create_user(client, "balance-provider-status-blocked")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Status Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "****8844",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()

    response = await client.get(f"/api/balance-provider/status?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "blocked"
    assert body["refresh_supported"] is False
    assert body["consent_required"] is True
    assert body["mapped_account_count"] == 0
    assert "provider_transport_not_configured" in body["reason_codes"]
    assert "account_mapping_required" in body["reason_codes"]
    assert body["accounts"][0]["status"] == "unmapped"


async def test_balance_provider_status_reports_observation_without_claiming_refresh(
    client,
    test_session_factory,
):
    user = await create_user(client, "balance-provider-status-observed")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Observed Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "****8855",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account_id = account_response.json()["id"]

    async with test_session_factory() as db:
        account = await db.get(FinancialAccount, account_id)
        assert account is not None
        account.connector_account_id = "provider-account-1"
        await db.commit()
        await BalanceSyncService(db).run(
            user["id"],
            _FakeBalanceConnector(),
            [account_id],
        )

    response = await client.get(f"/api/balance-provider/status?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "ready"
    assert body["refresh_supported"] is False
    assert body["mapped_account_count"] == 1
    assert body["last_success_at"] is not None
    assert body["accounts"][0]["status"] == "ready"
    assert body["accounts"][0]["freshness_status"] == "fresh"


async def test_balance_provider_consent_route_fails_closed_without_registered_provider(client):
    user = await create_user(client, "balance-provider-consent-unconfigured")

    response = await client.post(
        f"/api/balance-provider/connections?user_id={user['id']}",
        json={"provider_type": "fake_bank"},
    )

    assert response.status_code == 409
    assert "not configured" in response.json()["error"]["message"]


async def test_registered_provider_consent_and_refresh_job_are_idempotent_boundary(
    client,
    test_session_factory,
):
    user = await create_user(client, "balance-provider-refresh-boundary")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Refresh Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "****8866",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account_id = account_response.json()["id"]

    balance_connector_registry.register(
        "fake_bank",
        _fake_balance_factory,
        label="Fake test bank",
    )
    try:
        async with test_session_factory() as db:
            account = await db.get(FinancialAccount, account_id)
            assert account is not None
            account.connector_account_id = "provider-account-1"
            await db.commit()

            connections = BalanceProviderConnectionService(db)
            pending = await connections.request_consent(user["id"], "fake_bank")
            assert pending.status == "pending"
            active = await connections.grant_consent(
                user["id"],
                "fake_bank",
                "opaque-consent-reference",
            )
            assert active.status == "active"

            plan = await connections.prepare_refresh(
                user["id"],
                "fake_bank",
                [account_id],
            )
            assert plan.account_ids == [account_id]
            result = await _handle_balance_refresh(
                db,
                user["id"],
                {
                    "provider_type": "fake_bank",
                    "account_ids": [account_id],
                },
            )
            assert result["observations_ingested"] == 1

            refreshed = await connections.get_connection(user["id"], "fake_bank")
            assert refreshed is not None
            assert refreshed.status == "active"
            assert refreshed.last_refresh_completed_at is not None
            assert refreshed.consent_reference_hash != "opaque-consent-reference"
    finally:
        balance_connector_registry.unregister("fake_bank")


async def test_provider_consent_rejects_expired_grant_and_revoke_is_terminal(
    client, test_session_factory
):
    user = await create_user(client, "balance-provider-consent-expiry")
    balance_connector_registry.register("fake_bank", _fake_balance_factory)
    try:
        async with test_session_factory() as db:
            connections = BalanceProviderConnectionService(db)
            pending = await connections.request_consent(user["id"], "fake_bank")
            assert pending.status == "pending"
            with pytest.raises(ValueError, match="expiry must be in the future"):
                await connections.grant_consent(
                    user["id"],
                    "fake_bank",
                    "expired-consent",
                    expires_at=datetime.now(UTC),
                )
            revoked = await connections.revoke(user["id"], "fake_bank")
            assert revoked is not None
            assert revoked.status == "revoked"
            with pytest.raises(ValueError, match="consent is not active"):
                await connections.require_active_connection(user["id"], "fake_bank")
    finally:
        balance_connector_registry.unregister("fake_bank")


async def test_card_provider_observation_keeps_issuer_facts_typed(
    client,
    test_session_factory,
):
    user = await create_user(client, "card-provider-observation")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Issuer Card",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****8899",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account_id = account_response.json()["id"]

    async with test_session_factory() as db:
        account = await db.get(FinancialAccount, account_id)
        assert account is not None
        account.connector_account_id = "provider-card-1"
        await db.commit()

        result = await BalanceSyncService(db).run(
            user["id"],
            _FakeCardBalanceConnector(),
            [account_id],
        )
        assert result.observations_ingested == 1
        assert result.card_observations_ingested == 1

        record = await db.scalar(
            select(CardPositionObservation).where(
                CardPositionObservation.financial_account_id == account_id,
            )
        )
        assert record is not None
        assert record.billed_due == Decimal("9000.00")
        assert record.available_credit == Decimal("36800.00")

    overview = await client.get(f"/api/cards/{account_id}?user_id={user['id']}")
    overview.raise_for_status()
    body = overview.json()
    assert body["provider_current_outstanding"] == 12500.0
    assert body["provider_billed_due"] == 9000.0
    assert body["provider_pending_amount"] == 700.0
    assert body["provider_available_credit"] == 36800.0

    runway = await client.get(f"/api/cards/{account_id}/due-runway?user_id={user['id']}")
    runway.raise_for_status()
    runway_body = runway.json()
    assert runway_body["estimated_current_outstanding"] == 12500.0
    assert runway_body["credit_limit"] == 50000.0
    assert runway_body["issuer_available_credit_limit"] == 36800.0

    history = await client.get(f"/api/accounts/{account_id}/card-observations?user_id={user['id']}")
    history.raise_for_status()
    assert history.json()[0]["source_record_id"] == "fake-card-position-1"


async def test_card_observation_route_requires_provider_mapping(client):
    user = await create_user(client, "card-provider-observation-unmapped")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Unmapped Issuer",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****8900",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account_id = account_response.json()["id"]
    observed_at = datetime.now(UTC)
    response = await client.post(
        f"/api/accounts/{account_id}/card-observations?user_id={user['id']}",
        json={
            "current_outstanding": 500,
            "currency": "INR",
            "as_of": observed_at.date().isoformat(),
            "source_record_id": "unmapped-card-observation",
            "source_account_id": "spoofed-provider-card",
            "observed_at": observed_at.isoformat(),
            "coverage_start": observed_at.isoformat(),
            "coverage_end": observed_at.isoformat(),
        },
    )
    assert response.status_code == 409
    assert "mapping is required" in response.json()["error"]["message"]


async def test_balance_sync_rejects_duplicate_source_identity_before_persisting(
    client, test_session_factory
):
    user = await create_user(client, "balance-sync-duplicate-source")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Duplicate Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "****8877",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account_id = account_response.json()["id"]

    async with test_session_factory() as db:
        account = await db.get(FinancialAccount, account_id)
        assert account is not None
        account.connector_account_id = "provider-duplicate"
        await db.commit()

        with pytest.raises(ValueError, match="duplicate source record"):
            await BalanceSyncService(db).run(
                user["id"],
                _DuplicateBalanceConnector(),
                [account_id],
            )

        snapshots = list(
            (
                await db.scalars(
                    select(AccountBalanceSnapshot).where(
                        AccountBalanceSnapshot.financial_account_id == account_id,
                        AccountBalanceSnapshot.source == "connector",
                    )
                )
            ).all()
        )
    assert snapshots == []
