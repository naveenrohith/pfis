"""Owned account-deletion lifecycle and shared-household tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

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
from app.models.sync import ConnectorAuditEvent
from app.models.transaction import PaymentMethod, Transaction, TransactionType
from app.models.user import User
from app.models.workspace import RecommendationOutcome, RecommendationState
from app.security import encrypt_secret
from app.services import account_deletion_service
from app.services.account_deletion_service import (
    ACCOUNT_DELETION_PRIVATE_TABLES,
    account_deletion_inventory,
)
from app.services.ingestion.activity import tracked_user_ingestion
from sqlalchemy import func, select

from tests.pytest.helpers import auth_headers, register_user


def test_account_deletion_inventory_covers_every_persisted_table():
    inventory = account_deletion_inventory()
    assert set(inventory) == set(Base.metadata.tables)
    assert ACCOUNT_DELETION_PRIVATE_TABLES.isdisjoint(
        {"users", "categories", "merchants", "households", "household_members"}
    )


async def test_account_deletion_removes_private_data_and_preserves_shared_audit(
    client,
    auth_required,
    test_session_factory,
    monkeypatch,
):
    owner, _ = await register_user(client, "delete-owner")
    other, _ = await register_user(client, "delete-other")
    login = await client.post(
        "/api/auth/login",
        json={"email": owner["email"], "password": "Sup3rSecure!"},
    )
    login.raise_for_status()
    csrf = login.cookies.get("pfis_csrf")
    assert csrf
    revoked_tokens = []

    async def revoke(token: str) -> bool:
        revoked_tokens.append(token)
        return True

    monkeypatch.setattr(account_deletion_service, "revoke_google_token", revoke)

    async with test_session_factory() as db:
        category = await db.scalar(select(Category).order_by(Category.name))
        assert category is not None
        raw = RawEmail(
            user_id=owner["id"],
            gmail_message_id="delete-owned-source",
            sender="alerts@bank.test",
            subject="Delete owned source",
            body="Delete owned source body",
            received_at=datetime(2026, 7, 1, tzinfo=UTC),
            processed_flag=True,
        )
        other_raw = RawEmail(
            user_id=other["id"],
            gmail_message_id="delete-other-source",
            sender="other@bank.test",
            subject="Keep other source",
            body="Keep other body",
            received_at=datetime(2026, 7, 1, tzinfo=UTC),
            processed_flag=True,
        )
        db.add_all([raw, other_raw])
        await db.flush()
        db.add(
            Transaction(
                user_id=owner["id"],
                amount=Decimal("125.00"),
                currency="INR",
                transaction_type=TransactionType.DEBIT,
                payment_method=PaymentMethod.UPI,
                merchant_raw="DELETE STORE",
                merchant_normalized="Delete Store",
                category_id=category.id,
                transaction_date=date(2026, 7, 1),
                source_email_id=raw.id,
                fingerprint="delete-owned-transaction",
            )
        )
        db.add(
            GmailAccount(
                user_id=owner["id"],
                google_account_id="delete-google-account",
                access_token_ref=encrypt_secret("delete-access-token"),
                refresh_token_ref=encrypt_secret("delete-refresh-token"),
            )
        )
        db.add(
            TemporalEventDecision(
                user_id=owner["id"],
                event_id="delete-owned-temporal-event",
                event_kind="bill",
                source_type="bill",
                source_id="delete-owned-bill",
                occurrence_date=date(2026, 7, 2),
                event_ruleset_version="pfis-temporal-events-1",
                decision="cancelled",
                note="Delete this owned decision",
            )
        )
        forecast = CashFlowForecastSnapshot(
            user_id=owner["id"],
            target_month=7,
            target_year=2026,
            cutoff_date=date(2026, 7, 1),
            forecast_ruleset_version="pfis-cash-flow-5",
            projected_spend=Decimal("100.00"),
            projected_net=Decimal("-100.00"),
            projected_range_low=Decimal("80.00"),
            projected_range_high=Decimal("120.00"),
            expected_income=Decimal("0.00"),
            temporal_expected_income=Decimal("0.00"),
            temporal_expected_outflows=Decimal("100.00"),
            temporal_conflicted_outflows=Decimal("0.00"),
            confidence=Decimal("0.600"),
            data_sufficiency="medium",
            evidence_json="[]",
            assumptions_json="[]",
        )
        db.add(forecast)
        await db.flush()
        db.add(
            CashFlowForecastOutcome(
                user_id=owner["id"],
                snapshot_id=forecast.id,
                outcome_ruleset_version="pfis-cash-flow-outcome-1",
                actual_income=Decimal("0.00"),
                actual_spend=Decimal("110.00"),
                actual_net=Decimal("-110.00"),
                spend_absolute_error=Decimal("10.00"),
                spend_absolute_percentage_error=Decimal("9.091"),
                spend_range_covered=True,
            )
        )
        recommendation = RecommendationState(
            user_id=owner["id"],
            recommendation_id="delete-owned-recommendation",
            state="accepted",
            recommendation_type="review",
            title="Delete recommendation decision",
            target="review",
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
                user_id=owner["id"],
                decision_id=recommendation.id,
                outcome="helped",
                actual_impact_value=Decimal("1.00"),
                actual_impact_unit="records",
                outcome_ruleset_version="pfis-recommendation-outcome-1",
            )
        )

        shared = Household(owner_user_id=owner["id"], name="Shared household")
        sole = Household(owner_user_id=owner["id"], name="Sole household")
        db.add_all([shared, sole])
        await db.flush()
        db.add_all(
            [
                HouseholdMember(
                    household_id=shared.id,
                    user_id=owner["id"],
                    role="owner",
                ),
                HouseholdMember(
                    household_id=shared.id,
                    user_id=other["id"],
                    role="member",
                ),
                HouseholdMember(
                    household_id=sole.id,
                    user_id=owner["id"],
                    role="owner",
                ),
                HouseholdExpense(
                    household_id=shared.id,
                    created_by_user_id=owner["id"],
                    payer_user_id=owner["id"],
                    label="Shared historical expense",
                    amount=Decimal("100.00"),
                    currency="INR",
                    expense_date=date(2026, 7, 2),
                    splits_json=json.dumps({owner["id"]: "50.00", other["id"]: "50.00"}),
                ),
                HouseholdSettlement(
                    household_id=shared.id,
                    created_by_user_id=owner["id"],
                    from_user_id=owner["id"],
                    to_user_id=other["id"],
                    amount=Decimal("50.00"),
                    currency="INR",
                    settlement_date=date(2026, 7, 3),
                    status="planned",
                ),
            ]
        )
        await db.commit()
        shared_id = shared.id
        sole_id = sole.id

    response = await client.request(
        "DELETE",
        f"/api/users/{owner['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": f"DELETE {owner['email']}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "deleted"
    assert payload["provider_revocation"] == "revoked"
    assert payload["households_deleted"] == 1
    assert payload["household_ownership_transferred"] == 1
    assert payload["household_memberships_closed"] == 1
    assert revoked_tokens == ["delete-refresh-token"]
    assert "pfis_session=" in response.headers.get("set-cookie", "")

    assert (await client.get("/api/auth/session")).status_code == 401
    async with test_session_factory() as db:
        tombstone = await db.get(User, owner["id"])
        assert tombstone is not None
        assert tombstone.is_active is False
        assert tombstone.deleted_at is not None
        assert tombstone.deletion_started_at is None
        assert tombstone.email == f"deleted-{owner['id']}@deleted.invalid"
        assert tombstone.name == "Deleted participant"
        assert tombstone.password_hash is None

        assert (
            await db.scalar(select(func.count(RawEmail.id)).where(RawEmail.user_id == owner["id"]))
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(Transaction.id)).where(Transaction.user_id == owner["id"])
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(AuthSession.id)).where(AuthSession.user_id == owner["id"])
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(GmailAccount.id)).where(GmailAccount.user_id == owner["id"])
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(TemporalEventDecision.id)).where(
                    TemporalEventDecision.user_id == owner["id"]
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(CashFlowForecastSnapshot.id)).where(
                    CashFlowForecastSnapshot.user_id == owner["id"]
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(CashFlowForecastOutcome.id)).where(
                    CashFlowForecastOutcome.user_id == owner["id"]
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(RecommendationState.id)).where(
                    RecommendationState.user_id == owner["id"]
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count(RecommendationOutcome.id)).where(
                    RecommendationOutcome.user_id == owner["id"]
                )
            )
            == 0
        )
        assert (
            await db.scalar(select(func.count(RawEmail.id)).where(RawEmail.user_id == other["id"]))
            == 1
        )

        retained = await db.get(Household, shared_id)
        assert retained is not None
        assert retained.owner_user_id == other["id"]
        assert await db.get(Household, sole_id) is None
        former = await db.scalar(
            select(HouseholdMember).where(
                HouseholdMember.household_id == shared_id,
                HouseholdMember.user_id == owner["id"],
            )
        )
        assert former is not None
        assert former.left_at is not None
        settlement = await db.scalar(
            select(HouseholdSettlement).where(HouseholdSettlement.household_id == shared_id)
        )
        assert settlement is not None
        assert settlement.status == "cancelled"
        expense_count = await db.scalar(
            select(func.count(HouseholdExpense.id)).where(
                HouseholdExpense.household_id == shared_id
            )
        )
        assert expense_count == 1

        audit = await db.scalar(
            select(ConnectorAuditEvent).where(
                ConnectorAuditEvent.user_id == owner["id"],
                ConnectorAuditEvent.event_type == "account_deleted",
            )
        )
        assert audit is not None
        assert "delete-refresh-token" not in audit.payload_json
        assert json.loads(audit.payload_json)["household_ownership_transferred"] == 1


async def test_account_deletion_requires_recent_cookie_auth_and_exact_confirmation(
    client,
    auth_required,
    test_session_factory,
):
    user, token = await register_user(client, "delete-guards")
    csrf = client.cookies.get("pfis_csrf")
    assert csrf

    mismatch = await client.request(
        "DELETE",
        f"/api/users/{user['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": "DELETE the wrong account"},
    )
    assert mismatch.status_code == 422

    async with test_session_factory() as db:
        sessions = list(
            await db.scalars(select(AuthSession).where(AuthSession.user_id == user["id"]))
        )
        assert sessions
        for session in sessions:
            session.created_at = datetime.now(UTC) - timedelta(minutes=16)
        await db.commit()

    stale = await client.request(
        "DELETE",
        f"/api/users/{user['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": f"DELETE {user['email']}"},
    )
    assert stale.status_code == 403
    assert "Sign in again" in stale.text

    client.cookies.clear()
    bearer_only = await client.request(
        "DELETE",
        f"/api/users/{user['id']}",
        headers=auth_headers(token),
        json={"confirmation": f"DELETE {user['email']}"},
    )
    assert bearer_only.status_code == 403

    async with test_session_factory() as db:
        active = await db.get(User, user["id"])
        assert active is not None
        assert active.is_active is True
        assert active.deleted_at is None


async def test_account_deletion_continues_when_provider_revocation_is_unavailable(
    client,
    auth_required,
    test_session_factory,
    monkeypatch,
    caplog,
):
    user, _ = await register_user(client, "delete-provider-failure")
    csrf = client.cookies.get("pfis_csrf")
    assert csrf
    secret = "provider-failure-refresh-secret"
    async with test_session_factory() as db:
        db.add(
            GmailAccount(
                user_id=user["id"],
                google_account_id="delete-provider-failure-google",
                refresh_token_ref=encrypt_secret(secret),
            )
        )
        await db.commit()

    async def fail_revocation(_token: str) -> bool:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(account_deletion_service, "revoke_google_token", fail_revocation)
    response = await client.request(
        "DELETE",
        f"/api/users/{user['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": f"DELETE {user['email']}"},
    )

    assert response.status_code == 200
    assert response.json()["provider_revocation"] == "unconfirmed"
    assert secret not in caplog.text
    async with test_session_factory() as db:
        tombstone = await db.get(User, user["id"])
        assert tombstone is not None and tombstone.is_active is False
        assert (
            await db.scalar(
                select(func.count(GmailAccount.id)).where(GmailAccount.user_id == user["id"])
            )
            == 0
        )


async def test_account_deletion_rejects_cross_user_scope(
    client,
    auth_required,
    test_session_factory,
):
    owner, _ = await register_user(client, "delete-scope-owner")
    other, _ = await register_user(client, "delete-scope-other")
    login = await client.post(
        "/api/auth/login",
        json={"email": owner["email"], "password": "Sup3rSecure!"},
    )
    login.raise_for_status()
    csrf = login.cookies.get("pfis_csrf")
    assert csrf

    response = await client.request(
        "DELETE",
        f"/api/users/{other['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": f"DELETE {other['email']}"},
    )

    assert response.status_code == 403
    async with test_session_factory() as db:
        other_user = await db.get(User, other["id"])
        assert other_user is not None
        assert other_user.is_active is True


async def test_account_deletion_cancels_an_inflight_manual_ingestion(
    client,
    auth_required,
    test_session_factory,
):
    user, _ = await register_user(client, "delete-live-ingestion")
    csrf = client.cookies.get("pfis_csrf")
    assert csrf
    started = asyncio.Event()

    async def live_ingestion() -> None:
        async with (
            test_session_factory() as db,
            tracked_user_ingestion(db, user["id"]),
        ):
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(live_ingestion())
    await asyncio.wait_for(started.wait(), timeout=2)

    response = await client.request(
        "DELETE",
        f"/api/users/{user['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": f"DELETE {user['email']}"},
    )

    assert response.status_code == 200, response.text
    assert task.cancelled()
    async with test_session_factory() as db:
        tombstone = await db.get(User, user["id"])
        assert tombstone is not None
        assert tombstone.deleted_at is not None
        assert tombstone.deletion_started_at is None
