"""Runtime registry for consented balance connector implementations.

The registry is deliberately empty in the base deployment.  A provider
integration registers a factory at application startup; the refresh workflow
then receives only a short-lived database session, user scope, and the
non-secret connection row.  Credentials and provider SDK clients stay inside
the provider-owned factory boundary.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import BalanceProviderConnection
from app.services.connectors.base import BalanceAccountDiscovery, BalanceConnector

BalanceConnectorFactory = Callable[
    [AsyncSession, str, BalanceProviderConnection], Awaitable[BalanceConnector]
]
BalanceAccountDiscoveryFactory = Callable[
    [AsyncSession, str, BalanceProviderConnection], Awaitable[BalanceAccountDiscovery]
]


@dataclass(frozen=True)
class BalanceConnectorRegistration:
    provider_type: str
    label: str
    factory: BalanceConnectorFactory
    discovery_factory: BalanceAccountDiscoveryFactory | None = None


class BalanceConnectorRegistry:
    """Small explicit registry instead of an implicit provider singleton."""

    def __init__(self) -> None:
        self._registrations: dict[str, BalanceConnectorRegistration] = {}

    def register(
        self,
        provider_type: str,
        factory: BalanceConnectorFactory,
        *,
        label: str | None = None,
        discovery_factory: BalanceAccountDiscoveryFactory | None = None,
    ) -> BalanceConnectorRegistration:
        normalized = provider_type.strip().lower()
        if not normalized or len(normalized) > 50:
            raise ValueError("provider_type must be between 1 and 50 characters")
        if (
            not normalized.replace("_", "")
            .replace("-", "")
            .replace(".", "")
            .replace(":", "")
            .isalnum()
        ):
            raise ValueError("provider_type contains unsupported characters")
        registration = BalanceConnectorRegistration(
            provider_type=normalized,
            label=(label or normalized).strip()[:120],
            factory=factory,
            discovery_factory=discovery_factory,
        )
        self._registrations[normalized] = registration
        return registration

    def unregister(self, provider_type: str) -> None:
        self._registrations.pop(provider_type.strip().lower(), None)

    def get(self, provider_type: str) -> BalanceConnectorRegistration | None:
        return self._registrations.get(provider_type.strip().lower())

    def supported_provider_types(self) -> list[str]:
        return sorted(self._registrations)

    def labels(self) -> dict[str, str]:
        return {key: registration.label for key, registration in self._registrations.items()}


balance_connector_registry = BalanceConnectorRegistry()
