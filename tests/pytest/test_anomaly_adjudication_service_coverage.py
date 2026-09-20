"""Deterministic coverage for anomaly review persistence and summaries."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.models.anomaly import AnomalyAdjudication
from app.schemas.intelligence import SpendingAnomaly
from app.services.anomaly_adjudication_service import AnomalyAdjudicationService


class _Rows:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return self.rows


class _AnomalyDb:
    def __init__(self, rows=(), summary_rows=()):
        self.rows = list(rows)
        self.summary_rows = list(summary_rows)
        self.added = []
        self.committed = False

    def add(self, row):
        row.id = f"adjudication-{len(self.added) + 1}"
        row.created_at = datetime(2026, 9, 20, tzinfo=UTC)
        self.added.append(row)

    async def commit(self):
        self.committed = True

    async def refresh(self, _row):
        return None

    async def scalars(self, _statement):
        return _Rows(self.rows)

    async def execute(self, _statement):
        return _Rows(self.summary_rows)


def _anomaly(anomaly_id: str = "anomaly-1") -> SpendingAnomaly:
    return SpendingAnomaly(
        id=anomaly_id,
        kind="category",
        label="Food",
        current_amount=1200,
        baseline_amount=800,
        delta_amount=400,
        delta_pct=50,
        robust_score=2.4,
        history_periods=6,
        transaction_count=8,
        confidence=0.85,
    )


def _row(
    anomaly_id: str,
    *,
    decision: str = "material",
    ruleset: str = "pfis-anomaly-2",
    created_at: datetime = datetime(2026, 9, 20, tzinfo=UTC),
) -> AnomalyAdjudication:
    return AnomalyAdjudication(
        id=f"row-{anomaly_id}-{decision}-{created_at.day}",
        user_id="user-1",
        anomaly_id=anomaly_id,
        predicted_alert=True,
        kind="category",
        label="Food",
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        decision=decision,
        note="reviewed",
        current_amount=Decimal("1200"),
        baseline_amount=Decimal("800"),
        delta_amount=Decimal("400"),
        confidence=0.85,
        transaction_count=8,
        ruleset_version=ruleset,
        created_at=created_at,
    )


async def test_record_persists_leap_year_period_and_returns_safe_response():
    db = _AnomalyDb()
    response = await AnomalyAdjudicationService(db).record(
        "user-1",
        _anomaly(),
        month=2,
        year=2024,
        decision="expected",
        note=None,
        predicted_alert=False,
    )

    row = db.added[0]
    assert db.committed is True
    assert row.period_start == date(2024, 2, 1)
    assert row.period_end == date(2024, 2, 29)
    assert row.predicted_alert is False
    assert response.decision == "expected"
    assert response.note is None


async def test_latest_list_and_protected_cases_keep_only_latest_owned_evidence():
    older = _row("anomaly-1", decision="expected", created_at=datetime(2026, 9, 19, tzinfo=UTC))
    latest = _row("anomaly-1", decision="material", created_at=datetime(2026, 9, 20, tzinfo=UTC))
    other = _row("anomaly-2", decision="expected")
    db = _AnomalyDb([latest, older, other])
    service = AnomalyAdjudicationService(db)

    assert await service.latest_for("user-1", []) == {}
    latest_by_id = await service.latest_for("user-1", ["anomaly-1", "anomaly-2"])
    assert set(latest_by_id) == {"anomaly-1", "anomaly-2"}
    assert latest_by_id["anomaly-1"].decision == "material"

    listed = await service.list_for_user("user-1", limit=2)
    assert len(listed) == 3
    assert listed[0].anomaly_id == "anomaly-1"

    protected = await service.protected_evaluation_cases("user-1")
    assert protected == [
        {"kind": "category", "predicted_alert": True, "adjudicated_material": False},
        {"kind": "category", "predicted_alert": True, "adjudicated_material": True},
    ]


async def test_summary_ignores_unknown_and_total_groups():
    db = _AnomalyDb(
        summary_rows=[
            ("expected", 2),
            ("material", 3),
            ("insufficient_evidence", 1),
            ("total", 99),
            ("unexpected", 7),
        ]
    )

    assert await AnomalyAdjudicationService(db).summary("user-1") == {
        "total": 6,
        "expected": 2,
        "material": 3,
        "insufficient_evidence": 1,
    }
