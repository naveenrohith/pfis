"""Report data assembly and export helpers."""

from __future__ import annotations

import calendar
import csv
import io
from typing import Any

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.category import Category
from app.models.transaction import Transaction, TransactionType
from app.services.insights_service import InsightsService
from app.services.report_renderer import render_monthly_report_html


async def fetch_monthly_transaction_rows(
    db: AsyncSession,
    user_id: str,
    month: int,
    year: int,
) -> list[Any]:
    """Fetch transaction rows for monthly reports and exports."""
    result = await db.execute(
        select(Transaction, Category.name.label("cat_name"))
        .join(Category, Transaction.category_id == Category.id, isouter=True)
        .where(
            Transaction.user_id == user_id,
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        )
        .order_by(Transaction.transaction_date.asc())
    )
    return list(result.all())


async def fetch_monthly_category_rows(
    db: AsyncSession,
    user_id: str,
    month: int,
    year: int,
) -> list[Any]:
    """Fetch debit category summary rows for a monthly report."""
    result = await db.execute(
        select(
            Category.name,
            Category.icon,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        )
        .join(Category, Transaction.category_id == Category.id, isouter=True)
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.DEBIT,
            Transaction.is_transfer.is_(False),
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        )
        .group_by(Category.name, Category.icon)
        .order_by(func.sum(Transaction.amount).desc())
    )
    return list(result.all())


def build_transactions_csv(txn_rows: list[Any]) -> io.StringIO:
    """Build a CSV export from transaction/category rows."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Date",
            "Merchant",
            "Amount (INR)",
            "Type",
            "Category",
            "Account",
            "Confidence",
            "Reference ID",
        ]
    )

    for txn, cat_name in txn_rows:
        writer.writerow(
            [
                txn.transaction_date.strftime("%Y-%m-%d"),
                txn.merchant_normalized or txn.merchant_raw or "Unknown",
                f"{txn.amount:.2f}",
                txn.transaction_type.value,
                cat_name or "Uncategorized",
                f"**{txn.account_last4}" if txn.account_last4 else "",
                f"{txn.confidence_score:.0%}",
                txn.reference_id or "",
            ]
        )

    output.seek(0)
    return output


async def build_monthly_report_html(
    db: AsyncSession,
    user_id: str,
    month: int,
    year: int,
) -> str:
    """Assemble data and render the monthly report HTML."""
    insights_service = InsightsService(db)
    data = await insights_service.generate_insights(user_id, month, year)
    meta = data["meta"]

    total_spend = meta["total_spend"]
    total_income = meta["total_income"]
    net = total_income - total_spend
    savings_rate = ((total_income - total_spend) / total_income * 100) if total_income > 0 else 0

    return render_monthly_report_html(
        month_name=calendar.month_name[month],
        year=year,
        total_spend=total_spend,
        total_income=total_income,
        net=net,
        savings_rate=savings_rate,
        insights=data["insights"],
        categories=await fetch_monthly_category_rows(db, user_id, month, year),
        txn_rows=await fetch_monthly_transaction_rows(db, user_id, month, year),
        app_version=get_settings().APP_VERSION,
    )
