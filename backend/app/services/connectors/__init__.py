"""Connector contracts for source records that feed the PFIS pipeline."""

from app.services.connectors.base import (
    BackfillOptions,
    BaseConnector,
    ConnectorBatch,
    ConnectorCursor,
    ConnectorError,
    ConnectorErrorType,
)
from app.services.connectors.gmail_connector import GmailConnector
from app.services.connectors.source_record import SourceRecord, SourceType

__all__ = [
    "BackfillOptions",
    "BaseConnector",
    "ConnectorBatch",
    "ConnectorCursor",
    "ConnectorError",
    "ConnectorErrorType",
    "GmailConnector",
    "SourceRecord",
    "SourceType",
]
