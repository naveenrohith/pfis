from datetime import date, timedelta
from decimal import Decimal

from app.models.account import FinancialAccount
from app.schemas.financial_position import (
    CardOverviewResponse,
    CardStatementProjectionResponse,
)
from app.services.card_spend_routing_service import (
    _build_candidate,
    _rank_candidates,
    _select_reward,
)

from tests.pytest.helpers import create_user


def _overview(
    account_id: str,
    *,
    current: str = "20000",
    limit: str = "100000",
    target: str = "40",
    projected: str = "22000",
    reward_rules: list[dict] | None = None,
    balance_status: str = "observed",
) -> CardOverviewResponse:
    return CardOverviewResponse.model_construct(
        financial_account_id=account_id,
        currency="INR",
        provider_current_outstanding=None,
        estimated_current_balance=float(current) if current is not None else None,
        credit_limit=float(limit) if limit is not None else None,
        provider_credit_limit=None,
        utilization_target_pct=float(target) if target is not None else None,
        reward_rules=reward_rules or [],
        balance_status=balance_status,
        balance_confidence=0.82,
        next_statement_projection=CardStatementProjectionResponse(
            status="available",
            projected_statement_date=date.today() + timedelta(days=20),
            projected_balance=float(projected) if projected is not None else None,
            projected_utilization_pct=(
                float(Decimal(projected) / Decimal(limit) * 100)
                if projected is not None and limit is not None
                else None
            ),
            confidence=0.72,
            next_state="monitor_cycle",
        ),
    )


def _account(account_id: str, label: str) -> FinancialAccount:
    return FinancialAccount(
        id=account_id,
        institution_name=label,
        account_type="credit_card",
        balance_kind="liability",
        currency="INR",
    )


def test_reward_selection_prefers_exact_category_and_fails_closed_for_invalid_rules():
    selected = _select_reward(
        [
            {"label": "Everything", "rate_pct": 1},
            {"label": "Travel", "rate_pct": 5, "category": "Travel"},
            {"label": "Bad", "rate_pct": 101},
        ],
        " travel ",
    )
    assert selected.status == "explicit"
    assert selected.label == "Travel"
    assert selected.rate_pct == Decimal("5")
    assert "reward_rule_category_match" in selected.reason_codes
    assert "invalid_reward_rule_ignored" in selected.reason_codes

    mismatch = _select_reward([{"label": "Travel", "rate_pct": 5, "category": "travel"}], "fuel")
    assert mismatch.status == "category_mismatch"
    assert mismatch.rate_pct is None

    invalid = _select_reward(
        [
            {"label": "Broken", "rate_pct": "not-a-rate"},
            {"label": "Boolean", "rate_pct": True},
        ],
        None,
    )
    assert invalid.status == "invalid_rule"
    assert "all_reward_rules_invalid" in invalid.reason_codes


def test_routing_priority_balances_rewards_and_utilization_safety():
    first = _build_candidate(
        _account("card-a", "Card A"),
        _overview(
            "card-a",
            current="20000",
            target="40",
            projected="22000",
            reward_rules=[{"label": "Everywhere", "rate_pct": 1}],
        ),
        amount=Decimal("5000"),
        category="shopping",
        ledger_currency="INR",
    )
    second = _build_candidate(
        _account("card-b", "Card B"),
        _overview(
            "card-b",
            current="30000",
            target="20",
            projected="33000",
            reward_rules=[{"label": "Shopping", "rate_pct": 5, "category": "shopping"}],
        ),
        amount=Decimal("5000"),
        category="shopping",
        ledger_currency="INR",
    )

    rewards = _rank_candidates([first, second], "rewards")
    assert rewards[0].option.financial_account_id == "card-b"
    assert rewards[0].option.estimated_reward == 250.0

    safety = _rank_candidates([first, second], "utilization_safety")
    assert safety[0].option.financial_account_id == "card-a"
    assert safety[0].option.utilization_status == "within_target"


def test_routing_marks_hypothetical_limit_and_target_pressure():
    candidate = _build_candidate(
        _account("card-limit", "Limit Card"),
        _overview(
            "card-limit",
            current="95000",
            target="40",
            projected="96000",
            reward_rules=[{"label": "Everywhere", "rate_pct": 2}],
        ),
        amount=Decimal("6000"),
        category=None,
        ledger_currency="INR",
    )
    assert candidate.option.status == "over_limit"
    assert candidate.option.utilization_status == "over_limit"
    assert candidate.eligible is False
    assert "hypothetical_spend_exceeds_credit_limit" in candidate.option.reason_codes

    projected_limit_candidate = _build_candidate(
        _account("card-projected-limit", "Projected Limit Card"),
        _overview(
            "card-projected-limit",
            current="50000",
            target="90",
            projected="98000",
        ),
        amount=Decimal("5000"),
        category=None,
        ledger_currency="INR",
    )
    assert projected_limit_candidate.option.status == "over_limit"
    assert (
        "projected_statement_exceeds_credit_limit" in projected_limit_candidate.option.reason_codes
    )


async def test_spend_routing_returns_no_active_cards_without_mutation(client):
    user = await create_user(client, "spend-routing-empty")
    response = await client.post(
        f"/api/cards/portfolio/spend-routing?user_id={user['id']}",
        json={"amount": "1250.00", "category": "groceries", "priority": "rewards"},
    )
    response.raise_for_status()
    body = response.json()
    assert body["state"] == "no_active_cards"
    assert body["recommended_card_id"] is None
    assert body["options"] == []
    assert body["currency"] == "INR"
    assert body["ruleset_version"] == "pfis-card-spend-routing-1"


async def test_spend_routing_fails_closed_for_card_without_position_evidence(client):
    user = await create_user(client, "spend-routing-review")
    account = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Review Card",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****7711",
            "currency": "INR",
        },
    )
    account.raise_for_status()
    response = await client.post(
        f"/api/cards/portfolio/spend-routing?user_id={user['id']}",
        json={"amount": 500, "priority": "balanced"},
    )
    response.raise_for_status()
    body = response.json()
    assert body["state"] == "needs_review"
    assert body["recommended_card_id"] is None
    assert body["options"][0]["status"] == "needs_review"
    assert "current_outstanding_missing" in body["options"][0]["reason_codes"]
    assert "credit_limit_missing" in body["options"][0]["reason_codes"]


async def test_spend_routing_is_user_scoped(client):
    owner = await create_user(client, "spend-routing-owner")
    other = await create_user(client, "spend-routing-other")
    account = await client.post(
        f"/api/accounts?user_id={owner['id']}",
        json={
            "institution_name": "Owner Card",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****7722",
            "currency": "INR",
        },
    )
    account.raise_for_status()
    response = await client.post(
        f"/api/cards/portfolio/spend-routing?user_id={other['id']}",
        json={"amount": 500},
    )
    response.raise_for_status()
    assert response.json()["state"] == "no_active_cards"
    assert response.json()["options"] == []


async def test_spend_routing_uses_statement_limit_and_verified_balance(client):
    user = await create_user(client, "spend-routing-ready")
    card = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Ready Card",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "****7733",
            "currency": "INR",
        },
    )
    card.raise_for_status()
    card_id = card.json()["id"]
    today = date.today()
    statement_date = today - timedelta(days=5)
    statement = await client.post(
        f"/api/statements/hdfc/text?user_id={user['id']}",
        json={
            "financial_account_id": card_id,
            "document_fingerprint": "s" * 64,
            "statement_text": f"""
            HDFC BANK CREDIT CARD STATEMENT
            STATEMENT DATE: {statement_date:%d/%m/%Y}
            STATEMENT PERIOD: {(statement_date - timedelta(days=30)):%d/%m/%Y} TO {statement_date:%d/%m/%Y}
            TOTAL AMOUNT DUE: 20,000.00
            MINIMUM AMOUNT DUE: 2,000.00
            PAYMENT DUE DATE: {(today + timedelta(days=10)):%d/%m/%Y}
            TOTAL CREDIT LIMIT: 100,000.00
            AVAILABLE CREDIT LIMIT: 80,000.00
            """,
        },
    )
    statement.raise_for_status()
    balance = await client.post(
        f"/api/accounts/{card_id}/balances?user_id={user['id']}",
        json={"amount": 20000, "as_of": today.isoformat(), "source": "statement", "verified": True},
    )
    balance.raise_for_status()
    preference = await client.put(
        f"/api/cards/{card_id}/preferences?user_id={user['id']}",
        json={
            "utilization_target_pct": 40,
            "reward_rules": [{"label": "Everywhere", "rate_pct": 2}],
        },
    )
    preference.raise_for_status()

    response = await client.post(
        f"/api/cards/portfolio/spend-routing?user_id={user['id']}",
        json={"amount": 5000, "category": "groceries", "priority": "balanced"},
    )
    response.raise_for_status()
    body = response.json()
    option = body["options"][0]
    assert body["state"] == "ready"
    assert body["recommended_card_id"] == card_id
    assert option["status"] == "recommended"
    assert option["source_kind"] == "ledger_estimate"
    assert option["credit_limit"] == 100000.0
    assert option["projected_statement_balance"] == 25000.0
    assert option["reward_rate_pct"] == 2.0
    assert option["estimated_reward"] == 100.0
