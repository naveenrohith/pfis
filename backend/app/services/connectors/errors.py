"""Connector retry/error classification."""

from __future__ import annotations

from googleapiclient.errors import HttpError

from app.services.connectors.base import ConnectorErrorType


def classify_connector_exception(exc: Exception) -> ConnectorErrorType:
    message = str(exc).lower()
    status = getattr(getattr(exc, "resp", None), "status", None)

    if isinstance(exc, HttpError):
        if status in {401, 403}:
            return ConnectorErrorType.PERMANENT
        if status in {408, 429, 500, 502, 503, 504}:
            return ConnectorErrorType.TRANSIENT
        return ConnectorErrorType.UNKNOWN

    if any(token in message for token in ("revoked", "invalid_grant", "invalid credential")):
        return ConnectorErrorType.PERMANENT
    if any(
        token in message
        for token in (
            "timeout",
            "temporarily",
            "rate limit",
            "connection",
            "servernotfound",
            "unable to find the server",
            "getaddrinfo",
            "dns",
            "network unreachable",
        )
    ):
        return ConnectorErrorType.TRANSIENT
    return ConnectorErrorType.UNKNOWN
