"""
Gmail Sync Service
Fetches emails from Gmail API, filters financial ones, and stores raw emails.

Pipeline:
1. Build Gmail API client with stored credentials
2. Fetch emails (filtered by known bank senders)
3. Classify each email (transaction / OTP / promo / ignore)
4. Store transaction emails in raw_emails table
5. Log sync run in sync_runs table
"""

import base64
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import GmailAccount, RawEmail
from app.models.sync import SyncRun, SyncStatus
from app.security import decrypt_secret, encrypt_secret
from app.services.gmail.email_filter import (
    KNOWN_BANK_SENDERS,
    EmailType,
    classify_email,
)
from app.services.gmail.oauth_service import build_credentials
from app.services.sync_events import sync_event_manager

logger = logging.getLogger(__name__)


async def demo_sync_gmail_emails(
    db: AsyncSession,
    user_id: str,
) -> dict:
    """Simulate Gmail sync using deterministic sample emails for demo/testing."""
    from app.services.gmail.demo_data import SAMPLE_EMAILS

    stats = {
        "emails_fetched": len(SAMPLE_EMAILS),
        "emails_stored": 0,
        "emails_skipped_otp": 0,
        "emails_skipped_promo": 0,
        "emails_skipped_duplicate": 0,
        "classifications": [],
    }

    sync_run = SyncRun(user_id=user_id, status=SyncStatus.RUNNING)
    db.add(sync_run)
    await db.commit()
    await db.refresh(sync_run)

    try:
        for email_data in SAMPLE_EMAILS:
            fake_gmail_id = f"demo_{uuid.uuid5(uuid.NAMESPACE_DNS, email_data['body'][:50])}"
            scoped_gmail_id = f"{user_id}:{fake_gmail_id}"

            existing = await db.execute(
                select(RawEmail).where(RawEmail.gmail_message_id == scoped_gmail_id)
            )
            if existing.scalar_one_or_none():
                stats["emails_skipped_duplicate"] += 1
                stats["classifications"].append(
                    {
                        "subject": email_data["subject"][:60],
                        "type": "DUPLICATE",
                    }
                )
                continue

            email_type, bank_name, confidence = classify_email(
                email_data["sender"],
                email_data["subject"],
                email_data["body"],
            )

            stats["classifications"].append(
                {
                    "subject": email_data["subject"][:60],
                    "sender": email_data["sender"],
                    "type": email_type.value,
                    "bank": bank_name,
                    "confidence": confidence,
                }
            )

            if email_type == EmailType.OTP:
                stats["emails_skipped_otp"] += 1
                continue
            if email_type == EmailType.PROMOTION:
                stats["emails_skipped_promo"] += 1
                continue
            if email_type == EmailType.IGNORE:
                continue

            db.add(
                RawEmail(
                    user_id=user_id,
                    gmail_message_id=scoped_gmail_id,
                    subject=email_data["subject"],
                    body=email_data["body"],
                    sender=email_data["sender"],
                    received_at=datetime.now(UTC),
                    processed_flag=False,
                )
            )
            stats["emails_stored"] += 1

        sync_run.status = SyncStatus.COMPLETED
        sync_run.end_time = datetime.now(UTC)
        sync_run.emails_fetched = stats["emails_fetched"]
        sync_run.emails_processed = stats["emails_stored"]
        await db.commit()

        return stats
    except Exception as e:
        sync_run.status = SyncStatus.FAILED
        sync_run.end_time = datetime.now(UTC)
        sync_run.errors = json.dumps([{"error": str(e)}])
        await db.commit()
        raise


def _build_gmail_service_sync(access_token: str, refresh_token: str):
    """Build an authenticated Gmail API service instance (sync helper)."""
    credentials = build_credentials(access_token, refresh_token)
    refreshed = False

    # Refresh if expired
    if credentials.expired:
        logger.info("Access token expired, refreshing...")
        credentials.refresh(Request())
        refreshed = True

    return build("gmail", "v1", credentials=credentials), credentials, refreshed


async def _build_gmail_service(access_token: str, refresh_token: str):
    """Build Gmail service without blocking the event loop."""
    import asyncio

    return await asyncio.to_thread(_build_gmail_service_sync, access_token, refresh_token)


def _build_sender_query() -> str:
    """
    Build a Gmail search query for likely transaction emails.

    The first implementation only searched a fixed sender allowlist. Real inboxes
    often receive alerts from vendor-specific sender aliases, UPI apps, and
    notification gateways, so use a broader recent-email query and let the local
    classifier decide what is actually financial.
    """
    sender_list = " OR ".join(KNOWN_BANK_SENDERS.keys())
    keyword_query = (
        '"debited" OR "credited" OR "spent" OR "transaction" OR "payment" OR '
        '"UPI" OR "card" OR "account" OR "bank" OR "refund"'
    )
    return f"(from:({sender_list}) OR {keyword_query})"


def _build_incremental_query(last_sync_started_at: datetime | None) -> str:
    base_query = _build_sender_query()
    if last_sync_started_at is None:
        return f"({base_query}) newer_than:7d"

    if last_sync_started_at.tzinfo is None:
        last_sync_started_at = last_sync_started_at.replace(tzinfo=UTC)
    after = (last_sync_started_at - timedelta(days=1)).strftime("%Y/%m/%d")
    return f"({base_query}) after:{after}"


def _extract_email_body(payload: dict) -> str:
    """
    Extract plain text body from Gmail message payload.
    Handles both simple and multipart email structures.
    """
    body_text = ""

    if "body" in payload and payload["body"].get("data"):
        body_text = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="replace"
        )
        return body_text

    # Handle multipart messages
    parts = payload.get("parts", [])
    for part in parts:
        mime_type = part.get("mimeType", "")

        if mime_type == "text/plain" and part.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
            return body_text

        # Nested multipart
        if "parts" in part:
            nested_body = _extract_email_body(part)
            if nested_body:
                return nested_body

    # Fallback: try text/html if no plain text
    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
            return body_text

    return body_text


def _clean_email_body(body: str) -> str:
    """Normalize Gmail HTML/plain body before storage and parsing."""
    from app.utils.text import clean_html_to_text

    return clean_html_to_text(body)


def _extract_headers(headers: list[dict]) -> dict:
    """Extract useful headers (From, Subject, Date) from Gmail message."""
    result = {}
    for header in headers:
        name = header.get("name", "").lower()
        if name in ("from", "subject", "date"):
            result[name] = header.get("value", "")
    return result


async def _get_current_history_id(service) -> str | None:
    import asyncio

    profile = await asyncio.to_thread(lambda: service.users().getProfile(userId="me").execute())
    history_id = profile.get("historyId")
    return str(history_id) if history_id else None


async def _list_message_refs_by_query(service, query: str, max_results: int | None) -> list[dict]:
    messages = []
    next_page_token = None
    while True:
        page_size = 500 if max_results is None else min(max_results - len(messages), 500)
        if page_size <= 0:
            break

        list_kwargs = {"userId": "me", "q": query, "maxResults": page_size}
        if next_page_token:
            list_kwargs["pageToken"] = next_page_token

        import asyncio

        messages_response = await asyncio.to_thread(
            lambda lk=list_kwargs: service.users().messages().list(**lk).execute()
        )
        messages.extend(messages_response.get("messages", []))
        next_page_token = messages_response.get("nextPageToken")

        if not next_page_token or (max_results is not None and len(messages) >= max_results):
            break

    return messages[:max_results] if max_results is not None else messages


async def _list_message_refs_by_history(service, start_history_id: str) -> tuple[list[dict], str | None]:
    messages_by_id: dict[str, dict] = {}
    next_page_token = None
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

        import asyncio

        response = await asyncio.to_thread(
            lambda lk=list_kwargs: service.users().history().list(**lk).execute()
        )
        latest_history_id = str(response.get("historyId") or latest_history_id or "")
        for item in response.get("history", []):
            for added in item.get("messagesAdded", []):
                message = added.get("message") or {}
                message_id = message.get("id")
                if message_id:
                    messages_by_id[message_id] = {"id": message_id}

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return list(messages_by_id.values()), latest_history_id or None


async def _store_gmail_message_refs(
    db: AsyncSession,
    service,
    user_id: str,
    message_refs: list[dict],
) -> dict:
    stats = {
        "emails_fetched": len(message_refs),
        "emails_processed": 0,
        "emails_stored": 0,
        "emails_skipped_otp": 0,
        "emails_skipped_promo": 0,
        "emails_skipped_duplicate": 0,
        "emails_failed": 0,
        "errors": [],
    }

    for msg_ref in message_refs:
        gmail_msg_id = msg_ref["id"]
        scoped_gmail_msg_id = f"{user_id}:{gmail_msg_id}"

        try:
            existing = await db.execute(
                select(RawEmail).where(RawEmail.gmail_message_id == scoped_gmail_msg_id)
            )
            if existing.scalar_one_or_none():
                stats["emails_skipped_duplicate"] += 1
                continue

            import asyncio

            msg = await asyncio.to_thread(
                lambda mid=gmail_msg_id: service.users()
                .messages()
                .get(
                    userId="me",
                    id=mid,
                    format="full",
                )
                .execute()
            )

            payload = msg.get("payload", {})
            headers = _extract_headers(payload.get("headers", []))
            body = _clean_email_body(_extract_email_body(payload))
            sender = headers.get("from", "")
            subject = headers.get("subject", "")
            internal_date_ms = int(msg.get("internalDate", 0))
            received_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=UTC)

            email_type, bank_name, confidence = classify_email(sender, subject, body)
            if email_type == EmailType.OTP:
                stats["emails_skipped_otp"] += 1
                continue
            if email_type == EmailType.PROMOTION:
                stats["emails_skipped_promo"] += 1
                continue
            if email_type == EmailType.IGNORE:
                continue

            db.add(
                RawEmail(
                    user_id=user_id,
                    gmail_message_id=scoped_gmail_msg_id,
                    subject=subject,
                    body=body,
                    sender=sender,
                    received_at=received_at,
                    processed_flag=False,
                )
            )
            stats["emails_processed"] += 1
            stats["emails_stored"] += 1
            logger.info(
                f"Stored email: [{email_type.value}] [{bank_name}] "
                f"{subject[:60]} (conf={confidence:.2f})"
            )
        except Exception as e:
            stats["emails_failed"] += 1
            stats["errors"].append({"gmail_message_id": gmail_msg_id, "error": str(e)})
            logger.error(f"Failed to process email {gmail_msg_id}: {e}")

    return stats


async def sync_gmail_emails(
    db: AsyncSession,
    user_id: str,
    gmail_account_id: str,
    max_results: int | None = 50,
) -> dict:
    """
    Main sync function. Fetches emails from Gmail and stores them.

    Returns sync summary dict.
    """
    # Create sync run record
    sync_run = SyncRun(user_id=user_id, status=SyncStatus.RUNNING)
    db.add(sync_run)
    await db.commit()
    await db.refresh(sync_run)

    stats = {
        "emails_fetched": 0,
        "emails_processed": 0,
        "emails_stored": 0,
        "emails_skipped_otp": 0,
        "emails_skipped_promo": 0,
        "emails_skipped_duplicate": 0,
        "emails_failed": 0,
        "errors": [],
    }

    try:
        # Get Gmail account credentials
        result = await db.execute(select(GmailAccount).where(GmailAccount.id == gmail_account_id))
        gmail_account = result.scalar_one_or_none()

        if not gmail_account:
            raise ValueError(f"Gmail account {gmail_account_id} not found")

        # Build Gmail service (non-blocking)
        service, credentials, refreshed = await _build_gmail_service(
            decrypt_secret(gmail_account.access_token_ref) or "",
            decrypt_secret(gmail_account.refresh_token_ref) or "",
        )

        if refreshed:
            gmail_account.access_token_ref = encrypt_secret(credentials.token)
            gmail_account.refresh_token_ref = encrypt_secret(
                credentials.refresh_token or decrypt_secret(gmail_account.refresh_token_ref) or ""
            )

        # Build search query for bank emails
        query = _build_sender_query()
        logger.info(f"Syncing Gmail for user {user_id[:8]}... query={query[:80]}...")

        messages = await _list_message_refs_by_query(service, query, max_results)
        stats["emails_fetched"] = len(messages)
        logger.info(f"Found {len(messages)} emails matching bank senders")

        stats.update(await _store_gmail_message_refs(db, service, user_id, messages))

        # Single atomic commit for all changes
        gmail_account.last_synced_at = datetime.now(UTC)
        gmail_account.last_history_id = await _get_current_history_id(service)
        gmail_account.last_sync_started_at = sync_run.start_time
        gmail_account.auto_sync_status = "idle"
        gmail_account.auto_sync_error = None
        sync_run.status = SyncStatus.COMPLETED
        sync_run.end_time = datetime.now(UTC)
        sync_run.emails_fetched = stats["emails_fetched"]
        sync_run.emails_processed = stats["emails_processed"]
        sync_run.emails_failed = stats["emails_failed"]
        sync_run.errors = json.dumps(stats["errors"])
        await db.commit()

        logger.info(
            f"✅ Sync complete: fetched={stats['emails_fetched']}, "
            f"processed={stats['emails_processed']}, "
            f"dupes={stats['emails_skipped_duplicate']}, "
            f"otp={stats['emails_skipped_otp']}, "
            f"failed={stats['emails_failed']}"
        )

        return stats

    except Exception as e:
        # Mark sync as failed
        sync_run.status = SyncStatus.FAILED
        sync_run.end_time = datetime.now(UTC)
        sync_run.errors = json.dumps([{"error": str(e)}])
        await db.commit()

        logger.error(f"❌ Sync failed: {e}")
        raise


async def sync_gmail_emails_incremental(
    db: AsyncSession,
    user_id: str,
    gmail_account_id: str,
) -> dict:
    """Fetch only messages changed since the last Gmail checkpoint."""
    sync_run = SyncRun(user_id=user_id, status=SyncStatus.RUNNING)
    db.add(sync_run)
    await db.commit()
    await db.refresh(sync_run)
    await sync_event_manager.broadcast(user_id, "sync_started", {"mode": "incremental"})

    try:
        result = await db.execute(select(GmailAccount).where(GmailAccount.id == gmail_account_id))
        gmail_account = result.scalar_one_or_none()
        if not gmail_account:
            raise ValueError(f"Gmail account {gmail_account_id} not found")

        gmail_account.auto_sync_status = "running"
        gmail_account.auto_sync_error = None
        await db.commit()

        service, credentials, refreshed = await _build_gmail_service(
            decrypt_secret(gmail_account.access_token_ref) or "",
            decrypt_secret(gmail_account.refresh_token_ref) or "",
        )
        if refreshed:
            gmail_account.access_token_ref = encrypt_secret(credentials.token)
            gmail_account.refresh_token_ref = encrypt_secret(
                credentials.refresh_token or decrypt_secret(gmail_account.refresh_token_ref) or ""
            )

        latest_history_id: str | None = None
        fallback = False
        if gmail_account.last_history_id:
            try:
                messages, latest_history_id = await _list_message_refs_by_history(
                    service, gmail_account.last_history_id
                )
            except HttpError as exc:
                if getattr(exc.resp, "status", None) != 404:
                    raise
                fallback = True
                query = _build_incremental_query(gmail_account.last_sync_started_at)
                messages = await _list_message_refs_by_query(service, query, 500)
        else:
            fallback = True
            query = _build_incremental_query(gmail_account.last_sync_started_at)
            messages = await _list_message_refs_by_query(service, query, 500)

        await sync_event_manager.broadcast(
            user_id,
            "gmail_checked",
            {"fetched": len(messages), "fallback": fallback},
        )

        stats = await _store_gmail_message_refs(db, service, user_id, messages)
        await sync_event_manager.broadcast(
            user_id,
            "emails_stored",
            {
                "stored": stats["emails_stored"],
                "duplicates": stats["emails_skipped_duplicate"],
                "failed": stats["emails_failed"],
            },
        )

        now = datetime.now(UTC)
        gmail_account.last_synced_at = now
        gmail_account.last_sync_started_at = sync_run.start_time
        gmail_account.last_history_id = latest_history_id or await _get_current_history_id(service)
        gmail_account.auto_sync_status = "idle"
        gmail_account.auto_sync_error = None
        sync_run.status = SyncStatus.COMPLETED
        sync_run.end_time = now
        sync_run.emails_fetched = stats["emails_fetched"]
        sync_run.emails_processed = stats["emails_processed"]
        sync_run.emails_failed = stats["emails_failed"]
        sync_run.errors = json.dumps(stats["errors"])
        await db.commit()
        return stats
    except Exception as e:
        result = await db.execute(select(GmailAccount).where(GmailAccount.id == gmail_account_id))
        gmail_account = result.scalar_one_or_none()
        if gmail_account:
            gmail_account.auto_sync_status = "error"
            gmail_account.auto_sync_error = str(e)
        sync_run.status = SyncStatus.FAILED
        sync_run.end_time = datetime.now(UTC)
        sync_run.errors = json.dumps([{"error": str(e)}])
        await db.commit()
        await sync_event_manager.broadcast(user_id, "sync_failed", {"error": str(e)})
        raise
