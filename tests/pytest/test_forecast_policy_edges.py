"""Boundary coverage for forecast and card-position policy decisions."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.models.account import FinancialAccount
from app.models.financial_position import CreditCardStatement, StatementImport
from app.services.balance_forecast_service import BalanceForecastService
from app.services.card_due_runway_service import CardDueRunwayService
from app.services.card_position_observation_service import CardPositionObservationService
from app.services.card_utilization_history_service import CardUtilizationHistoryService
from app.services.connectors.base import CardPositionObservation
from app.utils.financial_time import financial_today

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, account_type: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Policy Edge Bank",
            "account_type": account_type,
            "balance_kind": "liability" if account_type == "credit_card" else "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


@pytest.mark.parametrize(
    ("starting_balance", "position_status", "expected"),
    [
        (None, "observed", "needs_anchor"),
        (Decimal("100"), "needs_review", "needs_review"),
        (Decimal("100"), "incomplete", "needs_review"),
        (Decimal("100"), "stale", "needs_review"),
        (Decimal("100"), "needs_observation", "needs_review"),
        (Decimal("100"), "observed", "ready"),
    ],
)
def test_balance_forecast_status_requires_a_trustworthy_anchor(
    starting_balance: Decimal | None, position_status: str, expected: str
):
    assert BalanceForecastService._forecast_status(starting_balance, position_status) == expected


@pytest.mark.parametrize(
    ("activity_count", "history_days", "baseline_enabled", "expected"),
    [
        (0, 180, False, "low"),
        (3, 30, True, "medium"),
        (30, 119, True, "medium"),
        (30, 120, True, "high"),
    ],
)
def test_balance_forecast_data_sufficiency_reflects_history_depth(
    activity_count: int, history_days: int, baseline_enabled: bool, expected: str
):
    assert (
        BalanceForecastService._data_sufficiency(activity_count, history_days, baseline_enabled)
        == expected
    )


def test_balance_forecast_numeric_helpers_keep_optional_values_explicit():
    assert BalanceForecastService._decimal(Decimal("12.345")) == Decimal("12.345")
    assert BalanceForecastService._decimal("12.345") == Decimal("12.345")
    assert BalanceForecastService._rounded_float(Decimal("12.345")) == 12.35
    assert BalanceForecastService._rounded_float(None) is None
    assert BalanceForecastService._required_float(Decimal("12.345")) == 12.35


def test_card_due_scenarios_cover_unavailable_and_lower_band_risk():
    unavailable = CardDueRunwayService._payment_scenarios(
        total_due=Decimal("1000"),
        minimum_due=None,
        due_date=date(2026, 9, 30),
        planned_payment_total=Decimal("250"),
        expected=None,
        low=None,
        high=None,
    )
    assert len(unavailable) == 1
    assert unavailable[0].status == "unavailable"
    assert unavailable[0].planned_payment_applied == 250
    assert unavailable[0].remaining_total_due == 0

    at_risk = CardDueRunwayService._payment_scenarios(
        total_due=Decimal("1000"),
        minimum_due=Decimal("100"),
        due_date=date(2026, 9, 30),
        planned_payment_total=Decimal("250"),
        expected=Decimal("600"),
        low=Decimal("300"),
        high=Decimal("800"),
    )
    by_name = {item.scenario: item for item in at_risk}
    assert by_name["minimum_due"].status == "covered"
    assert by_name["minimum_due"].lower_band_covered is True
    assert by_name["total_due"].status == "at_risk"
    assert by_name["total_due"].expected_cash_gap == 400
    assert by_name["total_due"].lower_band_cash_gap == 700


@pytest.mark.parametrize(
    ("balance", "credit_limit", "target", "expected"),
    [
        (None, Decimal("1000"), Decimal("30"), "unavailable"),
        (Decimal("500"), None, Decimal("30"), "unavailable"),
        (Decimal("500"), Decimal("1000"), None, "within_limit"),
        (Decimal("250"), Decimal("1000"), Decimal("30"), "within_target"),
        (Decimal("500"), Decimal("1000"), Decimal("30"), "over_target"),
        (Decimal("1000"), Decimal("1000"), Decimal("30"), "over_limit"),
    ],
)
def test_card_utilization_point_labels_each_limit_boundary(
    balance: Decimal | None,
    credit_limit: Decimal | None,
    target: Decimal | None,
    expected: str,
):
    point = CardUtilizationHistoryService._point(
        as_of=date(2026, 9, 19),
        basis="issuer_statement",
        statement_id="statement-1",
        balance=balance,
        credit_limit=credit_limit,
        target=target,
        source_transaction_count=2,
        confidence=0.8,
        reason_codes=[],
    )
    assert point.status == expected


def test_card_utilization_trend_handles_history_and_current_cycle_directions():
    point = CardUtilizationHistoryService._point
    first = point(
        as_of=date(2026, 8, 1),
        basis="issuer_statement",
        statement_id="first",
        balance=Decimal("200"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=0,
        confidence=1.0,
        reason_codes=[],
    )
    higher = point(
        as_of=date(2026, 9, 1),
        basis="issuer_statement",
        statement_id="higher",
        balance=Decimal("250"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=0,
        confidence=1.0,
        reason_codes=[],
    )
    lower = point(
        as_of=date(2026, 9, 1),
        basis="issuer_statement",
        statement_id="lower",
        balance=Decimal("150"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=0,
        confidence=1.0,
        reason_codes=[],
    )
    stable = point(
        as_of=date(2026, 9, 1),
        basis="issuer_statement",
        statement_id="stable",
        balance=Decimal("205"),
        credit_limit=Decimal("1000"),
        target=None,
        source_transaction_count=0,
        confidence=1.0,
        reason_codes=[],
    )

    assert CardUtilizationHistoryService._trend([], []) == ("unavailable", "unavailable", None)
    assert CardUtilizationHistoryService._trend([first], []) == (
        "insufficient_history",
        "issuer_statements",
        None,
    )
    assert CardUtilizationHistoryService._trend([first, higher], []) == (
        "worsening",
        "issuer_statements",
        5.0,
    )
    assert CardUtilizationHistoryService._trend([first, lower], []) == (
        "improving",
        "issuer_statements",
        -5.0,
    )
    assert CardUtilizationHistoryService._trend([first, stable], []) == (
        "stable",
        "issuer_statements",
        0.5,
    )
    assert CardUtilizationHistoryService._trend([first], [lower]) == (
        "improving",
        "issuer_to_current_estimate",
        -5.0,
    )


async def test_balance_forecast_marks_cash_shortfall_from_confirmed_commitment(client):
    user = await create_user(client, "forecast-shortfall-edge")
    account = await _account(client, user["id"], "bank", "9401")
    today = date.today()

    anchor = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={"amount": 100, "as_of": today.isoformat(), "verified": True},
    )
    anchor.raise_for_status()
    commitment = await client.post(
        f"/api/commitments?user_id={user['id']}",
        json={
            "label": "Large edge-case obligation",
            "commitment_type": "other",
            "amount": 500,
            "due_date": (today + timedelta(days=1)).isoformat(),
            "financial_account_id": account["id"],
            "confirmed": True,
        },
    )
    commitment.raise_for_status()

    response = await client.get(
        f"/api/accounts/{account['id']}/balance-forecast?user_id={user['id']}&horizon_days=2"
    )
    response.raise_for_status()
    body = response.json()
    shortfall = next(
        item for item in body["points"] if item["date"] == (today + timedelta(days=1)).isoformat()
    )
    assert body["first_shortfall_date"] == (today + timedelta(days=1)).isoformat()
    assert shortfall["risk"] == "shortfall"
    assert shortfall["risk_reasons"] == ["projected_cash_shortfall"]


async def test_balance_forecast_marks_credit_limit_pressure_from_settled_history(
    client, test_session_factory
):
    user = await create_user(client, "forecast-limit-pressure-edge")
    card = await _account(client, user["id"], "credit_card", "9402")
    today = date.today()
    anchor = await client.post(
        f"/api/accounts/{card['id']}/balances?user_id={user['id']}",
        json={"amount": 950, "as_of": today.isoformat(), "source": "statement"},
    )
    anchor.raise_for_status()
    for index in range(3):
        transaction = await client.post(
            f"/api/transactions/?user_id={user['id']}",
            json={
                "amount": 10000,
                "currency": "INR",
                "transaction_type": "debit",
                "transaction_status": "settled",
                "card_event": "purchase",
                "transaction_date": (today - timedelta(days=index + 1)).isoformat(),
                "merchant_raw": f"Pressure purchase {index}",
                "confidence_score": 1.0,
                "financial_account_id": card["id"],
            },
        )
        transaction.raise_for_status()

    async with test_session_factory() as db:
        imported = StatementImport(
            user_id=user["id"],
            financial_account_id=card["id"],
            issuer="EDGE",
            document_fingerprint="f" * 64,
            extractor_version="forecast-policy-edge",
        )
        db.add(imported)
        await db.flush()
        db.add(
            CreditCardStatement(
                user_id=user["id"],
                statement_import_id=imported.id,
                financial_account_id=card["id"],
                statement_date=today,
                period_start=today - timedelta(days=30),
                period_end=today,
                due_date=today + timedelta(days=20),
                total_due=Decimal("950"),
                minimum_due=Decimal("95"),
                credit_limit=Decimal("1000"),
                available_credit_limit=Decimal("50"),
                currency="INR",
            )
        )
        await db.commit()

    response = await client.get(
        f"/api/accounts/{card['id']}/balance-forecast?user_id={user['id']}&horizon_days=2"
    )
    response.raise_for_status()
    body = response.json()
    assert body["balance_kind"] == "liability"
    assert body["historical_activity_count"] == 3
    assert any(point["risk"] == "limit_pressure" for point in body["points"][1:])


async def test_balance_forecast_projects_liability_schedule_rows(client):
    user = await create_user(client, "forecast-liability-schedule-edge")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "Forecast Loan Bank",
            "account_type": "loan",
            "balance_kind": "liability",
            "masked_number": "****9405",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account = account_response.json()
    today = date.today()

    anchor = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={"amount": 5000, "as_of": today.isoformat(), "verified": True},
    )
    anchor.raise_for_status()
    liability = await client.post(
        f"/api/liabilities?user_id={user['id']}",
        json={
            "label": "Forecast loan",
            "liability_type": "loan",
            "financial_account_id": account["id"],
            "outstanding_principal": 5000,
            "monthly_due": 1000,
            "interest_rate": 12,
        },
    )
    liability.raise_for_status()
    schedule = await client.post(
        f"/api/liabilities/{liability.json()['id']}/schedule/confirm?user_id={user['id']}",
        json={
            "source_kind": "statement",
            "items": [
                {
                    "due_date": (today + timedelta(days=2)).isoformat(),
                    "installment_amount": 1000,
                }
            ],
        },
    )
    schedule.raise_for_status()

    response = await client.get(
        f"/api/accounts/{account['id']}/balance-forecast?user_id={user['id']}&horizon_days=3"
    )
    response.raise_for_status()
    body = response.json()
    due_day = next(
        point
        for point in body["points"]
        if point["date"] == (today + timedelta(days=2)).isoformat()
    )

    assert body["balance_kind"] == "liability"
    assert body["event_count"] == 1
    assert body["scheduled_decrease_total"] == 1000
    assert due_day["scheduled_decrease"] == 1000
    assert due_day["evidence_ids"][0].startswith("liability_schedule:")


async def test_card_due_runway_marks_a_past_statement_due_date(client, test_session_factory):
    user = await create_user(client, "due-passed-edge", timezone="UTC")
    card = await _account(client, user["id"], "credit_card", "9403")
    today = financial_today("UTC", now_utc=datetime.now(UTC))
    async with test_session_factory() as db:
        imported = StatementImport(
            user_id=user["id"],
            financial_account_id=card["id"],
            issuer="EDGE",
            document_fingerprint="e" * 64,
            extractor_version="forecast-policy-edge",
        )
        db.add(imported)
        await db.flush()
        db.add(
            CreditCardStatement(
                user_id=user["id"],
                statement_import_id=imported.id,
                financial_account_id=card["id"],
                statement_date=today - timedelta(days=20),
                period_start=today - timedelta(days=50),
                period_end=today - timedelta(days=20),
                due_date=today - timedelta(days=2),
                total_due=Decimal("800"),
                minimum_due=Decimal("80"),
                credit_limit=Decimal("10000"),
                available_credit_limit=Decimal("9200"),
                currency="INR",
            )
        )
        await db.commit()

    response = await client.get(f"/api/cards/{card['id']}/due-runway?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()
    assert body["status"] == "due_passed"
    assert body["days_until_due"] == -2
    assert "settlement status" in " ".join(body["assumptions"])


async def test_card_position_batch_is_idempotent_and_lists_recent_facts(
    client, test_session_factory
):
    user = await create_user(client, "card-position-batch-edge")
    card = await _account(client, user["id"], "credit_card", "9404")
    async with test_session_factory() as db:
        account = await db.get(FinancialAccount, card["id"])
        assert account is not None
        account.connector_account_id = "edge-provider-card"
        await db.commit()

        observed_at = datetime.now(UTC)
        observation = CardPositionObservation(
            financial_account_id=card["id"],
            currency="INR",
            current_outstanding=Decimal("700"),
            billed_due=Decimal("500"),
            pending_amount=Decimal("25"),
            credit_limit=Decimal("10000"),
            available_credit=Decimal("9300"),
            as_of=observed_at.date(),
            source_record_id="edge-position-1",
            observed_at=observed_at,
            source_account_id="edge-provider-card",
            coverage_complete=False,
        )
        service = CardPositionObservationService(db)
        responses = await service.ingest_batch(
            user["id"],
            [observation],
            coverage_complete=False,
            provider_account_ids={card["id"]: "edge-provider-card"},
        )
        assert len(responses) == 1
        assert responses[0].current_outstanding == 700

        repeated = await service.ingest(user["id"], observation)
        assert repeated.id == responses[0].id
        recent = await service.list_recent(user["id"], card["id"], limit=0)
        assert len(recent) == 1
        assert recent[0].source_account_id == "edge-provider-card"
