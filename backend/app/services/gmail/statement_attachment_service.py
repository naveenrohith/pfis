"""Bounded read-only Gmail PDF discovery and retrieval without source storage."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from email.utils import parseaddr
from typing import Any

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from googleapiclient.errors import HttpError

from app.models.email import GmailAccount
from app.security import get_cipher
from app.services.connectors.base import ConnectorErrorType
from app.services.connectors.errors import classify_connector_exception
from app.services.connectors.gmail_connector import GmailConnector

MAX_PDF_BYTES = 10 * 1024 * 1024
REFERENCE_TTL_SECONDS = 30 * 60
MAX_MIME_PARTS = 200


def public_error(code: str, message: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def seal_reference(user_id: str, account_id: str, generation: int, kind: str, **values: Any) -> str:
    return (
        get_cipher()
        .encrypt(
            json.dumps(
                {
                    "user": user_id,
                    "account": account_id,
                    "generation": generation,
                    "kind": kind,
                    **values,
                },
                separators=(",", ":"),
            ).encode()
        )
        .decode()
    )


def open_reference(
    token: str, user_id: str, account_id: str, generation: int, kind: str
) -> dict[str, Any]:
    try:
        values = json.loads(get_cipher().decrypt(token.encode(), ttl=REFERENCE_TTL_SECONDS))
        if (
            not isinstance(values, dict)
            or values.get("user") != user_id
            or values.get("account") != account_id
            or values.get("generation") != generation
            or values.get("kind") != kind
        ):
            raise ValueError
        return values
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise public_error(
            "source_expired", "This Gmail selection expired or changed; search again", 409
        ) from None


def display_metadata(value: str, limit: int = 160) -> str:
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    # Mask long identifiers including numbers separated by spaces or hyphens.
    value = re.sub(r"(?<!\d)\d(?:[ -]?\d){4,}(?!\d)", "••••", value)
    return value[:limit]


def pdf_parts(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(payload, dict):
        return [], True
    pending = [(payload, 0)]
    parts: list[dict[str, Any]] = []
    visited = 0
    truncated = False
    while pending and visited < MAX_MIME_PARTS:
        part, depth = pending.pop()
        visited += 1
        body = part.get("body", {})
        filename = str(part.get("filename", ""))
        if (
            (part.get("mimeType") == "application/pdf" or filename.lower().endswith(".pdf"))
            and isinstance(part.get("partId"), str)
            and isinstance(body, dict)
            and (
                isinstance(body.get("attachmentId"), str)
                and bool(body["attachmentId"])
                or isinstance(body.get("data"), str)
                and bool(body["data"])
            )
        ):
            parts.append(part)
        children = part.get("parts", [])
        if isinstance(children, list):
            if depth >= 10 and children:
                truncated = True
            else:
                pending.extend(
                    (child, depth + 1)
                    for child in reversed(children[:MAX_MIME_PARTS])
                    if isinstance(child, dict)
                )
                truncated = truncated or len(children) > MAX_MIME_PARTS
    return parts, truncated or bool(pending)


@dataclass
class AttachmentPage:
    candidates: list[dict[str, Any]]
    next_page_token: str | None
    message_failures: int = 0
    truncated: bool = False


class GmailStatementAttachments:
    def __init__(self, account: GmailAccount) -> None:
        # Refresh only a detached snapshot. Routes persist it under the connection fence.
        self.connector = GmailConnector(
            GmailAccount(
                id=account.id,
                user_id=account.user_id,
                google_account_id=account.google_account_id,
                access_token_ref=account.access_token_ref,
                refresh_token_ref=account.refresh_token_ref,
                token_expires_at=account.token_expires_at,
            )
        )

    async def _execute(self, request: Any) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(request.execute, num_retries=1)
        except Exception as exc:
            if isinstance(exc, HttpError) and getattr(exc.resp, "status", None) == 404:
                raise public_error(
                    "attachment_missing", "This attachment is no longer available", 404
                ) from None
            error_type = classify_connector_exception(exc)
            if error_type == ConnectorErrorType.PERMANENT:
                raise public_error(
                    "gmail_reauthorization_required", "Reconnect Gmail to read statements", 409
                ) from None
            raise public_error(
                "gmail_unavailable", "Gmail could not be reached; try again", 503
            ) from None
        if not isinstance(result, dict):
            raise public_error("gmail_unavailable", "Gmail returned an invalid response", 503)
        return result

    async def _service(self) -> Any:
        try:
            service = await self.connector._service_or_refresh()
        except Exception as exc:
            if classify_connector_exception(exc) == ConnectorErrorType.PERMANENT:
                raise public_error(
                    "gmail_reauthorization_required", "Reconnect Gmail to read statements", 409
                ) from None
            raise public_error(
                "gmail_unavailable", "Gmail could not be reached; try again", 503
            ) from None
        # google-auth-httplib2 exposes the underlying transport; bound socket I/O,
        # including requests that continue briefly after async task cancellation.
        transport = getattr(getattr(service, "_http", None), "http", None)
        if transport is not None:
            transport.timeout = 20
        return service

    async def candidates(
        self, start_date: date, end_date: date, page_token: str | None = None
    ) -> AttachmentPage:
        service = await self._service()
        after = int(datetime.combine(start_date, time.min, UTC).timestamp())
        before = int(datetime.combine(end_date, time.min, UTC).timestamp())
        page = await self._execute(
            service.users()
            .messages()
            .list(
                userId="me",
                q=f"has:attachment filename:pdf after:{after} before:{before}",
                maxResults=20,
                pageToken=page_token,
            )
        )
        items: list[dict[str, Any]] = []
        failures = 0
        truncated = False
        refs = page.get("messages", [])
        if not isinstance(refs, list) or len(refs) > 20:
            raise public_error("gmail_unavailable", "Gmail returned an invalid statement page", 503)
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
                failures += 1
                continue
            message_id = ref["id"]
            try:
                message = await self._execute(
                    service.users().messages().get(userId="me", id=message_id, format="full")
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                failures += 1
                continue
            payload = message.get("payload", {})
            if not isinstance(payload, dict):
                failures += 1
                continue
            raw_headers = payload.get("headers", [])
            headers = GmailConnector._extract_headers(
                [
                    header
                    for header in raw_headers
                    if isinstance(header, dict)
                    and isinstance(header.get("name"), str)
                    and isinstance(header.get("value"), str)
                ]
                if isinstance(raw_headers, list)
                else []
            )
            parts, clipped = pdf_parts(payload)
            truncated = truncated or clipped
            for part in parts:
                if len(items) >= 100:
                    truncated = True
                    break
                size = part["body"].get("size", 0)
                if not isinstance(size, int) or size <= 0 or size > MAX_PDF_BYTES:
                    truncated = True
                    continue
                items.append(
                    {
                        "message_id": message_id,
                        "part_id": part["partId"],
                        "sender": display_metadata(parseaddr(headers.get("from", ""))[1]),
                        "subject": display_metadata(headers.get("subject", "")),
                        "filename": display_metadata(str(part.get("filename") or "statement.pdf")),
                        "size_bytes": size,
                        "received_at": GmailConnector._parse_internal_date(
                            message.get("internalDate")
                        ),
                    }
                )
        next_token = page.get("nextPageToken")
        if next_token is not None and (not isinstance(next_token, str) or next_token == page_token):
            raise public_error(
                "gmail_unavailable", "Gmail returned an invalid statement cursor", 503
            )
        return AttachmentPage(items, next_token, failures, truncated)

    async def fetch(self, message_id: str, part_id: str) -> bytes:
        service = await self._service()
        message = await self._execute(
            service.users().messages().get(userId="me", id=message_id, format="full")
        )
        parts, _ = pdf_parts(message.get("payload", {}))
        matches = [part for part in parts if part["partId"] == part_id]
        if len(matches) != 1:
            raise public_error(
                "attachment_missing", "This PDF attachment is no longer available", 404
            )
        body = matches[0]["body"]
        size = body.get("size", 0)
        if not isinstance(size, int) or size <= 0 or size > MAX_PDF_BYTES:
            raise public_error("payload_too_large", "Statements must be 10 MB or smaller", 413)
        if body.get("attachmentId"):
            body = await self._execute(
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=body["attachmentId"])
            )
        encoded = body.get("data", "")
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_PDF_BYTES + 2) // 3):
            raise public_error("payload_too_large", "Statements must be 10 MB or smaller", 413)
        try:
            payload = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
        except (ValueError, binascii.Error):
            raise public_error("invalid_pdf", "Gmail returned an unreadable attachment") from None
        if len(payload) > MAX_PDF_BYTES:
            raise public_error("payload_too_large", "Statements must be 10 MB or smaller", 413)
        if not payload.startswith(b"%PDF"):
            raise public_error("invalid_pdf", "Choose a PDF statement attachment")
        return payload
