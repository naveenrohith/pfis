"""Parser edge case tests — empty bodies, HTML-only, amount vs balance."""

from app.services.parser import patterns
from app.services.parser.bank_parsers import GenericParser, HDFCParser, ICICIParser, SBIParser


def test_parse_email_with_empty_body():
    """Parser handles empty body gracefully."""
    parser = GenericParser()
    result = parser.parse("Alert", "")
    assert result.amount is None
    assert result.confidence_score == 0.0


def test_parse_email_with_html_only():
    """Parser strips HTML and still extracts data."""
    parser = GenericParser()
    html_body = """
    <html><body>
    <p>Dear Customer,</p>
    <p>Rs.1,500.00 has been debited from your account XX1234 on 05-05-2026.</p>
    <p>Available balance: Rs.25,000.00</p>
    </body></html>
    """
    result = parser.parse("Transaction Alert", html_body)
    assert result.amount == 1500.0
    assert result.transaction_type is not None
    assert result.transaction_type.value == "debit"


def test_amount_extraction_prefers_transaction_context():
    """Amount extraction picks transaction amount over balance."""
    text = "Rs.500.00 has been debited from your account. Avl bal: Rs.45,670.00"
    amount = patterns.extract_amount(text)
    assert amount == 500.0


def test_amount_extraction_ignores_standalone_balance():
    """When only a balance is present without debit/credit context, generic fallback is used."""
    text = "Your available balance is Rs.45,670.00 as of today."
    amount = patterns.extract_amount(text)
    # Falls back to generic AMOUNT_PATTERNS, picks 45670
    assert amount == 45670.0


def test_date_extraction_dmy4_format():
    """Date extraction handles dd-mm-yyyy format."""
    from datetime import date

    text = "Transaction on 15-03-2026 at SWIGGY"
    result = patterns.extract_date(text)
    assert result == date(2026, 3, 15)


def test_date_extraction_named_month():
    """Date extraction handles dd Mon yyyy format."""
    from datetime import date

    text = "Transaction on 05 May, 2026 at AMAZON"
    result = patterns.extract_date(text)
    assert result == date(2026, 5, 5)


def test_merchant_extraction_from_at_pattern():
    """Merchant extraction finds 'at MERCHANT' patterns."""
    text = "Rs.500.00 spent at SWIGGY via UPI on 05-05-2026"
    merchant = patterns.extract_merchant(text)
    assert merchant is not None
    assert "SWIGGY" in merchant.upper()


def test_refund_takes_priority_over_credit():
    """Refund detection takes priority over generic credit keywords."""
    text = "Refund of Rs.500.00 has been credited to your account"
    txn_type = patterns.detect_transaction_type(text)
    assert txn_type == "refund"


def test_hdfc_parser_specific_patterns():
    """HDFC parser uses bank-specific patterns."""
    parser = HDFCParser()
    result = parser.parse(
        "HDFC Bank Alert",
        "Rs.1,500.00 has been debited from a/c **5678 on 05-05-26 to VPA payzomato@hdfcbank ZOMATO on 05-05-26",
    )
    assert result.bank == "HDFC"
    assert result.amount == 1500.0
    assert result.account_last4 == "5678"


def test_sbi_parser_specific_patterns():
    """SBI parser extracts from SBI-specific format."""
    parser = SBIParser()
    result = parser.parse(
        "SBI Alert",
        "Your a/c no. XXXXXXXX1234 is debited for Rs.230.00 on 05-05-2026. Ref No 412345678901",
    )
    assert result.bank == "SBI"
    assert result.amount == 230.0
    assert result.account_last4 == "1234"


def test_icici_parser_specific_patterns():
    """ICICI parser extracts from ICICI-specific format."""
    parser = ICICIParser()
    result = parser.parse(
        "ICICI Bank Alert",
        "INR 499.00 has been debited from your ICICI Bank Account XX5678 on 05-May-2026 towards NETFLIX.COM on UPI",
    )
    assert result.bank == "ICICI"
    assert result.amount == 499.0
    assert result.account_last4 == "5678"
