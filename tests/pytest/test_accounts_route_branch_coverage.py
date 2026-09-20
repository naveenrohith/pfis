"""Direct endpoint coverage for account and balance-provider route branches."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.api.routes import accounts as routes
from fastapi import HTTPException


class _AccountService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def _call(self, name, *args):
        value = self.behavior.get(name, [])
        if isinstance(value, BaseException):
            raise value
        return value

    async def list_link_rules(self, *args):
        return await self._call("list_link_rules", *args)

    async def create_link_rule(self, *args):
        return await self._call("create_link_rule", *args)

    async def deactivate_link_rule(self, *args):
        return await self._call("deactivate_link_rule", *args)

    async def list_accounts(self, *args):
        return await self._call("list_accounts", *args)

    async def create_account(self, *args):
        return await self._call("create_account", *args)

    async def update_account(self, *args):
        return await self._call("update_account", *args)

    async def identity_history(self, *args):
        return await self._call("identity_history", *args)

    async def add_balance(self, *args):
        return await self._call("add_balance", *args)

    async def net_worth(self, *args):
        return await self._call("net_worth", *args)

    async def create_transfer(self, *args):
        return await self._call("create_transfer", *args)


class _ObservationService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def _call(self, name, *args, **kwargs):
        value = self.behavior.get(name, [])
        if isinstance(value, BaseException):
            raise value
        return value

    async def ingest(self, *args, **kwargs):
        return await self._call("ingest", *args, **kwargs)

    async def list_coverage(self, *args, **kwargs):
        return await self._call("list_coverage", *args, **kwargs)


class _CardObservationService(_ObservationService):
    async def list_recent(self, *args, **kwargs):
        return await self._call("list_recent", *args, **kwargs)


class _ProviderConnectionService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def status(self, *args):
        return await self._call("status", *args)

    async def list_connections(self, *args):
        return await self._call("list_connections", *args)

    async def request_consent(self, *args):
        return await self._call("request_consent", *args)

    async def revoke(self, *args):
        return await self._call("revoke", *args)

    async def _call(self, name, *args):
        value = self.behavior.get(name, [])
        if isinstance(value, BaseException):
            raise value
        return value


class _ProviderMappingService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def _call(self, name, *args):
        value = self.behavior.get(name, [])
        if isinstance(value, BaseException):
            raise value
        return value

    async def list_mappings(self, *args):
        return await self._call("list_mappings", *args)

    async def map_account(self, *args):
        return await self._call("map_account", *args)

    async def unmap_account(self, *args):
        return await self._call("unmap_account", *args)


class _ProviderDiscoveryService:
    behavior = {}

    def __init__(self, _db):
        pass

    async def discover(self, *args):
        value = self.behavior.get("discover", [])
        if isinstance(value, BaseException):
            raise value
        return value


def _data(**values):
    return SimpleNamespace(**values)


async def _expect_status(awaitable, status_code):
    with pytest.raises(HTTPException) as caught:
        await awaitable
    assert caught.value.status_code == status_code


@pytest.mark.asyncio
async def test_account_crud_and_link_rule_routes_cover_success_and_errors(monkeypatch):
    monkeypatch.setattr(routes, "AccountService", _AccountService)
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    _AccountService.behavior = {
        "list_link_rules": ["rule"],
        "create_link_rule": "created",
        "deactivate_link_rule": True,
        "list_accounts": ["account"],
        "create_account": "new-account",
        "update_account": "updated",
        "identity_history": ["history"],
        "add_balance": "balance",
    }
    db = object()
    data = _data()

    assert await routes.list_account_link_rules("user-1", None, db) == ["rule"]
    assert await routes.create_account_link_rule(data, "user-1", None, db) == "created"
    assert await routes.deactivate_account_link_rule("rule-1", "user-1", None, db) is None
    assert await routes.list_accounts("user-1", None, db) == ["account"]
    assert await routes.create_account(data, "user-1", None, db) == "new-account"
    assert await routes.update_account("account-1", data, "user-1", None, db) == "updated"
    assert await routes.get_account_identity_history("account-1", "user-1", None, db) == ["history"]
    assert await routes.add_account_balance("account-1", data, "user-1", None, db) == "balance"

    _AccountService.behavior.update(
        {
            "create_link_rule": LookupError("missing account"),
            "create_account": ValueError("duplicate account"),
            "update_account": None,
            "identity_history": None,
            "add_balance": None,
        }
    )
    await _expect_status(routes.create_account_link_rule(data, "user-1", None, db), 404)
    _AccountService.behavior["create_link_rule"] = ValueError("invalid rule")
    await _expect_status(routes.create_account_link_rule(data, "user-1", None, db), 422)
    await _expect_status(routes.create_account(data, "user-1", None, db), 409)
    await _expect_status(routes.update_account("missing", data, "user-1", None, db), 404)
    await _expect_status(routes.get_account_identity_history("missing", "user-1", None, db), 404)
    await _expect_status(routes.add_account_balance("missing", data, "user-1", None, db), 404)
    _AccountService.behavior["add_balance"] = ValueError("invalid balance")
    await _expect_status(routes.add_account_balance("account-1", data, "user-1", None, db), 409)
    _AccountService.behavior["deactivate_link_rule"] = False
    await _expect_status(routes.deactivate_account_link_rule("missing", "user-1", None, db), 404)


@pytest.mark.asyncio
async def test_observation_and_card_routes_cover_success_not_found_and_conflicts(monkeypatch):
    monkeypatch.setattr(routes, "BalanceObservationService", _ObservationService)
    monkeypatch.setattr(routes, "CardPositionObservationService", _CardObservationService)
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    monkeypatch.setattr(routes, "observation_from_create", lambda account_id, data: data)
    monkeypatch.setattr(routes, "card_observation_from_create", lambda account_id, data: data)
    _ObservationService.behavior = {"ingest": "observation", "list_coverage": ["coverage"]}
    _CardObservationService.behavior = {"ingest": "card", "list_recent": ["recent"]}
    db = object()
    data = _data()

    assert await routes.ingest_balance_observation("account-1", data, "user-1", None, db) == (
        "observation"
    )
    assert await routes.list_balance_coverage("account-1", "user-1", None, None, db) == ["coverage"]
    assert await routes.ingest_card_position_observation("account-1", data, "user-1", None, db) == (
        "card"
    )
    assert await routes.list_card_position_observations("account-1", "user-1", 20, None, db) == [
        "recent"
    ]

    _ObservationService.behavior = {
        "ingest": LookupError("account missing"),
        "list_coverage": None,
    }
    await _expect_status(
        routes.ingest_balance_observation("account-1", data, "user-1", None, db), 404
    )
    _ObservationService.behavior["ingest"] = ValueError("currency mismatch")
    await _expect_status(
        routes.ingest_balance_observation("account-1", data, "user-1", None, db), 409
    )
    await _expect_status(routes.list_balance_coverage("account-1", "user-1", None, None, db), 404)

    _CardObservationService.behavior = {
        "ingest": LookupError("card missing"),
        "list_recent": None,
    }
    await _expect_status(
        routes.ingest_card_position_observation("account-1", data, "user-1", None, db), 404
    )
    _CardObservationService.behavior["ingest"] = ValueError("invalid observation")
    await _expect_status(
        routes.ingest_card_position_observation("account-1", data, "user-1", None, db), 409
    )
    await _expect_status(
        routes.list_card_position_observations("account-1", "user-1", 20, None, db), 404
    )


@pytest.mark.asyncio
async def test_provider_connection_mapping_discovery_and_transfer_routes(monkeypatch):
    monkeypatch.setattr(routes, "BalanceProviderStatusService", _ProviderConnectionService)
    monkeypatch.setattr(routes, "BalanceProviderConnectionService", _ProviderConnectionService)
    monkeypatch.setattr(routes, "BalanceProviderMappingService", _ProviderMappingService)
    monkeypatch.setattr(routes, "BalanceProviderDiscoveryService", _ProviderDiscoveryService)
    monkeypatch.setattr(routes, "AccountService", _AccountService)
    monkeypatch.setattr(routes, "resolve_user_scope", lambda user_id, _current: user_id)
    _ProviderConnectionService.behavior = {
        "status": [],
        "list_connections": ["connection"],
        "request_consent": "requested",
        "revoke": "revoked",
    }
    _ProviderMappingService.behavior = {
        "list_mappings": ["mapping"],
        "map_account": "mapped",
        "unmap_account": True,
    }
    _ProviderDiscoveryService.behavior = {"discover": ["candidate"]}
    _AccountService.behavior = {
        "net_worth": "net-worth",
        "create_transfer": "transfer",
    }
    db = object()
    data = _data(provider_type="demo", provider_account_id="provider-1")

    assert await routes.balance_provider_status("user-1", None, db) == []
    assert await routes.list_balance_provider_connections("user-1", None, db) == ["connection"]
    assert await routes.request_balance_provider_consent(data, "user-1", None, db) == "requested"
    assert await routes.revoke_balance_provider_consent("demo", "user-1", None, db) == "revoked"
    assert await routes.list_balance_provider_mappings("user-1", "demo", None, db) == ["mapping"]
    assert await routes.discover_balance_provider_accounts("demo", "user-1", None, db) == [
        "candidate"
    ]
    assert await routes.map_balance_provider_account("account-1", data, "user-1", None, db) == (
        "mapped"
    )
    assert (
        await routes.unmap_balance_provider_account("account-1", "demo", "user-1", None, db) is None
    )
    assert await routes.get_net_worth("user-1", None, None, db) == "net-worth"
    assert await routes.create_transfer(data, "user-1", None, db) == "transfer"

    _ProviderConnectionService.behavior.update(
        {"request_consent": ValueError("unsupported"), "revoke": None}
    )
    await _expect_status(routes.request_balance_provider_consent(data, "user-1", None, db), 409)
    await _expect_status(routes.revoke_balance_provider_consent("demo", "user-1", None, db), 404)
    _ProviderDiscoveryService.behavior["discover"] = LookupError("not configured")
    await _expect_status(routes.discover_balance_provider_accounts("demo", "user-1", None, db), 404)
    _ProviderDiscoveryService.behavior["discover"] = ValueError("invalid provider")
    await _expect_status(routes.discover_balance_provider_accounts("demo", "user-1", None, db), 409)
    _ProviderMappingService.behavior["map_account"] = LookupError("account missing")
    await _expect_status(
        routes.map_balance_provider_account("account-1", data, "user-1", None, db), 404
    )
    _ProviderMappingService.behavior["map_account"] = ValueError("duplicate mapping")
    await _expect_status(
        routes.map_balance_provider_account("account-1", data, "user-1", None, db), 409
    )
    _ProviderMappingService.behavior["unmap_account"] = False
    await _expect_status(
        routes.unmap_balance_provider_account("account-1", "demo", "user-1", None, db), 404
    )
    _AccountService.behavior["net_worth"] = ValueError("bad date")
    await _expect_status(routes.get_net_worth("user-1", None, None, db), 422)
    _AccountService.behavior["create_transfer"] = LookupError("account missing")
    await _expect_status(routes.create_transfer(data, "user-1", None, db), 404)
    _AccountService.behavior["create_transfer"] = ValueError("invalid transfer")
    await _expect_status(routes.create_transfer(data, "user-1", None, db), 422)
