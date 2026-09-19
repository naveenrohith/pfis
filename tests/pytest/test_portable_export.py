"""Portable full-data export completeness, privacy, and ownership tests."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zipfile import ZipFile

from app.database import Base
from app.models.auth import AuthSession
from app.models.category import Category
from app.models.email import GmailAccount, RawEmail
from app.models.forecast import CashFlowForecastOutcome, CashFlowForecastSnapshot
from app.models.knowledge import TemporalEventDecision
from app.models.roadmap import (
    Household,
    HouseholdExpense,
    HouseholdMember,
    HouseholdSettlement,
)
from app.models.sync import UserCorrection
from app.models.transaction import PaymentMethod, Transaction, TransactionType
from app.models.workspace import RecommendationOutcome, RecommendationState
from app.security import encrypt_secret
from app.services.portable_export_service import (
    PORTABLE_EXPORT_EXCLUDED_TABLES,
    PORTABLE_EXPORT_SCHEMA_VERSION,
    PORTABLE_EXPORT_TABLES,
    SECRET_COLUMN_NAMES,
    build_portable_export,
)
from sqlalchemy import select

from tests.pytest.helpers import auth_headers, create_user, register_user


def _archive(response_content: bytes) -> ZipFile:
    return ZipFile(io.BytesIO(response_content))


def _manifest(archive: ZipFile) -> dict:
    return json.loads(archive.read("manifest.json"))


def _records(archive: ZipFile, table_name: str) -> list[dict]:
    payload = archive.read(f"data/{table_name}.jsonl").decode("utf-8")
    return [json.loads(line) for line in payload.splitlines() if line]


def test_portable_export_inventory_requires_a_decision_for_every_model():
    assert PORTABLE_EXPORT_TABLES.isdisjoint(PORTABLE_EXPORT_EXCLUDED_TABLES)
    assert PORTABLE_EXPORT_TABLES | set(PORTABLE_EXPORT_EXCLUDED_TABLES) == set(
        Base.metadata.tables
    )


async def test_portable_export_is_owned_complete_and_secret_free(
    client,
    auth_required,
    test_session_factory,
):
    user, token = await register_user(client, "portable-owner")
    other, _ = await register_user(client, "portable-other")
    raw_body = "Full owned evidence body for portability"
    access_secret = "access-token-must-not-leave"
    refresh_secret = "refresh-token-must-not-leave"
    session_secret = "session-hash-must-not-leave"

    async with test_session_factory() as db:
        category = await db.scalar(select(Category).order_by(Category.name))
        assert category is not None
        own_email = RawEmail(
            user_id=user["id"],
            gmail_message_id="portable-owned-email",
            sender="alerts@example.test",
            subject="Owned source evidence",
            body=raw_body,
            received_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
            processed_flag=True,
        )
        other_email = RawEmail(
            user_id=other["id"],
            gmail_message_id="portable-other-email",
            sender="other@example.test",
            subject="Other user's source",
            body="must never cross the export boundary",
            received_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
        )
        db.add_all([own_email, other_email])
        await db.flush()
        own_transaction = Transaction(
            user_id=user["id"],
            amount=Decimal("123.45"),
            currency="INR",
            transaction_type=TransactionType.DEBIT,
            payment_method=PaymentMethod.UPI,
            merchant_raw="PORTABLE MERCHANT",
            merchant_normalized="Portable Merchant",
            category_id=category.id,
            transaction_date=date(2026, 7, 1),
            source_email_id=own_email.id,
            fingerprint="portable-owned-fingerprint",
            tags_json='["portable"]',
        )
        other_transaction = Transaction(
            user_id=other["id"],
            amount=Decimal("999.00"),
            currency="INR",
            transaction_type=TransactionType.DEBIT,
            payment_method=PaymentMethod.OTHER,
            merchant_raw="OTHER PRIVATE MERCHANT",
            merchant_normalized="Other Private Merchant",
            category_id=category.id,
            transaction_date=date(2026, 7, 1),
            source_email_id=other_email.id,
            fingerprint="portable-other-fingerprint",
        )
        db.add_all([own_transaction, other_transaction])
        await db.flush()
        db.add_all(
            [
                TemporalEventDecision(
                    user_id=user["id"],
                    event_id="portable-owned-temporal-event",
                    event_kind="bill",
                    source_type="bill",
                    source_id="portable-owned-bill",
                    occurrence_date=date(2026, 7, 2),
                    event_ruleset_version="pfis-temporal-events-1",
                    decision="linked",
                    transaction_id=own_transaction.id,
                    observed_date=own_transaction.transaction_date,
                    observed_amount=own_transaction.amount,
                    note="Owned temporal evidence",
                ),
                TemporalEventDecision(
                    user_id=other["id"],
                    event_id="portable-other-temporal-event",
                    event_kind="bill",
                    source_type="bill",
                    source_id="portable-other-bill",
                    occurrence_date=date(2026, 7, 2),
                    event_ruleset_version="pfis-temporal-events-1",
                    decision="conflict",
                    note="must never cross the export boundary",
                ),
            ]
        )
        recommendation = RecommendationState(
            user_id=user["id"],
            recommendation_id="portable-owned-recommendation",
            state="accepted",
            recommendation_type="review",
            title="Review uncertain activity",
            target="review",
            expected_impact="Improve financial totals",
            evidence_json="[]",
            reason_codes_json='["review"]',
            guidance_ruleset_version="pfis-guidance-3",
            decision_as_of=date(2026, 7, 1),
            decided_at=datetime(2026, 7, 1, 10, tzinfo=UTC),
        )
        db.add(recommendation)
        await db.flush()
        db.add(
            RecommendationOutcome(
                user_id=user["id"],
                decision_id=recommendation.id,
                outcome="helped",
                actual_impact_value=Decimal("2.00"),
                actual_impact_unit="records",
                outcome_ruleset_version="pfis-recommendation-outcome-1",
            )
        )
        own_forecast = CashFlowForecastSnapshot(
            user_id=user["id"],
            target_month=7,
            target_year=2026,
            cutoff_date=date(2026, 7, 1),
            forecast_ruleset_version="pfis-cash-flow-5",
            temporal_ruleset_version="pfis-temporal-events-1",
            projected_spend=Decimal("100.00"),
            projected_net=Decimal("50.00"),
            projected_range_low=Decimal("90.00"),
            projected_range_high=Decimal("110.00"),
            expected_income=Decimal("150.00"),
            temporal_expected_income=Decimal("0.00"),
            temporal_expected_outflows=Decimal("0.00"),
            temporal_conflicted_outflows=Decimal("0.00"),
            confidence=Decimal("0.700"),
            data_sufficiency="medium",
            evidence_json="[]",
            assumptions_json="[]",
        )
        other_forecast = CashFlowForecastSnapshot(
            user_id=other["id"],
            target_month=7,
            target_year=2026,
            cutoff_date=date(2026, 7, 1),
            forecast_ruleset_version="pfis-cash-flow-5",
            projected_spend=Decimal("999.00"),
            projected_net=Decimal("-999.00"),
            projected_range_low=Decimal("900.00"),
            projected_range_high=Decimal("1100.00"),
            expected_income=Decimal("0.00"),
            temporal_expected_income=Decimal("0.00"),
            temporal_expected_outflows=Decimal("999.00"),
            temporal_conflicted_outflows=Decimal("0.00"),
            confidence=Decimal("0.500"),
            data_sufficiency="low",
            evidence_json="[]",
            assumptions_json="[]",
        )
        db.add_all([own_forecast, other_forecast])
        await db.flush()
        db.add_all(
            [
                CashFlowForecastOutcome(
                    user_id=user["id"],
                    snapshot_id=own_forecast.id,
                    outcome_ruleset_version="pfis-cash-flow-outcome-1",
                    actual_income=Decimal("140.00"),
                    actual_spend=Decimal("105.00"),
                    actual_net=Decimal("35.00"),
                    spend_absolute_error=Decimal("5.00"),
                    spend_absolute_percentage_error=Decimal("4.762"),
                    spend_range_covered=True,
                ),
                CashFlowForecastOutcome(
                    user_id=other["id"],
                    snapshot_id=other_forecast.id,
                    outcome_ruleset_version="pfis-cash-flow-outcome-1",
                    actual_income=Decimal("0.00"),
                    actual_spend=Decimal("999.00"),
                    actual_net=Decimal("-999.00"),
                    spend_absolute_error=Decimal("0.00"),
                    spend_absolute_percentage_error=Decimal("0.000"),
                    spend_range_covered=True,
                ),
            ]
        )
        db.add(
            UserCorrection(
                transaction_id=own_transaction.id,
                field_corrected="merchant_normalized",
                old_value="PORTABLE MERCHANT",
                new_value="Portable Merchant",
            )
        )
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="portable-google-subject",
                access_token_ref=encrypt_secret(access_secret),
                refresh_token_ref=encrypt_secret(refresh_secret),
            )
        )
        db.add(
            AuthSession(
                user_id=user["id"],
                token_hash=session_secret,
                csrf_token_hash="csrf-hash-must-not-leave",
                mode="auth",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        household = Household(owner_user_id=user["id"], name="Portable household")
        closed_household = Household(owner_user_id=other["id"], name="Closed household")
        db.add_all([household, closed_household])
        await db.flush()
        db.add_all(
            [
                HouseholdMember(
                    household_id=household.id,
                    user_id=user["id"],
                    role="owner",
                ),
                HouseholdMember(
                    household_id=household.id,
                    user_id=other["id"],
                    role="member",
                ),
                HouseholdExpense(
                    household_id=household.id,
                    created_by_user_id=user["id"],
                    payer_user_id=other["id"],
                    label="Shared annotation",
                    amount=Decimal("80.00"),
                    currency="INR",
                    expense_date=date(2026, 7, 2),
                    splits_json=json.dumps({user["id"]: "40.00", other["id"]: "40.00"}),
                ),
                HouseholdSettlement(
                    household_id=household.id,
                    created_by_user_id=user["id"],
                    from_user_id=user["id"],
                    to_user_id=other["id"],
                    amount=Decimal("40.00"),
                    currency="INR",
                    settlement_date=date(2026, 7, 3),
                ),
                HouseholdMember(
                    household_id=closed_household.id,
                    user_id=user["id"],
                    role="member",
                    left_at=datetime(2026, 7, 4, tzinfo=UTC),
                ),
                HouseholdExpense(
                    household_id=closed_household.id,
                    created_by_user_id=other["id"],
                    payer_user_id=other["id"],
                    label="Closed household evidence",
                    amount=Decimal("99.00"),
                    currency="INR",
                    expense_date=date(2026, 7, 4),
                ),
            ]
        )
        await db.commit()

    response = await client.post(
        f"/api/reports/export/portable?user_id={user['id']}",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "pfis-portable-export-" in response.headers["content-disposition"]
    archive_bytes = response.content

    with _archive(archive_bytes) as archive:
        exported_text = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
        assert access_secret not in exported_text
        assert refresh_secret not in exported_text
        assert session_secret not in exported_text
        assert other["email"] not in exported_text
        assert other["id"] not in exported_text

        manifest = _manifest(archive)
        assert manifest["schema_version"] == PORTABLE_EXPORT_SCHEMA_VERSION
        assert manifest["privacy"]["credential_material_included"] is False
        assert manifest["user"]["ledger_currency"] == "INR"
        assert manifest["user"]["timezone"] == "Asia/Kolkata"
        assert {entity["name"] for entity in manifest["entities"]} == PORTABLE_EXPORT_TABLES
        for entity in manifest["entities"]:
            assert not SECRET_COLUMN_NAMES.intersection(entity["fields"])
            payload = archive.read(entity["path"])
            assert entity["sha256"] == hashlib.sha256(payload).hexdigest()

        raw_emails = _records(archive, "raw_emails")
        transactions = _records(archive, "transactions")
        corrections = _records(archive, "user_corrections")
        members = _records(archive, "household_members")
        expenses = _records(archive, "household_expenses")
        households = _records(archive, "households")
        temporal_decisions = _records(archive, "temporal_event_decisions")
        forecast_snapshots = _records(archive, "cash_flow_forecast_snapshots")
        forecast_outcomes = _records(archive, "cash_flow_forecast_outcomes")
        recommendation_outcomes = _records(archive, "recommendation_outcomes")
        assert [row["body"] for row in raw_emails] == [raw_body]
        assert [row["merchant_normalized"] for row in transactions] == ["Portable Merchant"]
        assert corrections[0]["new_value"] == "Portable Merchant"
        assert {row["user_id"] for row in members} == {user["id"], "shared-member-001"}
        assert set(expenses[0]["splits_json"]) == {user["id"], "shared-member-001"}
        assert all(row["id"] != closed_household.id for row in households)
        assert all(row["label"] != "Closed household evidence" for row in expenses)
        assert [row["event_id"] for row in temporal_decisions] == ["portable-owned-temporal-event"]
        assert temporal_decisions[0]["transaction_id"] == transactions[0]["id"]
        assert [row["id"] for row in forecast_snapshots] == [own_forecast.id]
        assert [row["snapshot_id"] for row in forecast_outcomes] == [own_forecast.id]
        assert [row["decision_id"] for row in recommendation_outcomes] == [recommendation.id]


async def test_portable_export_archive_is_deterministic_for_a_fixed_instant(
    client,
    test_session_factory,
):
    user = await create_user(client, "portable-deterministic")
    instant = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)

    async with test_session_factory() as db:
        first = await build_portable_export(db, user["id"], exported_at=instant)
        first_bytes = first.stream.read()
        first.stream.close()
        second = await build_portable_export(db, user["id"], exported_at=instant)
        second_bytes = second.stream.read()
        second.stream.close()

    assert first_bytes == second_bytes


async def test_portable_export_rejects_cross_user_scope(client, auth_required):
    user, token = await register_user(client, "portable-scope-owner")
    other, _ = await register_user(client, "portable-scope-other")

    response = await client.post(
        f"/api/reports/export/portable?user_id={other['id']}",
        headers=auth_headers(token),
    )

    assert user["id"] != other["id"]
    assert response.status_code == 403
