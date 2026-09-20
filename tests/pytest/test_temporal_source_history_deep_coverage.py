"""Deterministic coverage for temporal source snapshots and backfill."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services import temporal_source_history as module


class _Rows:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, *, scalar_values=(), scalar_rows=(), execute_values=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [_Rows(rows) for rows in scalar_rows]
        self.execute_values = list(execute_values)
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return self.scalar_rows.pop(0) if self.scalar_rows else _Rows()

    async def execute(self, _statement):
        return self.execute_values.pop(0) if self.execute_values else _Result()

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


def _backfill_db():
    transaction = SimpleNamespace(id="txn-1")
    account = SimpleNamespace(id="account-1")
    statement_line = SimpleNamespace(id="line-1")
    deposit_line = SimpleNamespace(id="deposit-line-1")
    intent = SimpleNamespace(id="intent-1")
    return _Db(
        scalar_values=["user-1"],
        scalar_rows=[
            [transaction],
            [],
            [account],
            [],
            [statement_line],
            [],
            [deposit_line],
            [],
            [intent],
            [],
        ],
        execute_values=[
            _Result([("line-1", "account-1")]),
            _Result([("deposit-line-1", "account-2")]),
        ],
    )


@pytest.mark.asyncio
async def test_temporal_backfill_covers_all_sources_dry_run_and_capture(monkeypatch):
    captured = []

    async def capture(*args, **kwargs):
        captured.append((args, kwargs))

    monkeypatch.setattr(module, "capture_transaction_snapshot", capture)
    monkeypatch.setattr(module, "capture_financial_account_snapshot", capture)
    monkeypatch.setattr(module, "capture_statement_line_snapshot", capture)
    monkeypatch.setattr(module, "capture_deposit_statement_line_snapshot", capture)
    monkeypatch.setattr(module, "capture_card_payment_intent_snapshot", capture)
    result = await module.backfill_temporal_source_history(
        _backfill_db(),
        user_id="user-1",
        source_types=[
            "transaction",
            "financial_account",
            "statement_line",
            "deposit_statement_line",
            "card_payment_intent",
        ],
        dry_run=False,
        max_rows_per_source=10,
    )
    assert result.captured_at.tzinfo == UTC
    assert len(result.sources) == 5
    assert all(item.captured_count == 1 for item in result.sources)
    assert len(captured) == 5

    dry_run_db = _backfill_db()
    dry_run = await module.backfill_temporal_source_history(
        dry_run_db,
        user_id="user-1",
        source_types=["transaction"],
        dry_run=True,
        max_rows_per_source=1,
    )
    assert dry_run.sources[0].captured_count == 0
    assert dry_run_db.commits == 0

    with pytest.raises(LookupError, match="User"):
        await module.backfill_temporal_source_history(
            _Db(scalar_values=[None]),
            user_id="missing",
            source_types=[],
            dry_run=True,
            max_rows_per_source=1,
        )
    with pytest.raises(ValueError, match="Unsupported"):
        await module.backfill_temporal_source_history(
            _Db(scalar_values=["user-1"]),
            user_id="user-1",
            source_types=["unsupported"],
            dry_run=True,
            max_rows_per_source=1,
        )


@pytest.mark.asyncio
async def test_temporal_snapshot_deduplication_and_historical_reads_handle_bad_data():
    db = _Db(scalar_values=[None])
    await module.capture_temporal_source_snapshot(
        db,
        user_id="user-1",
        source_type="test",
        source_id="source-1",
        payload={"date": date(2026, 9, 20), "amount": Decimal("12.30")},
        captured_at=datetime(2026, 9, 20),
    )
    assert len(db.added) == 1
    assert json.loads(db.added[0].payload_json)["amount"] == "12.30"

    serialized = db.added[0].payload_json
    same = SimpleNamespace(deleted=False, payload_json=serialized)
    duplicate_db = _Db(scalar_values=[same])
    await module.capture_temporal_source_snapshot(
        duplicate_db,
        user_id="user-1",
        source_type="test",
        source_id="source-1",
        payload={"amount": Decimal("12.30"), "date": date(2026, 9, 20)},
        deleted=False,
        captured_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    assert duplicate_db.added == []
    assert module._identity_evidence_payload("bad") == []
    assert module._identity_evidence_payload("{}") == []

    rows = [
        SimpleNamespace(
            source_type="transaction",
            source_id="txn-1",
            deleted=False,
            payload_json='{"value": 1}',
            captured_at=datetime(2026, 9, 19, tzinfo=UTC),
            id="1",
        ),
        SimpleNamespace(
            source_type="transaction",
            source_id="txn-1",
            deleted=True,
            payload_json='{"value": 2}',
            captured_at=datetime(2026, 9, 20, tzinfo=UTC),
            id="2",
        ),
        SimpleNamespace(
            source_type="account",
            source_id="account-1",
            deleted=False,
            payload_json="not-json",
            captured_at=datetime(2026, 9, 19, tzinfo=UTC),
            id="3",
        ),
        SimpleNamespace(
            source_type="account",
            source_id="account-2",
            deleted=False,
            payload_json="[]",
            captured_at=datetime(2026, 9, 19, tzinfo=UTC),
            id="4",
        ),
        SimpleNamespace(
            source_type="account",
            source_id="account-3",
            deleted=False,
            payload_json='{"value": 3}',
            captured_at=datetime(2026, 9, 19, tzinfo=UTC),
            id="5",
        ),
    ]
    history = await module.historical_source_snapshots(
        _Db(scalar_rows=[rows]),
        user_id="user-1",
        timezone="not/a/timezone",
        as_of=date(2026, 9, 20),
    )
    assert ("transaction", "txn-1") not in history
    assert history[("account", "account-3")] == {"value": 3}


def test_temporal_json_default_rejects_unsupported_types():
    assert module._json_default(date(2026, 9, 20)) == "2026-09-20"
    assert module._json_default(Decimal("1.20")) == "1.20"
    with pytest.raises(TypeError, match="Unsupported"):
        module._json_default(object())
