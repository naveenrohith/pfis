"""Prospective daily forecast snapshot and outcome coverage."""

from datetime import date, timedelta

from tests.pytest.helpers import create_user


async def _account(client, user_id: str, suffix: str) -> dict:
    response = await client.post(
        f"/api/accounts?user_id={user_id}",
        json={
            "institution_name": "Forecast Evidence Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": f"****{suffix}",
            "currency": "INR",
        },
    )
    response.raise_for_status()
    return response.json()


async def test_daily_forecast_snapshot_evaluates_later_verified_observation(client):
    user = await create_user(client, "daily-forecast-accountability")
    account = await _account(client, user["id"], "2001")
    today = date.today()
    cutoff = today - timedelta(days=1)

    opening = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 10000,
            "as_of": cutoff.isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    opening.raise_for_status()

    snapshot = await client.post(
        f"/api/accounts/{account['id']}/balance-forecast/snapshots?user_id={user['id']}",
        json={"horizon_days": 1, "cutoff_date": cutoff.isoformat()},
    )
    snapshot.raise_for_status()
    snapshot_body = snapshot.json()
    assert snapshot_body["status"] == "ready"
    assert snapshot_body["cutoff_date"] == cutoff.isoformat()
    assert snapshot_body["points"][-1]["date"] == today.isoformat()

    closing = await client.post(
        f"/api/accounts/{account['id']}/balances?user_id={user['id']}",
        json={
            "amount": 9900,
            "as_of": today.isoformat(),
            "source": "manual",
            "verified": True,
        },
    )
    closing.raise_for_status()

    evaluated = await client.post(
        f"/api/accounts/{account['id']}/balance-forecast/outcomes/evaluate?user_id={user['id']}"
    )
    evaluated.raise_for_status()
    body = evaluated.json()
    assert body["evaluated_count"] == 1
    assert body["pending_count"] == 0
    assert body["mean_absolute_error"] == 100
    assert body["interval_coverage_pct"] == 0
    assert body["median_absolute_percentage_error"] == 1.0
    assert body["calibration_status"] == "insufficient_sample"
    assert body["calibration_thresholds"]["minimum_outcomes"] == 3
    assert body["outcomes"][0]["actual_balance"] == 9900
    assert body["outcomes"][0]["signed_error"] == -100

    repeated = await client.post(
        f"/api/accounts/{account['id']}/balance-forecast/outcomes/evaluate?user_id={user['id']}"
    )
    repeated.raise_for_status()
    assert repeated.json()["evaluated_count"] == 0
    assert repeated.json()["already_evaluated_count"] == 1
