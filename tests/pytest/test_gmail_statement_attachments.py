"""Gmail PDF intake tests: no live provider access or private fixture data."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from app.api.routes import gmail_statements as routes
from app.models.account import FinancialAccount
from app.models.email import GmailAccount
from app.models.financial_position import StatementImport
from app.models.transaction import Transaction
from app.models.user import User
from app.security import create_access_token, get_cipher
from app.services.gmail import statement_attachment_service as service_module
from app.services.gmail.statement_attachment_service import (
    MAX_PDF_BYTES,
    AttachmentPage,
    GmailStatementAttachments,
    display_metadata,
    open_reference,
    pdf_parts,
    seal_reference,
)
from fastapi import HTTPException
from googleapiclient.errors import HttpError
from httplib2 import Response
from sqlalchemy import func, select

from tests.pytest.helpers import create_user
from tests.pytest.test_generic_credit_card_statement_extractor import GENERIC_CARD_STATEMENT
from tests.pytest.test_hdfc_statement_extractor import _reviewed_statement


def statement_pdf(*, encrypted=False, text=GENERIC_CARD_STATEMENT) -> bytes:
    import fitz

    with fitz.open() as document:
        page = document.new_page(width=1200, height=800)
        page.insert_text((20, 20), text, fontname="cour", fontsize=10)
        return document.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256 if encrypted else fitz.PDF_ENCRYPT_NONE,
            user_pw="statement-secret" if encrypted else None,
            owner_pw="test-owner" if encrypted else None,
        )


def part(payload=b"%PDF test", *, inline=False, part_id="1", filename="card-1234567890123456.pdf"):
    body = {"size": len(payload)}
    body.update(
        {"data": base64.urlsafe_b64encode(payload).decode()}
        if inline
        else {"attachmentId": "attachment-1"}
    )
    return {"partId": part_id, "mimeType": "application/pdf", "filename": filename, "body": body}


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self, *, num_retries):
        assert num_retries == 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeGmail:
    def __init__(self, messages, *, page=None, attachment=b"%PDF test"):
        self.message_data = messages
        self.page = page or {"messages": [{"id": key} for key in messages]}
        self.attachment = attachment
        self.calls = []

    def users(self):
        return self

    def messages(self):
        return self

    def attachments(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        return FakeRequest(self.page)

    def get(self, **kwargs):
        self.calls.append(kwargs)
        if "messageId" in kwargs:
            return FakeRequest({"data": base64.urlsafe_b64encode(self.attachment).decode()})
        return FakeRequest(self.message_data[kwargs["id"]])


def provider(fake):
    value = GmailStatementAttachments(
        GmailAccount(id="account", user_id="user", google_account_id="google")
    )
    value.connector._service = fake
    return value


async def test_nested_and_inline_candidates_are_bounded_redacted_and_paginated():
    inline = part(inline=True, part_id="2")
    fake = FakeGmail(
        {
            "mail": {
                "internalDate": "1750000000000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Bank <bank@example.com>"},
                        {"name": "Subject", "value": "Statement for 1234 5678 9012 3456"},
                    ],
                    "parts": [{"partId": "0", "parts": [part(), inline]}],
                },
            }
        },
        page={"messages": [{"id": "mail"}], "nextPageToken": "next-page"},
    )
    fetched = await provider(fake).candidates(date(2025, 1, 1), date(2026, 1, 1))
    assert len(fetched.candidates) == 2
    assert fetched.next_page_token == "next-page"
    assert fetched.candidates[0]["sender"] == "bank@example.com"
    assert "1234" not in fetched.candidates[0]["subject"]
    assert "123456" not in fetched.candidates[0]["filename"]
    assert "body" not in fetched.candidates[0]
    assert "after:1735689600 before:1767225600" in fake.calls[0]["q"]
    assert await provider(fake).fetch("mail", "2") == b"%PDF test"
    assert await provider(fake).fetch("mail", "1") == b"%PDF test"


async def test_invalid_size_and_payload_fail_before_parsing(monkeypatch):
    large = part()
    large["body"]["size"] = MAX_PDF_BYTES + 1
    fake = FakeGmail({"mail": {"payload": {"parts": [large]}}})
    page = await provider(fake).candidates(date(2025, 1, 1), date(2026, 1, 1))
    assert page.candidates == [] and page.truncated
    with pytest.raises(HTTPException) as oversized:
        await provider(fake).fetch("mail", "1")
    assert oversized.value.status_code == 413
    assert not any("messageId" in call for call in fake.calls)
    fake = FakeGmail({"mail": {"payload": {"parts": [part()]}}}, attachment=b"not a PDF")
    with pytest.raises(HTTPException) as invalid:
        await provider(fake).fetch("mail", "1")
    assert invalid.value.detail["code"] == "invalid_pdf"
    monkeypatch.setattr(service_module, "MAX_PDF_BYTES", 12)
    fake.attachment = b"%PDF" + b"a" * 20
    with pytest.raises(HTTPException) as actual_size:
        await provider(fake).fetch("mail", "1")
    assert actual_size.value.status_code == 413


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "gmail_reauthorization_required"),
        (503, "gmail_unavailable"),
        (404, "attachment_missing"),
    ],
)
async def test_provider_errors_do_not_echo_provider_secrets(status, code):
    error = HttpError(Response({"status": str(status)}), b"provider-private-token")
    fake = FakeGmail({"mail": error})
    with pytest.raises(HTTPException) as caught:
        await provider(fake).fetch("mail", "1")
    assert caught.value.detail["code"] == code
    assert "provider-private-token" not in str(caught.value.detail)


async def test_missing_messages_partial_pages_and_repeated_cursor():
    error = HttpError(Response({"status": "404"}), b"removed")
    fake = FakeGmail({"mail": error})
    page = await provider(fake).candidates(date(2025, 1, 1), date(2026, 1, 1))
    assert page.message_failures == 1
    fake.page = {"messages": [], "nextPageToken": "same"}
    with pytest.raises(HTTPException, match="503"):
        await provider(fake).candidates(date(2025, 1, 1), date(2026, 1, 1), "same")


def test_source_reference_is_confidential_user_bound_expiring_and_purpose_bound():
    token = seal_reference("user", "account", 1, "source", message="mail", part="1")
    assert "mail" not in token
    assert open_reference(token, "user", "account", 1, "source")["message"] == "mail"
    for args in [
        ("other", "account", 1, "source"),
        ("user", "other", 1, "source"),
        ("user", "account", 2, "source"),
        ("user", "account", 1, "cursor"),
    ]:
        with pytest.raises(HTTPException):
            open_reference(token, *args)
    with pytest.raises(HTTPException):
        open_reference(token[:-5] + "bad", "user", "account", 1, "source")
    expired = (
        get_cipher()
        .encrypt_at_time(
            get_cipher().decrypt(token.encode()), int(datetime.now(UTC).timestamp()) - 1801
        )
        .decode()
    )
    with pytest.raises(HTTPException):
        open_reference(expired, "user", "account", 1, "source")


def test_mime_depth_and_public_metadata_are_bounded():
    root = part(inline=True)
    for _ in range(15):
        root = {"parts": [root]}
    parts, truncated = pdf_parts(root)
    assert not parts and truncated
    assert "\n" not in display_metadata("statement\n1234567890")


async def connected_user(client, factory):
    user = await create_user(client, "gmail-statement")
    async with factory() as db:
        account = GmailAccount(
            user_id=user["id"],
            google_account_id=user["id"],
            access_token_ref="original-token",
            refresh_token_ref="refresh-token",
        )
        db.add(account)
        await db.commit()
        account_id = account.id
    return user, account_id


class StubAttachments:
    payload = b"%PDF test"
    fetch_hook = None

    def __init__(self, account):
        self.connector = SimpleNamespace(
            account=SimpleNamespace(
                access_token_ref=account.access_token_ref,
                refresh_token_ref=account.refresh_token_ref,
                token_expires_at=account.token_expires_at,
            )
        )

    async def candidates(self, _start, _end, page_token=None):
        return AttachmentPage(
            [
                {
                    "message_id": "mail",
                    "part_id": "1",
                    "sender": "bank@example.com",
                    "subject": "Statement",
                    "filename": "statement.pdf",
                    "size_bytes": len(self.payload),
                    "received_at": None,
                }
            ],
            "page-2" if page_token is None else None,
        )

    async def fetch(self, _message, _part):
        if type(self).fetch_hook:
            await type(self).fetch_hook(self)
        return type(self).payload


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setattr(routes, "GmailStatementAttachments", StubAttachments)
    monkeypatch.setattr(StubAttachments, "payload", statement_pdf(encrypted=True))
    monkeypatch.setattr(StubAttachments, "fetch_hook", None)
    return StubAttachments


async def test_routes_password_detection_import_idempotency_and_validation_privacy(
    client, test_session_factory, stub
):
    user, account_id = await connected_user(client, test_session_factory)
    url = "/api/statements/gmail"
    page = await client.get(f"{url}/candidates?user_id={user['id']}")
    page.raise_for_status()
    body = page.json()
    assert not body["coverage_complete"] and body["next_cursor"]
    source = body["candidates"][0]["source_ref"]
    payload = {"source_ref": source}
    missing = await client.post(f"{url}/detect?user_id={user['id']}", json=payload)
    assert missing.json()["status"] == "password_required"
    payload["password"] = "bad-password"
    incorrect = await client.post(f"{url}/detect?user_id={user['id']}", json=payload)
    assert incorrect.json()["status"] == "incorrect_password"
    assert "bad-password" not in incorrect.text
    payload["password"] = "statement-secret"
    detected = await client.post(f"{url}/detect?user_id={user['id']}", json=payload)
    detected.raise_for_status()
    assert detected.json()["detection"]["support_status"] == "supported"
    assert "statement-secret" not in detected.text
    account = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "ICICI",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****9911",
            "currency": "INR",
        },
    )
    account.raise_for_status()
    payload.update(
        financial_account_id=account.json()["id"],
        document_fingerprint=detected.json()["document_fingerprint"],
    )
    imported = await client.post(f"{url}/import?user_id={user['id']}", json=payload)
    imported.raise_for_status()
    retry = await client.post(f"{url}/import?user_id={user['id']}", json=payload)
    retry.raise_for_status()
    assert (
        retry.json()["credit_card_statement"]["id"]
        == imported.json()["credit_card_statement"]["id"]
    )
    payload["document_fingerprint"] = "wrong"
    malformed = await client.post(f"{url}/import?user_id={user['id']}", json=payload)
    assert malformed.status_code == 422 and "statement-secret" not in malformed.text
    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count(Transaction.id)).where(Transaction.user_id == user["id"])
            )
            == 3
        )


async def test_source_fingerprint_and_owner_checks_write_nothing(
    client, test_session_factory, stub
):
    user, account_id = await connected_user(client, test_session_factory)
    source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")
    response = await client.post(
        f"/api/statements/gmail/import?user_id={user['id']}",
        json={
            "source_ref": source,
            "password": "statement-secret",
            "document_fingerprint": "0" * 64,
            "financial_account_id": "unowned",
        },
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "source_changed"
    other, _ = await connected_user(client, test_session_factory)
    response = await client.post(
        f"/api/statements/gmail/detect?user_id={other['id']}",
        json={"source_ref": source, "password": "statement-secret"},
    )
    assert response.status_code == 409
    token = create_access_token(other["id"])
    response = await client.get(
        f"/api/statements/gmail/candidates?user_id={user['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    async with test_session_factory() as db:
        assert await db.scalar(select(func.count(StatementImport.id))) == 0


async def test_generation_change_during_fetch_is_a_database_fence(
    client, test_session_factory, stub
):
    user, account_id = await connected_user(client, test_session_factory)
    source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")

    async def invalidate(_provider):
        async with test_session_factory() as db:
            owner = await db.get(User, user["id"])
            owner.gmail_connection_generation += 1
            await db.commit()

    stub.fetch_hook = invalidate
    response = await client.post(
        f"/api/statements/gmail/import?user_id={user['id']}",
        json={
            "source_ref": source,
            "password": "statement-secret",
            "document_fingerprint": hashlib.sha256(stub.payload).hexdigest(),
            "financial_account_id": "missing",
        },
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "source_expired"
    async with test_session_factory() as db:
        assert await db.scalar(select(func.count(StatementImport.id))) == 0


async def test_concurrent_refresh_does_not_overwrite_new_credentials(
    client, test_session_factory, stub
):
    user, account_id = await connected_user(client, test_session_factory)
    source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")

    async def reconnect(value):
        value.connector.account.access_token_ref = "stale-refreshed-token"
        async with test_session_factory() as db:
            account = await db.get(GmailAccount, account_id)
            account.access_token_ref = "new-reconnect-token"
            await db.commit()

    stub.fetch_hook = reconnect
    response = await client.post(
        f"/api/statements/gmail/detect?user_id={user['id']}",
        json={"source_ref": source, "password": "statement-secret"},
    )
    response.raise_for_status()
    async with test_session_factory() as db:
        account = await db.get(GmailAccount, account_id)
        assert account.access_token_ref == "new-reconnect-token"


@pytest.mark.parametrize("operation", ["detect", "import"])
async def test_generation_change_after_pdf_read_blocks_detection(
    client, test_session_factory, stub, monkeypatch, operation
):
    user, account_id = await connected_user(client, test_session_factory)
    source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")
    original = routes.asyncio.to_thread
    parsed = asyncio.Event()
    resume = asyncio.Event()

    async def pause_after_read(function, *args, **kwargs):
        result = await original(function, *args, **kwargs)
        if function is routes.extract_statement_pdf_text:
            parsed.set()
            await resume.wait()
        return result

    monkeypatch.setattr(routes.asyncio, "to_thread", pause_after_read)
    payload = {"source_ref": source, "password": "statement-secret"}
    if operation == "import":
        payload.update(
            financial_account_id="missing",
            document_fingerprint=hashlib.sha256(stub.payload).hexdigest(),
        )
    task = asyncio.create_task(
        client.post(f"/api/statements/gmail/{operation}?user_id={user['id']}", json=payload)
    )
    try:
        await asyncio.wait_for(parsed.wait(), 5)
        async with test_session_factory() as db:
            owner = await db.get(User, user["id"])
            owner.gmail_connection_generation += 1
            await db.commit()
    finally:
        resume.set()
    response = await asyncio.wait_for(task, 5)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_expired"


@pytest.mark.parametrize("legacy", [False, True])
async def test_concurrent_gmail_and_upload_import_share_one_fingerprint(
    client, test_session_factory, stub, legacy
):
    stub.payload = statement_pdf(text=_reviewed_statement([]) if legacy else GENERIC_CARD_STATEMENT)
    user, account_id = await connected_user(client, test_session_factory)
    source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")
    account = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "HDFC Bank" if legacy else "ICICI",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****9911",
            "currency": "INR",
        },
    )
    account.raise_for_status()
    target = account.json()["id"]
    entered = asyncio.Event()
    release = asyncio.Event()

    async def pause_fetch(_provider):
        entered.set()
        await release.wait()

    stub.fetch_hook = pause_fetch
    gmail = asyncio.create_task(
        client.post(
            f"/api/statements/gmail/import?user_id={user['id']}",
            json={
                "source_ref": source,
                "document_fingerprint": hashlib.sha256(stub.payload).hexdigest(),
                "financial_account_id": target,
            },
        )
    )
    await asyncio.wait_for(entered.wait(), 5)
    upload_path = "hdfc" if legacy else "import"
    upload = asyncio.create_task(
        client.post(
            f"/api/statements/{upload_path}/upload?user_id={user['id']}&financial_account_id={target}",
            content=stub.payload,
            headers={"Content-Type": "application/pdf"},
        )
    )
    release.set()
    results = await asyncio.wait_for(asyncio.gather(gmail, upload), 15)
    for result in results:
        result.raise_for_status()
    assert results[0].json()["credit_card_statement"]["id"] == (
        results[1].json()["id"] if legacy else results[1].json()["credit_card_statement"]["id"]
    )
    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 1
        )
        assert await db.scalar(
            select(func.count(Transaction.id)).where(Transaction.user_id == user["id"])
        ) == (0 if legacy else 3)


@pytest.mark.parametrize("institution,active", [("ICICI", True), ("HDFC Bank", False)])
async def test_hdfc_gmail_rejects_wrong_issuer_and_inactive_card(
    client, test_session_factory, stub, institution, active
):
    stub.payload = statement_pdf(text=_reviewed_statement([]))
    user, account_id = await connected_user(client, test_session_factory)
    target = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": institution,
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****9911",
            "currency": "INR",
        },
    )
    target.raise_for_status()
    async with test_session_factory() as db:
        account = await db.get(FinancialAccount, target.json()["id"])
        account.is_active = active
        await db.commit()
    source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")
    response = await client.post(
        f"/api/statements/gmail/import?user_id={user['id']}",
        json={
            "source_ref": source,
            "financial_account_id": target.json()["id"],
            "document_fingerprint": hashlib.sha256(stub.payload).hexdigest(),
        },
    )
    assert response.status_code == 409
    assert (
        ("active" in response.text) if not active else ("HDFC financial account" in response.text)
    )
    async with test_session_factory() as db:
        assert (
            await db.scalar(
                select(func.count(StatementImport.id)).where(StatementImport.user_id == user["id"])
            )
            == 0
        )


async def test_gmail_preview_masks_separated_identifiers(client, test_session_factory, stub):
    stub.payload = statement_pdf(
        text=GENERIC_CARD_STATEMENT.replace(
            "AMAZON PURCHASE", "IMPS 1234 5678 9012 AND 1234-5678-9012"
        )
    )
    user, account_id = await connected_user(client, test_session_factory)
    source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")
    response = await client.post(
        f"/api/statements/gmail/detect?user_id={user['id']}", json={"source_ref": source}
    )
    response.raise_for_status()
    assert response.json()["status"] == "detected"
    assert response.json()["detection"]["analysis"]["lines"]
    assert "1234 5678 9012" not in response.text
    assert "1234-5678-9012" not in response.text


@pytest.mark.parametrize("operation", ["candidates", "detect", "import"])
async def test_gmail_provider_operation_deadline(
    client, test_session_factory, stub, monkeypatch, operation
):
    user, account_id = await connected_user(client, test_session_factory)

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(stub, "candidates", slow)
    monkeypatch.setattr(stub, "fetch", slow)
    monkeypatch.setattr(routes, "CANDIDATE_DEADLINE_SECONDS", 0.01)
    monkeypatch.setattr(routes, "FETCH_DEADLINE_SECONDS", 0.01)
    url = f"/api/statements/gmail/{operation}?user_id={user['id']}"
    if operation == "candidates":
        response = await client.get(url)
    else:
        source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")
        payload = {"source_ref": source}
        if operation == "import":
            payload.update(financial_account_id="missing", document_fingerprint="0" * 64)
        response = await client.post(url, json=payload)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "gmail_unavailable"


async def test_candidates_register_before_connection_fence(
    client, test_session_factory, stub, monkeypatch
):
    from contextlib import asynccontextmanager

    user, account_id = await connected_user(client, test_session_factory)
    calls = []
    original = routes.tracked_user_ingestion

    @asynccontextmanager
    async def disconnect_after_registration(db, user_id):
        async with original(db, user_id):
            async with test_session_factory() as other:
                account = await other.get(GmailAccount, account_id)
                account.auto_sync_status = "disconnecting"
                owner = await other.get(User, user_id)
                owner.gmail_connection_generation += 1
                await other.commit()
            yield

    async def should_not_call(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Provider called after disconnect")

    monkeypatch.setattr(routes, "tracked_user_ingestion", disconnect_after_registration)
    monkeypatch.setattr(stub, "candidates", should_not_call)
    response = await client.get(f"/api/statements/gmail/candidates?user_id={user['id']}")
    assert response.status_code == 409 and not calls


@pytest.mark.parametrize(
    "case", ["disconnected", "reauthorize", "inactive", "dates", "password", "cursor"]
)
async def test_gmail_recovery_errors_are_safe(client, test_session_factory, stub, case):
    user, account_id = await connected_user(client, test_session_factory)
    async with test_session_factory() as db:
        account = await db.get(GmailAccount, account_id)
        if case == "disconnected":
            await db.delete(account)
        if case == "reauthorize":
            account.auto_sync_status = "paused"
            account.auto_sync_error = "private-provider-error"
        if case == "inactive":
            owner = await db.get(User, user["id"])
            owner.is_active = False
        await db.commit()
    url = f"/api/statements/gmail/candidates?user_id={user['id']}"
    if case == "dates":
        url += "&start_date=2026-09-10&end_date=2026-09-01"
    if case == "cursor":
        url += "&cursor=tampered"
    if case == "password":
        source = seal_reference(user["id"], account_id, 0, "source", message="mail", part="1")
        response = await client.post(
            f"/api/statements/gmail/detect?user_id={user['id']}",
            json={"source_ref": source, "password": "secret" * 100},
        )
    else:
        response = await client.get(url)
    assert response.status_code in {403, 409, 422}
    assert "private-provider-error" not in response.text and "secretsecret" not in response.text
