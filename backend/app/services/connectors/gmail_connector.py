"""Gmail connector implementation for connector-driven ingestion."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.models.email import GmailAccount
from app.security import decrypt_secret, encrypt_secret
from app.services.classification.engine import KNOWN_BANK_SENDERS
from app.services.connectors.base import (
    BackfillOptions,
    ConnectorBatch,
    ConnectorCursor,
    ConnectorError,
    ConnectorErrorType,
)
from app.services.connectors.errors import classify_connector_exception
from app.services.connectors.source_record import SourceRecord, SourceType
from app.services.gmail.oauth_service import build_credentials
from app.utils.text import clean_html_to_text

logger = logging.getLogger(__name__)


class GmailConnector:
    source_type = SourceType.GMAIL.value

    def __init__(self, account: GmailAccount) -> None:
        self.account = account
        self._service: Any | None = None
        self._refreshed_credentials: Any | None = None

    async def refresh_credentials(self) -> dict[str, Any]:
        service, credentials, refreshed = await asyncio.to_thread(self._build_service_sync)
        self._service = service
        if refreshed:
            self.account.access_token_ref = encrypt_secret(credentials.token)
            self.account.refresh_token_ref = encrypt_secret(
                credentials.refresh_token or decrypt_secret(self.account.refresh_token_ref) or ""
            )
            token_expiry = credentials.expiry
            if token_expiry is not None and token_expiry.tzinfo is None:
                token_expiry = token_expiry.replace(tzinfo=UTC)
            self.account.token_expires_at = token_expiry
            self._refreshed_credentials = credentials
        return {"refreshed": refreshed}

    async def fetch_incremental(self, user_id: str, cursor: ConnectorCursor) -> ConnectorBatch:
        service = await self._service_or_refresh()
        fallback_used = False
        latest_history_id: str | None = None

        if cursor.history_id:
            try:
                refs, latest_history_id = await self._list_message_refs_by_history(
                    service, cursor.history_id
                )
            except HttpError as exc:
                if getattr(exc.resp, "status", None) != 404:
                    raise
                fallback_used = True
                refs = await self._list_message_refs_by_query(
                    service,
                    self._build_incremental_query(self.account.last_sync_started_at),
                    500,
                )
        else:
            fallback_used = True
            refs = await self._list_message_refs_by_query(
                service,
                self._build_incremental_query(self.account.last_sync_started_at),
                500,
            )

        records, errors = await self._message_refs_to_records(service, user_id, refs)
        return ConnectorBatch(
            records=records,
            cursor=ConnectorCursor(
                history_id=latest_history_id or await self._get_current_history_id(service),
                fallback_used=fallback_used,
            ),
            metrics={
                "fetched": len(refs),
                "records": len(records),
                "message_failures": len(errors),
                "fallback_used": fallback_used,
                "credentials_refreshed": self._refreshed_credentials is not None,
            },
            errors=errors,
        )

    async def fetch_backfill(self, user_id: str, options: BackfillOptions) -> ConnectorBatch:
        service = await self._service_or_refresh()
        refs = await self._list_message_refs_by_query(
            service,
            self._build_sender_query(),
            options.max_results,
        )
        records, errors = await self._message_refs_to_records(service, user_id, refs)
        return ConnectorBatch(
            records=records,
            cursor=ConnectorCursor(history_id=await self._get_current_history_id(service)),
            metrics={
                "fetched": len(refs),
                "records": len(records),
                "message_failures": len(errors),
                "fallback_used": False,
                "credentials_refreshed": self._refreshed_credentials is not None,
            },
            errors=errors,
        )

    def _build_service_sync(self):
        credentials = build_credentials(
            decrypt_secret(self.account.access_token_ref) or "",
            decrypt_secret(self.account.refresh_token_ref) or "",
            self.account.token_expires_at,
        )
        refreshed = False
        should_refresh = bool(
            credentials.refresh_token and (credentials.expiry is None or credentials.expired)
        )
        if should_refresh:
            logger.info("Refreshing Gmail access credentials")
            credentials.refresh(Request())
            refreshed = True
        return build("gmail", "v1", credentials=credentials), credentials, refreshed

    async def _service_or_refresh(self):
        if self._service is None:
            await self.refresh_credentials()
        return self._service

    @staticmethod
    def _build_sender_query() -> str:
        sender_list = " OR ".join(KNOWN_BANK_SENDERS.keys())
        keyword_query = (
            '"debited" OR "credited" OR "spent" OR "transaction" OR "payment" OR '
            '"UPI" OR "card" OR "account" OR "bank" OR "refund"'
        )
        return f"(from:({sender_list}) OR {keyword_query})"

    @classmethod
    def _build_incremental_query(cls, last_sync_started_at: datetime | None) -> str:
        base_query = cls._build_sender_query()
        if last_sync_started_at is None:
            return f"({base_query}) newer_than:7d"
        if last_sync_started_at.tzinfo is None:
            last_sync_started_at = last_sync_started_at.replace(tzinfo=UTC)
        after = (last_sync_started_at - timedelta(days=1)).strftime("%Y/%m/%d")
        return f"({base_query}) after:{after}"

    @staticmethod
    async def _get_current_history_id(service) -> str | None:
        request = service.users().getProfile(userId="me")
        profile = await asyncio.to_thread(request.execute)
        history_id = profile.get("historyId")
        return str(history_id) if history_id else None

    @staticmethod
    async def _list_message_refs_by_query(
        service, query: str, max_results: int | None
    ) -> list[dict]:
        messages: list[dict[str, Any]] = []
        next_page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            page_size = 500 if max_results is None else min(max_results - len(messages), 500)
            if page_size <= 0:
                break

            list_kwargs: dict[str, Any] = {
                "userId": "me",
                "q": query,
                "maxResults": page_size,
            }
            if next_page_token:
                list_kwargs["pageToken"] = next_page_token

            request = service.users().messages().list(**list_kwargs)
            response = await asyncio.to_thread(request.execute)
            messages.extend(response.get("messages", []))
            next_page_token = response.get("nextPageToken")
            if next_page_token and next_page_token in seen_page_tokens:
                raise RuntimeError("Gmail pagination repeated a page token")
            if next_page_token:
                seen_page_tokens.add(next_page_token)
            if not next_page_token or (max_results is not None and len(messages) >= max_results):
                break

        return messages[:max_results] if max_results is not None else messages

    @staticmethod
    async def _list_message_refs_by_history(
        service, start_history_id: str
    ) -> tuple[list[dict], str | None]:
        messages_by_id: dict[str, dict] = {}
        next_page_token = None
        seen_page_tokens: set[str] = set()
        latest_history_id: str | None = None

        while True:
            list_kwargs = {
                "userId": "me",
                "startHistoryId": start_history_id,
                "historyTypes": ["messageAdded"],
                "maxResults": 500,
            }
            if next_page_token:
                list_kwargs["pageToken"] = next_page_token

            request = service.users().history().list(**list_kwargs)
            response = await asyncio.to_thread(request.execute)
            latest_history_id = str(response.get("historyId") or latest_history_id or "")
            for item in response.get("history", []):
                for added in item.get("messagesAdded", []):
                    message = added.get("message") or {}
                    message_id = message.get("id")
                    if message_id:
                        messages_by_id[message_id] = {"id": message_id}

            next_page_token = response.get("nextPageToken")
            if next_page_token and next_page_token in seen_page_tokens:
                raise RuntimeError("Gmail history pagination repeated a page token")
            if next_page_token:
                seen_page_tokens.add(next_page_token)
            if not next_page_token:
                break

        return list(messages_by_id.values()), latest_history_id or None

    async def _message_refs_to_records(
        self,
        service,
        user_id: str,
        refs: list[dict],
    ) -> tuple[list[SourceRecord], list[ConnectorError]]:
        records: list[SourceRecord] = []
        errors: list[ConnectorError] = []
        for ref in refs:
            message_id = ref.get("id")
            if not isinstance(message_id, str) or not message_id:
                errors.append(
                    ConnectorError(
                        ConnectorErrorType.UNKNOWN,
                        "Gmail returned an invalid message reference",
                        False,
                    )
                )
                continue
            try:
                request = service.users().messages().get(userId="me", id=message_id, format="full")
                message = await asyncio.to_thread(request.execute)
                records.append(self._message_to_record(user_id, message))
            except Exception as exc:
                error_type = classify_connector_exception(exc)
                if error_type != ConnectorErrorType.UNKNOWN:
                    raise
                errors.append(
                    ConnectorError(
                        ConnectorErrorType.UNKNOWN,
                        "Gmail message could not be decoded",
                        False,
                    )
                )
        return records, errors

    @classmethod
    def _message_to_record(cls, user_id: str, message: dict) -> SourceRecord:
        payload = message.get("payload", {})
        headers = cls._extract_headers(payload.get("headers", []))
        received_at = cls._parse_internal_date(message.get("internalDate"))
        return SourceRecord(
            user_id=user_id,
            source_type=SourceType.GMAIL,
            source_message_id=message.get("id"),
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            body=clean_html_to_text(cls._extract_email_body(payload)),
            received_at=received_at,
        )

    @staticmethod
    def _parse_internal_date(value: object) -> datetime | None:
        try:
            internal_date_ms = int(str(value))
            if internal_date_ms <= 0:
                return None
            return datetime.fromtimestamp(internal_date_ms / 1000, tz=UTC)
        except (OverflowError, TypeError, ValueError):
            return None

    @staticmethod
    def _extract_headers(headers: list[dict]) -> dict:
        result = {}
        for header in headers:
            name = header.get("name", "").lower()
            if name in ("from", "subject", "date"):
                result[name] = header.get("value", "")
        return result

    @classmethod
    def _extract_email_body(cls, payload: dict) -> str:
        if "body" in payload and payload["body"].get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )

        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
            if "parts" in part:
                nested_body = cls._extract_email_body(part)
                if nested_body:
                    return nested_body

        for part in parts:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
        return ""
