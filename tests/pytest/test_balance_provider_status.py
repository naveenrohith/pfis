"""Integrated readiness coverage for provider-backed account status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.account import AccountBalanceSource
from app.models.sync import BalanceProviderAccountMapping
from app.services.balance_provider_connection_service import BalanceProviderConnectionService
from app.services.connectors.balance_registry import balance_connector_registry

from tests.pytest.helpers import create_user


class _StatusConnector:
    async def fetch_balance_observations(self, user_id, account_ids, cursor):
        raise AssertionError("status tests must not invoke the provider transport")


async def _status_factory(_db, _user_id, _connection):
    return _StatusConnector()


async def _create_status_account(client, user_id: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": f"Status Bank {suffix}",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_balance_provider_status_reports_no_active_accounts(client):
    user = await create_user(client, "provider-status-empty")

    response = await client.get(f"/api/balance-provider/status?user_id={user['id']}")

    response.raise_for_status()
    assert response.json()["status"] == "not_configured"
    assert response.json()["account_count"] == 0
    assert response.json()["mapped_account_count"] == 0
    assert response.json()["reason_codes"] == ["no_active_accounts"]
    assert response.json()["accounts"] == []


async def test_balance_provider_status_aggregates_account_states_without_claiming_data(
    client, test_session_factory
):
    provider_type = "fake_status"
    balance_connector_registry.register(provider_type, _status_factory, label="Fake status")
    try:
        user = await create_user(client, "provider-status-matrix")
        account_ids: dict[str, str] = {}
        for suffix in ("1001", "1002", "1003", "1004", "1005", "1006"):
            account = await _create_status_account(client, user["id"], suffix)
            account_ids[suffix] = account["id"]

        now = datetime.now(UTC)
        async with test_session_factory() as db:
            connection_service = BalanceProviderConnectionService(db)
            await connection_service.request_consent(user["id"], provider_type)
            granted = await connection_service.grant_consent(
                user["id"], provider_type, "opaque-status-grant"
            )
            assert granted.status == "active"

            db.add_all(
                [
                    BalanceProviderAccountMapping(
                        user_id=user["id"],
                        financial_account_id=account_ids["1002"],
                        provider_type=provider_type,
                        provider_account_id="provider-missing",
                    ),
                    BalanceProviderAccountMapping(
                        user_id=user["id"],
                        financial_account_id=account_ids["1003"],
                        provider_type=provider_type,
                        provider_account_id="provider-incomplete",
                    ),
                    BalanceProviderAccountMapping(
                        user_id=user["id"],
                        financial_account_id=account_ids["1004"],
                        provider_type=provider_type,
                        provider_account_id="provider-due",
                    ),
                    BalanceProviderAccountMapping(
                        user_id=user["id"],
                        financial_account_id=account_ids["1005"],
                        provider_type=provider_type,
                        provider_account_id="provider-overdue",
                    ),
                    BalanceProviderAccountMapping(
                        user_id=user["id"],
                        financial_account_id=account_ids["1006"],
                        provider_type=provider_type,
                        provider_account_id="provider-ready",
                    ),
                    AccountBalanceSource(
                        user_id=user["id"],
                        financial_account_id=account_ids["1003"],
                        source="connector",
                        source_account_id="provider-incomplete",
                        coverage_complete=False,
                        last_success_at=now,
                        expected_cadence_minutes=60,
                        last_error_code="connector_batch_incomplete",
                    ),
                    AccountBalanceSource(
                        user_id=user["id"],
                        financial_account_id=account_ids["1004"],
                        source="connector",
                        source_account_id="provider-due",
                        coverage_complete=True,
                        last_success_at=now - timedelta(minutes=61),
                        expected_cadence_minutes=60,
                    ),
                    AccountBalanceSource(
                        user_id=user["id"],
                        financial_account_id=account_ids["1005"],
                        source="connector",
                        source_account_id="provider-overdue",
                        coverage_complete=True,
                        last_success_at=now - timedelta(minutes=121),
                        expected_cadence_minutes=60,
                    ),
                    AccountBalanceSource(
                        user_id=user["id"],
                        financial_account_id=account_ids["1006"],
                        source="connector",
                        source_account_id="provider-ready",
                        coverage_complete=True,
                        last_success_at=now,
                        expected_cadence_minutes=60,
                    ),
                ]
            )
            await db.commit()

        response = await client.get(f"/api/balance-provider/status?user_id={user['id']}")

        response.raise_for_status()
        body = response.json()
        by_account = {item["financial_account_id"]: item for item in body["accounts"]}
        assert body["refresh_supported"] is True
        assert body["consent_required"] is False
        assert body["provider_name"] == "Fake status"
        assert body["account_count"] == 6
        assert body["mapped_account_count"] == 5
        assert body["status"] == "incomplete"
        assert "account_mapping_required" in body["reason_codes"]
        assert "provider_observation_missing" in body["reason_codes"]
        assert by_account[account_ids["1001"]]["status"] == "unmapped"
        assert by_account[account_ids["1002"]]["status"] == "not_configured"
        assert by_account[account_ids["1003"]]["status"] == "incomplete"
        assert by_account[account_ids["1004"]]["status"] == "due"
        assert by_account[account_ids["1005"]]["status"] == "overdue"
        assert by_account[account_ids["1006"]]["status"] == "ready"
        assert by_account[account_ids["1004"]]["freshness_status"] == "due"
        assert by_account[account_ids["1005"]]["freshness_status"] == "overdue"
    finally:
        balance_connector_registry.unregister(provider_type)
