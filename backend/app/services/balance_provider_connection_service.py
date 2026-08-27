"""Consent lifecycle and refresh preparation for balance providers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.sync import BalanceProviderConnection, ConnectorAuditEvent
from app.schemas.account import (
    BalanceProviderConnectionResponse,
    BalanceProviderConnectionStatus,
)
from app.services.connectors.balance_registry import balance_connector_registry


@dataclass(frozen=True)
class BalanceRefreshPlan:
    provider_type: str
    account_ids: list[str]


class BalanceProviderConnectionService:
    """Own provider consent state without storing credentials or payloads."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_connections(self, user_id: str) -> list[BalanceProviderConnectionResponse]:
        rows = list(
            (
                await self.db.scalars(
                    select(BalanceProviderConnection)
                    .where(BalanceProviderConnection.user_id == user_id)
                    .order_by(BalanceProviderConnection.provider_type)
                )
            ).all()
        )
        return [self._response(row) for row in rows]

    async def get_connection(
        self,
        user_id: str,
        provider_type: str,
    ) -> BalanceProviderConnection | None:
        return await self._get(user_id, provider_type.strip().lower())

    async def request_consent(
        self,
        user_id: str,
        provider_type: str,
    ) -> BalanceProviderConnectionResponse:
        normalized = self._require_registered(provider_type)
        now = datetime.now(UTC)
        connection = await self._get(user_id, normalized)
        if connection is None:
            connection = BalanceProviderConnection(
                user_id=user_id,
                provider_type=normalized,
            )
            self.db.add(connection)
        connection.status = "pending"
        connection.consent_requested_at = now
        connection.last_error_code = None
        self._audit(
            user_id,
            normalized,
            "balance_provider_consent_requested",
            {"status": "pending"},
        )
        await self.db.commit()
        await self.db.refresh(connection)
        return self._response(connection)

    async def grant_consent(
        self,
        user_id: str,
        provider_type: str,
        consent_reference: str,
        *,
        expires_at: datetime | None = None,
    ) -> BalanceProviderConnectionResponse:
        """Activate a consent from a provider callback/internal integration.

        This method is intentionally not exposed as a generic user-facing
        route: only a provider adapter that has verified the external consent
        can call it.
        """

        normalized = self._require_registered(provider_type)
        reference = consent_reference.strip()
        if not reference:
            raise ValueError("A provider consent reference is required")
        now = datetime.now(UTC)
        normalized_expiry = self._as_utc(expires_at) if expires_at else None
        if normalized_expiry is not None and normalized_expiry <= now:
            raise ValueError("Provider consent expiry must be in the future")
        connection = await self._get(user_id, normalized)
        if connection is None:
            connection = BalanceProviderConnection(
                user_id=user_id,
                provider_type=normalized,
            )
            self.db.add(connection)
        connection.status = "active"
        connection.consent_reference_hash = hashlib.sha256(reference.encode()).hexdigest()
        connection.consent_requested_at = connection.consent_requested_at or now
        connection.consent_granted_at = now
        connection.consent_expires_at = normalized_expiry
        connection.last_error_code = None
        self._audit(
            user_id,
            normalized,
            "balance_provider_consent_granted",
            {
                "status": "active",
                "expires_at": (
                    connection.consent_expires_at.isoformat()
                    if connection.consent_expires_at
                    else None
                ),
            },
        )
        await self.db.commit()
        await self.db.refresh(connection)
        return self._response(connection)

    async def revoke(
        self,
        user_id: str,
        provider_type: str,
    ) -> BalanceProviderConnectionResponse | None:
        normalized = provider_type.strip().lower()
        connection = await self._get(user_id, normalized)
        if connection is None:
            return None
        connection.status = "revoked"
        connection.consent_reference_hash = None
        connection.last_error_code = None
        self._audit(
            user_id,
            normalized,
            "balance_provider_consent_revoked",
            {"status": "revoked"},
        )
        await self.db.commit()
        await self.db.refresh(connection)
        return self._response(connection)

    async def prepare_refresh(
        self,
        user_id: str,
        provider_type: str,
        account_ids: list[str] | None = None,
    ) -> BalanceRefreshPlan:
        connection = await self.require_active_connection(user_id, provider_type)
        normalized = connection.provider_type

        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                    )
                )
            ).all()
        )
        # New mappings are provider-scoped.  The legacy account field remains
        # a read-only compatibility fallback for pre-migration fixtures and
        # must not be used to overwrite a provider-scoped mapping.
        from app.services.balance_provider_mapping_service import BalanceProviderMappingService

        mapped_provider_ids = await BalanceProviderMappingService(self.db).account_provider_ids(
            user_id,
            normalized,
            [account.id for account in accounts],
        )
        by_id = {account.id: account for account in accounts}
        requested = list(dict.fromkeys(account_ids or []))
        if not requested:
            requested = [
                account.id
                for account in accounts
                if mapped_provider_ids.get(account.id) or account.connector_account_id
            ]
        if not requested:
            raise ValueError("Map at least one active account before requesting a refresh")
        if any(account_id not in by_id for account_id in requested):
            raise LookupError("One or more financial accounts were not found")
        unmapped = [
            account_id
            for account_id in requested
            if not (mapped_provider_ids.get(account_id) or by_id[account_id].connector_account_id)
        ]
        if unmapped:
            raise ValueError("Map every requested account to its provider account first")

        now = datetime.now(UTC)
        connection.last_refresh_requested_at = now
        connection.last_error_code = None
        await self.db.commit()
        return BalanceRefreshPlan(provider_type=normalized, account_ids=requested)

    async def require_active_connection(
        self,
        user_id: str,
        provider_type: str,
    ) -> BalanceProviderConnection:
        """Re-check registry, consent, and expiry at job execution time."""

        normalized = self._require_registered(provider_type)
        connection = await self._get(user_id, normalized)
        if connection is None or connection.status != "active":
            raise ValueError("Provider consent is not active")
        if connection.consent_expires_at is not None:
            expires_at = self._as_utc(connection.consent_expires_at)
            if expires_at <= datetime.now(UTC):
                connection.status = "expired"
                connection.last_error_code = "consent_expired"
                self._audit(
                    user_id,
                    normalized,
                    "balance_provider_consent_expired",
                    {"status": "expired"},
                )
                await self.db.commit()
                raise ValueError("Provider consent has expired")
        return connection

    async def mark_started(self, user_id: str, provider_type: str) -> None:
        connection = await self._get(user_id, provider_type)
        if connection is None:
            return
        connection.last_refresh_started_at = datetime.now(UTC)
        await self.db.commit()

    async def mark_completed(self, user_id: str, provider_type: str) -> None:
        connection = await self._get(user_id, provider_type)
        if connection is None:
            return
        connection.status = "active"
        connection.last_refresh_completed_at = datetime.now(UTC)
        connection.last_error_code = None
        await self.db.commit()

    async def mark_failed(self, user_id: str, provider_type: str, error_code: str) -> None:
        connection = await self._get(user_id, provider_type)
        if connection is None:
            return
        connection.last_error_code = error_code[:80]
        await self.db.commit()

    async def _get(self, user_id: str, provider_type: str) -> BalanceProviderConnection | None:
        return await self.db.scalar(
            select(BalanceProviderConnection).where(
                BalanceProviderConnection.user_id == user_id,
                BalanceProviderConnection.provider_type == provider_type,
            )
        )

    @staticmethod
    def _require_registered(provider_type: str) -> str:
        normalized = provider_type.strip().lower()
        if balance_connector_registry.get(normalized) is None:
            raise ValueError("The requested balance provider is not configured")
        return normalized

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _response(connection: BalanceProviderConnection) -> BalanceProviderConnectionResponse:
        return BalanceProviderConnectionResponse(
            id=connection.id,
            provider_type=connection.provider_type,
            status=cast(BalanceProviderConnectionStatus, connection.status),
            consent_requested_at=connection.consent_requested_at,
            consent_granted_at=connection.consent_granted_at,
            consent_expires_at=connection.consent_expires_at,
            last_refresh_requested_at=connection.last_refresh_requested_at,
            last_refresh_started_at=connection.last_refresh_started_at,
            last_refresh_completed_at=connection.last_refresh_completed_at,
            last_error_code=connection.last_error_code,
        )

    def _audit(
        self,
        user_id: str,
        provider_type: str,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        self.db.add(
            ConnectorAuditEvent(
                user_id=user_id,
                connector_type=provider_type,
                connector_account_id=None,
                event_type=event_type,
                payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
                created_at=datetime.now(UTC),
            )
        )
