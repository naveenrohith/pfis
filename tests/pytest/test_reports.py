"""Reports and CSV export tests."""

import pytest
from httpx import AsyncClient

from tests.pytest.helpers import create_user


@pytest.mark.asyncio
async def test_csv_export_has_correct_headers(client: AsyncClient):
    """CSV export contains the expected header row."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    from datetime import date

    today = date.today()

    # Create a transaction so CSV has data
    await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 1500.0,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": "SWIGGY",
            "merchant_normalized": "Swiggy",
            "category_id": categories[0]["id"],
            "transaction_date": today.isoformat(),
            "confidence_score": 0.92,
            "reference_id": f"CSV_TEST_{today.isoformat()}",
        },
    )

    resp = await client.get(
        f"/api/reports/export/csv?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")

    content = resp.text
    lines = content.strip().split("\n")
    assert len(lines) >= 2  # header + at least 1 data row
    header = lines[0].lower()
    assert "date" in header
    assert "amount" in header
    assert "merchant" in header


@pytest.mark.asyncio
async def test_csv_export_contains_transaction_data(client: AsyncClient):
    """CSV export includes the transaction data rows."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

    from datetime import date

    today = date.today()

    await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 2500.0,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": "AMAZON",
            "merchant_normalized": "Amazon",
            "category_id": categories[0]["id"],
            "transaction_date": today.isoformat(),
            "confidence_score": 0.88,
            "reference_id": f"AMZ_CSV_{today.isoformat()}",
        },
    )

    resp = await client.get(
        f"/api/reports/export/csv?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    content = resp.text
    assert "Amazon" in content or "AMAZON" in content
    assert "2500" in content


@pytest.mark.asyncio
async def test_monthly_report_html_renders(client: AsyncClient):
    """Monthly report endpoint returns HTML content."""
    user = await create_user(client)

    from datetime import date

    today = date.today()

    resp = await client.get(
        f"/api/reports/monthly?user_id={user['id']}&month={today.month}&year={today.year}"
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Monthly Financial Report" in resp.text or "report" in resp.text.lower()


@pytest.mark.asyncio
async def test_csv_export_empty_month(client: AsyncClient):
    """CSV export for month with no transactions returns headers only."""
    user = await create_user(client)

    resp = await client.get(f"/api/reports/export/csv?user_id={user['id']}&month=1&year=2021")
    assert resp.status_code == 200
    content = resp.text
    lines = content.strip().split("\n")
    # Should have at least the header row
    assert len(lines) >= 1
