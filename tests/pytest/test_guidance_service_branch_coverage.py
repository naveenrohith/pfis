"""Direct branch coverage for grounded guidance plans and position answers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from app.services import guidance_service as guidance_module
from app.services.account_service import AccountService
from app.services.financial_position_service import FinancialPositionService
from app.services.guidance_service import GuidanceService
from app.services.insights_service import InsightsService
from app.services.intelligence_service import IntelligenceService


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _ScalarsDB:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, _statement):
        return _ScalarRows(self.rows)


def _plan_result(intent: str):
    return GuidanceService._result(intent, "stub", [], 8, 2026, [])


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("compare card payment plans", "card_portfolio_payment_plan"),
        ("can I pay my card", "card_due_affordability"),
        ("what is due across my cards", "card_portfolio_upcoming"),
        ("what's next on my card", "card_upcoming_state"),
        ("what is my current balance", "bank_position"),
        ("what is my net worth", "current_net_worth"),
        ("what is my card balance", "card_position"),
        ("what is my bank balance", "bank_position"),
        ("how much recurring spending do I have", "recurring_charges"),
        ("show my budget status", "budget_status"),
        ("compare this month with last month", "month_comparison"),
        ("how much did I spend at coffee this month", "merchant_spend"),
        ("how much did I spend", "monthly_spend"),
        ("how much income did I get", "monthly_income"),
        ("how much were my savings", "monthly_savings"),
    ],
)
def test_query_plan_classifies_supported_intents(query, intent):
    plan = GuidanceService._query_plan(query)

    assert plan is not None
    assert plan.intent == intent
    if intent == "merchant_spend":
        assert plan.merchant == "coffee"


def test_query_plan_refuses_unrecognized_and_exercises_classifier_guards():
    assert GuidanceService._query_plan("tell me a joke") is None
    assert GuidanceService._asks_card_due_affordability("pay my bill") is False
    assert GuidanceService._asks_card_portfolio_payment_plan("compare payment plans") is False
    assert GuidanceService._asks_card_portfolio_upcoming("what is due") is False
    assert GuidanceService._asks_card_upcoming_state("what happens next") is False


def test_recommendation_metrics_and_presentation_helpers():
    workspace = SimpleNamespace(
        review_summary=SimpleNamespace(low_confidence_count=3),
        snapshot=SimpleNamespace(budget_risk_count=2, income=4000, savings=800),
        recurring_commitments=[{"monthly_equivalent": 100}, {"avg_amount": 25}],
    )

    assert GuidanceService._recommendation_metric("review", workspace) == (
        "unresolved_review_count",
        3,
        "records",
    )
    assert GuidanceService._recommendation_metric("budget", workspace) == (
        "budget_risk_count",
        2,
        "records",
    )
    assert GuidanceService._recommendation_metric("recurring", workspace) == (
        "monthly_recurring_amount",
        125,
        "currency",
    )
    assert GuidanceService._recommendation_metric("savings", workspace) == (
        "savings_rate",
        20,
        "percentage_points",
    )
    assert (
        GuidanceService._recommendation_metric(
            "savings", SimpleNamespace(snapshot=SimpleNamespace(income=0, savings=0))
        )
        is None
    )
    assert GuidanceService._recommendation_metric("unknown", workspace) is None

    assert GuidanceService._expected_impact("budget").startswith("Reduce")
    assert GuidanceService._expected_impact("unknown").startswith("Improve")
    assert GuidanceService._money(1200, "INR") == "₹1,200"
    assert GuidanceService._money(1200, "USD") == "USD 1,200"
    unsupported = GuidanceService._unsupported_query_result(8, 2026)
    assert unsupported.supported is False
    assert unsupported.confidence == 0


@pytest.mark.asyncio
async def test_query_dispatches_all_read_model_families(monkeypatch):
    service = GuidanceService(object())

    async def fake_card_plan(self, user_id, month, year, currency):
        return _plan_result("card_portfolio_payment_plan")

    async def fake_card_due(self, user_id, query, month, year, currency):
        return _plan_result("card_due_affordability")

    async def fake_portfolio(self, user_id, month, year, currency):
        return _plan_result("card_portfolio_upcoming")

    async def fake_upcoming(self, user_id, month, year, currency):
        return _plan_result("card_upcoming_state")

    async def fake_position(self, user_id, query, month, year, currency):
        return _plan_result("current_net_worth")

    monkeypatch.setattr(GuidanceService, "_card_portfolio_payment_plan_query", fake_card_plan)
    monkeypatch.setattr(GuidanceService, "_card_due_affordability_query", fake_card_due)
    monkeypatch.setattr(GuidanceService, "_card_portfolio_upcoming_query", fake_portfolio)
    monkeypatch.setattr(GuidanceService, "_card_upcoming_state_query", fake_upcoming)
    monkeypatch.setattr(GuidanceService, "_current_position_query", fake_position)

    async def fake_insights(self, user_id, month, year):
        return {"recurring_payments": [{"monthly_equivalent": 50}]}

    async def fake_budget(self, user_id, month, year):
        return 83.4

    async def fake_comparison(self, user_id, month, year):
        return SimpleNamespace(spend=120, previous_spend=100, spend_change_pct=20)

    async def fake_summary(self, user_id, month, year):
        return (500, 120)

    async def fake_merchant(self, user_id, month, year, merchant):
        assert merchant == "coffee"
        return 75

    monkeypatch.setattr(InsightsService, "generate_insights", fake_insights)
    monkeypatch.setattr(IntelligenceService, "_budget_adherence", fake_budget)
    monkeypatch.setattr(IntelligenceService, "month_comparison", fake_comparison)
    monkeypatch.setattr(IntelligenceService, "monthly_income_spend", fake_summary)
    monkeypatch.setattr(GuidanceService, "_merchant_total", fake_merchant)

    cases = [
        ("compare card payment plans", "card_portfolio_payment_plan"),
        ("can I pay my card", "card_due_affordability"),
        ("what is due across my cards", "card_portfolio_upcoming"),
        ("what's next on my card", "card_upcoming_state"),
        ("what is my net worth", "current_net_worth"),
        ("how much recurring spending do I have", "recurring_charges"),
        ("show my budget status", "budget_status"),
        ("compare this month with last month", "month_comparison"),
        ("how much did I spend at coffee this month", "merchant_spend"),
        ("how much did I spend", "monthly_spend"),
        ("how much income did I get", "monthly_income"),
        ("how much were my savings", "monthly_savings"),
    ]
    results = [await service.query("u1", query, 8, 2026, "INR") for query, _intent in cases]

    assert [result.intent for result in results] == [intent for _query, intent in cases]
    assert results[5].metrics[0].value == "₹50"
    assert results[6].metrics[0].value == "83%"
    assert results[7].metrics[0].value == "₹120"
    assert results[8].metrics[0].value == "₹75"
    assert results[9].metrics[0].value == "₹120"
    assert results[10].metrics[0].value == "₹500"
    assert results[11].metrics[0].value == "₹380"


@pytest.mark.asyncio
async def test_query_handles_budget_and_comparison_without_data(monkeypatch):
    service = GuidanceService(object())

    async def no_budget(self, user_id, month, year):
        return None

    async def no_comparison(self, user_id, month, year):
        return SimpleNamespace(spend=0, previous_spend=0, spend_change_pct=None)

    monkeypatch.setattr(IntelligenceService, "_budget_adherence", no_budget)
    monkeypatch.setattr(IntelligenceService, "month_comparison", no_comparison)

    budget = await service.query("u1", "show budget status", 8, 2026)
    comparison = await service.query("u1", "compare last month", 8, 2026)

    assert budget.metrics[0].value == "Not configured"
    assert comparison.metrics[0].value == "₹0"
    assert "not comparable" in comparison.answer


@pytest.mark.asyncio
async def test_current_position_covers_cash_and_net_worth_states(monkeypatch):
    service = GuidanceService(object())
    ready = SimpleNamespace(
        readiness="ready",
        flexible_money=250.0,
        next_income_date="2026-09-01",
        planning_balance=500.0,
        estimated_balance=400.0,
        position_status="observed",
        assumptions=[],
        pending_increase=0,
        pending_decrease=0,
    )
    blocked = SimpleNamespace(
        readiness="blocked",
        flexible_money=None,
        next_income_date=None,
        planning_balance=None,
        estimated_balance=None,
        position_status="needs_review",
        assumptions=["A fresh balance is required."],
        pending_increase=10,
        pending_decrease=20,
    )
    plans = iter([ready, blocked])

    async def fake_cash_plan(self, user_id):
        return next(plans)

    monkeypatch.setattr(FinancialPositionService, "cash_plan", fake_cash_plan)
    first = await service._current_position_query("u1", "is it safe to spend", 8, 2026, "INR")
    second = await service._current_position_query("u1", "is it spendable", 8, 2026, "INR")

    assert first.intent == "safe_to_spend"
    assert first.metrics[1].value == "₹250"
    assert second.intent == "safe_to_spend_blocked"
    assert "fresh balance" in second.answer

    async def fake_net_worth(self, user_id, as_of=None):
        return next(net_worth_states)

    net_worth_states = iter(
        [
            SimpleNamespace(
                current_position_status="observed",
                net_worth=1000,
                assets=1500,
                liabilities=500,
                current_position_as_of=date(2026, 8, 20),
                as_of=date(2026, 8, 20),
            ),
            SimpleNamespace(
                current_position_status="needs_review",
                net_worth=900,
                assets=1500,
                liabilities=600,
                current_position_as_of=None,
                as_of=date(2026, 8, 15),
            ),
            SimpleNamespace(
                current_position_status="unknown",
                net_worth=0,
                assets=0,
                liabilities=0,
                current_position_as_of=None,
                as_of=None,
            ),
        ]
    )
    monkeypatch.setattr(AccountService, "net_worth", fake_net_worth)
    observed = await service._current_position_query("u1", "what is my net worth", 8, 2026, "INR")
    stale = await service._current_position_query(
        "u1", "what is my financial position", 8, 2026, "INR"
    )
    absent = await service._current_position_query("u1", "what is my worth", 8, 2026, "INR")

    assert "current net worth" in observed.answer
    assert "cannot call it current" in stale.answer
    assert "cannot calculate net worth" in absent.answer


@pytest.mark.asyncio
async def test_current_position_covers_card_and_bank_branches(monkeypatch):
    today = date(2026, 8, 20)

    async def fake_today(db, user_id):
        return today

    monkeypatch.setattr(guidance_module, "user_financial_today", fake_today)

    card = SimpleNamespace(id="card-1", institution_name="Test Card")
    card_overview = SimpleNamespace(
        provider_current_outstanding=200.0,
        provider_source="connector",
        provider_coverage_complete=True,
        provider_available_credit=800.0,
        provider_current_outstanding_as_of=date(2026, 8, 19),
        estimated_current_balance=250.0,
        available_credit_limit=750.0,
        observed_balance_as_of=date(2026, 8, 19),
        statement_date=date(2026, 8, 1),
        total_due=100.0,
        balance_status="observed",
        balance_reason_codes=[],
        estimated_current_as_of=date(2026, 8, 19),
    )

    async def fake_card_overview(self, user_id, account_id):
        return card_overview

    monkeypatch.setattr(FinancialPositionService, "card_overview", fake_card_overview)
    one_card_service = GuidanceService(_ScalarsDB([card]))
    provider = await one_card_service._current_position_query(
        "u1", "what is my card balance", 8, 2026, "INR"
    )
    available = await one_card_service._current_position_query(
        "u1", "what is my available credit", 8, 2026, "INR"
    )
    assert "provider-observed" in provider.answer
    assert available.metrics[2].value == "₹800"

    stale_overview = SimpleNamespace(
        **{
            **card_overview.__dict__,
            "provider_source": "manual",
            "provider_coverage_complete": False,
            "provider_current_outstanding": None,
            "estimated_current_balance": 250.0,
            "observed_balance_as_of": date(2026, 8, 1),
            "balance_status": "observed",
        }
    )

    async def fake_stale_overview(self, user_id, account_id):
        return stale_overview

    monkeypatch.setattr(FinancialPositionService, "card_overview", fake_stale_overview)
    stale = await one_card_service._current_position_query(
        "u1", "what is my card balance", 8, 2026, "INR"
    )
    assert "stale" in stale.answer

    review_overview = SimpleNamespace(
        **{
            **stale_overview.__dict__,
            "observed_balance_as_of": today,
            "balance_status": "needs_review",
        }
    )

    async def fake_review_overview(self, user_id, account_id):
        return review_overview

    monkeypatch.setattr(FinancialPositionService, "card_overview", fake_review_overview)
    review = await one_card_service._current_position_query(
        "u1", "what is my card balance", 8, 2026, "INR"
    )
    assert "needs review" in review.answer

    no_card = await GuidanceService(_ScalarsDB([]))._current_position_query(
        "u1", "what is my card balance", 8, 2026, "INR"
    )
    assert "No active credit-card" in no_card.answer

    cards = [
        SimpleNamespace(id="card-1", institution_name="One"),
        SimpleNamespace(id="card-2", institution_name="Two"),
    ]
    overviews = [
        SimpleNamespace(
            provider_current_outstanding=None,
            provider_source="manual",
            provider_coverage_complete=False,
            estimated_current_balance=100.0,
            balance_status="observed",
            balance_reason_codes=[],
            observed_balance_as_of=today,
        ),
        SimpleNamespace(
            provider_current_outstanding=None,
            provider_source="manual",
            provider_coverage_complete=False,
            estimated_current_balance=None,
            balance_status="needs_review",
            balance_reason_codes=["missing"],
            observed_balance_as_of=None,
        ),
    ]

    async def fake_multi_overview(self, user_id, account_id):
        return overviews[int(account_id[-1]) - 1]

    monkeypatch.setattr(FinancialPositionService, "card_overview", fake_multi_overview)
    multi = GuidanceService(_ScalarsDB(cards))
    partial = await multi._current_position_query("u1", "what is my card balance", 8, 2026, "INR")
    per_card = await multi._current_position_query(
        "u1", "what is my available credit", 8, 2026, "INR"
    )
    assert "not every card" in partial.answer
    assert per_card.metrics[1].value == "Per-card only"

    bank = SimpleNamespace(id="bank-1")

    async def no_position(self, user_id, account_id):
        return None

    monkeypatch.setattr(FinancialPositionService, "account_position", no_position)
    blocked = await GuidanceService(_ScalarsDB([bank]))._current_position_query(
        "u1", "what is my bank balance", 8, 2026, "INR"
    )
    assert blocked.intent == "bank_position_blocked"

    position = SimpleNamespace(
        estimated_balance=1000.0,
        position_status="estimated",
        observed_as_of=today,
        position_reason_codes=[],
        observed_source="manual",
        coverage_complete=False,
    )

    async def estimated_position(self, user_id, account_id):
        return position

    monkeypatch.setattr(FinancialPositionService, "account_position", estimated_position)
    estimated = await GuidanceService(_ScalarsDB([bank]))._current_position_query(
        "u1", "what is my bank balance", 8, 2026, "INR"
    )
    assert "estimated" in estimated.answer

    provider_position = SimpleNamespace(
        **{
            **position.__dict__,
            "position_status": "observed",
            "observed_source": "connector",
            "coverage_complete": True,
            "estimated_balance": 1200.0,
        }
    )

    async def provider_account_position(self, user_id, account_id):
        return provider_position

    monkeypatch.setattr(FinancialPositionService, "account_position", provider_account_position)
    provider = await GuidanceService(_ScalarsDB([bank]))._current_position_query(
        "u1", "what is my bank balance", 8, 2026, "INR"
    )
    assert "provider-observed" in provider.answer

    no_bank = await GuidanceService(_ScalarsDB([]))._current_position_query(
        "u1", "what is my bank balance", 8, 2026, "INR"
    )
    assert "No active bank" in no_bank.answer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "next_event", "expected_action"),
    [
        ("no_active_cards", None, "Confirm a credit-card account"),
        (
            "limit_pressure",
            SimpleNamespace(label="Limit", date=date(2026, 9, 25), status="observed"),
            "Reduce limit-risk spend",
        ),
        ("target_pressure", None, "Review utilization targets"),
        (
            "payment_due",
            SimpleNamespace(label="Due", date=date(2026, 9, 25), status="observed"),
            "Open Card due runway",
        ),
        ("review_evidence", None, "Refresh card evidence"),
        (
            "ready",
            SimpleNamespace(label="Statement", date=date(2026, 9, 25), status="estimated"),
            "Review upcoming card events",
        ),
    ],
)
async def test_card_portfolio_upcoming_query_formats_each_state(
    monkeypatch, state, next_event, expected_action
):
    portfolio = SimpleNamespace(
        state=state,
        issuer_total_due=500.0 if state != "no_active_cards" else None,
        issuer_total_due_complete=state == "ready",
        issuer_total_due_cards=1,
        card_count=2 if state != "no_active_cards" else 0,
        next_event=next_event,
        cards_needing_review=1 if state == "review_evidence" else 0,
        confidence=0.75,
        as_of=date(2026, 9, 20),
    )

    async def fake_upcoming(self, user_id):
        return portfolio

    monkeypatch.setattr(
        guidance_module.CardPortfolioUpcomingStateService, "upcoming", fake_upcoming
    )
    result = await GuidanceService(object())._card_portfolio_upcoming_query("u1", 9, 2026, "INR")

    assert result.intent == "card_portfolio_upcoming"
    assert expected_action in result.suggested_actions
    assert result.confidence == 0.75


@pytest.mark.asyncio
async def test_card_portfolio_payment_plan_query_formats_missing_and_populated_plans(monkeypatch):
    empty = SimpleNamespace(
        state="no_active_cards",
        card_count=0,
        cards_needing_review=0,
        confidence=0.0,
        as_of=date(2026, 9, 20),
        minimum_due_plan=SimpleNamespace(
            issuer_payment_target_total=None, additional_payment_total=None, status="unavailable"
        ),
        total_due_plan=SimpleNamespace(
            issuer_payment_target_total=None, additional_payment_total=None, status="unavailable"
        ),
    )
    populated = SimpleNamespace(
        state="ready",
        card_count=2,
        cards_needing_review=1,
        confidence=0.8,
        as_of=date(2026, 9, 20),
        minimum_due_plan=SimpleNamespace(
            issuer_payment_target_total=100.0, additional_payment_total=50.0, status="covered"
        ),
        total_due_plan=SimpleNamespace(
            issuer_payment_target_total=500.0, additional_payment_total=450.0, status="at_risk"
        ),
    )
    plans = iter([empty, populated])

    async def fake_compare(self, user_id):
        return next(plans)

    monkeypatch.setattr(guidance_module.CardPortfolioPaymentPlanService, "compare", fake_compare)
    service = GuidanceService(object())
    no_cards = await service._card_portfolio_payment_plan_query("u1", 9, 2026, "INR")
    result = await service._card_portfolio_payment_plan_query("u1", 9, 2026, "INR")

    assert no_cards.metrics[0].value == "no active cards"
    assert "Resolve card evidence" not in no_cards.suggested_actions
    assert result.metrics[2].value == "₹100"
    assert result.metrics[4].value == "₹50"
    assert "Resolve card evidence" in result.suggested_actions


@pytest.mark.asyncio
async def test_card_upcoming_state_query_handles_card_count_and_event_relative_labels(monkeypatch):
    service = GuidanceService(_ScalarsDB([]))
    no_cards = await service._card_upcoming_state_query("u1", 9, 2026, "INR")
    assert no_cards.confidence == 0

    multi = GuidanceService(_ScalarsDB([SimpleNamespace(id="one"), SimpleNamespace(id="two")]))
    many = await multi._card_upcoming_state_query("u1", 9, 2026, "INR")
    assert many.confidence == 0

    card = SimpleNamespace(id="card-1", institution_name="Coverage Card")
    states = iter(
        [
            SimpleNamespace(
                state="review_evidence",
                next_event=None,
                events=[],
                confidence=0.3,
                as_of=date(2026, 9, 20),
            ),
            SimpleNamespace(
                state="payment_due",
                next_event=SimpleNamespace(
                    label="Due",
                    date=date(2026, 9, 20),
                    days_from_today=0,
                    amount=100,
                    status="observed",
                    source_kind="statement",
                ),
                events=[1],
                confidence=0.8,
                as_of=date(2026, 9, 20),
            ),
            SimpleNamespace(
                state="target_pressure",
                next_event=SimpleNamespace(
                    label="Upcoming",
                    date=date(2026, 9, 22),
                    days_from_today=2,
                    amount=None,
                    status="estimated",
                    source_kind="ledger",
                ),
                events=[1, 2],
                confidence=0.7,
                as_of=date(2026, 9, 20),
            ),
        ]
    )

    async def fake_upcoming(self, user_id, account_id):
        return next(states)

    monkeypatch.setattr(guidance_module.CardUpcomingStateService, "upcoming", fake_upcoming)
    single = GuidanceService(_ScalarsDB([card]))
    no_event = await single._card_upcoming_state_query("u1", 9, 2026, "INR")
    event_today = await single._card_upcoming_state_query("u1", 9, 2026, "INR")
    event_later = await single._card_upcoming_state_query("u1", 9, 2026, "INR")

    assert "no dated event" in no_event.answer
    assert "today" in event_today.answer
    assert "in 2 days" in event_later.answer
    assert event_later.metrics[1].value == "Upcoming"
