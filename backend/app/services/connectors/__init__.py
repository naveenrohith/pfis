"""Connector contracts for source records that feed the PFIS pipeline."""

from app.services.connectors.balance_registry import (
    BalanceConnectorRegistration,
    BalanceConnectorRegistry,
    balance_connector_registry,
)
from app.services.connectors.base import (
    BackfillOptions,
    BalanceAccountCandidate,
    BalanceAccountDiscovery,
    BalanceConnector,
    BalanceObservation,
    BalanceObservationBatch,
    BaseConnector,
    CardPositionObservation,
    ConnectorBatch,
    ConnectorCursor,
    ConnectorError,
    ConnectorErrorType,
)
from app.services.connectors.gmail_connector import GmailConnector
from app.services.connectors.rebit_deposit import (
    DEFAULT_EXPECTED_CADENCE_MINUTES,
    REBIT_DEPOSIT_SCHEMA_VERSION,
    REBIT_DEPOSIT_SOURCE_TYPE,
    RebitDepositConnector,
    RebitDepositPayload,
    parse_rebit_deposit_payload,
    register_rebit_deposit_provider,
)
from app.services.connectors.source_record import SourceRecord, SourceType

__all__ = [
    "BackfillOptions",
    "BalanceAccountCandidate",
    "BalanceAccountDiscovery",
    "BaseConnector",
    "BalanceConnector",
    "BalanceConnectorRegistration",
    "BalanceConnectorRegistry",
    "BalanceObservation",
    "BalanceObservationBatch",
    "CardPositionObservation",
    "balance_connector_registry",
    "ConnectorBatch",
    "ConnectorCursor",
    "ConnectorError",
    "ConnectorErrorType",
    "DEFAULT_EXPECTED_CADENCE_MINUTES",
    "GmailConnector",
    "REBIT_DEPOSIT_SCHEMA_VERSION",
    "REBIT_DEPOSIT_SOURCE_TYPE",
    "RebitDepositConnector",
    "RebitDepositPayload",
    "register_rebit_deposit_provider",
    "SourceRecord",
    "SourceType",
    "parse_rebit_deposit_payload",
]
