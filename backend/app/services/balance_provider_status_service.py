"""Read-only readiness for provider-backed bank and card refreshes.

The balance observation and sync services already define the ingestion
boundary.  This service gives the product a truthful status surface around
that boundary: it reports mapping, coverage, and freshness, while making it
impossible for the UI to mistake transaction roll-forwards for a live issuer
amount.  A provider transport and consent implementation can later be wired
in without changing this response contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSource, FinancialAccount
from app.schemas.account import (
    AccountProductType,
    BalanceProviderAccountResponse,
    BalanceProviderAccountStatus,
    BalanceProviderReadinessStatus,
    BalanceProviderStatusResponse,
)
from app.services.balance_observation_service import BalanceObservationService
from app.services.balance_provider_connection_service import BalanceProviderConnectionService
from app.services.balance_provider_mapping_service import BalanceProviderMappingService
from app.services.connectors.balance_registry import balance_connector_registry


class BalanceProviderStatusService:
    """Build a user-scoped, non-secret provider readiness response."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def status(self, user_id: str) -> BalanceProviderStatusResponse:
        connections = await BalanceProviderConnectionService(self.db).list_connections(user_id)
        supported_provider_types = balance_connector_registry.supported_provider_types()
        active_provider_types = {
            connection.provider_type for connection in connections if connection.status == "active"
        }
        connection_statuses = {connection.status for connection in connections}
        refreshable_provider_types = active_provider_types.intersection(supported_provider_types)
        refresh_supported = bool(refreshable_provider_types)
        provider_labels = balance_connector_registry.labels()
        provider_name = next(
            (provider_labels[item] for item in sorted(refreshable_provider_types)),
            None,
        )
        mapping_provider_type = next(
            iter(sorted(refreshable_provider_types)),
            next(iter(sorted(supported_provider_types)), None),
        )
        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount)
                    .where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                    )
                    .order_by(FinancialAccount.institution_name, FinancialAccount.id)
                )
            ).all()
        )
        if not accounts:
            return BalanceProviderStatusResponse(
                status="not_configured",
                refresh_supported=refresh_supported,
                consent_required=not refresh_supported,
                provider_name=provider_name,
                supported_provider_types=supported_provider_types,
                connections=connections,
                account_count=0,
                mapped_account_count=0,
                reason_codes=["no_active_accounts"],
                next_step=("Add a bank or card account before connecting a balance provider."),
            )

        account_ids = [account.id for account in accounts]
        provider_mappings = (
            await BalanceProviderMappingService(self.db).account_provider_ids(
                user_id,
                mapping_provider_type,
                account_ids,
            )
            if mapping_provider_type
            else {}
        )
        source_rows = list(
            (
                await self.db.scalars(
                    select(AccountBalanceSource).where(
                        AccountBalanceSource.user_id == user_id,
                        AccountBalanceSource.financial_account_id.in_(account_ids),
                        AccountBalanceSource.source == "connector",
                    )
                )
            ).all()
        )
        by_account: dict[str, list[AccountBalanceSource]] = {}
        for row in source_rows:
            by_account.setdefault(row.financial_account_id, []).append(row)

        account_statuses: list[BalanceProviderAccountResponse] = []
        top_reasons: list[str] = []
        mapped_count = 0
        last_success_at: datetime | None = None
        coverage_service = BalanceObservationService(self.db)

        for account in accounts:
            provider_account_id = (
                provider_mappings.get(account.id) or (account.connector_account_id or "").strip()
            ) or None
            if provider_account_id:
                mapped_count += 1
            state = self._source_state(
                by_account.get(account.id, []),
                provider_account_id,
            )
            account_status = self._account_status(
                account,
                state,
                provider_account_id,
                coverage_service,
            )
            account_statuses.append(account_status)
            top_reasons.extend(account_status.reason_codes)
            if account_status.last_success_at is not None and (
                last_success_at is None or account_status.last_success_at > last_success_at
            ):
                last_success_at = account_status.last_success_at

        # The connector-neutral runner is usable by injected/provider code,
        # but this deployment still has no transport or consent registry.  It
        # is deliberately exposed as a capability flag instead of fabricating
        # a live refresh action.
        consent_required = not refresh_supported
        if not supported_provider_types:
            top_reasons.append("provider_transport_not_configured")
        elif not refresh_supported:
            if "pending" in connection_statuses:
                top_reasons.append("provider_consent_pending")
            elif "expired" in connection_statuses:
                top_reasons.append("provider_consent_expired")
            elif "error" in connection_statuses:
                top_reasons.append("provider_connection_error")
            else:
                top_reasons.append("provider_consent_required")
        if mapped_count < len(accounts):
            top_reasons.append("account_mapping_required")

        statuses = {item.status for item in account_statuses}
        if "incomplete" in statuses:
            overall_status = "incomplete"
        elif "unmapped" in statuses or "not_configured" in statuses:
            overall_status = "blocked"
        elif "overdue" in statuses:
            overall_status = "overdue"
        elif "due" in statuses:
            overall_status = "due"
        else:
            overall_status = "ready"

        if mapped_count < len(accounts):
            next_step = "Complete provider consent and map every owned bank/card account."
        elif not refresh_supported:
            next_step = "Choose a consented institution or Account Aggregator connector before requesting live amounts."
        elif overall_status in {"overdue", "due", "incomplete"}:
            next_step = (
                "Refresh the provider and confirm complete coverage before using current amounts."
            )
        else:
            next_step = "Provider refresh is available; confirm the latest coverage before acting."

        return BalanceProviderStatusResponse(
            status=cast(BalanceProviderReadinessStatus, overall_status),
            refresh_supported=refresh_supported,
            consent_required=consent_required,
            provider_name=provider_name,
            supported_provider_types=supported_provider_types,
            connections=connections,
            account_count=len(accounts),
            mapped_account_count=mapped_count,
            last_success_at=last_success_at,
            reason_codes=list(dict.fromkeys(top_reasons)),
            next_step=next_step,
            accounts=account_statuses,
        )

    @staticmethod
    def _source_state(
        rows: list[AccountBalanceSource],
        provider_account_id: str | None,
    ) -> AccountBalanceSource | None:
        if provider_account_id:
            exact_rows = [row for row in rows if row.source_account_id == provider_account_id]
            if exact_rows:
                return max(
                    exact_rows,
                    key=lambda row: (
                        BalanceProviderStatusService._as_utc(row.last_success_at)
                        or BalanceProviderStatusService._as_utc(row.last_observed_at)
                        or datetime.min.replace(tzinfo=UTC)
                    ),
                )
        # Failure records are intentionally created without a provider
        # account key.  Use the sole row as a safe health signal when there is
        # no conflicting provider state.
        return rows[0] if len(rows) == 1 else None

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _account_status(
        account: FinancialAccount,
        state: AccountBalanceSource | None,
        provider_account_id: str | None,
        coverage_service: BalanceObservationService,
    ) -> BalanceProviderAccountResponse:
        if provider_account_id is None:
            return BalanceProviderAccountResponse(
                financial_account_id=account.id,
                account_type=cast(AccountProductType, account.account_type),
                masked_number=account.masked_number,
                status="unmapped",
                reason_codes=["account_mapping_required"],
            )

        if state is None:
            return BalanceProviderAccountResponse(
                financial_account_id=account.id,
                account_type=cast(AccountProductType, account.account_type),
                masked_number=account.masked_number,
                status="not_configured",
                source_account_id=provider_account_id,
                reason_codes=["provider_observation_missing"],
            )

        coverage = coverage_service._coverage_response(state, now=datetime.now(UTC))
        reasons = list(coverage.reason_codes)
        if state.last_success_at is None and state.last_error_code:
            status = "incomplete"
            reasons.append(state.last_error_code)
        elif not coverage.coverage_complete:
            status = "incomplete"
        elif coverage.freshness_status == "overdue":
            status = "overdue"
        elif coverage.freshness_status == "due":
            status = "due"
        elif coverage.freshness_status == "unknown":
            status = "incomplete"
            reasons.append("provider_freshness_unknown")
        elif state.last_success_at is None:
            status = "not_configured"
            reasons.append("provider_observation_missing")
        else:
            status = "ready"

        return BalanceProviderAccountResponse(
            financial_account_id=account.id,
            account_type=cast(AccountProductType, account.account_type),
            masked_number=account.masked_number,
            status=cast(BalanceProviderAccountStatus, status),
            source_account_id=coverage.source_account_id,
            expected_next_at=coverage.expected_next_at,
            last_observed_at=coverage.last_observed_at,
            last_success_at=coverage.last_success_at,
            coverage_complete=coverage.coverage_complete,
            freshness_status=coverage.freshness_status,
            reason_codes=list(dict.fromkeys(reasons)),
        )
