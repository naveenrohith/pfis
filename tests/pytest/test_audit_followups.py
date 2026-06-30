"""Tests for audit follow-up fixes: duplicate error typing, prod schema policy,
and parser-fallback metrics."""

# pyright: reportMissingImports=false

from __future__ import annotations

import app.database as database_module
from app.models.email import RawEmail
from app.schemas.transaction import TransactionCreate, TransactionTypeEnum
from app.services.parser.pipeline import process_raw_emails
from app.services.transaction_service import DuplicateTransactionError, TransactionService

from tests.pytest.helpers import create_user


def _txn(**overrides) -> TransactionCreate:
    base = {
        "amount": 250.0,
        "currency": "INR",
        "transaction_type": TransactionTypeEnum.DEBIT,
        "merchant_raw": "SWIGGY",
        "merchant_normalized": "Swiggy",
        "transaction_date": "2026-02-10",
        "confidence_score": 0.9,
    }
    base.update(overrides)
    return TransactionCreate(**base)


async def test_duplicate_error_is_value_error_subclass():
    # Route handlers map ValueError -> 409, so the subclass must preserve that.
    assert issubclass(DuplicateTransactionError, ValueError)


async def test_create_transaction_raises_typed_duplicate(client, test_session_factory):
    user = await create_user(client, "dupe")
    async with test_session_factory() as db:
        service = TransactionService(db)
        await service.create_transaction(user["id"], _txn())
        try:
            await service.create_transaction(user["id"], _txn())
        except DuplicateTransactionError:
            pass
        else:
            raise AssertionError("expected DuplicateTransactionError on duplicate insert")


async def test_init_db_skips_create_all_in_production(monkeypatch):
    class _Prod:
        is_production = True

    class _Engine:
        def begin(self):  # pragma: no cover - must never be called
            raise AssertionError("create_all must be skipped in the production profile")

    monkeypatch.setattr(database_module, "get_settings", lambda: _Prod())
    monkeypatch.setattr(database_module, "engine", _Engine())

    await database_module.init_db()  # returns without touching the engine


async def test_init_db_runs_create_all_locally(monkeypatch):
    calls = []

    class _Local:
        is_production = False

    class _Ctx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def run_sync(self, fn):
            calls.append(fn)

    class _Engine:
        def begin(self):
            return _Ctx()

    monkeypatch.setattr(database_module, "get_settings", lambda: _Local())
    monkeypatch.setattr(database_module, "engine", _Engine())

    await database_module.init_db()

    assert calls, "create_all should run in the local profile"


async def test_pipeline_tracks_fallback_parser_usage(client, test_session_factory):
    # AXIS is a known sender mapped to the generic fallback parser; the bank
    # label is AXIS but the fallback flag must still be recorded.
    user = await create_user(client, "fallback")
    async with test_session_factory() as db:
        db.add(
            RawEmail(
                user_id=user["id"],
                gmail_message_id=f"{user['id']}:axis-fallback",
                sender="AXIS Bank <alerts@axisbank.com>",
                subject="Debit alert",
                body=(
                    "Dear Customer, Rs. 750.00 has been debited from your account "
                    "XX1234 on 10-02-2026 towards AMAZON. Ref 412345678901."
                ),
            )
        )
        await db.commit()

        stats = await process_raw_emails(db, user["id"])

    assert stats["fallback_parsed"] >= 1
    assert any(r.get("parser_fallback") for r in stats["results"])
