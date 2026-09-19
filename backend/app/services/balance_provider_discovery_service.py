"""Provider account discovery before an owned account is mapped."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import BalanceProviderAccountMapping
from app.schemas.account import (
    AccountProductType,
    BalanceProviderAccountCandidateResponse,
)
from app.services.balance_provider_connection_service import BalanceProviderConnectionService
from app.services.connectors.balance_registry import balance_connector_registry
from app.services.connectors.base import BalanceAccountCandidate


class BalanceProviderDiscoveryService:
    """Expose only an adapter's sanitized account identity candidates."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def discover(
        self,
        user_id: str,
        provider_type: str,
    ) -> list[BalanceProviderAccountCandidateResponse]:
        normalized = provider_type.strip().lower()
        connection = await BalanceProviderConnectionService(self.db).require_active_connection(
            user_id, normalized
        )
        registration = balance_connector_registry.get(normalized)
        if registration is None or registration.discovery_factory is None:
            raise ValueError("Account discovery is not configured for this provider")
        discovery = await registration.discovery_factory(self.db, user_id, connection)
        raw_candidates = await discovery.discover_accounts(user_id)
        candidates = self._normalize_candidates(raw_candidates)
        mapped = {
            row.provider_account_id: row.financial_account_id
            for row in (
                await self.db.scalars(
                    select(BalanceProviderAccountMapping).where(
                        BalanceProviderAccountMapping.user_id == user_id,
                        BalanceProviderAccountMapping.provider_type == normalized,
                    )
                )
            ).all()
        }
        return [
            BalanceProviderAccountCandidateResponse(
                provider_account_id=candidate.provider_account_id.strip(),
                display_name=candidate.display_name.strip() if candidate.display_name else None,
                masked_number=(
                    candidate.masked_number.strip() if candidate.masked_number else None
                ),
                account_type=self._account_type(candidate.account_type),
                currency=candidate.currency.strip().upper() if candidate.currency else None,
                mapped_financial_account_id=mapped.get(candidate.provider_account_id.strip()),
            )
            for candidate in candidates
        ]

    @staticmethod
    def _normalize_candidates(
        candidates: Iterable[BalanceAccountCandidate],
    ) -> list[BalanceAccountCandidate]:
        seen: set[str] = set()
        normalized: list[BalanceAccountCandidate] = []
        for candidate in candidates:
            provider_id = candidate.provider_account_id.strip()
            if provider_id in seen:
                raise ValueError("Provider account discovery returned a duplicate identity")
            seen.add(provider_id)
            if candidate.currency is not None and len(candidate.currency.strip()) != 3:
                raise ValueError("Provider account discovery returned an invalid currency")
            normalized.append(candidate)
        if len(normalized) > 200:
            raise ValueError("Provider account discovery returned too many accounts")
        return normalized

    @staticmethod
    def _account_type(value: str | None) -> AccountProductType | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized in {"bank", "credit_card", "loan", "pay_later", "cash", "investment"}:
            return normalized  # type: ignore[return-value]
        return None
