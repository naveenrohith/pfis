"""Reports and CSV export tests."""

from datetime import date

import pytest
from app.services.report_renderer import render_monthly_report_html
from app.services.report_service import build_monthly_report_html, build_transactions_csv
from httpx import AsyncClient

from tests.pytest.helpers import create_user


@pytest.mark.asyncio
async def test_csv_export_has_correct_headers(client: AsyncClient):
    """CSV export contains the expected header row."""
    user = await create_user(client)
    cat_resp = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = cat_resp.json()

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


def test_monthly_report_renderer_escapes_server_controlled_text():
    """Report renderer escapes fields that may originate from stored data."""

    class Txn:
        transaction_date = __import__("datetime").date(2026, 5, 1)
        transaction_type = type("TxnType", (), {"value": "debit"})()
        merchant_normalized = "<script>alert('merchant')</script>"
        merchant_raw = None
        amount = 99.0
        confidence_score = 0.91

    html = render_monthly_report_html(
        month_name="May",
        year=2026,
        total_spend=99.0,
        total_income=0.0,
        net=-99.0,
        savings_rate=0.0,
        insights=[
            {
                "severity": "info",
                "icon": "<icon>",
                "title": "<b>Unsafe</b>",
                "description": "Injected <script>alert('x')</script>",
            }
        ],
        categories=[],
        txn_rows=[(Txn(), "<img src=x>")],
        app_version="0.1.0",
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x&gt;" in html


def test_build_transactions_csv_formats_rows():
    """CSV service helper renders exported transaction rows consistently."""

    class TxnType:
        value = "debit"

    class Txn:
        transaction_date = date(2026, 5, 9)
        merchant_normalized = "Bookmyshow"
        merchant_raw = "BOOKMYSHOW"
        amount = 750.0
        transaction_type = TxnType()
        account_last4 = "1234"
        confidence_score = 0.91
        reference_id = "REF123"

    output = build_transactions_csv([(Txn(), "Entertainment")])

    csv_text = output.getvalue()
    assert "Date,Merchant,Amount (INR),Type,Category,Account,Confidence,Reference ID" in csv_text
    assert "2026-05-09,Bookmyshow,750.00,debit,Entertainment,**1234,91%,REF123" in csv_text


@pytest.mark.asyncio
async def test_build_monthly_report_html_assembles_service_data(client, test_session_factory):
    """Monthly report service assembles DB data and renderer output."""
    user = await create_user(client, "reportservice")
    categories_response = await client.get(f"/api/categories/?user_id={user['id']}")
    categories = categories_response.json()

    create_response = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 800.0,
            "currency": "INR",
            "transaction_type": "debit",
            "merchant_raw": "BOOKMYSHOW",
            "merchant_normalized": "Bookmyshow",
            "category_id": categories[0]["id"],
            "transaction_date": "2026-05-09",
            "confidence_score": 0.91,
            "reference_id": "REPORT_SERVICE_REF",
        },
    )
    create_response.raise_for_status()

    async with test_session_factory() as db:
        html = await build_monthly_report_html(db, user["id"], 5, 2026)

    assert "Monthly Finance Report" in html
    assert "Bookmyshow" in html
    assert "REPORT_SERVICE_REF" not in html
