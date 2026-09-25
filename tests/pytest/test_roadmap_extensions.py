"""Integration coverage for roadmap phases 7 and 8."""

from datetime import date, timedelta
from decimal import Decimal

from app.models.temporal_history import TemporalSourceSnapshot
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionType,
)
from sqlalchemy import select

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


async def test_card_calendar_lifecycle_and_milestone_progress(client, test_session_factory):
    owner = await create_user(client, "calendar-owner")
    other = await create_user(client, "calendar-other")
    card = await _account(client, owner["id"], "credit_card", "4455")
    other_card = await _account(client, other["id"], "credit_card", "4466")
    period_start = date(2026, 9, 1)
    period_end = date(2026, 9, 30)

    async with test_session_factory() as session:
        session.add_all(
            [
                Transaction(
                    user_id=owner["id"],
                    financial_account_id=card["id"],
                    amount=Decimal("1000.00"),
                    currency="INR",
                    transaction_type=TransactionType.DEBIT,
                    payment_method=PaymentMethod.CREDIT_CARD,
                    payment_rail=PaymentRail.OTHER,
                    card_event=CardEvent.PURCHASE,
                    transaction_status="settled",
                    merchant_raw="Book Store",
                    merchant_normalized="Book Store",
                    transaction_date=date(2026, 9, 5),
                    source_kind="statement",
                    source_identifier="stmt-line-1",
                    confidence_score=1.0,
                    reviewed_flag=True,
                    review_outcome="newly_imported",
                ),
                Transaction(
                    user_id=owner["id"],
                    financial_account_id=card["id"],
                    amount=Decimal("300.00"),
                    currency="INR",
                    transaction_type=TransactionType.REFUND,
                    payment_method=PaymentMethod.CREDIT_CARD,
                    payment_rail=PaymentRail.OTHER,
                    card_event=CardEvent.REFUND,
                    transaction_status="posted",
                    merchant_raw="Book Store",
                    merchant_normalized="Book Store",
                    transaction_date=date(2026, 9, 8),
                    source_kind="statement",
                    source_identifier="stmt-line-2",
                    confidence_score=1.0,
                    reviewed_flag=True,
                    review_outcome="newly_imported",
                ),
                Transaction(
                    user_id=owner["id"],
                    financial_account_id=card["id"],
                    amount=Decimal("500.00"),
                    currency="INR",
                    transaction_type=TransactionType.DEBIT,
                    payment_method=PaymentMethod.CREDIT_CARD,
                    payment_rail=PaymentRail.OTHER,
                    card_event=CardEvent.PURCHASE,
                    transaction_status="pending",
                    merchant_raw="Pending Merchant",
                    merchant_normalized="Pending Merchant",
                    transaction_date=date(2026, 9, 9),
                    source_kind="email",
                    confidence_score=1.0,
                    reviewed_flag=True,
                    review_outcome="newly_imported",
                ),
                Transaction(
                    user_id=other["id"],
                    financial_account_id=other_card["id"],
                    amount=Decimal("7000.00"),
                    currency="INR",
                    transaction_type=TransactionType.DEBIT,
                    payment_method=PaymentMethod.CREDIT_CARD,
                    payment_rail=PaymentRail.OTHER,
                    card_event=CardEvent.PURCHASE,
                    transaction_status="settled",
                    merchant_raw="Other User",
                    merchant_normalized="Other User",
                    transaction_date=date(2026, 9, 10),
                    source_kind="statement",
                    confidence_score=1.0,
                    reviewed_flag=True,
                    review_outcome="newly_imported",
                ),
            ]
        )
        await session.commit()

    invalid = await client.post(
        f"/api/cards/{card['id']}/calendar?user_id={owner['id']}",
        json={
            "event_type": "milestone_spend",
            "label": "Quarterly milestone",
            "event_date": period_end.isoformat(),
            "source_kind": "manual",
            "source_label": "User-entered bank offer",
            "milestone_spend_target": 2000,
            "milestone_period_start": period_end.isoformat(),
            "milestone_period_end": period_start.isoformat(),
        },
    )
    assert invalid.status_code == 422

    created = await client.post(
        f"/api/cards/{card['id']}/calendar?user_id={owner['id']}",
        json={
            "event_type": "milestone_spend",
            "label": "Quarterly milestone",
            "event_date": period_end.isoformat(),
            "source_kind": "manual",
            "source_label": "User-entered bank offer",
            "milestone_spend_target": 2000,
            "milestone_period_start": period_start.isoformat(),
            "milestone_period_end": period_end.isoformat(),
        },
    )
    created.raise_for_status()
    item = created.json()
    assert item["milestone_progress"]["counted_amount"] == "700.00"
    assert item["milestone_progress"]["remaining_amount"] == "1300.00"
    evidence = item["milestone_progress"]["evidence"]
    assert [row["direction"] for row in evidence] == ["spend", "refund"]
    assert {row["source_identifier"] for row in evidence} == {"stmt-line-1", "stmt-line-2"}

    listed = await client.get(f"/api/cards/{card['id']}/calendar?user_id={owner['id']}")
    listed.raise_for_status()
    assert [row["id"] for row in listed.json()] == [item["id"]]

    hidden_list = await client.get(f"/api/cards/{card['id']}/calendar?user_id={other['id']}")
    assert hidden_list.status_code == 404
    hidden_update = await client.patch(
        f"/api/cards/{card['id']}/calendar/{item['id']}?user_id={other['id']}",
        json={"label": "Cross-user edit"},
    )
    assert hidden_update.status_code == 404

    invalid_update = await client.patch(
        f"/api/cards/{card['id']}/calendar/{item['id']}?user_id={owner['id']}",
        json={"milestone_period_end": (period_start - timedelta(days=1)).isoformat()},
    )
    assert invalid_update.status_code == 422

    updated = await client.patch(
        f"/api/cards/{card['id']}/calendar/{item['id']}?user_id={owner['id']}",
        json={"label": "Updated milestone", "milestone_spend_target": 1000},
    )
    updated.raise_for_status()
    assert updated.json()["label"] == "Updated milestone"
    assert updated.json()["milestone_progress"]["remaining_amount"] == "300.00"

    deleted = await client.delete(
        f"/api/cards/{card['id']}/calendar/{item['id']}?user_id={owner['id']}"
    )
    assert deleted.status_code == 204
    empty = await client.get(f"/api/cards/{card['id']}/calendar?user_id={owner['id']}")
    empty.raise_for_status()
    assert empty.json() == []

    async with test_session_factory() as session:
        snapshots = (
            await session.scalars(
                select(TemporalSourceSnapshot)
                .where(
                    TemporalSourceSnapshot.user_id == owner["id"],
                    TemporalSourceSnapshot.source_type == "card_calendar",
                    TemporalSourceSnapshot.source_id == item["id"],
                )
                .order_by(TemporalSourceSnapshot.captured_at)
            )
        ).all()
    assert [snapshot.deleted for snapshot in snapshots] == [False, False, True]


async def test_card_calendar_milestone_without_terms_is_insufficient(client):
    owner = await create_user(client, "calendar-insufficient")
    card = await _account(client, owner["id"], "credit_card", "7799")

    created = await client.post(
        f"/api/cards/{card['id']}/calendar?user_id={owner['id']}",
        json={
            "event_type": "milestone_spend",
            "label": "Issuer offer noted without spend terms",
            "event_date": date(2027, 4, 1).isoformat(),
            "source_kind": "manual",
            "source_label": "User-entered issuer message",
        },
    )

    created.raise_for_status()
    progress = created.json()["milestone_progress"]
    assert progress["status"] == "insufficient"
    assert progress["counted_amount"] == "0.00"
    assert progress["target_amount"] is None
    assert progress["remaining_amount"] is None
    assert "Milestone target and period" in progress["reason"]
    assert progress["evidence"] == []


async def test_card_calendar_fee_and_reversal_fields_are_source_labelled(client):
    owner = await create_user(client, "calendar-fee")
    card = await _account(client, owner["id"], "credit_card", "7788")
    renewal = await client.post(
        f"/api/cards/{card['id']}/calendar?user_id={owner['id']}",
        json={
            "event_type": "renewal",
            "label": "Card renewal",
            "event_date": date(2027, 1, 31).isoformat(),
            "source_kind": "statement",
            "source_label": "January statement",
            "source_identifier": "statement:jan",
        },
    )
    renewal.raise_for_status()
    assert renewal.json()["source_label"] == "January statement"

    fee = await client.post(
        f"/api/cards/{card['id']}/calendar?user_id={owner['id']}",
        json={
            "event_type": "annual_fee",
            "label": "Annual fee",
            "event_date": date(2027, 2, 1).isoformat(),
            "source_kind": "statement",
            "source_label": "Fee row",
            "annual_fee_amount": 999,
        },
    )
    fee.raise_for_status()
    assert fee.json()["annual_fee_amount"] == "999.00"

    reversal = await client.post(
        f"/api/cards/{card['id']}/calendar?user_id={owner['id']}",
        json={
            "event_type": "fee_reversal",
            "label": "Fee waiver review",
            "event_date": date(2027, 3, 1).isoformat(),
            "source_kind": "manual",
            "source_label": "User-entered issuer message",
            "fee_reversal_condition": "User-entered: spend threshold confirmed by cardholder.",
            "fee_reversal_status": "pending",
        },
    )
    reversal.raise_for_status()
    assert reversal.json()["fee_reversal_status"] == "pending"


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
