"""Owned bank/card account mappings for consented balance providers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.sync import (
    BalanceProviderAccountMapping,
    ConnectorAuditEvent,
)
from app.schemas.account import BalanceProviderAccountMappingResponse
from app.services.balance_provider_connection_service import BalanceProviderConnectionService


class BalanceProviderMappingService:
    """Persist provider identities without treating them as credentials."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_mappings(
        self,
        user_id: str,
        provider_type: str | None = None,
    ) -> list[BalanceProviderAccountMappingResponse]:
        statement = select(BalanceProviderAccountMapping).where(
            BalanceProviderAccountMapping.user_id == user_id
        )
        if provider_type:
            statement = statement.where(
                BalanceProviderAccountMapping.provider_type == provider_type.strip().lower()
            )
        rows = list(
            (
                await self.db.scalars(
                    statement.order_by(
                        BalanceProviderAccountMapping.provider_type,
                        BalanceProviderAccountMapping.financial_account_id,
                    )
                )
            ).all()
        )
        return [self._response(row) for row in rows]

    async def map_account(
        self,
        user_id: str,
        financial_account_id: str,
        provider_type: str,
        provider_account_id: str,
        *,
        source: str = "provider_discovery",
    ) -> BalanceProviderAccountMappingResponse:
        normalized_provider = provider_type.strip().lower()
        provider_identity = provider_account_id.strip()
        if not provider_identity:
            raise ValueError("A provider account identity is required")
        if len(provider_identity) > 128:
            raise ValueError("The provider account identity is too long")
        if len(source.strip()) > 32:
            raise ValueError("The mapping source is too long")

        # A mapping is meaningful only after the external provider has granted
        # consent. This also keeps the provider registry check in one place.
        await BalanceProviderConnectionService(self.db).require_active_connection(
            user_id, normalized_provider
        )
        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == financial_account_id,
                FinancialAccount.user_id == user_id,
                FinancialAccount.is_active.is_(True),
            )
        )
        if account is None:
            raise LookupError("Financial account not found")

        identity_owner = await self.db.scalar(
            select(BalanceProviderAccountMapping).where(
                BalanceProviderAccountMapping.user_id == user_id,
                BalanceProviderAccountMapping.provider_type == normalized_provider,
                BalanceProviderAccountMapping.provider_account_id == provider_identity,
            )
        )
        if identity_owner is not None and identity_owner.financial_account_id != account.id:
            raise ValueError("The provider account is already mapped to another account")

        mapping = await self.db.scalar(
            select(BalanceProviderAccountMapping).where(
                BalanceProviderAccountMapping.user_id == user_id,
                BalanceProviderAccountMapping.provider_type == normalized_provider,
                BalanceProviderAccountMapping.financial_account_id == account.id,
            )
        )
        if mapping is None:
            mapping = BalanceProviderAccountMapping(
                user_id=user_id,
                financial_account_id=account.id,
                provider_type=normalized_provider,
                provider_account_id=provider_identity,
                source=source.strip() or "provider_discovery",
            )
            self.db.add(mapping)
        else:
            mapping.provider_account_id = provider_identity
            mapping.source = source.strip() or "provider_discovery"
            mapping.updated_at = datetime.now(UTC)

        self._audit(
            user_id,
            normalized_provider,
            "balance_provider_account_mapped",
            {
                "financial_account_id": account.id,
                "provider_account_hash": self._identity_hash(provider_identity),
                "source": mapping.source,
            },
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("The provider account is already mapped to another account") from exc
        await self.db.refresh(mapping)
        return self._response(mapping)

    async def unmap_account(
        self,
        user_id: str,
        financial_account_id: str,
        provider_type: str,
    ) -> bool:
        normalized_provider = provider_type.strip().lower()
        mapping = await self.db.scalar(
            select(BalanceProviderAccountMapping).where(
                BalanceProviderAccountMapping.user_id == user_id,
                BalanceProviderAccountMapping.provider_type == normalized_provider,
                BalanceProviderAccountMapping.financial_account_id == financial_account_id,
            )
        )
        if mapping is None:
            return False
        self._audit(
            user_id,
            normalized_provider,
            "balance_provider_account_unmapped",
            {
                "financial_account_id": financial_account_id,
                "provider_account_hash": self._identity_hash(mapping.provider_account_id),
            },
        )
        await self.db.delete(mapping)
        await self.db.commit()
        return True

    async def account_provider_ids(
        self,
        user_id: str,
        provider_type: str,
        account_ids: list[str],
    ) -> dict[str, str]:
        normalized_provider = provider_type.strip().lower()
        if not account_ids:
            return {}
        rows = list(
            (
                await self.db.scalars(
                    select(BalanceProviderAccountMapping).where(
                        BalanceProviderAccountMapping.user_id == user_id,
                        BalanceProviderAccountMapping.provider_type == normalized_provider,
                        BalanceProviderAccountMapping.financial_account_id.in_(account_ids),
                    )
                )
            ).all()
        )
        return {row.financial_account_id: row.provider_account_id for row in rows}

    async def delete_user_mappings(self, user_id: str) -> int:
        result = await self.db.execute(
            delete(BalanceProviderAccountMapping).where(
                BalanceProviderAccountMapping.user_id == user_id
            )
        )
        return max(int(result.rowcount or 0), 0)

    @staticmethod
    def _identity_hash(provider_account_id: str) -> str:
        return hashlib.sha256(provider_account_id.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _response(
        mapping: BalanceProviderAccountMapping,
    ) -> BalanceProviderAccountMappingResponse:
        return BalanceProviderAccountMappingResponse(
            id=mapping.id,
            financial_account_id=mapping.financial_account_id,
            provider_type=mapping.provider_type,
            provider_account_id=mapping.provider_account_id,
            source=mapping.source,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at,
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
