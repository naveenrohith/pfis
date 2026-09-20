"""Exercise the public guidance query contract across supported intents."""

from __future__ import annotations

from datetime import date

from tests.pytest.helpers import create_user


async def test_empty_workspace_supports_every_audited_guidance_query(client):
    user = await create_user(client, "guidance-query-matrix")
    selected = date(2026, 8, 20)
    queries = (
        ("show my recurring subscriptions", "recurring_charges"),
        ("how is my budget", "budget_status"),
        ("compare this with last month", "month_comparison"),
        ("how much did I spend at Coffee Bar this month", "merchant_spend"),
        ("what was my income", "monthly_income"),
        ("how much were my savings", "monthly_savings"),
        ("how much did I spend this month", "monthly_spend"),
        ("what is my net worth", "current_net_worth"),
        ("what is my current outstanding balance", "card_position"),
        ("which cards are due across all cards", "card_portfolio_upcoming"),
        ("compare minimum and total card payment plans", "card_portfolio_payment_plan"),
        ("what happens next with my card", "card_upcoming_state"),
        ("can I pay my card before the due date", "card_due_affordability"),
    )

    for query, intent in queries:
        response = await client.post(
            f"/api/guidance/query?user_id={user['id']}",
            json={"query": query, "month": selected.month, "year": selected.year},
        )
        response.raise_for_status()
        body = response.json()
        assert body["supported"] is True
        assert body["intent"] == intent
        assert body["evidence"]
        assert body["uncertainty"]
