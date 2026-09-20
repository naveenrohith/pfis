"""Behavioral coverage for provider account discovery and owned mappings."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from app.services.balance_provider_connection_service import BalanceProviderConnectionService
from app.services.balance_provider_discovery_service import BalanceProviderDiscoveryService
from app.services.connectors.balance_registry import balance_connector_registry
from app.services.connectors.base import BalanceAccountCandidate

from tests.pytest.helpers import create_user


class _DiscoveryConnector:
    async def discover_accounts(self, user_id: str) -> list[BalanceAccountCandidate]:
        return [
            BalanceAccountCandidate(
                provider_account_id=" provider-bank-1 ",
                display_name=" Primary account ",
                masked_number=" ****1234 ",
                account_type=" BANK ",
                currency="inr",
            ),
            BalanceAccountCandidate(
                provider_account_id="provider-card-1",
                display_name="Rewards card",
                masked_number="****5678",
                account_type="credit_card",
                currency="INR",
            ),
        ]


class _NoopBalanceConnector:
    source_type = "fake_discovery"

    async def fetch_balance_observations(self, user_id, account_ids, cursor):
        raise AssertionError("discovery tests must not call the refresh transport")


async def _connector_factory(db, user_id, connection):
    return _NoopBalanceConnector()


async def _discovery_factory(db, user_id, connection):
    return _DiscoveryConnector()


def _register_provider() -> None:
    balance_connector_registry.register(
        "fake_discovery",
        _connector_factory,
        label="Fake discovery provider",
        discovery_factory=_discovery_factory,
    )


def _unregister_provider() -> None:
    balance_connector_registry.unregister("fake_discovery")


async def _create_account(client, user_id: str, suffix: str = "1234") -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Discovery Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_discovery_sanitizes_candidates_and_exposes_existing_mapping(
    client,
    test_session_factory,
):
    _register_provider()
    try:
        user = await create_user(client, "provider-discovery")
        account = await _create_account(client, user["id"])

        async with test_session_factory() as db:
            connection_service = BalanceProviderConnectionService(db)
            await connection_service.request_consent(user["id"], "FAKE_DISCOVERY")
            granted = await connection_service.grant_consent(
                user["id"],
                "fake_discovery",
                "opaque-provider-grant",
            )
            assert granted.status == "active"

        response = await client.get(
            f"/api/balance-provider/discovered-accounts?user_id={user['id']}&provider_type=FAKE_DISCOVERY"
        )
        response.raise_for_status()
        assert response.json() == [
            {
                "provider_account_id": "provider-bank-1",
                "display_name": "Primary account",
                "masked_number": "****1234",
                "account_type": "bank",
                "currency": "INR",
                "mapped_financial_account_id": None,
            },
            {
                "provider_account_id": "provider-card-1",
                "display_name": "Rewards card",
                "masked_number": "****5678",
                "account_type": "credit_card",
                "currency": "INR",
                "mapped_financial_account_id": None,
            },
        ]

        mapped = await client.post(
            f"/api/accounts/{account['id']}/balance-provider-mapping?user_id={user['id']}",
            json={
                "provider_type": "fake_discovery",
                "provider_account_id": " provider-bank-1 ",
            },
        )
        assert mapped.status_code == 201
        assert mapped.json()["provider_account_id"] == "provider-bank-1"

        discovered_again = await client.get(
            f"/api/balance-provider/discovered-accounts?user_id={user['id']}&provider_type=fake_discovery"
        )
        discovered_again.raise_for_status()
        assert discovered_again.json()[0]["mapped_financial_account_id"] == account["id"]

        mappings = await client.get(
            f"/api/balance-provider/mappings?user_id={user['id']}&provider_type=FAKE_DISCOVERY"
        )
        mappings.raise_for_status()
        assert [item["provider_account_id"] for item in mappings.json()] == ["provider-bank-1"]
    finally:
        _unregister_provider()


async def test_mapping_rejects_unconsented_and_cross_user_accounts(
    client,
    test_session_factory,
):
    _register_provider()
    try:
        owner = await create_user(client, "provider-mapping-owner")
        other = await create_user(client, "provider-mapping-other")
        owner_account = await _create_account(client, owner["id"], "2345")
        other_account = await _create_account(client, other["id"], "6789")

        unconsented = await client.post(
            f"/api/accounts/{owner_account['id']}/balance-provider-mapping?user_id={owner['id']}",
            json={
                "provider_type": "fake_discovery",
                "provider_account_id": "provider-bank-1",
            },
        )
        assert unconsented.status_code == 409
        assert "consent" in unconsented.json()["error"]["message"]

        async with test_session_factory() as db:
            service = BalanceProviderConnectionService(db)
            await service.request_consent(owner["id"], "fake_discovery")
            await service.grant_consent(owner["id"], "fake_discovery", "owner-grant")
            await service.request_consent(other["id"], "fake_discovery")
            await service.grant_consent(other["id"], "fake_discovery", "other-grant")

        cross_user = await client.post(
            f"/api/accounts/{owner_account['id']}/balance-provider-mapping?user_id={other['id']}",
            json={
                "provider_type": "fake_discovery",
                "provider_account_id": "provider-bank-1",
            },
        )
        assert cross_user.status_code == 404
        assert other_account["id"] != owner_account["id"]
    finally:
        _unregister_provider()


async def test_mapping_identity_is_unique_and_unmap_is_explicit(
    client,
    test_session_factory,
):
    _register_provider()
    try:
        user = await create_user(client, "provider-mapping-unique")
        first = await _create_account(client, user["id"], "3456")
        second = await _create_account(client, user["id"], "7890")

        async with test_session_factory() as db:
            service = BalanceProviderConnectionService(db)
            await service.request_consent(user["id"], "fake_discovery")
            await service.grant_consent(user["id"], "fake_discovery", "grant")

        first_mapping = await client.post(
            f"/api/accounts/{first['id']}/balance-provider-mapping?user_id={user['id']}",
            json={
                "provider_type": "fake_discovery",
                "provider_account_id": "provider-bank-1",
            },
        )
        assert first_mapping.status_code == 201

        duplicate_identity = await client.post(
            f"/api/accounts/{second['id']}/balance-provider-mapping?user_id={user['id']}",
            json={
                "provider_type": "fake_discovery",
                "provider_account_id": "provider-bank-1",
            },
        )
        assert duplicate_identity.status_code == 409
        assert "already mapped" in duplicate_identity.json()["error"]["message"]

        removed = await client.delete(
            f"/api/accounts/{first['id']}/balance-provider-mapping/fake_discovery?user_id={user['id']}"
        )
        assert removed.status_code == 204

        missing = await client.delete(
            f"/api/accounts/{first['id']}/balance-provider-mapping/fake_discovery?user_id={user['id']}"
        )
        assert missing.status_code == 404
    finally:
        _unregister_provider()


def test_discovery_normalization_rejects_unsafe_provider_results():
    with pytest.raises(ValueError, match="duplicate identity"):
        BalanceProviderDiscoveryService._normalize_candidates(
            [
                BalanceAccountCandidate("same"),
                BalanceAccountCandidate(" same "),
            ]
        )

    with pytest.raises(ValueError, match="invalid currency"):
        BalanceProviderDiscoveryService._normalize_candidates(
            [BalanceAccountCandidate("account", currency="IN")]
        )

    too_many: Iterable[BalanceAccountCandidate] = (
        BalanceAccountCandidate(f"account-{index}") for index in range(201)
    )
    with pytest.raises(ValueError, match="too many accounts"):
        BalanceProviderDiscoveryService._normalize_candidates(too_many)

    assert BalanceProviderDiscoveryService._account_type(" unknown ") is None
    assert BalanceProviderDiscoveryService._account_type(None) is None
