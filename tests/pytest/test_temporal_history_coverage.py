"""Coverage for immutable temporal baselines and historical-safe reconstruction."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.account import FinancialAccount
from app.models.financial_position import (
    CardCalendarEvent,
    CardPaymentIntent,
    CashPlan,
    Commitment,
    CreditCardStatement,
    DepositAccountStatement,
    DepositStatementLine,
    Liability,
    LiabilityScheduleItem,
    ReservePlan,
    StatementImport,
    StatementLine,
)
from app.models.roadmap import RoadmapBill
from app.models.temporal_history import TemporalSourceSnapshot
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionType,
)
from app.services.temporal_event_service import TemporalEventService
from app.services.temporal_source_history import (
    capture_temporal_source_snapshot,
    historical_source_snapshots,
)
from sqlalchemy import select

from tests.pytest.helpers import create_user


async def _backfill(client, user_id: str, source_types: list[str], *, dry_run: bool):
    response = await client.post(
        f"/api/knowledge/history/backfill?user_id={user_id}",
        json={
            "dry_run": dry_run,
            "source_types": source_types,
            "max_rows_per_source": 10,
        },
    )
    response.raise_for_status()
    return response.json()


@pytest.mark.asyncio
async def test_temporal_backfill_and_historical_safe_timeline_cover_source_families(
    client, test_session_factory
):
    user = await create_user(client, "temporal-history", timezone="UTC")
    user_id = user["id"]
    # The test user is explicitly on UTC; use the same calendar as the
    # service so a local-time midnight cannot move the cutoff into the future
    # or exclude snapshots captured later during a long CI run.
    today = datetime.now(UTC).date()

    async with test_session_factory() as db:
        bank = FinancialAccount(
            user_id=user_id,
            institution_name="History Bank",
            account_type="bank",
            balance_kind="asset",
            masked_number="****1100",
            currency="INR",
            identity_status="inferred",
            identity_confidence=Decimal("0.72"),
        )
        card = FinancialAccount(
            user_id=user_id,
            institution_name="History Card",
            account_type="credit_card",
            balance_kind="liability",
            masked_number="****2200",
            currency="INR",
            is_active=False,
            identity_status="confirmed",
            identity_confidence=Decimal("0.99"),
        )
        db.add_all([bank, card])
        await db.flush()

        transaction = Transaction(
            user_id=user_id,
            financial_account_id=bank.id,
            amount=Decimal("125.50"),
            currency="INR",
            transaction_type=TransactionType.DEBIT,
            payment_method=PaymentMethod.OTHER,
            payment_rail=PaymentRail.OTHER,
            card_event=CardEvent.NONE,
            transaction_status="pending",
            transaction_date=today,
            merchant_raw="History transaction",
            merchant_normalized="History transaction",
            confidence_score=0.72,
            reviewed_flag=False,
            source_kind="connector",
            review_outcome="newly_imported",
        )
        intent = CardPaymentIntent(
            user_id=user_id,
            financial_account_id=card.id,
            paying_account_id=bank.id,
            amount=Decimal("80.00"),
            planned_for=today + timedelta(days=2),
            status="planned",
            note="Historical payment plan",
        )
        db.add_all([transaction, intent])

        card_import = StatementImport(
            user_id=user_id,
            financial_account_id=card.id,
            issuer="history-card",
            document_fingerprint="history-card-fingerprint",
            extractor_version="test",
        )
        deposit_import = StatementImport(
            user_id=user_id,
            financial_account_id=bank.id,
            issuer="history-bank",
            document_fingerprint="history-bank-fingerprint",
            extractor_version="test",
        )
        db.add_all([card_import, deposit_import])
        await db.flush()
        card_statement = CreditCardStatement(
            user_id=user_id,
            statement_import_id=card_import.id,
            financial_account_id=card.id,
            statement_date=today,
            period_start=today - timedelta(days=30),
            period_end=today,
            currency="INR",
        )
        deposit_statement = DepositAccountStatement(
            user_id=user_id,
            statement_import_id=deposit_import.id,
            financial_account_id=bank.id,
            period_start=today - timedelta(days=30),
            period_end=today,
            opening_balance=Decimal("1000"),
            closing_balance=Decimal("1125.50"),
            currency="INR",
        )
        db.add_all([card_statement, deposit_statement])
        await db.flush()
        db.add_all(
            [
                StatementLine(
                    user_id=user_id,
                    credit_card_statement_id=card_statement.id,
                    line_number=1,
                    transaction_date=today,
                    description="History card line",
                    amount=Decimal("125.50"),
                    transaction_type="debit",
                    card_event="purchase",
                    review_outcome="needs_review",
                ),
                DepositStatementLine(
                    user_id=user_id,
                    deposit_account_statement_id=deposit_statement.id,
                    line_number=1,
                    transaction_date=today,
                    value_date=today,
                    description="History deposit line",
                    amount=Decimal("125.50"),
                    transaction_type="credit",
                    payment_rail="bank_transfer",
                    balance_after=Decimal("1125.50"),
                    review_outcome="newly_imported",
                ),
            ]
        )
        await db.commit()

    source_types = [
        "transaction",
        "financial_account",
        "statement_line",
        "deposit_statement_line",
    ]
    preview = await _backfill(client, user_id, source_types, dry_run=True)
    assert preview["dry_run"] is True
    assert {row["source_type"] for row in preview["sources"]} == set(source_types)
    assert [row["candidate_count"] for row in preview["sources"]] == [1, 2, 1, 1], preview[
        "sources"
    ]
    assert all(row["captured_count"] == 0 for row in preview["sources"])

    captured = await _backfill(client, user_id, source_types, dry_run=False)
    assert [row["captured_count"] for row in captured["sources"]] == [1, 2, 1, 1]
    repeated = await _backfill(client, user_id, source_types, dry_run=False)
    assert [row["existing_snapshot_count"] for row in repeated["sources"]] == [1, 2, 1, 1]
    assert all(row["captured_count"] == 0 for row in repeated["sources"])

    intent_preview = await _backfill(client, user_id, ["card_payment_intent"], dry_run=True)
    assert intent_preview["sources"][0]["candidate_count"] == 1
    intent_capture = await _backfill(client, user_id, ["card_payment_intent"], dry_run=False)
    assert intent_capture["sources"][0]["captured_count"] == 1

    captured_at = datetime.combine(today, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
    async with test_session_factory() as db:
        manual_snapshots = [
            (
                "cash_plan",
                "cash-1",
                {
                    "next_income_date": today + timedelta(days=2),
                    "next_income_amount": "3000",
                },
            ),
            (
                "bill",
                "bill-paid",
                {
                    "due_date": today,
                    "status": "paid",
                    "amount": "450",
                    "label": "Paid bill",
                    "bill_type": "utility",
                    "confirmed": True,
                },
            ),
            (
                "bill",
                "bill-skipped",
                {
                    "due_date": today + timedelta(days=1),
                    "status": "skipped",
                    "amount": "500",
                    "label": "Skipped bill",
                    "bill_type": "subscription",
                    "confirmed": False,
                },
            ),
            (
                "commitment",
                "commitment-1",
                {
                    "due_date": today + timedelta(days=1),
                    "amount": "600",
                    "cadence": "weekly",
                    "label": "Weekly commitment",
                    "confirmed": True,
                    "is_active": True,
                },
            ),
            (
                "liability_schedule",
                "liability-1",
                {
                    "due_date": today + timedelta(days=1),
                    "installment_amount": "700",
                    "status": "paid",
                    "label": "Statement instalment",
                    "source_kind": "statement",
                    "confidence": "0.91",
                    "complete_schedule": True,
                },
            ),
            (
                "reserve_plan",
                "reserve-1",
                {
                    "due_date": today + timedelta(days=3),
                    "target_amount": "800",
                    "label": "Emergency reserve",
                    "approved": True,
                    "is_active": True,
                },
            ),
            (
                "card_calendar",
                "calendar-1",
                {
                    "event_date": today + timedelta(days=4),
                    "label": "Statement closes",
                },
            ),
        ]
        for source_type, source_id, payload in manual_snapshots:
            await capture_temporal_source_snapshot(
                db,
                user_id=user_id,
                source_type=source_type,
                source_id=source_id,
                payload=payload,
                captured_at=captured_at,
            )
        liability = Liability(
            user_id=user_id,
            financial_account_id=card.id,
            label="History loan",
            liability_type="loan",
            source_kind="statement",
            source_confidence=Decimal("0.84"),
            complete_schedule=True,
        )
        db.add(
            CashPlan(
                user_id=user_id,
                primary_financial_account_id=bank.id,
                next_income_date=today + timedelta(days=2),
                next_income_amount=Decimal("3000"),
            )
        )
        db.add(
            RoadmapBill(
                user_id=user_id,
                financial_account_id=bank.id,
                label="Normal paid bill",
                bill_type="utility",
                amount=Decimal("450"),
                due_date=today,
                status="paid",
                source_kind="manual",
                confirmed=True,
                paid_at=datetime.now(UTC),
            )
        )
        db.add(
            Commitment(
                user_id=user_id,
                financial_account_id=bank.id,
                label="Normal weekly commitment",
                commitment_type="subscription",
                amount=Decimal("600"),
                due_date=today + timedelta(days=1),
                cadence="weekly",
                confirmed=True,
                is_active=True,
            )
        )
        db.add(liability)
        await db.flush()
        db.add(
            LiabilityScheduleItem(
                liability_id=liability.id,
                user_id=user_id,
                due_date=today + timedelta(days=1),
                installment_amount=Decimal("700"),
                source_kind="statement",
                confidence=Decimal("0.91"),
                status="paid",
            )
        )
        db.add(
            ReservePlan(
                user_id=user_id,
                financial_account_id=bank.id,
                label="Normal reserve",
                target_amount=Decimal("800"),
                due_date=today + timedelta(days=3),
                monthly_allocation=Decimal("100"),
                approved=True,
                is_active=True,
            )
        )
        db.add(
            CardCalendarEvent(
                user_id=user_id,
                financial_account_id=card.id,
                event_type="statement_close",
                label="Normal statement close",
                event_date=today + timedelta(days=4),
            )
        )
        await capture_temporal_source_snapshot(
            db,
            user_id=user_id,
            source_type="cash_plan",
            source_id="cash-1",
            payload=manual_snapshots[0][2],
            captured_at=captured_at + timedelta(minutes=1),
        )
        await capture_temporal_source_snapshot(
            db,
            user_id=user_id,
            source_type="deleted-source",
            source_id="gone",
            payload={"event_date": today},
            captured_at=captured_at,
        )
        await capture_temporal_source_snapshot(
            db,
            user_id=user_id,
            source_type="deleted-source",
            source_id="gone",
            payload=None,
            deleted=True,
            captured_at=captured_at + timedelta(minutes=1),
        )
        db.add(
            TemporalSourceSnapshot(
                user_id=user_id,
                source_type="malformed",
                source_id="bad-json",
                captured_at=captured_at,
                payload_json="{not-json",
                ruleset_version="test",
            )
        )
        await db.commit()

        snapshots = await historical_source_snapshots(
            db, user_id=user_id, timezone="Not/AZone", as_of=today
        )
        assert ("deleted-source", "gone") not in snapshots
        assert ("malformed", "bad-json") not in snapshots
        assert snapshots[("cash_plan", "cash-1")]["next_income_amount"] == "3000"

        timeline = await TemporalEventService(db).timeline(
            user_id,
            range_start=today,
            range_end=today + timedelta(days=5),
            as_of=today,
            historical_safe=True,
        )
        normal_timeline = await TemporalEventService(db).timeline(
            user_id,
            range_start=today,
            range_end=today + timedelta(days=5),
            as_of=today,
        )

    source_kinds = {event.evidence[0].source_type for event in timeline.events if event.evidence}
    assert {
        "cash_plan",
        "bill",
        "commitment",
        "liability_schedule",
        "reserve_plan",
        "card_calendar",
        "financial_account",
        "transaction",
        "card_payment_intent",
    } <= source_kinds
    assert any(event.state == "observed" for event in timeline.events)
    assert any(event.state == "cancelled" for event in timeline.events)
    assert any(event.kind == "account_identity" for event in timeline.events)
    assert any(event.kind == "transaction_lifecycle" for event in timeline.events)
    assert any(event.kind == "liability_installment" for event in timeline.events)
    normal_kinds = {event.kind for event in normal_timeline.events}
    assert {
        "income",
        "bill",
        "commitment",
        "liability_installment",
        "reserve",
        "card_milestone",
        "account_identity",
        "transaction_lifecycle",
    } <= normal_kinds

    async with test_session_factory() as db:
        snapshot_count = await db.scalar(
            select(TemporalSourceSnapshot.id).where(
                TemporalSourceSnapshot.user_id == user_id,
                TemporalSourceSnapshot.source_type == "transaction",
            )
        )
        assert snapshot_count is not None
