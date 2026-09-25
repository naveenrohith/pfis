"""Financial Horizon route coverage."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from app.schemas.balance_forecast import (
    AccountBalanceForecastPoint,
    AccountBalanceForecastResponse,
)
from app.schemas.financial_position import AccountPositionResponse, CashPlanResponse
from app.services.card_due_runway_service import CardDueRunwayService
from app.services.card_portfolio_upcoming_service import CardPortfolioUpcomingStateService
from app.services.financial_horizon_service import FinancialHorizonService
from httpx import AsyncClient

from tests.pytest.helpers import auth_headers, create_user, register_user


async def _account(client: AsyncClient, user_id: str, suffix: str, *, headers=None) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        headers=headers,
        json={
            "institution_name": "Horizon Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def _verified_balance(
    client: AsyncClient, user_id: str, account_id: str, amount: int, as_of: date
) -> None:
    response = await client.post(
        f"/api/accounts/{account_id}/balances?user_id={user_id}",
        json={"amount": amount, "as_of": as_of.isoformat(), "verified": True},
    )
    response.raise_for_status()


async def test_financial_horizon_success_composes_existing_read_models(client: AsyncClient):
    user = await create_user(client, "horizon-success")
    account = await _account(client, user["id"], "8101")
    today = date.today()
    await _verified_balance(client, user["id"], account["id"], 10000, today)

    plan = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (today + timedelta(days=10)).isoformat(),
            "next_income_amount": 5000,
        },
    )
    plan.raise_for_status()
    commitment = await client.post(
        f"/api/commitments?user_id={user['id']}",
        json={
            "label": "Rent",
            "commitment_type": "rent",
            "amount": 2000,
            "due_date": (today + timedelta(days=3)).isoformat(),
            "confirmed": True,
        },
    )
    commitment.raise_for_status()

    response = await client.get(f"/api/horizon?user_id={user['id']}&days=30")
    response.raise_for_status()
    body = response.json()

    assert body["ruleset_version"] == "pfis-horizon-1"
    assert body["status"] == "healthy"
    assert body["horizon_days"] == 30
    assert body["current_position"]["verified"]["assets"] == 10000
    assert body["current_position"]["provisional"]["assets"] == 0
    assert body["current_position"]["safe_to_spend"] == 8000
    assert body["lowest_projected_point"] is not None
    event_sources = {event["source"] for event in body["events"]}
    assert {"cash_plan", "commitment"} <= event_sources
    rent = next(event for event in body["events"] if event["label"] == "Rent")
    assert rent["status"] == "verified"
    assert rent["confidence"] >= 0.9


async def test_financial_horizon_low_data_fails_closed(client: AsyncClient):
    user = await create_user(client, "horizon-low-data")

    response = await client.get(f"/api/horizon?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "low_data"
    assert body["current_position"]["verified"]["assets"] == 0
    assert "active_financial_account" in body["missing_evidence"]
    assert body["lowest_projected_point"] is None


async def test_financial_horizon_marks_stale_sources(client: AsyncClient):
    user = await create_user(client, "horizon-stale")
    account = await _account(client, user["id"], "8102")
    old_day = date.today() - timedelta(days=14)
    await _verified_balance(client, user["id"], account["id"], 7000, old_day)
    plan = await client.put(
        f"/api/cash-plan?user_id={user['id']}",
        json={
            "primary_financial_account_id": account["id"],
            "next_income_date": (date.today() + timedelta(days=8)).isoformat(),
            "next_income_amount": 3000,
        },
    )
    plan.raise_for_status()

    response = await client.get(f"/api/horizon?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["status"] == "stale"
    assert any(signal["code"] == "stale_source" for signal in body["risk_signals"])
    assert any("stale" in code for code in body["source_health"][0]["reason_codes"])


@pytest.mark.asyncio
async def test_financial_horizon_enforces_user_scope(client: AsyncClient, auth_required):
    owner, owner_token = await register_user(client, "horizon-owner")
    _, attacker_token = await register_user(client, "horizon-attacker")
    client.cookies.clear()
    await _account(client, owner["id"], "8103", headers=auth_headers(owner_token))

    forbidden = await client.get(
        f"/api/horizon?user_id={owner['id']}", headers=auth_headers(attacker_token)
    )
    assert forbidden.status_code == 403

    anonymous = await client.get(f"/api/horizon?user_id={owner['id']}")
    assert anonymous.status_code == 401

    scoped = await client.get("/api/horizon", headers=auth_headers(owner_token))
    assert scoped.status_code == 200


async def test_financial_horizon_days_bounds_are_validated(client: AsyncClient):
    user = await create_user(client, "horizon-bounds")

    too_short = await client.get(f"/api/horizon?user_id={user['id']}&days=6")
    too_long = await client.get(f"/api/horizon?user_id={user['id']}&days=91")

    assert too_short.status_code == 422
    assert too_long.status_code == 422


async def test_financial_horizon_no_forecast_fallback_keeps_lowest_point_null(
    client: AsyncClient,
):
    user = await create_user(client, "horizon-no-forecast")
    account = await _account(client, user["id"], "8104")
    await _verified_balance(client, user["id"], account["id"], 5000, date.today())

    response = await client.get(f"/api/horizon?user_id={user['id']}")
    response.raise_for_status()
    body = response.json()

    assert body["lowest_projected_point"] is None
    assert body["lowest_projected_point_unavailable_reason"] == "cash_plan_primary_account_required"
    assert "balance_forecast" in body["missing_evidence"]
    assert body["status"] == "low_data"


def _position(
    account_id: str,
    *,
    balance_kind: str = "asset",
    verified_balance: float | None = 1000.0,
    estimated_balance: float | None = None,
    status: str = "observed",
    position_status: str = "observed",
    coverage_status: str = "fresh",
    coverage_complete: bool | None = True,
    reason_codes: list[str] | None = None,
    position_reason_codes: list[str] | None = None,
) -> AccountPositionResponse:
    return AccountPositionResponse(
        financial_account_id=account_id,
        account_id=account_id,
        product_type="bank",
        currency="INR",
        balance_kind=balance_kind,
        verified_balance=verified_balance,
        balance_as_of=date(2026, 9, 25),
        balance_source="manual",
        observed_source="manual",
        coverage_complete=coverage_complete,
        coverage_status=coverage_status,
        estimated_balance=estimated_balance,
        estimated_as_of=date(2026, 9, 25) if estimated_balance is not None else None,
        position_status=position_status,
        position_confidence=0.8,
        position_reason_codes=position_reason_codes or [],
        status=status,
        confidence=0.8,
        reason_codes=reason_codes or [],
        inflows=0.0,
        outflows=0.0,
        rail_breakdown={},
        reconciliation_status="reconciled",
        unexplained_amount=None,
        review_count=0,
    )


def _cash_plan(
    *,
    primary_account_id: str = "acct-primary",
    flexible_money: float | None = 100.0,
    readiness: str = "ready",
) -> CashPlanResponse:
    return CashPlanResponse(
        primary_financial_account_id=primary_account_id,
        currency="INR",
        verified_balance=1000.0,
        balance_as_of=date(2026, 9, 25),
        planning_balance=1000.0,
        planning_balance_as_of=date(2026, 9, 25),
        balance_basis="verified",
        next_income_date=date(2026, 10, 1),
        confirmed_commitments=[],
        commitment_total=0.0,
        approved_reserve_total=0.0,
        flexible_money=flexible_money,
        daily_allowance=None,
        readiness=readiness,
        assumptions=[],
    )


def _forecast(
    *,
    status: str = "ready",
    points: list[AccountBalanceForecastPoint] | None = None,
    lowest_expected_balance: float | None = 500.0,
    lowest_expected_date: date | None = date(2026, 9, 27),
    data_sufficiency: str = "medium",
    event_count: int = 1,
) -> AccountBalanceForecastResponse:
    return AccountBalanceForecastResponse(
        financial_account_id="acct-primary",
        account_type="bank",
        institution_name="Horizon Bank",
        masked_number="****1234",
        currency="INR",
        balance_kind="asset",
        status=status,
        horizon_start=date(2026, 9, 25),
        horizon_end=date(2026, 10, 25),
        horizon_days=30,
        starting_balance=1000.0,
        starting_balance_as_of=date(2026, 9, 25),
        starting_balance_basis="observed",
        expected_ending_balance=700.0,
        expected_change=-300.0,
        lowest_expected_balance=lowest_expected_balance,
        lowest_expected_date=lowest_expected_date,
        first_shortfall_date=None,
        event_count=event_count,
        historical_days=20,
        historical_activity_count=5,
        coverage_status="fresh",
        position_status="observed",
        position_confidence=0.8,
        confidence=0.7,
        data_sufficiency=data_sufficiency,
        points=points or [],
    )


def test_financial_horizon_helper_branches_qualify_sources_risks_and_statuses():
    service = FinancialHorizonService(db=None)  # type: ignore[arg-type]
    positions = [
        _position("stale", status="stale", reason_codes=["old_anchor"]),
        _position("review", status="needs_review", position_reason_codes=["unreviewed_activity"]),
        _position("incomplete", coverage_complete=False, coverage_status="fresh"),
        _position(
            "liability",
            balance_kind="liability",
            verified_balance=-2000.0,
            estimated_balance=-1800.0,
            status="estimated",
            position_status="estimated",
            coverage_status="due",
        ),
    ]

    source_health = service._source_health(positions)
    assert [item.status for item in source_health] == [
        "overdue",
        "review",
        "incomplete",
        "due",
    ]
    assert "unreviewed_activity" in source_health[1].reason_codes

    risks = service._base_risks(
        _cash_plan(flexible_money=-250.0), positions, source_health, as_of=date(2026, 9, 25)
    )
    assert any(risk.code == "unfunded_commitment" and risk.severity == "danger" for risk in risks)
    assert any(risk.code == "stale_source" for risk in risks)
    assert (
        service._status(
            missing_evidence=[],
            risk_signals=risks,
            source_health=source_health,
            cash_plan=_cash_plan(),
            forecast=_forecast(),
        )
        == "deficit"
    )

    stale_status = service._status(
        missing_evidence=[],
        risk_signals=[risk for risk in risks if risk.severity != "danger"],
        source_health=source_health,
        cash_plan=_cash_plan(),
        forecast=_forecast(),
    )
    assert stale_status == "stale"

    assert (
        service._status(
            missing_evidence=["cash_plan_needs_next_income"],
            risk_signals=[],
            source_health=[],
            cash_plan=_cash_plan(readiness="needs_next_income"),
            forecast=_forecast(),
        )
        == "attention"
    )

    current = service._current_position("INR", positions, _cash_plan(flexible_money=-250.0))
    assert current.verified.assets == 3000.0
    assert current.verified.liabilities == -2000.0
    assert current.provisional.liabilities == -1800.0
    assert current.safe_to_spend == -250.0


def test_financial_horizon_lowest_point_and_missing_evidence_reasons():
    service = FinancialHorizonService(db=None)  # type: ignore[arg-type]
    assert service._lowest_point(None) == (None, "cash_plan_primary_account_required")
    assert service._lowest_point(_forecast(status="needs_review")) == (
        None,
        "forecast_needs_review",
    )
    assert service._lowest_point(
        _forecast(points=[], lowest_expected_balance=None, lowest_expected_date=None)
    ) == (None, "forecast_path_unavailable")
    point = AccountBalanceForecastPoint(
        date=date(2026, 9, 27),
        expected_balance=500.0,
        low_balance=350.0,
        high_balance=650.0,
    )
    assert service._lowest_point(_forecast(points=[point], data_sufficiency="low", event_count=0))[
        1
    ] == ("forecast_low_data")

    lowest, reason = service._lowest_point(_forecast(points=[point]))
    assert reason is None
    assert lowest is not None
    assert lowest.low_balance == 350.0
    assert lowest.high_balance == 650.0

    missing = service._missing_evidence(
        accounts=[],
        positions=[],
        cash_plan=_cash_plan(primary_account_id="", readiness="needs_verified_balance"),
        forecast=_forecast(status="needs_anchor"),
        lowest_reason="forecast_needs_anchor",
    )
    assert missing == [
        "active_financial_account",
        "verified_balance_position",
        "cash_plan_primary_account",
        "cash_plan_needs_verified_balance",
        "balance_forecast_needs_anchor",
        "lowest_point_forecast_needs_anchor",
    ]


@pytest.mark.asyncio
async def test_financial_horizon_card_due_risk_maps_runway_statuses(monkeypatch):
    service = FinancialHorizonService(db=None)  # type: ignore[arg-type]
    runway = SimpleNamespace(
        status="at_risk",
        due_date=date(2026, 10, 5),
        lower_band_cash_gap=250.0,
        expected_cash_gap=300.0,
        total_due=1200.0,
    )

    async def fake_runway(_service, user_id: str, account_id: str):
        assert (user_id, account_id) == ("user-1", "card-1")
        return runway

    monkeypatch.setattr(CardDueRunwayService, "runway", fake_runway)
    at_risk = await service._card_due_risk("user-1", "card-1")
    assert at_risk is not None
    assert at_risk.code == "card_due_shortfall"
    assert at_risk.severity == "danger"
    assert at_risk.amount == 250.0

    runway.status = "needs_payment_account"
    needs_account = await service._card_due_risk("user-1", "card-1")
    assert needs_account is not None
    assert needs_account.code == "unfunded_commitment"
    assert needs_account.severity == "warning"
    assert needs_account.amount == 1200.0

    runway.status = "covered"
    assert await service._card_due_risk("user-1", "card-1") is None

    async def missing_runway(_service, user_id: str, account_id: str):
        raise LookupError("missing card")

    monkeypatch.setattr(CardDueRunwayService, "runway", missing_runway)
    assert await service._card_due_risk("user-1", "card-1") is None


@pytest.mark.asyncio
async def test_financial_horizon_events_combine_planned_obligations_and_card_calendar(
    monkeypatch,
):
    service = FinancialHorizonService(db=None)  # type: ignore[arg-type]
    as_of = date(2026, 9, 25)
    horizon_end = date(2026, 10, 25)

    class FakePositionService:
        async def cash_plan(self, user_id: str):
            assert user_id == "user-1"
            return _cash_plan(
                primary_account_id="acct-primary",
                readiness="ready",
            ).model_copy(update={"next_income_date": date(2026, 10, 1)})

        async def list_commitments(self, user_id: str):
            return [
                SimpleNamespace(
                    id="rent",
                    is_active=True,
                    due_date=date(2026, 10, 3),
                    label="Rent",
                    amount=2500.0,
                    confirmed=True,
                    source_kind="statement",
                ),
                SimpleNamespace(
                    id="inactive",
                    is_active=False,
                    due_date=date(2026, 10, 4),
                    label="Inactive",
                    amount=999.0,
                    confirmed=False,
                    source_kind="manual",
                ),
            ]

        async def liability_overview(self, user_id: str):
            return SimpleNamespace(
                liabilities=[
                    SimpleNamespace(
                        id="loan",
                        next_due_date=date(2026, 10, 5),
                        monthly_due=1500.0,
                        label="Loan EMI",
                        complete_schedule=False,
                        source_confidence=None,
                        schedule_status="estimated",
                    ),
                    SimpleNamespace(
                        id="no-due",
                        next_due_date=None,
                        monthly_due=100.0,
                        label="No due",
                    ),
                ]
            )

    async def fake_upcoming(_service, user_id: str):
        assert user_id == "user-1"
        return SimpleNamespace(
            events=[
                SimpleNamespace(
                    id="due",
                    date=date(2026, 10, 6),
                    label="Card due",
                    amount=900.0,
                    event_type="payment_due",
                    status="observed",
                    confidence=0.8,
                    reason_codes=["issuer_due"],
                ),
                SimpleNamespace(
                    id="renewal",
                    date=date(2026, 10, 7),
                    label="Card renewal",
                    amount=None,
                    event_type="renewal",
                    status="planned",
                    confidence=0.7,
                    reason_codes=["calendar_event"],
                ),
                SimpleNamespace(
                    id="outside",
                    date=date(2026, 11, 1),
                    label="Outside",
                    amount=1.0,
                    event_type="payment_due",
                    status="planned",
                    confidence=0.5,
                    reason_codes=[],
                ),
            ]
        )

    monkeypatch.setattr(CardPortfolioUpcomingStateService, "upcoming", fake_upcoming)

    events = await service._events(
        "user-1",
        as_of=as_of,
        horizon_end=horizon_end,
        position_service=FakePositionService(),
    )

    by_label = {event.label: event for event in events}
    assert set(by_label) == {
        "Confirmed next income",
        "Rent",
        "Loan EMI",
        "Card due",
        "Card renewal",
    }
    assert by_label["Rent"].status == "verified"
    assert by_label["Rent"].confidence == 0.98
    assert by_label["Loan EMI"].status == "provisional"
    assert by_label["Loan EMI"].confidence == 0.72
    assert by_label["Card due"].direction == "out"
    assert by_label["Card due"].status == "verified"
    assert by_label["Card renewal"].direction == "neutral"
