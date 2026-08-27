from decimal import Decimal
from pathlib import Path

import pytest
from app.services.hdfc_deposit_statement_extractor import (
    LAYOUT_NAME,
    extract_hdfc_deposit_statement,
    is_reviewed_deposit_layout,
)

FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "hdfc_deposit_statement_reviewed.txt"
).read_text(encoding="utf-8")


def test_reviewed_deposit_profile_extracts_identity_rails_and_balances():
    assert is_reviewed_deposit_layout(FIXTURE) is True

    extracted = extract_hdfc_deposit_statement(FIXTURE)

    assert extracted["layout_name"] == LAYOUT_NAME
    assert extracted["account_last4"] == "1234"
    assert extracted["opening_balance"] == Decimal("10000.00")
    assert extracted["closing_balance"] == Decimal("31510.00")
    assert [line["payment_rail"] for line in extracted["lines"]] == [
        "upi",
        "debit_card",
        "atm",
        "transfer",
        "other",
    ]
    assert [line["transaction_type"] for line in extracted["lines"]] == [
        "debit",
        "debit",
        "debit",
        "credit",
        "credit",
    ]
    assert extracted["lines"][-1]["review_outcome"] == "needs_review"


@pytest.mark.parametrize(
    "old,new,error",
    [
        ("| 500.00 | | 9,500.00", "| 500.00 | 5.00 | 9,500.00", "one withdrawal"),
        ("| 500.00 | | 9,500.00", "| 500.00 | | 9,499.00", "does not reconcile"),
        ("XXXXXXXX1234", "XXXXXXXX5678", None),
    ],
)
def test_deposit_profile_fails_closed_or_preserves_verified_identity(old, new, error):
    changed = FIXTURE.replace(old, new, 1)
    if error is None:
        assert extract_hdfc_deposit_statement(changed)["account_last4"] == "5678"
    else:
        with pytest.raises(ValueError, match=error):
            extract_hdfc_deposit_statement(changed)


def test_recognized_free_form_deposit_text_is_not_write_enabled():
    text = """HDFC BANK ACCOUNT STATEMENT
    Account Number XXXXXXXX1234
    Date Narration Withdrawal Deposit Closing Balance
    01/07/2026 UPI SHOP 500.00 9500.00
    """

    assert is_reviewed_deposit_layout(text) is False
    with pytest.raises(ValueError, match="not the reviewed"):
        extract_hdfc_deposit_statement(text)
