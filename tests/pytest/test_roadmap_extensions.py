"""Integration coverage for roadmap phases 7 and 8."""

from datetime import date, timedelta

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Roadmap Bank",
            "account_type": account_type,
            "balance_kind": ("liability" if account_type == "credit_card" else "asset"),
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_bill_lifecycle_and_health_checklist_are_user_scoped(client):
    owner = await create_user(client, "roadmap-owner")
    other = await create_user(client, "roadmap-other")
    bank = await _account(client, owner["id"], "bank", "1801")
    created = await client.post(
        f"/api/bills?user_id={owner['id']}",
        json={
            "financial_account_id": bank["id"],
            "label": "Electricity",
            "bill_type": "utility",
            "amount": 1850,
            "due_date": (date.today() + timedelta(days=4)).isoformat(),
            "cadence": "monthly",
            "source_kind": "manual",
            "confirmed": True,
        },
    )
    created.raise_for_status()
    bill = created.json()
    assert bill["status"] == "due"
    assert bill["paid_at"] is None

    paid = await client.patch(
        f"/api/bills/{bill['id']}?user_id={owner['id']}",
        json={"status": "paid"},
    )
    paid.raise_for_status()
    assert paid.json()["paid_at"] is not None

    hidden = await client.patch(
        f"/api/bills/{bill['id']}?user_id={other['id']}",
        json={"status": "skipped"},
    )
    assert hidden.status_code == 404

    first = await client.put(
        f"/api/health-checklist/emergency_fund?user_id={owner['id']}",
        json={
            "item_type": "emergency_fund",
            "label": "Emergency reserve",
            "status": "in_progress",
            "note": "Build three months of coverage.",
        },
    )
    first.raise_for_status()
    updated = await client.put(
        f"/api/health-checklist/emergency_fund?user_id={owner['id']}",
        json={
            "item_type": "emergency_fund",
            "label": "Emergency reserve",
            "status": "complete",
            "note": "Confirmed.",
        },
    )
    updated.raise_for_status()
    assert updated.json()["id"] == first.json()["id"]
    assert updated.json()["status"] == "complete"


async def test_card_disputes_require_owned_card_and_matching_statement_line(client):
    owner = await create_user(client, "dispute-owner")
    other = await create_user(client, "dispute-other")
    card = await _account(client, owner["id"], "credit_card", "2921")
    other_card = await _account(client, owner["id"], "credit_card", "2922")

    statement_text = """
    HDFC BANK CREDIT CARD STATEMENT
    STATEMENT DATE: 05/03/2026
    STATEMENT PERIOD: 06/02/2026 TO 05/03/2026
    TOTAL AMOUNT DUE: 900.00
    MINIMUM AMOUNT DUE: 90.00
    PAYMENT DUE DATE: 25/03/2026
    TOTAL CREDIT LIMIT: 100,000.00
    AVAILABLE CREDIT LIMIT: 99,100.00
    02/03/2026 MERCHANT UNDER REVIEW 900.00
    """
    imported = await client.post(
        f"/api/statements/hdfc/text?user_id={owner['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "d" * 64,
            "statement_text": statement_text,
        },
    )
    imported.raise_for_status()
    statement_line_id = imported.json()["lines"][0]["id"]

    wrong_card = await client.post(
        f"/api/cards/{other_card['id']}/disputes?user_id={owner['id']}",
        json={
            "statement_line_id": statement_line_id,
            "label": "Wrong card line",
            "amount": 900,
            "complaint_date": date.today().isoformat(),
        },
    )
    assert wrong_card.status_code == 404

    created = await client.post(
        f"/api/cards/{card['id']}/disputes?user_id={owner['id']}",
        json={
            "statement_line_id": statement_line_id,
            "label": "Merchant charge",
            "amount": 900,
            "complaint_date": date.today().isoformat(),
            "reference_number": "HDFC-CASE-1",
        },
    )
    created.raise_for_status()
    dispute = created.json()
    assert dispute["status"] == "open"

    hidden = await client.get(f"/api/cards/{card['id']}/disputes?user_id={other['id']}")
    assert hidden.status_code == 404
    resolved = await client.patch(
        f"/api/card-disputes/{dispute['id']}?user_id={owner['id']}",
        json={"status": "resolved", "reference_number": "HDFC-CASE-1"},
    )
    resolved.raise_for_status()
    assert resolved.json()["status"] == "resolved"


async def test_households_require_one_shared_ledger_currency(client):
    owner = await create_user(client, "household-inr-owner")
    usd_member = await create_user(client, "household-usd-member", currency="USD")
    created = await client.post(
        f"/api/households?user_id={owner['id']}",
        json={"name": "Cross-currency home"},
    )
    created.raise_for_status()

    response = await client.post(
        f"/api/households/{created.json()['id']}/members?user_id={owner['id']}",
        json={
            "user_id": usd_member["id"],
            "role": "member",
            "visibility": "annotations_only",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["message"] == (
        "Household requires members with the same ledger currency"
    )


async def test_household_annotations_and_settlements_do_not_expose_private_evidence(
    client,
):
    owner = await create_user(client, "household-owner")
    member = await create_user(client, "household-member")
    outsider = await create_user(client, "household-outsider")
    created = await client.post(
        f"/api/households?user_id={owner['id']}",
        json={"name": "Home"},
    )
    created.raise_for_status()
    household = created.json()

    added = await client.post(
        f"/api/households/{household['id']}/members?user_id={owner['id']}",
        json={
            "user_id": member["id"],
            "role": "member",
            "visibility": "annotations_only",
        },
    )
    added.raise_for_status()
    assert added.json()["member_count"] == 2
    wrong_currency_expense = await client.post(
        f"/api/households/{household['id']}/expenses?user_id={owner['id']}",
        json={
            "payer_user_id": owner["id"],
            "label": "Unsafe mixed-currency expense",
            "amount": 100,
            "currency": "USD",
            "expense_date": date.today().isoformat(),
            "splits": {owner["id"]: 50, member["id"]: 50},
        },
    )
    assert wrong_currency_expense.status_code == 422
    assert wrong_currency_expense.json()["error"]["message"] == (
        "Household expense currency USD does not match ledger currency INR"
    )
    listed = await client.get(f"/api/households/{household['id']}/members?user_id={owner['id']}")
    listed.raise_for_status()
    roles = {item["user_id"]: item["role"] for item in listed.json()}
    assert roles == {owner["id"]: "owner", member["id"]: "member"}

    forbidden_add = await client.post(
        f"/api/households/{household['id']}/members?user_id={member['id']}",
        json={
            "user_id": outsider["id"],
            "role": "member",
            "visibility": "annotations_only",
        },
    )
    assert forbidden_add.status_code == 403
    viewer = await client.patch(
        f"/api/households/{household['id']}/members/{member['id']}?user_id={owner['id']}",
        json={"role": "viewer", "visibility": "annotations_only"},
    )
    viewer.raise_for_status()
    assert viewer.json()["role"] == "viewer"
    forbidden_role_change = await client.patch(
        f"/api/households/{household['id']}/members/{member['id']}?user_id={member['id']}",
        json={"role": "member", "visibility": "annotations_only"},
    )
    assert forbidden_role_change.status_code == 403
    viewer_expense = await client.post(
        f"/api/households/{household['id']}/expenses?user_id={member['id']}",
        json={
            "payer_user_id": owner["id"],
            "label": "Viewer must not edit",
            "amount": 100,
            "currency": "INR",
            "expense_date": date.today().isoformat(),
            "splits": {owner["id"]: 50, member["id"]: 50},
        },
    )
    assert viewer_expense.status_code == 403
    restored = await client.patch(
        f"/api/households/{household['id']}/members/{member['id']}?user_id={owner['id']}",
        json={"role": "member", "visibility": "annotations_only"},
    )
    restored.raise_for_status()

    expense = await client.post(
        f"/api/households/{household['id']}/expenses?user_id={member['id']}",
        json={
            "payer_user_id": owner["id"],
            "label": "Groceries",
            "amount": 1200,
            "currency": "INR",
            "expense_date": date.today().isoformat(),
            "splits": {owner["id"]: 600, member["id"]: 600},
        },
    )
    expense.raise_for_status()
    expense_payload = expense.json()
    assert expense_payload["splits"][owner["id"]] == "600"
    assert "transaction_id" not in expense_payload
    assert "financial_account_id" not in expense_payload
    assert "source_identifier" not in expense_payload

    invisible = await client.get(
        f"/api/households/{household['id']}/expenses?user_id={outsider['id']}"
    )
    assert invisible.status_code == 404

    settlement = await client.post(
        f"/api/households/{household['id']}/settlements?user_id={member['id']}",
        json={
            "from_user_id": member["id"],
            "to_user_id": owner["id"],
            "amount": 600,
            "currency": "INR",
            "settlement_date": date.today().isoformat(),
            "status": "planned",
        },
    )
    settlement.raise_for_status()
    assert settlement.json()["status"] == "planned"

    blocked_removal = await client.delete(
        f"/api/households/{household['id']}/members/{member['id']}?user_id={owner['id']}"
    )
    assert blocked_removal.status_code == 422
    recorded = await client.patch(
        f"/api/households/{household['id']}/settlements/"
        f"{settlement.json()['id']}?user_id={member['id']}",
        json={"status": "recorded", "note": "Settled outside PFIS."},
    )
    recorded.raise_for_status()

    removed = await client.delete(
        f"/api/households/{household['id']}/members/{member['id']}?user_id={owner['id']}"
    )
    assert removed.status_code == 204
    former_member = await client.get(
        f"/api/households/{household['id']}/expenses?user_id={member['id']}"
    )
    assert former_member.status_code == 404
    deleted = await client.delete(f"/api/households/{household['id']}?user_id={owner['id']}")
    assert deleted.status_code == 204


async def test_payoff_comparison_uses_only_complete_explicit_liabilities(client):
    user = await create_user(client, "payoff")
    for payload in (
        {
            "label": "High-rate loan",
            "liability_type": "loan",
            "outstanding_principal": 12000,
            "monthly_due": 1000,
            "interest_rate": 24,
        },
        {
            "label": "Small balance",
            "liability_type": "pay_later",
            "outstanding_principal": 5000,
            "monthly_due": 500,
            "interest_rate": 10,
        },
        {
            "label": "Unknown rate",
            "liability_type": "loan",
            "outstanding_principal": 8000,
            "monthly_due": 800,
        },
    ):
        response = await client.post(
            f"/api/liabilities?user_id={user['id']}",
            json=payload,
        )
        response.raise_for_status()

    insufficient = await client.get(
        f"/api/liabilities/payoff-comparison?user_id={user['id']}&monthly_budget=1200"
    )
    insufficient.raise_for_status()
    assert insufficient.json()["readiness"] == "insufficient_budget"

    ready = await client.get(
        f"/api/liabilities/payoff-comparison?user_id={user['id']}&monthly_budget=2500"
    )
    ready.raise_for_status()
    comparison = ready.json()
    assert comparison["readiness"] == "ready"
    assert len(comparison["debts"]) == 2
    assert len(comparison["excluded_liability_ids"]) == 1
    scenarios = {item["method"]: item for item in comparison["scenarios"]}
    assert scenarios["highest_interest_first"]["payoff_order"][0] == "High-rate loan"
    assert scenarios["smallest_balance_first"]["payoff_order"][0] == "Small balance"
    assert all(item["estimated_months"] for item in scenarios.values())
