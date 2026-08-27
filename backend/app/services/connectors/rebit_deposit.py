"""ReBIT deposit FI-type adapter for provider-backed balance observations.

The adapter intentionally stops at the PFIS ``BalanceConnector`` contract. It
parses a ReBIT deposit response and converts the provider's current balance and
transaction window into append-only, provider-neutral observations. Transport,
consent, encryption, and institution selection remain responsibilities of the
Account Aggregator integration that supplies the payload.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ElementTree
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync import BalanceProviderConnection
from app.services.connectors.balance_registry import (
    BalanceAccountDiscoveryFactory,
    BalanceConnectorRegistration,
    balance_connector_registry,
)
from app.services.connectors.base import (
    BalanceConnector,
    BalanceObservation,
    BalanceObservationBatch,
    ConnectorCursor,
    ConnectorError,
    ConnectorErrorType,
)

REBIT_DEPOSIT_SOURCE_TYPE = "rebit_deposit"
REBIT_DEPOSIT_SCHEMA_VERSION = "2.0.0"
DEFAULT_EXPECTED_CADENCE_MINUTES = 24 * 60
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class RebitDepositPayload:
    """A fetched FI-type document plus the provider's opaque resume cursor."""

    body: str | bytes
    cursor: ConnectorCursor = field(default_factory=ConnectorCursor)


RebitDepositFetcher = Callable[[str, list[str], ConnectorCursor], Awaitable[RebitDepositPayload]]


def _local_name(tag: str) -> str:
    """Return an XML element's local name for namespaced and plain tags."""

    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    for candidate in element:
        if _local_name(candidate.tag) == name:
            return candidate
    return None


def _utc_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _utc_window_start(value: str | None) -> datetime | None:
    parsed = _date(value)
    return datetime.combine(parsed, time.min, tzinfo=UTC) if parsed else None


def _utc_window_end(value: str | None) -> datetime | None:
    parsed = _date(value)
    return datetime.combine(parsed, time.max, tzinfo=UTC) if parsed else None


def _date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _amount(value: str | None) -> Decimal | None:
    if not value or not value.strip():
        return None
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    try:
        return parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _source_record_id(
    linked_account_reference: str,
    version: str,
    effective_at: datetime,
    amount: Decimal,
    currency: str,
    coverage_start: datetime | None,
    coverage_end: datetime | None,
    has_pending_transactions: bool,
) -> str:
    """Create a retry-stable ID without echoing provider identifiers."""

    identity = "|".join(
        (
            linked_account_reference,
            version,
            effective_at.isoformat(),
            str(amount),
            currency,
            coverage_start.isoformat() if coverage_start else "",
            coverage_end.isoformat() if coverage_end else "",
            "pending" if has_pending_transactions else "settled",
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:48]
    return f"rebit-deposit:{digest}"


def _invalid_batch(
    account_ids: list[str],
    message: str,
    *,
    cursor: ConnectorCursor | None = None,
) -> BalanceObservationBatch:
    return BalanceObservationBatch(
        source="connector",
        cursor=cursor or ConnectorCursor(),
        coverage_complete=False,
        errors=[
            ConnectorError(
                error_type=ConnectorErrorType.PERMANENT,
                message=message,
                retryable=False,
            )
        ],
        affected_account_ids=sorted(set(account_ids)),
    )


def parse_rebit_deposit_payload(
    payload: str | bytes,
    account_map: Mapping[str, str],
    *,
    observed_at: datetime | None = None,
    expected_cadence_minutes: int = DEFAULT_EXPECTED_CADENCE_MINUTES,
    cursor: ConnectorCursor | None = None,
) -> BalanceObservationBatch:
    """Parse a ReBIT deposit v2.0.0 document into PFIS observations.

    ``account_map`` maps local PFIS account IDs to opaque ReBIT
    ``linkedAccRef`` values. Unknown provider accounts are ignored, while a
    requested account that is absent or malformed is marked affected and makes
    the batch incomplete. Negative balances are rejected because the current
    PFIS observation contract stores non-negative amounts; overdraft semantics
    need a typed liability/available-credit contract before they can be safely
    represented.
    """

    local_account_ids = list(account_map)
    if not local_account_ids or any(
        not local_id.strip() or not provider_id.strip()
        for local_id, provider_id in account_map.items()
    ):
        return _invalid_batch(local_account_ids, "ReBIT account mapping is invalid", cursor=cursor)
    provider_to_local: dict[str, str] = {}
    for local_id, provider_id in account_map.items():
        if provider_id in provider_to_local:
            return _invalid_batch(
                local_account_ids,
                "ReBIT account mapping contains duplicate provider identities",
                cursor=cursor,
            )
        provider_to_local[provider_id] = local_id

    if expected_cadence_minutes <= 0:
        return _invalid_batch(
            local_account_ids,
            "ReBIT balance cadence must be positive",
            cursor=cursor,
        )
    retrieval_time = observed_at or datetime.now(UTC)
    if retrieval_time.tzinfo is None or retrieval_time.utcoffset() is None:
        return _invalid_batch(
            local_account_ids,
            "ReBIT retrieval time must include a timezone",
            cursor=cursor,
        )
    retrieval_time = retrieval_time.astimezone(UTC)

    if isinstance(payload, bytes):
        unsafe_payload = payload.upper()
    else:
        unsafe_payload = payload.upper().encode("utf-8", errors="ignore")
    if b"<!DOCTYPE" in unsafe_payload or b"<!ENTITY" in unsafe_payload:
        return _invalid_batch(
            local_account_ids,
            "ReBIT payload contains unsupported XML declarations",
            cursor=cursor,
        )
    try:
        root = ElementTree.fromstring(payload)
    except (ElementTree.ParseError, TypeError, ValueError):
        return _invalid_batch(local_account_ids, "ReBIT payload is not valid XML", cursor=cursor)

    account_elements = [element for element in root.iter() if _local_name(element.tag) == "Account"]
    if not account_elements:
        return _invalid_batch(local_account_ids, "ReBIT payload contains no account", cursor=cursor)

    observations: list[BalanceObservation] = []
    affected: set[str] = set()
    errors: list[ConnectorError] = []
    seen_provider_ids: set[str] = set()
    for account in account_elements:
        linked_reference = account.attrib.get("linkedAccRef", "").strip()
        matched_local_id = provider_to_local.get(linked_reference)
        if matched_local_id is None:
            continue
        if linked_reference in seen_provider_ids:
            affected.add(matched_local_id)
            errors.append(
                ConnectorError(
                    error_type=ConnectorErrorType.PERMANENT,
                    message="ReBIT payload contains a duplicate account identity",
                    retryable=False,
                )
            )
            continue
        seen_provider_ids.add(linked_reference)
        if len(linked_reference) > 128:
            affected.add(matched_local_id)
            errors.append(
                ConnectorError(
                    error_type=ConnectorErrorType.PERMANENT,
                    message="ReBIT provider account identity is too long",
                    retryable=False,
                )
            )
            continue
        if (
            account.attrib.get("type") != "deposit"
            or account.attrib.get("version") != REBIT_DEPOSIT_SCHEMA_VERSION
        ):
            affected.add(matched_local_id)
            errors.append(
                ConnectorError(
                    error_type=ConnectorErrorType.PERMANENT,
                    message="ReBIT account type or schema version is unsupported",
                    retryable=False,
                )
            )
            continue

        summary = _child(account, "Summary")
        if summary is None:
            affected.add(matched_local_id)
            errors.append(
                ConnectorError(
                    error_type=ConnectorErrorType.PERMANENT,
                    message="ReBIT account summary is missing",
                    retryable=False,
                )
            )
            continue
        amount = _amount(summary.attrib.get("currentBalance"))
        currency = summary.attrib.get("currency", "").strip().upper()
        effective_at = _utc_datetime(summary.attrib.get("balanceDateTime"))
        if amount is None or not _CURRENCY_PATTERN.fullmatch(currency) or effective_at is None:
            affected.add(matched_local_id)
            errors.append(
                ConnectorError(
                    error_type=ConnectorErrorType.PERMANENT,
                    message="ReBIT account summary has invalid balance evidence",
                    retryable=False,
                )
            )
            continue

        transactions = _child(account, "Transactions")
        coverage_start = _utc_window_start(
            transactions.attrib.get("startDate") if transactions is not None else None
        )
        coverage_end = _utc_window_end(
            transactions.attrib.get("endDate") if transactions is not None else None
        )
        # Pending transactions are intentionally not projected into the
        # append-only balance fact. Keep the observation, but fail closed on
        # coverage so the position layer cannot call it fully settled.
        has_pending_transactions = _child(summary, "PendingTxns") is not None
        coverage_complete = (
            coverage_start is not None and coverage_end is not None and not has_pending_transactions
        )
        if (
            coverage_start is not None
            and coverage_end is not None
            and coverage_end < coverage_start
        ):
            coverage_start = None
            coverage_end = None
            coverage_complete = False

        observation_time = max(retrieval_time, effective_at)
        observations.append(
            BalanceObservation(
                financial_account_id=matched_local_id,
                amount=amount,
                currency=currency,
                as_of=effective_at.date(),
                source_record_id=_source_record_id(
                    linked_reference,
                    account.attrib.get("version", ""),
                    effective_at,
                    amount,
                    currency,
                    coverage_start,
                    coverage_end,
                    has_pending_transactions,
                ),
                observed_at=observation_time,
                source="connector",
                source_account_id=linked_reference,
                effective_at=effective_at,
                expected_cadence_minutes=expected_cadence_minutes,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                coverage_complete=coverage_complete,
            )
        )
        if not coverage_complete:
            affected.add(matched_local_id)

    missing = set(local_account_ids) - {
        observation.financial_account_id for observation in observations
    }
    affected.update(missing)
    batch_coverage_complete = (
        bool(observations)
        and not errors
        and not missing
        and all(observation.coverage_complete for observation in observations)
    )
    return BalanceObservationBatch(
        source="connector",
        observations=observations,
        cursor=cursor or ConnectorCursor(),
        coverage_complete=batch_coverage_complete,
        errors=errors,
        affected_account_ids=sorted(affected),
    )


class RebitDepositConnector:
    """Injectable ReBIT adapter; a transport supplies the FI-type payload."""

    source_type = REBIT_DEPOSIT_SOURCE_TYPE

    def __init__(
        self,
        account_map: Mapping[str, str],
        fetch_payload: RebitDepositFetcher,
        *,
        expected_cadence_minutes: int = DEFAULT_EXPECTED_CADENCE_MINUTES,
    ) -> None:
        self._account_map = dict(account_map)
        self._fetch_payload = fetch_payload
        self._expected_cadence_minutes = expected_cadence_minutes

    async def fetch_balance_observations(
        self,
        user_id: str,
        account_ids: list[str],
        cursor: ConnectorCursor,
    ) -> BalanceObservationBatch:
        requested_map = {
            account_id: self._account_map[account_id]
            for account_id in account_ids
            if account_id in self._account_map
        }
        missing = [account_id for account_id in account_ids if account_id not in requested_map]
        if missing:
            return _invalid_batch(
                account_ids,
                "ReBIT connector account mapping is incomplete",
                cursor=cursor,
            )
        payload = await self._fetch_payload(
            user_id,
            [requested_map[account_id] for account_id in account_ids],
            cursor,
        )
        return parse_rebit_deposit_payload(
            payload.body,
            requested_map,
            observed_at=datetime.now(UTC),
            expected_cadence_minutes=self._expected_cadence_minutes,
            cursor=payload.cursor,
        )


def register_rebit_deposit_provider(
    fetch_payload: RebitDepositFetcher,
    *,
    discovery_factory: BalanceAccountDiscoveryFactory | None = None,
    label: str = "ReBIT deposit provider",
    expected_cadence_minutes: int = DEFAULT_EXPECTED_CADENCE_MINUTES,
) -> BalanceConnectorRegistration:
    """Register ReBIT once a deployment supplies transport and discovery.

    The fetcher is the provider-owned transport boundary.  It must handle
    Account Aggregator authentication, encryption, rate limits, and consent;
    PFIS receives only a fetched FI-type payload and never stores those
    artifacts.  Keeping registration explicit prevents local/demo deployments
    from accidentally presenting an injected adapter as a live provider.
    """

    async def factory(
        db: AsyncSession,
        user_id: str,
        _connection: BalanceProviderConnection,
    ) -> BalanceConnector:
        from app.services.balance_provider_mapping_service import (
            BalanceProviderMappingService,
        )

        mappings = await BalanceProviderMappingService(db).list_mappings(
            user_id,
            REBIT_DEPOSIT_SOURCE_TYPE,
        )
        account_map = {
            mapping.financial_account_id: mapping.provider_account_id for mapping in mappings
        }
        return RebitDepositConnector(
            account_map,
            fetch_payload,
            expected_cadence_minutes=expected_cadence_minutes,
        )

    return balance_connector_registry.register(
        REBIT_DEPOSIT_SOURCE_TYPE,
        factory,
        label=label,
        discovery_factory=discovery_factory,
    )
