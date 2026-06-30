"""HTML rendering helpers for PFIS reports."""

from __future__ import annotations

from html import escape
from typing import Any


def _money(value: float) -> str:
    return f"&#8377;{value:,.0f}"


def _safe(value: object, fallback: str = "") -> str:
    text = fallback if value is None else str(value)
    return escape(text, quote=True)


def _render_category_rows(categories: list[Any], total_spend: float) -> str:
    rows = []
    for cat in categories:
        total = float(cat.total)
        pct = (total / total_spend * 100) if total_spend > 0 else 0
        rows.append(
            f"""
        <tr>
            <td>{_safe(cat.icon or "")} {_safe(cat.name, "Uncategorized")}</td>
            <td style="text-align:right;">{_money(total)}</td>
            <td style="text-align:right;">{cat.count}</td>
            <td style="text-align:right;">{pct:.0f}%</td>
        </tr>"""
        )
    return "".join(rows) or (
        '<tr><td colspan="4" style="text-align:center;color:#94a3b8;">No data</td></tr>'
    )


def _render_transaction_rows(txn_rows: list[Any]) -> str:
    rows = []
    for txn, cat_name in txn_rows:
        txn_type = txn.transaction_type.value
        amount_color = "#22c55e" if txn_type == "credit" else "#ef4444"
        sign = "+" if txn_type == "credit" else "-"
        merchant = txn.merchant_normalized or txn.merchant_raw or "Unknown"
        rows.append(
            f"""
        <tr>
            <td>{txn.transaction_date.strftime("%d %b")}</td>
            <td>{_safe(merchant)}</td>
            <td style="text-align:right; color:{amount_color}; font-weight:600;">{sign}{_money(txn.amount)}</td>
            <td>{_safe(cat_name, "-")}</td>
            <td style="text-align:center;">{txn.confidence_score:.0%}</td>
        </tr>"""
        )
    return "".join(rows) or (
        '<tr><td colspan="5" style="text-align:center;color:#94a3b8;">No transactions</td></tr>'
    )


def _render_insights(insights: list[dict[str, Any]]) -> str:
    blocks = []
    for insight in insights:
        severity_color = {
            "info": "#3b82f6",
            "success": "#22c55e",
            "warning": "#f59e0b",
            "danger": "#ef4444",
        }.get(str(insight.get("severity")), "#64748b")
        blocks.append(
            f"""
        <div style="display:flex; gap:10px; padding:10px 12px; border-left:3px solid {severity_color}; background:#f8fafc; border-radius:6px; margin-bottom:8px;">
            <span style="font-size:1.2rem;">{_safe(insight.get("icon"))}</span>
            <div>
                <div style="font-weight:600; font-size:0.9rem;">{_safe(insight.get("title"))}</div>
                <div style="font-size:0.8rem; color:#64748b;">{_safe(insight.get("description"))}</div>
            </div>
        </div>"""
        )
    return "".join(blocks) or '<p style="color:#94a3b8;">No insights available.</p>'


def render_monthly_report_html(
    *,
    month_name: str,
    year: int,
    total_spend: float,
    total_income: float,
    net: float,
    savings_rate: float,
    insights: list[dict[str, Any]],
    categories: list[Any],
    txn_rows: list[Any],
    app_version: str,
) -> str:
    """Render the printable monthly finance report."""
    net_class = "value-green" if net >= 0 else "value-red"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PFIS Monthly Report - {_safe(month_name)} {year}</title>
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
        <button onclick="window.print()" style="padding:8px 18px; background:#3b82f6; color:#fff; border:none; border-radius:6px; font-size:0.85rem; cursor:pointer;">Print / Save PDF</button>
        <button onclick="window.close()" style="padding:8px 18px; background:#e2e8f0; color:#334155; border:none; border-radius:6px; font-size:0.85rem; cursor:pointer;">Back</button>
    </div>

    <h1>Monthly Finance Report</h1>
    <p class="subtitle">{_safe(month_name)} {year} - Generated by PFIS</p>

    <div class="summary-grid">
        <div class="summary-card"><div class="label">Total Spend</div><div class="value value-red">{_money(total_spend)}</div></div>
        <div class="summary-card"><div class="label">Total Income</div><div class="value value-green">{_money(total_income)}</div></div>
        <div class="summary-card"><div class="label">Net Savings</div><div class="value {net_class}">{_money(net)}</div></div>
        <div class="summary-card"><div class="label">Savings Rate</div><div class="value value-purple">{savings_rate:.0f}%</div></div>
    </div>

    <h2>Key Insights</h2>
    {_render_insights(insights)}

    <h2>Category Breakdown</h2>
    <table>
        <thead><tr><th>Category</th><th style="text-align:right;">Amount</th><th style="text-align:right;">Txns</th><th style="text-align:right;">% of Spend</th></tr></thead>
        <tbody>{_render_category_rows(categories, total_spend)}</tbody>
    </table>

    <h2>All Transactions</h2>
    <table>
        <thead><tr><th>Date</th><th>Merchant</th><th style="text-align:right;">Amount</th><th>Category</th><th style="text-align:center;">Conf.</th></tr></thead>
        <tbody>{_render_transaction_rows(txn_rows)}</tbody>
    </table>

    <div class="footer">
        PFIS v{_safe(app_version)} - Personal Finance Intelligence System<br>
        Report generated automatically from email transaction data
    </div>
</body>
</html>"""
