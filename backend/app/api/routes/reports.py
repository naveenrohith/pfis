"""
Reports & Export Routes — Phase 6
CSV export and monthly report generation.
"""

import io
import csv
import logging
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.transaction import Transaction, TransactionType
from app.models.category import Category
from app.models.user import User
from app.security import get_current_user_optional, resolve_user_scope
from app.services.insights_service import InsightsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/export/csv")
async def export_csv(
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Export transactions as CSV for the given month.
    Returns a downloadable CSV file.
    """
    user_id = resolve_user_scope(user_id, current_user)
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
    rows = result.all()

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Merchant", "Amount (₹)", "Type", "Category",
        "Account", "Confidence", "Reference ID",
    ])

    for txn, cat_name in rows:
        writer.writerow([
            txn.transaction_date.strftime("%Y-%m-%d"),
            txn.merchant_normalized or txn.merchant_raw or "Unknown",
            f"{txn.amount:.2f}",
            txn.transaction_type.value,
            cat_name or "Uncategorized",
            f"••{txn.account_last4}" if txn.account_last4 else "",
            f"{txn.confidence_score:.0%}",
            txn.reference_id or "",
        ])

    output.seek(0)
    filename = f"pfis_transactions_{year}-{month:02d}.csv"

    logger.info(f"CSV export: {len(rows)} transactions for {year}-{month:02d}")

    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/monthly", response_class=HTMLResponse)
async def monthly_report(
    user_id: str = Query(...),
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2030),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a printable monthly financial report as HTML.
    Can be printed to PDF from the browser.
    """
    user_id = resolve_user_scope(user_id, current_user)
    import calendar

    month_name = calendar.month_name[month]

    # Get insights (reuse the insights service)
    svc = InsightsService(db)
    data = await svc.generate_insights(user_id, month, year)

    meta = data["meta"]
    insights = data["insights"]
    daily_trend = data["daily_trend"]
    recurring = data["recurring_payments"]

    # Get transactions
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
    txn_rows = result.all()

    # Category breakdown
    cat_result = await db.execute(
        select(
            Category.name, Category.icon,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        )
        .join(Category, Transaction.category_id == Category.id, isouter=True)
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == TransactionType.DEBIT,
            extract("month", Transaction.transaction_date) == month,
            extract("year", Transaction.transaction_date) == year,
        )
        .group_by(Category.name, Category.icon)
        .order_by(func.sum(Transaction.amount).desc())
    )
    categories = cat_result.all()

    total_spend = meta["total_spend"]
    total_income = meta["total_income"]
    net = total_income - total_spend
    savings_rate = ((total_income - total_spend) / total_income * 100) if total_income > 0 else 0

    # Build category rows
    cat_html = ""
    for cat in categories:
        pct = (float(cat.total) / total_spend * 100) if total_spend > 0 else 0
        cat_html += f"""
        <tr>
            <td>{cat.icon or '📦'} {cat.name or 'Uncategorized'}</td>
            <td style="text-align:right;">₹{float(cat.total):,.0f}</td>
            <td style="text-align:right;">{cat.count}</td>
            <td style="text-align:right;">{pct:.0f}%</td>
        </tr>"""

    # Build transaction rows
    txn_html = ""
    for txn, cat_name in txn_rows:
        txn_type = txn.transaction_type.value
        amount_color = "#22c55e" if txn_type == "credit" else "#ef4444"
        sign = "+" if txn_type == "credit" else "-"
        txn_html += f"""
        <tr>
            <td>{txn.transaction_date.strftime('%d %b')}</td>
            <td>{txn.merchant_normalized or txn.merchant_raw or 'Unknown'}</td>
            <td style="text-align:right; color:{amount_color}; font-weight:600;">{sign}₹{txn.amount:,.0f}</td>
            <td>{cat_name or '—'}</td>
            <td style="text-align:center;">{txn.confidence_score:.0%}</td>
        </tr>"""

    # Build insights list
    insights_html = ""
    for ins in insights:
        severity_color = {"info": "#3b82f6", "success": "#22c55e", "warning": "#f59e0b", "danger": "#ef4444"}.get(ins["severity"], "#64748b")
        insights_html += f"""
        <div style="display:flex; gap:10px; padding:10px 12px; border-left:3px solid {severity_color}; background:#f8fafc; border-radius:6px; margin-bottom:8px;">
            <span style="font-size:1.2rem;">{ins['icon']}</span>
            <div>
                <div style="font-weight:600; font-size:0.9rem;">{ins['title']}</div>
                <div style="font-size:0.8rem; color:#64748b;">{ins['description']}</div>
            </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PFIS Monthly Report — {month_name} {year}</title>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family: 'Segoe UI', -apple-system, sans-serif; color:#1e293b; background:#fff; padding:40px; max-width:900px; margin:0 auto; line-height:1.5; }}
        h1 {{ font-size:1.6rem; margin-bottom:4px; color:#0f172a; }}
        h2 {{ font-size:1.1rem; margin:28px 0 12px; color:#334155; border-bottom:2px solid #e2e8f0; padding-bottom:6px; }}
        .subtitle {{ color:#64748b; font-size:0.85rem; margin-bottom:24px; }}
        .summary-grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin:20px 0 28px; }}
        .summary-card {{ border:1px solid #e2e8f0; border-radius:10px; padding:16px; text-align:center; }}
        .summary-card .label {{ font-size:0.72rem; text-transform:uppercase; letter-spacing:0.05em; color:#64748b; font-weight:600; }}
        .summary-card .value {{ font-size:1.4rem; font-weight:700; margin-top:4px; }}
        .value-red {{ color:#ef4444; }}
        .value-green {{ color:#22c55e; }}
        .value-purple {{ color:#8b5cf6; }}
        .value-blue {{ color:#3b82f6; }}
        table {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
        th {{ background:#f1f5f9; text-align:left; padding:8px 10px; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.04em; color:#64748b; font-weight:700; border-bottom:2px solid #e2e8f0; }}
        td {{ padding:8px 10px; border-bottom:1px solid #f1f5f9; }}
        tr:hover td {{ background:#f8fafc; }}
        .footer {{ margin-top:32px; text-align:center; color:#94a3b8; font-size:0.75rem; border-top:1px solid #e2e8f0; padding-top:16px; }}
        @media print {{
            body {{ padding:20px; }}
            .no-print {{ display:none; }}
            .summary-card {{ border:1px solid #ccc; }}
        }}
    </style>
</head>
<body>
    <div class="no-print" style="margin-bottom:20px; display:flex; gap:10px;">
        <button onclick="window.print()" style="padding:8px 18px; background:#3b82f6; color:#fff; border:none; border-radius:6px; font-size:0.85rem; cursor:pointer;">🖨️ Print / Save PDF</button>
        <button onclick="window.close()" style="padding:8px 18px; background:#e2e8f0; color:#334155; border:none; border-radius:6px; font-size:0.85rem; cursor:pointer;">← Back</button>
    </div>

    <h1>💰 Monthly Finance Report</h1>
    <p class="subtitle">{month_name} {year} • Generated by PFIS</p>

    <div class="summary-grid">
        <div class="summary-card">
            <div class="label">Total Spend</div>
            <div class="value value-red">₹{total_spend:,.0f}</div>
        </div>
        <div class="summary-card">
            <div class="label">Total Income</div>
            <div class="value value-green">₹{total_income:,.0f}</div>
        </div>
        <div class="summary-card">
            <div class="label">Net Savings</div>
            <div class="value {'value-green' if net >= 0 else 'value-red'}">₹{net:,.0f}</div>
        </div>
        <div class="summary-card">
            <div class="label">Savings Rate</div>
            <div class="value value-purple">{savings_rate:.0f}%</div>
        </div>
    </div>

    <h2>🧠 Key Insights</h2>
    {insights_html if insights_html else '<p style="color:#94a3b8;">No insights available.</p>'}

    <h2>📊 Category Breakdown</h2>
    <table>
        <thead><tr><th>Category</th><th style="text-align:right;">Amount</th><th style="text-align:right;">Txns</th><th style="text-align:right;">% of Spend</th></tr></thead>
        <tbody>{cat_html if cat_html else '<tr><td colspan="4" style="text-align:center;color:#94a3b8;">No data</td></tr>'}</tbody>
    </table>

    <h2>💳 All Transactions</h2>
    <table>
        <thead><tr><th>Date</th><th>Merchant</th><th style="text-align:right;">Amount</th><th>Category</th><th style="text-align:center;">Conf.</th></tr></thead>
        <tbody>{txn_html if txn_html else '<tr><td colspan="5" style="text-align:center;color:#94a3b8;">No transactions</td></tr>'}</tbody>
    </table>

    <div class="footer">
        PFIS v0.1.0 — Personal Finance Intelligence System<br>
        Report generated automatically from email transaction data
    </div>
</body>
</html>"""

    return HTMLResponse(content=html)
