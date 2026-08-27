"""Coverage for the strict issuer-neutral credit-card tabular profile."""

from decimal import Decimal

import pytest
from app.services.generic_credit_card_statement_extractor import (
    extract_generic_credit_card_statement,
    is_reviewed_generic_credit_card_layout,
)
from app.services.statement_detection import detect_statement

from tests.pytest.helpers import create_user

GENERIC_CARD_STATEMENT = """ICICI CREDIT CARD STATEMENT
CREDIT CARD NUMBER: XXXX9911
CURRENCY: INR
STATEMENT PERIOD: 01/08/2026 TO 31/08/2026
STATEMENT DATE: 31/08/2026
PAYMENT DUE DATE: 20/09/2026
TOTAL AMOUNT DUE: INR 10,500.50
MINIMUM PAYMENT DUE: INR 525.03
CREDIT LIMIT: INR 100,000.00
AVAILABLE CREDIT LIMIT: INR 89,499.50
OPENING BALANCE: INR 8,000.00
TRANSACTION DATE | DESCRIPTION | REFERENCE | DEBIT | CREDIT | RUNNING BALANCE
05/08/2026 | AMAZON PURCHASE | REF001 | 3,000.00 | | 11,000.00
10/08/2026 | PAYMENT RECEIVED | PAY001 | | 1,000.00 | 10,000.00
15/08/2026 | MERCHANT REFUND | REF002 | | 100.00 | 9,900.00
20/08/2026 | GST ON FEE | REF003 | 600.50 | | 10,500.50
"""


def test_generic_credit_card_profile_proves_liability_balance_and_events():
    extracted = extract_generic_credit_card_statement(GENERIC_CARD_STATEMENT)

    assert extracted["card_last4"] == "9911"
    assert extracted["currency"] == "INR"
    assert extracted["credit_limit"] == Decimal("100000.00")
    assert extracted["available_credit_limit"] == Decimal("89499.50")
    assert extracted["total_due"] == Decimal("10500.50")
    assert extracted["payments_credits"] == Decimal("1000.00")
    assert extracted["purchases_debits"] == Decimal("3600.50")
    assert [line["transaction_type"] for line in extracted["lines"]] == [
        "debit",
        "credit",
        "refund",
        "debit",
    ]
    assert [line["card_event"] for line in extracted["lines"]] == [
        "purchase",
        "payment",
        "refund",
        "tax",
    ]
    assert is_reviewed_generic_credit_card_layout(GENERIC_CARD_STATEMENT)

    detection = detect_statement(GENERIC_CARD_STATEMENT)
    assert detection.institution is None
    assert detection.product_type == "credit_card"
    assert detection.format_id == "generic-credit-card-tabular-v1"
    assert detection.support_status == "supported"
    assert "reviewed_generic_card_balance_reconciled" in detection.reason_codes


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ("10,500.50", "running balance"),
        ("TOTAL AMOUNT DUE: INR 10,500.51", "closing balance"),
        ("MERCHANT REFUND", "explicitly classified"),
    ],
)
def test_generic_credit_card_profile_rejects_unproven_rows(replacement, message):
    tampered = GENERIC_CARD_STATEMENT
    if replacement == "10,500.50":
        tampered = tampered.replace("600.50 | | 10,500.50", "600.50 | | 10,500.49")
    elif replacement.startswith("TOTAL"):
        tampered = tampered.replace("TOTAL AMOUNT DUE: INR 10,500.50", replacement)
    else:
        tampered = tampered.replace(replacement, "CREDIT ADJUSTMENT")

    with pytest.raises(ValueError, match=message):
        extract_generic_credit_card_statement(tampered)


def test_generic_credit_card_profile_requires_masked_identity_and_exact_directions():
    unmasked = GENERIC_CARD_STATEMENT.replace("XXXX9911", "9911")
    with pytest.raises(ValueError, match="card identity"):
        extract_generic_credit_card_statement(unmasked)

    both_directions = GENERIC_CARD_STATEMENT.replace(
        "3,000.00 | | 11,000.00", "3,000.00 | 1.00 | 11,000.00"
    )
    with pytest.raises(ValueError, match="one debit or credit"):
        extract_generic_credit_card_statement(both_directions)


async def test_auto_import_dispatches_reviewed_generic_credit_card_statement(client):
    user = await create_user(client, "generic-credit-card-import")
    account_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "ICICI Bank",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "********9911",
            "currency": "INR",
        },
    )
    account_response.raise_for_status()
    account = account_response.json()
    payload = {
        "financial_account_id": account["id"],
        "document_fingerprint": "c" * 64,
        "statement_text": GENERIC_CARD_STATEMENT,
    }

    imported = await client.post(f"/api/statements/import/text?user_id={user['id']}", json=payload)
    imported.raise_for_status()
    body = imported.json()
    assert body["product_type"] == "credit_card"
    assert body["detection"]["format_id"] == "generic-credit-card-tabular-v1"
    assert body["detection"]["support_status"] == "supported"
    statement = body["credit_card_statement"]
    assert statement["financial_account_id"] == account["id"]
    assert statement["total_due"] == 10500.5
    assert len(statement["lines"]) == 4
    assert [line["card_event"] for line in statement["lines"]] == [
        "purchase",
        "payment",
        "refund",
        "tax",
    ]
    assert statement["lines"][1]["review_outcome"] == "needs_review"
    assert all(
        statement["lines"][index]["review_outcome"] == "newly_imported" for index in (0, 2, 3)
    )

    repeated = await client.post(f"/api/statements/import/text?user_id={user['id']}", json=payload)
    repeated.raise_for_status()
    assert repeated.json()["credit_card_statement"]["id"] == statement["id"]


async def test_card_payment_candidates_rank_owned_bank_debits_without_mutation(client):
    user = await create_user(client, "card-payment-candidates")
    other = await create_user(client, "card-payment-candidates-other")
    card_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "ICICI Bank",
            "account_type": "credit_card",
            "balance_kind": "liability",
            "masked_number": "********9911",
            "currency": "INR",
        },
    )
    card_response.raise_for_status()
    card = card_response.json()
    bank_response = await client.post(
        f"/api/accounts?user_id={user['id']}",
        json={
            "institution_name": "ICICI Bank Savings",
            "account_type": "bank",
            "balance_kind": "asset",
            "masked_number": "********7788",
            "currency": "INR",
        },
    )
    bank_response.raise_for_status()
    bank = bank_response.json()
    imported = await client.post(
        f"/api/statements/import/text?user_id={user['id']}",
        json={
            "financial_account_id": card["id"],
            "document_fingerprint": "p" * 64,
            "statement_text": GENERIC_CARD_STATEMENT,
        },
    )
    imported.raise_for_status()
    payment_line = imported.json()["credit_card_statement"]["lines"][1]

    candidate_transaction = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 1000,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": "2026-08-10",
            "merchant_raw": "ICICI CREDIT CARD PAYMENT",
            "reference_id": "PAY001",
            "financial_account_id": bank["id"],
        },
    )
    candidate_transaction.raise_for_status()
    noise = await client.post(
        f"/api/transactions/?user_id={user['id']}",
        json={
            "amount": 1000,
            "transaction_type": "debit",
            "transaction_status": "settled",
            "transaction_date": "2026-08-10",
            "merchant_raw": "GROCERY STORE",
            "financial_account_id": bank["id"],
        },
    )
    noise.raise_for_status()

    response = await client.get(
        f"/api/statement-lines/{payment_line['id']}/payment-candidates?user_id={user['id']}"
    )
    response.raise_for_status()
    candidates = response.json()
    assert len(candidates) == 1
    assert candidates[0]["transaction_id"] == candidate_transaction.json()["id"]
    assert candidates[0]["paying_account_id"] == bank["id"]
    assert candidates[0]["match_method"] == "reference"
    assert candidates[0]["confidence"] == 0.99
    assert "statement_reference_match" in candidates[0]["evidence"]
    assert "explicit_card_payment_wording" in candidates[0]["evidence"]

    forbidden = await client.get(
        f"/api/statement-lines/{payment_line['id']}/payment-candidates?user_id={other['id']}"
    )
    assert forbidden.status_code == 404
