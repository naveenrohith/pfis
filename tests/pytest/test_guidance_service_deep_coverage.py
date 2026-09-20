"""Deterministic unit coverage for guidance classification, read models, and persistence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.models.workspace import RecommendationOutcome, RecommendationState
from app.schemas.dashboard import RecommendationResolution
from app.schemas.guidance import RecommendationOutcomeCreate, RecommendationStateUpdate
from app.services import guidance_service as guidance_module
from app.services.card_due_runway_service import CardDueRunwayService
from app.services.financial_position_service import FinancialPositionService
from app.services.guidance_service import GuidanceService


class _Rows:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return list(self.rows)


class _ScalarsDB:
    def __init__(self, rows):
        self.rows = list(rows)

    async def scalars(self, _statement):
        return _Rows(self.rows)


class _ExecuteResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return _Rows(self.value or [])


class _PersistenceDB:
    def __init__(self, *, state=None, scalars=None):
        self.state = state
        self.scalar_values = list(scalars or [])
        self.added = []
        self.commits = 0

    async def execute(self, _statement):
        return _ExecuteResult(self.state)

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    def add(self, row):
        self.added.append(row)
        if isinstance(row, RecommendationState):
            row.id = row.id or "decision-1"
        if isinstance(row, RecommendationOutcome):
            row.id = row.id or "outcome-1"
            row.observed_at = row.observed_at or datetime(2026, 8, 20, tzinfo=UTC)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _row):
        return None

    async def flush(self):
        return None

    def begin_nested(self):
        return _NestedTransaction()


class _NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _card(card_id="card-1"):
    return SimpleNamespace(id=card_id, institution_name="Coverage Card")


@pytest.mark.parametrize(
    ("query", "intent", "merchant"),
    [
        ("CAN I PAY MY CARD before payday?", "card_due_affordability", None),
        ("compare minimum versus total card payment plans", "card_portfolio_payment_plan", None),
        ("what is coming up across all cards?", "card_portfolio_upcoming", None),
        ("when is my next card payment?", "card_upcoming_state", None),
        ("how much did I spend from Coffee Bar this month", "merchant_spend", "coffee bar"),
        ("what is my current outstanding balance", "card_position", None),
    ],
)
def test_query_plan_uses_specific_card_and_merchant_intents(query, intent, merchant):
    plan = GuidanceService._query_plan(query.lower())

    assert plan is not None
    assert plan.intent == intent
    assert plan.merchant == merchant
    assert plan.evidence_sources


def test_query_classifier_rejects_ambiguous_card_phrases_without_card_terms():
    assert GuidanceService._asks_card_due_affordability("pay my bill") is False
    assert GuidanceService._asks_card_portfolio_payment_plan("compare payment plans") is False
    assert GuidanceService._asks_card_portfolio_upcoming("what is due across accounts") is False
    assert GuidanceService._asks_card_upcoming_state("what happens next") is False
    assert GuidanceService._query_plan("tell me a joke") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_text", "expected_action"),
    [
        ("covered", "can cover", "Open Card due runway"),
        ("at_risk", "shortfall", "Compare payment scenarios"),
        ("needs_payment_account", "no funding account", "Choose a funding account"),
        ("needs_statement", "no issuer statement", "Import the card statement"),
        ("due_passed", "due date has passed", "Review card activity"),
        ("needs_review", "needs review", "Review missing evidence"),
    ],
)
async def test_card_due_runway_formats_empty_and_failure_states(
    monkeypatch, status, expected_text, expected_action
):
    runway = SimpleNamespace(
        status=status,
        total_due=500 if status != "needs_statement" else None,
        currency="INR",
        due_date=date(2026, 8, 25),
        funding_balance_before_due_low=300 if status == "covered" else None,
        lower_band_cash_gap=200 if status == "at_risk" else None,
        confidence=0.7,
    )

    async def fake_runway(self, user_id, account_id):
        return runway

    monkeypatch.setattr(CardDueRunwayService, "runway", fake_runway)
    result = await GuidanceService(_ScalarsDB([_card()]))._card_due_affordability_query(
        "user-1", "can I pay my card", 8, 2026, "INR"
    )

    assert result.intent == "card_due_affordability"
    assert expected_text in result.answer
    assert expected_action in result.suggested_actions
    assert result.metrics[4].value == status.replace("_", " ")


@pytest.mark.asyncio
async def test_card_due_runway_returns_empty_and_multiple_card_states(monkeypatch):
    empty = await GuidanceService(_ScalarsDB([]))._card_due_affordability_query(
        "user-1", "can I pay my card", 8, 2026, "INR"
    )
    multiple = await GuidanceService(
        _ScalarsDB([_card("one"), _card("two")])
    )._card_due_affordability_query("user-1", "can I pay my card", 8, 2026, "INR")

    async def no_runway(self, user_id, account_id):
        return None

    monkeypatch.setattr(CardDueRunwayService, "runway", no_runway)
    unavailable = await GuidanceService(_ScalarsDB([_card()]))._card_due_affordability_query(
        "user-1", "can I pay my card", 8, 2026, "INR"
    )

    assert "No active credit-card" in empty.answer
    assert "more than one active card" in multiple.answer
    assert unavailable.metrics[0].value == "Unavailable"


@pytest.mark.asyncio
async def test_cash_and_bank_guidance_refuse_unverified_empty_positions(monkeypatch):
    async def blocked_cash(self, user_id):
        return SimpleNamespace(
            readiness="blocked",
            flexible_money=None,
            estimated_balance=None,
            assumptions=[],
            pending_increase=None,
            pending_decrease=None,
        )

    monkeypatch.setattr(FinancialPositionService, "cash_plan", blocked_cash)
    cash = await GuidanceService(object())._current_position_query(
        "user-1", "is it safe to spend", 8, 2026, "INR"
    )
    no_bank = await GuidanceService(_ScalarsDB([]))._current_position_query(
        "user-1", "what is my bank balance", 8, 2026, "INR"
    )

    assert cash.intent == "safe_to_spend_blocked"
    assert "not spendable" in cash.answer
    assert cash.metrics[0].value == "Unavailable"
    assert no_bank.intent == "bank_position"
    assert "No active bank" in no_bank.answer


@pytest.mark.asyncio
async def test_set_state_persists_recommendation_snapshot_and_baseline(monkeypatch):
    recommendation = SimpleNamespace(
        id="rec-1",
        type="budget",
        title="Review budget",
        target="budgets",
        expected_impact="Reduce risk",
        smallest_action="Open budgets",
        consequence=None,
        conflicts=[],
        goal_links=[],
        resolution=RecommendationResolution(rationale="Evidence is ready"),
        confidence=0.8,
        freshness_as_of=date(2026, 8, 20),
        urgency="this_period",
        reversibility="reversible",
        evidence=[{"label": "Budget risk", "value": "2 categories"}],
        reason_codes=["budget"],
    )
    workspace = SimpleNamespace(
        recommendations=[recommendation],
        snapshot=SimpleNamespace(budget_risk_count=2),
        review_summary=SimpleNamespace(low_confidence_count=0),
        recurring_commitments=[],
    )
    db = _PersistenceDB()

    async def fake_workspace(self, user_id, month, year):
        return workspace

    monkeypatch.setattr(guidance_module.WorkspaceService, "get_workspace", fake_workspace)
    response = await GuidanceService(db).set_state(
        "user-1",
        "rec-1",
        RecommendationStateUpdate(state="accepted", as_of=date(2026, 8, 20), note="Done"),
    )

    saved = db.added[0]
    assert response.state == "accepted"
    assert saved.recommendation_type == "budget"
    assert saved.baseline_metric_key == "budget_risk_count"
    assert saved.baseline_metric_value == Decimal("2")
    assert saved.decision_note == "Done"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_set_state_rejects_missing_blocked_and_immutable_decisions(monkeypatch):
    missing = await _raises(
        GuidanceService(_PersistenceDB()).set_state(
            "user-1", "missing", RecommendationStateUpdate(state="active")
        ),
        LookupError,
    )

    existing = RecommendationState(
        id="decision-1", user_id="user-1", recommendation_id="rec-1", state="active"
    )
    db = _PersistenceDB(state=existing, scalars=["outcome-1"])
    immutable = await _raises(
        GuidanceService(db).set_state(
            "user-1", "rec-1", RecommendationStateUpdate(state="dismissed")
        ),
        ValueError,
    )

    blocked_rec = SimpleNamespace(id="rec-2", resolution=SimpleNamespace(status="blocked"))
    workspace = SimpleNamespace(recommendations=[blocked_rec])

    async def fake_workspace(self, user_id, month, year):
        return workspace

    monkeypatch.setattr(guidance_module.WorkspaceService, "get_workspace", fake_workspace)
    blocked = await _raises(
        GuidanceService(_PersistenceDB()).set_state(
            "user-1", "rec-2", RecommendationStateUpdate(state="accepted", as_of=date(2026, 8, 20))
        ),
        ValueError,
    )

    assert "not found" in str(missing.value)
    assert "immutable" in str(immutable.value)
    assert "blocking" in str(blocked.value)


class _Raised:
    def __init__(self, value):
        self.value = value


async def _raises(awaitable, exception):
    with pytest.raises(exception) as caught:
        await awaitable
    return _Raised(caught.value)


@pytest.mark.asyncio
async def test_record_outcome_persists_automatic_impact_and_reuses_identical_outcome(
    monkeypatch,
):
    decision = RecommendationState(
        id="decision-1",
        user_id="user-1",
        recommendation_id="rec-1",
        state="accepted",
        recommendation_type="budget",
        decision_as_of=date(2026, 8, 20),
        baseline_metric_key="budget_risk_count",
        baseline_metric_value=Decimal("5"),
    )
    db = _PersistenceDB(scalars=[decision, None])
    service = GuidanceService(db)
    workspace = SimpleNamespace(
        snapshot=SimpleNamespace(budget_risk_count=2),
        review_summary=SimpleNamespace(low_confidence_count=0),
        recurring_commitments=[],
    )

    async def fake_workspace(self, user_id, month, year):
        return workspace

    monkeypatch.setattr(guidance_module.WorkspaceService, "get_workspace", fake_workspace)
    monkeypatch.setattr(
        GuidanceService,
        "_recommendation_metric",
        staticmethod(lambda kind, ws: ("budget_risk_count", Decimal("2"), "records")),
    )
    first = await service.record_outcome(
        "user-1", "decision-1", RecommendationOutcomeCreate(outcome="helped", note="Lower risk")
    )
    db.scalar_values = [decision, db.added[-1]]
    second = await service.record_outcome(
        "user-1", "decision-1", RecommendationOutcomeCreate(outcome="helped", note="Lower risk")
    )

    assert first.outcome == "helped"
    assert first.automatic_impact_value == 3
    assert first.metric_key == "budget_risk_count"
    assert second.id == first.id
    assert db.commits == 1
