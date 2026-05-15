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
import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional
import uuid

from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email import RawEmail, GmailAccount
from app.models.sync import SyncRun, SyncStatus
from app.security import decrypt_secret, encrypt_secret
from app.services.gmail.oauth_service import build_credentials, refresh_access_token
from app.services.gmail.email_filter import (
    classify_email,
    EmailType,
    KNOWN_BANK_SENDERS,
)

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
                stats["classifications"].append({
                    "subject": email_data["subject"][:60],
                    "type": "DUPLICATE",
                })
                continue

            email_type, bank_name, confidence = classify_email(
                email_data["sender"],
                email_data["subject"],
                email_data["body"],
            )

            stats["classifications"].append({
                "subject": email_data["subject"][:60],
                "sender": email_data["sender"],
                "type": email_type.value,
                "bank": bank_name,
                "confidence": confidence,
            })

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
                    received_at=datetime.now(timezone.utc),
                    processed_flag=False,
                )
            )
            stats["emails_stored"] += 1

        sync_run.status = SyncStatus.COMPLETED
        sync_run.end_time = datetime.now(timezone.utc)
        sync_run.emails_fetched = stats["emails_fetched"]
        sync_run.emails_processed = stats["emails_stored"]
        await db.commit()

        return stats
    except Exception as e:
        sync_run.status = SyncStatus.FAILED
        sync_run.end_time = datetime.now(timezone.utc)
        sync_run.errors = json.dumps([{"error": str(e)}])
        await db.commit()
        raise


def _build_gmail_service(access_token: str, refresh_token: str):
    """Build an authenticated Gmail API service instance."""
    credentials = build_credentials(access_token, refresh_token)
    refreshed = False

    # Refresh if expired
    if credentials.expired:
        logger.info("Access token expired, refreshing...")
        credentials.refresh(Request())
        refreshed = True

    return build("gmail", "v1", credentials=credentials), credentials, refreshed


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
    return f'newer_than:365d (from:({sender_list}) OR {keyword_query})'


def _extract_email_body(payload: dict) -> str:
    """
    Extract plain text body from Gmail message payload.
    Handles both simple and multipart email structures.
    """
    body_text = ""

    if "body" in payload and payload["body"].get("data"):
        body_text = base64.urlsafe_b64decode(
            payload["body"]["data"]
        ).decode("utf-8", errors="replace")
        return body_text

    # Handle multipart messages
    parts = payload.get("parts", [])
    for part in parts:
        mime_type = part.get("mimeType", "")

        if mime_type == "text/plain" and part.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(
                part["body"]["data"]
            ).decode("utf-8", errors="replace")
            return body_text

        # Nested multipart
        if "parts" in part:
            nested_body = _extract_email_body(part)
            if nested_body:
                return nested_body

    # Fallback: try text/html if no plain text
    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            body_text = base64.urlsafe_b64decode(
                part["body"]["data"]
            ).decode("utf-8", errors="replace")
            return body_text

    return body_text


def _clean_email_body(body: str) -> str:
    """Normalize Gmail HTML/plain body before storage and parsing."""
    body = html.unescape(body or "")
    body = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", body)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"(?i)<br\s*/?>", " ", body)
    body = re.sub(r"(?i)</(?:p|div|tr|td|table|li|h\d)>", " ", body)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", body).strip()


def _extract_headers(headers: list[dict]) -> dict:
    """Extract useful headers (From, Subject, Date) from Gmail message."""
    result = {}
    for header in headers:
        name = header.get("name", "").lower()
        if name in ("from", "subject", "date"):
            result[name] = header.get("value", "")
    return result


async def sync_gmail_emails(
    db: AsyncSession,
    user_id: str,
    gmail_account_id: str,
    max_results: int = 50,
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
        "emails_skipped_otp": 0,
        "emails_skipped_promo": 0,
        "emails_skipped_duplicate": 0,
        "emails_failed": 0,
        "errors": [],
    }

    try:
        # Get Gmail account credentials
        result = await db.execute(
            select(GmailAccount).where(GmailAccount.id == gmail_account_id)
        )
        gmail_account = result.scalar_one_or_none()

        if not gmail_account:
            raise ValueError(f"Gmail account {gmail_account_id} not found")

        # Build Gmail service
        service, credentials, refreshed = _build_gmail_service(
            decrypt_secret(gmail_account.access_token_ref) or "",
            decrypt_secret(gmail_account.refresh_token_ref) or "",
        )

        if refreshed:
            gmail_account.access_token_ref = encrypt_secret(credentials.token)
            gmail_account.refresh_token_ref = encrypt_secret(
                credentials.refresh_token or decrypt_secret(gmail_account.refresh_token_ref) or ""
            )
            await db.commit()

        # Build search query for bank emails
        query = _build_sender_query()
        logger.info(f"Syncing Gmail for user {user_id[:8]}... query={query[:80]}...")

        # Fetch message IDs
        messages_response = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages = messages_response.get("messages", [])
        stats["emails_fetched"] = len(messages)
        logger.info(f"Found {len(messages)} emails matching bank senders")

        # Process each message
        for msg_ref in messages:
            gmail_msg_id = msg_ref["id"]
            scoped_gmail_msg_id = f"{user_id}:{gmail_msg_id}"

            try:
                # Check if already stored (dedup by gmail_message_id)
                existing = await db.execute(
                    select(RawEmail).where(
                        RawEmail.gmail_message_id == scoped_gmail_msg_id
                    )
                )
                if existing.scalar_one_or_none():
                    stats["emails_skipped_duplicate"] += 1
                    continue

                # Fetch full message
                msg = service.users().messages().get(
                    userId="me",
                    id=gmail_msg_id,
                    format="full",
                ).execute()

                # Extract headers and body
                payload = msg.get("payload", {})
                headers = _extract_headers(payload.get("headers", []))
                body = _clean_email_body(_extract_email_body(payload))
                sender = headers.get("from", "")
                subject = headers.get("subject", "")

                # Parse received date from internal timestamp
                internal_date_ms = int(msg.get("internalDate", 0))
                received_at = datetime.fromtimestamp(
                    internal_date_ms / 1000, tz=timezone.utc
                )

                # Classify the email
                email_type, bank_name, confidence = classify_email(
                    sender, subject, body
                )

                # Only store transaction-relevant emails
                if email_type == EmailType.OTP:
                    stats["emails_skipped_otp"] += 1
                    continue
                elif email_type == EmailType.PROMOTION:
                    stats["emails_skipped_promo"] += 1
                    continue
                elif email_type == EmailType.IGNORE:
                    continue

                # Store raw email (TRANSACTION or STATEMENT type)
                raw_email = RawEmail(
                    user_id=user_id,
                    gmail_message_id=scoped_gmail_msg_id,
                    subject=subject,
                    body=body,
                    sender=sender,
                    received_at=received_at,
                    processed_flag=False,
                )
                db.add(raw_email)
                stats["emails_processed"] += 1

                logger.info(
                    f"Stored email: [{email_type.value}] [{bank_name}] "
                    f"{subject[:60]} (conf={confidence:.2f})"
                )

            except Exception as e:
                stats["emails_failed"] += 1
                stats["errors"].append({
                    "gmail_message_id": gmail_msg_id,
                    "error": str(e),
                })
                logger.error(f"Failed to process email {gmail_msg_id}: {e}")
                continue

        await db.commit()

        # Update Gmail account last_synced_at
        gmail_account.last_synced_at = datetime.now(timezone.utc)
        await db.commit()

        # Update sync run
        sync_run.status = SyncStatus.COMPLETED
        sync_run.end_time = datetime.now(timezone.utc)
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
        sync_run.end_time = datetime.now(timezone.utc)
        sync_run.errors = json.dumps([{"error": str(e)}])
        await db.commit()

        logger.error(f"❌ Sync failed: {e}")
        raise
