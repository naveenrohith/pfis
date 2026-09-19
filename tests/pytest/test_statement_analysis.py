"""Read-only statement analysis contracts."""

from pathlib import Path

from app.services.statement_analysis import analyze_statement
from app.services.statement_detection import detect_statement

DEPOSIT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "hdfc_deposit_statement_reviewed.txt"
).read_text(encoding="utf-8")


def test_reviewed_deposit_analysis_is_reconciled_and_redacts_identity_tokens():
    detection = detect_statement(DEPOSIT_FIXTURE)

    analysis = analyze_statement(DEPOSIT_FIXTURE, detection)

    assert analysis["status"] == "available"
    assert analysis["source_kind"] == "reviewed_extractor"
    assert analysis["row_count"] == 5
    assert analysis["debit_total"] == 3500.0
    assert analysis["credit_total"] == 25010.0
    assert analysis["rail_totals"] == {
        "atm": 2000.0,
        "debit_card": 1000.0,
        "other": 10.0,
        "transfer": 25000.0,
        "upi": 500.0,
    }
    assert analysis["opening_balance"] == 10000.0
    assert analysis["closing_balance"] == 31510.0
    assert analysis["reconciled"] is True
    assert "XXXXXXXX1234" not in str(analysis)


def test_generic_bank_table_gets_partial_rows_without_write_enablement():
    text = """ICICI BANK ACCOUNT STATEMENT
    ACCOUNT NUMBER XX7788
    DATE DESCRIPTION DEBIT CREDIT BALANCE
    01/08/2026 UPI-MERCHANT-ONE 500.00 0.00 9500.00
    02/08/2026 NEFT-SALARY 0.00 50000.00 59500.00
    """
    detection = detect_statement(text)

    analysis = analyze_statement(text, detection)

    assert detection.support_status == "recognized_not_supported"
    assert analysis["status"] == "partial"
    assert analysis["source_kind"] == "generic_table"
    assert analysis["row_count"] == 2
    assert [line["direction"] for line in analysis["lines"]] == ["debit", "credit"]
    assert [line["payment_rail"] for line in analysis["lines"]] == ["upi", "transfer"]
    assert analysis["debit_total"] == 500.0
    assert analysis["credit_total"] == 50000.0
    assert analysis["reconciled"] is None
    assert "7788" not in str(analysis)


def test_hdfc_recognized_free_form_table_is_analyzed_without_import_claim():
    text = """HDFC BANK LTD ACCOUNT STATEMENT
    ACCOUNT NO: XX0011
    DATE NARRATION CHQ./REF.NO. VALUE DT WITHDRAWAL AMT. DEPOSIT AMT. CLOSING BALANCE
    01/08/2026 UPI-MERCHANT-ONE 01/08/2026 500.00 0.00 9500.00
    """
    detection = detect_statement(text)

    analysis = analyze_statement(text, detection)

    assert detection.support_status == "recognized_not_supported"
    assert analysis["status"] == "partial"
    assert analysis["row_count"] == 1
    assert analysis["lines"][0]["description"] == "UPI-MERCHANT-ONE"
    assert analysis["lines"][0]["direction"] == "debit"


def test_generic_card_preview_keeps_unproven_direction_out_of_totals():
    text = """ICICI BANK CREDIT CARD STATEMENT
    CREDIT CARD NUMBER XXXX9911
    BILLING PERIOD 01/07/2026 - 31/07/2026
    TOTAL AMOUNT DUE 500.00
    MINIMUM PAYMENT 50.00
    PAYMENT DUE DATE 20/08/2026
    CREDIT LIMIT 100000.00
    TRANSACTION DATE TRANSACTION DESCRIPTION AMOUNT
    04/07/2026 DE-IDENTIFIED SHOP 500.00
    05/07/2026 PAYMENT RECEIVED + 300.00
    """
    detection = detect_statement(text)

    analysis = analyze_statement(text, detection)

    assert detection.product_type == "credit_card"
    assert analysis["status"] == "partial"
    assert analysis["row_count"] == 2
    assert [line["direction"] for line in analysis["lines"]] == ["unknown", "credit"]
    assert analysis["debit_total"] == 0.0
    assert analysis["credit_total"] == 300.0


def test_unsupported_statement_remains_signature_only():
    text = "HDFC BANK your monthly statement is ready. Sign in to view it securely."
    detection = detect_statement(text)

    analysis = analyze_statement(text, detection)

    assert analysis["status"] == "signature_only"
    assert analysis["row_count"] == 0
    assert analysis["lines"] == []
