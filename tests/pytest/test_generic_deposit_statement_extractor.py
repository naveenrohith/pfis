"""Coverage for the issuer-neutral, reconciled bank-statement profile."""

from datetime import date

import pytest
from app.models.financial_position import DepositStatementLineReviewDecision
from app.models.temporal_history import TemporalSourceSnapshot
from app.services.generic_deposit_statement_extractor import (
    extract_generic_deposit_statement,
)
from app.services.statement_analysis import analyze_statement
from app.services.statement_detection import detect_statement
from sqlalchemy import func, select

from tests.pytest.helpers import create_user

GENERIC_BANK_STATEMENT = """ICICI BANK ACCOUNT STATEMENT
ACCOUNT NUMBER: XXXXXXXX7788
STATEMENT PERIOD: 01/08/2026 TO 03/08/2026
OPENING BALANCE: INR 10,000.00
DATE | DESCRIPTION | REFERENCE | VALUE DATE | DEBIT | CREDIT | BALANCE
01/08/2026 | UPI/DR/123/GROCER/OKICICI | UPI123 | 01/08/2026 | 500.00 | | 9,500.00
02/08/2026 | POS DEBIT CARD SUPERMARKET | POS123 | 02/08/2026 | 1,000.00 | | 8,500.00
03/08/2026 | NEFT CR-SALARY | N123 | 03/08/2026 | | 25,000.00 | 33,500.00
"""

GENERIC_FIXED_WIDTH_STATEMENT = """AXIS BANK ACCOUNT STATEMENT
ACCOUNT NO: XXXX7788
PERIOD: 01-08-2026 TO 03-08-2026
OPENING BALANCE: INR 10,000.00
DATE DESCRIPTION WITHDRAWAL DEPOSIT BALANCE
01-08-2026 UPI/DR/123/GROCER 500.00 0.00 9,500.00
02-08-2026 POS DEBIT CARD SUPERMARKET 1,000.00 0.00 8,500.00
03-08-2026 NEFT CR-SALARY 0.00 25,000.00 33,500.00
"""

GENERIC_UNKNOWN_RAIL_STATEMENT = """ICICI BANK ACCOUNT STATEMENT
ACCOUNT NUMBER: XXXXXXXX7788
STATEMENT PERIOD: 01/08/2026 TO 04/08/2026
OPENING BALANCE: INR 10,000.00
DATE | DESCRIPTION | REFERENCE | VALUE DATE | DEBIT | CREDIT | BALANCE
01/08/2026 | UPI/DR/123/GROCER/OKICICI | UPI123 | 01/08/2026 | 500.00 | | 9,500.00
02/08/2026 | POS DEBIT CARD SUPERMARKET | POS123 | 02/08/2026 | 1,000.00 | | 8,500.00
03/08/2026 | CASH DEPOSIT COUNTER | CASH123 | 03/08/2026 | | 25,000.00 | 33,500.00
04/08/2026 | CHEQUE CLEARING CREDIT | CHQ123 | 04/08/2026 | | 2,000.00 | 35,500.00
"""


def test_generic_deposit_profile_requires_and_proves_running_balance():
    extracted = extract_generic_deposit_statement(GENERIC_BANK_STATEMENT)

    assert extracted["account_last4"] == "7788"
    assert extracted["period_start"] == date(2026, 8, 1)
    assert extracted["period_end"] == date(2026, 8, 3)
    assert extracted["opening_balance"] == 10_000
    assert extracted["closing_balance"] == 33_500
    assert [line["payment_rail"] for line in extracted["lines"]] == [
        "upi",
        "debit_card",
        "transfer",
    ]
    assert all(line["review_outcome"] == "ready_to_import" for line in extracted["lines"])

    detection = detect_statement(GENERIC_BANK_STATEMENT)
    assert detection.institution is None
    assert detection.product_type == "deposit_account"
    assert detection.format_id == "generic-deposit-tabular-v1"
    assert detection.support_status == "supported"

    analysis = analyze_statement(GENERIC_BANK_STATEMENT, detection)
    assert analysis["status"] == "available"
    assert analysis["reconciled"] is True
    assert analysis["row_count"] == 3
    assert analysis["debit_total"] == 1500
    assert analysis["credit_total"] == 25_000
    assert "7788" not in str(analysis)


def test_generic_deposit_profile_rejects_running_balance_drift():
    tampered = GENERIC_BANK_STATEMENT.replace("33,500.00", "33,499.99")

    with pytest.raises(ValueError, match="running balance"):
        extract_generic_deposit_statement(tampered)


def test_generic_deposit_profile_accepts_unambiguous_fixed_width_rows():
    extracted = extract_generic_deposit_statement(GENERIC_FIXED_WIDTH_STATEMENT)

    assert extracted["account_last4"] == "7788"
    assert extracted["closing_balance"] == 33_500
    assert [line["transaction_type"] for line in extracted["lines"]] == [
        "debit",
        "debit",
        "credit",
    ]


async def test_auto_import_dispatches_reviewed_generic_bank_statement(client):
    user = await create_user(client, "generic-bank-statement-import")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "ICICI Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********7788",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account = account_response.json()
    payload = {
        "financial_account_id": account["id"],
        "document_fingerprint": "g" * 64,
        "statement_text": GENERIC_BANK_STATEMENT,
    }

    imported = await client.post(f"/api/statements/import/text?user_id={user['id']}", json=payload)
    imported.raise_for_status()
    body = imported.json()

    assert body["product_type"] == "deposit_account"
    assert body["detection"]["support_status"] == "supported"
    assert body["detection"]["format_id"] == "generic-deposit-tabular-v1"
    statement = body["deposit_account_statement"]
    assert statement["opening_balance"] == 10_000
    assert statement["closing_balance"] == 33_500
    assert statement["imported_transaction_count"] == 3
    assert statement["review_count"] == 0
    assert [line["payment_rail"] for line in statement["lines"]] == [
        "upi",
        "debit_card",
        "transfer",
    ]

    repeated = await client.post(f"/api/statements/import/text?user_id={user['id']}", json=payload)
    repeated.raise_for_status()
    assert repeated.json()["deposit_account_statement"]["id"] == statement["id"]


async def test_unknown_deposit_rows_have_owned_review_import_and_ignore_flow(
    client, test_session_factory
):
    user = await create_user(client, "generic-bank-statement-review")
    other = await create_user(client, "generic-bank-statement-review-other")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "ICICI Bank",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********7788",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account = account_response.json()
    imported = await client.post(
        f"/api/statements/import/text?user_id={user['id']}",
        json={
            "financial_account_id": account["id"],
            "document_fingerprint": "u" * 64,
            "statement_text": GENERIC_UNKNOWN_RAIL_STATEMENT,
        },
    )
    imported.raise_for_status()
    statement = imported.json()["deposit_account_statement"]
    assert statement["imported_transaction_count"] == 2
    assert statement["review_count"] == 2

    review = await client.get(f"/api/review/deposit-statement-lines?user_id={user['id']}")
    review.raise_for_status()
    items = review.json()
    assert len(items) == 2
    assert {item["payment_rail"] for item in items} == {"other"}
    assert all(item["financial_account_id"] == account["id"] for item in items)
    first_line_id, second_line_id = (item["id"] for item in items)

    forbidden = await client.patch(
        f"/api/deposit-statement-lines/{first_line_id}/review?user_id={other['id']}",
        json={"decision": "import", "payment_rail": "transfer"},
    )
    assert forbidden.status_code == 404

    missing_rail = await client.patch(
        f"/api/deposit-statement-lines/{first_line_id}/review?user_id={user['id']}",
        json={"decision": "import"},
    )
    assert missing_rail.status_code == 422

    classified = await client.patch(
        f"/api/deposit-statement-lines/{first_line_id}/review?user_id={user['id']}",
        json={"decision": "import", "payment_rail": "transfer", "note": "Reviewed"},
    )
    classified.raise_for_status()
    classified_body = classified.json()
    assert classified_body["new_outcome"] == "newly_imported"
    assert classified_body["payment_rail"] == "transfer"
    assert classified_body["created_transaction_id"]

    repeated = await client.patch(
        f"/api/deposit-statement-lines/{first_line_id}/review?user_id={user['id']}",
        json={"decision": "import", "payment_rail": "transfer"},
    )
    repeated.raise_for_status()
    assert repeated.json()["created_transaction_id"] == classified_body["created_transaction_id"]

    ignored = await client.patch(
        f"/api/deposit-statement-lines/{second_line_id}/review?user_id={user['id']}",
        json={"decision": "ignore", "note": "Unsupported cheque evidence"},
    )
    ignored.raise_for_status()
    assert ignored.json()["new_outcome"] == "ignored_by_rule"
    assert ignored.json()["payment_rail"] == "other"

    remaining = await client.get(f"/api/review/deposit-statement-lines?user_id={user['id']}")
    remaining.raise_for_status()
    assert remaining.json() == []

    async with test_session_factory() as db:
        decision_count = await db.scalar(
            select(func.count(DepositStatementLineReviewDecision.id)).where(
                DepositStatementLineReviewDecision.user_id == user["id"]
            )
        )
        snapshot_count = await db.scalar(
            select(func.count(TemporalSourceSnapshot.id)).where(
                TemporalSourceSnapshot.user_id == user["id"],
                TemporalSourceSnapshot.source_type == "deposit_statement_line",
            )
        )
    assert decision_count == 2
    assert snapshot_count == 6
