"""End-to-end classification coverage for provider readiness status."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.schemas.account import BalanceProviderConnectionResponse
from app.services import balance_provider_status_service as module
from app.services.balance_provider_status_service import BalanceProviderStatusService


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, rows=()):
        self.rows = list(rows)

    async def scalars(self, _statement):
        return _Rows(self.rows.pop(0) if self.rows else [])


class _ConnectionService:
    connections = []

    def __init__(self, _db):
        pass

    async def list_connections(self, _user_id):
        return list(self.connections)


class _MappingService:
    mappings = {}

    def __init__(self, _db):
        pass

    async def account_provider_ids(self, *_args):
        return dict(self.mappings)


class _CoverageService:
    values = {}

    def __init__(self, _db):
        pass

    def _coverage_response(self, state, *, now):
        del now
        values = self.values.get(state.financial_account_id, {})
        return SimpleNamespace(
            source_account_id=state.source_account_id,
            expected_next_at=values.get("expected_next_at"),
            last_observed_at=values.get("last_observed_at"),
            last_success_at=state.last_success_at,
            coverage_complete=values.get("coverage_complete", True),
            freshness_status=values.get("freshness_status", "fresh"),
            reason_codes=values.get("reason_codes", []),
        )


def _connection(provider_type="mock", status="active"):
    return BalanceProviderConnectionResponse(
        id=f"connection-{status}", provider_type=provider_type, status=status
    )


def _account(account_id, *, provider_id=None, account_type="bank"):
    return SimpleNamespace(
        id=account_id,
        account_type=account_type,
        masked_number="****1234",
        connector_account_id=provider_id,
    )


def _source(account_id, provider_id, *, success=True, error=None):
    return SimpleNamespace(
        financial_account_id=account_id,
        source_account_id=provider_id,
        last_success_at=datetime(2026, 9, 20, tzinfo=UTC) if success else None,
        last_observed_at=datetime(2026, 9, 20, tzinfo=UTC),
        last_error_code=error,
    )


@pytest.mark.asyncio
async def test_status_reports_no_accounts_and_provider_consent_state(monkeypatch):
    monkeypatch.setattr(module, "BalanceProviderConnectionService", _ConnectionService)
    monkeypatch.setattr(module, "BalanceProviderMappingService", _MappingService)
    monkeypatch.setattr(module, "BalanceObservationService", _CoverageService)
    monkeypatch.setattr(
        module,
        "balance_connector_registry",
        SimpleNamespace(
            supported_provider_types=lambda: ["mock"], labels=lambda: {"mock": "Mock Bank"}
        ),
    )
    _ConnectionService.connections = [_connection(status="pending")]
    result = await BalanceProviderStatusService(_Db([[]])).status("user-1")
    assert result.status == "not_configured"
    assert result.refresh_supported is False
    assert result.consent_required is True
    assert result.reason_codes == ["no_active_accounts"]
    assert result.next_step.startswith("Add a bank")


@pytest.mark.asyncio
async def test_status_composes_mapped_accounts_freshness_and_transport_reasons(monkeypatch):
    monkeypatch.setattr(module, "BalanceProviderConnectionService", _ConnectionService)
    monkeypatch.setattr(module, "BalanceProviderMappingService", _MappingService)
    monkeypatch.setattr(module, "BalanceObservationService", _CoverageService)
    monkeypatch.setattr(
        module,
        "balance_connector_registry",
        SimpleNamespace(
            supported_provider_types=lambda: ["mock"], labels=lambda: {"mock": "Mock Bank"}
        ),
    )
    _ConnectionService.connections = [_connection()]
    _MappingService.mappings = {"account-1": "provider-1"}
    accounts = [_account("account-1"), _account("account-2", provider_id="provider-2")]
    sources = [
        _source("account-1", "provider-1"),
        _source("account-2", "provider-2", success=False, error="provider_error"),
    ]
    _CoverageService.values = {
        "account-1": {"freshness_status": "fresh"},
        "account-2": {"coverage_complete": False, "freshness_status": "fresh"},
    }
    result = await BalanceProviderStatusService(_Db([accounts, sources])).status("user-1")
    assert result.status == "incomplete"
    assert result.refresh_supported is True
    assert result.provider_name == "Mock Bank"
    assert result.account_count == 2
    assert result.mapped_account_count == 2
    assert result.reason_codes == ["provider_error"]
    assert result.next_step.startswith("Refresh the provider")
    assert result.accounts[0].status == "ready"
    assert result.accounts[1].status == "incomplete"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "connection_status, reason",
    [
        ("pending", "provider_consent_pending"),
        ("expired", "provider_consent_expired"),
        ("error", "provider_connection_error"),
    ],
)
async def test_status_reports_unmapped_accounts_and_pending_consent(
    monkeypatch, connection_status, reason
):
    monkeypatch.setattr(module, "BalanceProviderConnectionService", _ConnectionService)
    monkeypatch.setattr(module, "BalanceProviderMappingService", _MappingService)
    monkeypatch.setattr(module, "BalanceObservationService", _CoverageService)
    monkeypatch.setattr(
        module,
        "balance_connector_registry",
        SimpleNamespace(
            supported_provider_types=lambda: ["mock"], labels=lambda: {"mock": "Mock Bank"}
        ),
    )
    _ConnectionService.connections = [_connection(status=connection_status)]
    _MappingService.mappings = {}
    result = await BalanceProviderStatusService(_Db([[_account("account-1")], []])).status("user-1")
    assert result.status == "blocked"
    assert result.mapped_account_count == 0
    assert reason in result.reason_codes
    assert "account_mapping_required" in result.reason_codes
    assert result.next_step.startswith("Complete provider consent")


@pytest.mark.asyncio
async def test_status_handles_empty_registry_without_fabricating_refresh(monkeypatch):
    monkeypatch.setattr(module, "BalanceProviderConnectionService", _ConnectionService)
    monkeypatch.setattr(module, "BalanceProviderMappingService", _MappingService)
    monkeypatch.setattr(module, "BalanceObservationService", _CoverageService)
    monkeypatch.setattr(
        module,
        "balance_connector_registry",
        SimpleNamespace(supported_provider_types=lambda: [], labels=lambda: {}),
    )
    _ConnectionService.connections = []
    _MappingService.mappings = {}
    result = await BalanceProviderStatusService(_Db([[_account("account-1")], []])).status("user-1")
    assert result.status == "blocked"
    assert result.refresh_supported is False
    assert "provider_transport_not_configured" in result.reason_codes
    assert result.accounts[0].status == "unmapped"
