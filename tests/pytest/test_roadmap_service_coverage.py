"""Deterministic service coverage for roadmap policy and ownership helpers."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.models.roadmap import HealthChecklistItem, Household, RoadmapBill
from app.schemas.roadmap import (
    BillCreate,
    BillUpdate,
    HealthChecklistUpsert,
    HouseholdCreate,
)
from app.services.roadmap_service import RoadmapService


class _Rows:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _RoadmapDb:
    def __init__(self, *, scalar_values=(), scalar_rows=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = [list(rows) for rows in scalar_rows]
        self.added = []
        self.deleted = []
        self.commit_count = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return _Rows(self.scalar_rows.pop(0) if self.scalar_rows else [])

    def add(self, value):
        self.added.append(value)

    def _materialize(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = str(uuid4())
            if getattr(value, "created_at", None) is None:
                value.created_at = datetime.now(UTC)
            if isinstance(value, RoadmapBill) and value.status is None:
                value.status = "due"
            if hasattr(value, "reviewed_at") and value.reviewed_at is None:
                value.reviewed_at = datetime.now(UTC)

    async def flush(self):
        self._materialize()

    async def commit(self):
        self._materialize()
        self.commit_count += 1

    async def refresh(self, _value):
        return None

    async def delete(self, value):
        self.deleted.append(value)


def _bill() -> RoadmapBill:
    return RoadmapBill(
        id="bill-1",
        user_id="user-1",
        label="Internet",
        bill_type="utility",
        amount=Decimal("900"),
        due_date=date(2026, 9, 25),
        source_kind="manual",
        confirmed=True,
        status="due",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_roadmap_service_crud_helpers_cover_bills_health_and_households(monkeypatch):
    bill = _bill()
    listed = await RoadmapService(_RoadmapDb(scalar_rows=[[bill]])).list_bills("user-1")
    assert listed[0].label == "Internet"

    create_db = _RoadmapDb()
    monkeypatch.setattr(RoadmapService, "_snapshot_bill", lambda *args, **kwargs: _noop())
    created = await RoadmapService(create_db).create_bill(
        "user-1",
        BillCreate(
            label="Rent",
            bill_type="rent",
            amount=Decimal("25000"),
            due_date=date(2026, 10, 1),
            confirmed=True,
        ),
    )
    assert created.label == "Rent"
    assert create_db.commit_count == 1

    paid_bill = _bill()
    update_db = _RoadmapDb(scalar_values=[paid_bill, paid_bill])
    service = RoadmapService(update_db)
    paid = await service.update_bill("user-1", "bill-1", BillUpdate(status="paid"))
    assert paid is not None
    assert paid.status == "paid"
    assert paid_bill.paid_at is not None
    skipped = await service.update_bill("user-1", "bill-1", BillUpdate(status="skipped"))
    assert skipped is not None
    assert skipped.status == "skipped"
    assert paid_bill.paid_at is None

    health = HealthChecklistItem(
        id="health-1",
        user_id="user-1",
        item_type="nominee",
        label="Nominee",
        status="not_started",
        note=None,
        reviewed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    health_list = await RoadmapService(_RoadmapDb(scalar_rows=[[health]])).list_health("user-1")
    assert health_list[0].item_type == "nominee"

    new_health_db = _RoadmapDb(scalar_values=[None])
    new_health = await RoadmapService(new_health_db).upsert_health(
        "user-1",
        HealthChecklistUpsert(item_type="will", label="Will", status="in_progress", note="Draft"),
    )
    assert new_health.status == "in_progress"
    updated_health_db = _RoadmapDb(scalar_values=[health])
    updated_health = await RoadmapService(updated_health_db).upsert_health(
        "user-1",
        HealthChecklistUpsert(
            item_type="nominee", label="Nominee updated", status="complete", note=None
        ),
    )
    assert updated_health.status == "complete"
    assert health.label == "Nominee updated"

    household = Household(
        id="household-1",
        owner_user_id="user-1",
        name="Home",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    summary = SimpleNamespace(
        id=household.id,
        owner_user_id=household.owner_user_id,
        name=household.name,
        member_count=1,
        expense_count=0,
        open_settlement_count=0,
        created_at=household.created_at,
    )

    async def fake_summary(self, value):
        assert value.name == household.name
        return summary

    monkeypatch.setattr(RoadmapService, "_household_summary", fake_summary)
    created_household = await RoadmapService(_RoadmapDb()).create_household(
        "user-1", HouseholdCreate(name="Home")
    )
    assert created_household.name == "Home"
    listed_households = await RoadmapService(_RoadmapDb(scalar_rows=[[household]])).list_households(
        "user-1"
    )
    assert listed_households == [summary]


async def _noop():
    return None


@pytest.mark.asyncio
async def test_roadmap_payoff_and_private_guards_cover_ready_and_empty_paths():
    eligible = SimpleNamespace(
        id="loan-1",
        label="Loan",
        outstanding_principal=Decimal("1200"),
        interest_rate=Decimal("12"),
        monthly_due=Decimal("200"),
    )
    incomplete = SimpleNamespace(
        id="loan-2",
        label="Incomplete",
        outstanding_principal=Decimal("500"),
        interest_rate=None,
        monthly_due=Decimal("100"),
    )

    insufficient = await RoadmapService(
        _RoadmapDb(scalar_rows=[[eligible, incomplete]])
    ).payoff_comparison("user-1", Decimal("100"))
    assert insufficient.readiness == "insufficient_budget"
    assert insufficient.excluded_liability_ids == ["loan-2"]

    ready = await RoadmapService(_RoadmapDb(scalar_rows=[[eligible]])).payoff_comparison(
        "user-1", Decimal("300")
    )
    assert ready.readiness == "ready"
    assert len(ready.scenarios) == 2
    assert (
        RoadmapService._simulate_payoff([eligible], Decimal("300"), "smallest_balance_first").method
        == "smallest_balance_first"
    )

    empty = await RoadmapService(_RoadmapDb(scalar_rows=[[]])).payoff_comparison(
        "user-1", Decimal("300")
    )
    assert empty.readiness == "needs_complete_liabilities"

    missing = RoadmapService(_RoadmapDb(scalar_values=[None]))
    with pytest.raises(LookupError, match="Financial account"):
        await missing._require_account("user-1", "missing")

    bank = SimpleNamespace(account_type="bank")
    with pytest.raises(ValueError, match="credit-card"):
        await RoadmapService(_RoadmapDb(scalar_values=[bank]))._require_card("user-1", "bank-1")
    card = SimpleNamespace(account_type="credit_card")
    assert (
        await RoadmapService(_RoadmapDb(scalar_values=[card]))._require_card("user-1", "card-1")
    ) is card

    missing_household = RoadmapService(_RoadmapDb(scalar_values=[None]))
    with pytest.raises(LookupError, match="Household"):
        await missing_household._require_household_member("user-1", "missing")
    household = SimpleNamespace(
        owner_user_id="user-1",
        id="household-1",
        name="Home",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    with pytest.raises(PermissionError, match="read-only"):
        await RoadmapService(
            _RoadmapDb(scalar_values=[household, "viewer"])
        )._require_household_editor("user-1", "household-1")
    assert (
        await RoadmapService(
            _RoadmapDb(scalar_values=[household, "member"])
        )._require_household_editor("user-1", "household-1")
    ) is household

    member_ids = await RoadmapService(
        _RoadmapDb(scalar_rows=[["user-1", "user-2"]])
    )._household_member_ids("household-1")
    assert member_ids == {"user-1", "user-2"}
    summary_db = _RoadmapDb(scalar_values=[2, 3, 1])
    summary = await RoadmapService(summary_db)._household_summary(household)
    assert summary.member_count == 2
    assert summary.expense_count == 3
    assert summary.open_settlement_count == 1

    expense = SimpleNamespace(
        id="expense-1",
        household_id="household-1",
        created_by_user_id="user-1",
        payer_user_id="user-2",
        label="Dinner",
        amount=Decimal("100"),
        currency="INR",
        expense_date=date(2026, 9, 19),
        splits_json='{"user-1": "50", "user-2": "50"}',
        created_at=datetime(2026, 9, 19, tzinfo=UTC),
    )
    response = RoadmapService._expense_response(expense)
    assert response.splits == {"user-1": Decimal("50"), "user-2": Decimal("50")}
