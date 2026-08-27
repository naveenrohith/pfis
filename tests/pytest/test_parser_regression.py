"""Regression tests for parser accuracy and merchant inference edge cases."""

# pyright: reportMissingImports=false

from __future__ import annotations

from datetime import date

import pytest
from app.services.gmail.demo_data import SAMPLE_EMAILS
from app.services.gmail.email_filter import EmailType, classify_email
from app.services.parser.normalizer import infer_merchant_from_text
from app.services.parser.registry import get_parser_registry


@pytest.mark.parametrize(
    "email_index, expected_type, expected_merchant, min_confidence",
    [
        (0, "debit", "UPI TRANSFER", 0.8),
        (2, "credit", "NEFT CREDIT", 0.8),
        (6, "debit", "SWIGGY", 1.0),
        (11, "debit", "FLIPKART INTERNET", 1.0),
        (14, "refund", "AMAZON PAY", 1.0),
    ],
)
def test_parser_regression_on_known_formats(
    email_index, expected_type, expected_merchant, min_confidence
):
    registry = get_parser_registry()
    email = SAMPLE_EMAILS[email_index]

    result = registry.parse_email(email["sender"], email["subject"], email["body"])

    assert result.is_valid is True
    assert result.transaction_type.value == expected_type
    assert result.merchant_raw == expected_merchant
    assert result.confidence_score >= min_confidence


@pytest.mark.parametrize(
    "sender, subject, body, expected",
    [
        (
            "alerts@hdfcbank.net",
            "HDFC Bank Alert",
            (
                "Rs.1,500.00 has been debited from a/c **5678 on 05-05-26 "
                "to VPA payzomato@hdfcbank ZOMATO on 05-05-26"
            ),
            {
                "bank": "HDFC",
                "amount": 1500.0,
                "transaction_type": "debit",
                "merchant_raw": "ZOMATO",
                "date": date(2026, 5, 5),
                "account_last4": "5678",
                "confidence_score": 1.0,
            },
        ),
        (
            "alerts@sbi.co.in",
            "SBI Alert",
            (
                "Your a/c no. XXXXXXXX1234 is debited for Rs.230.00 on 05-05-2026. "
                "Ref No 412345678901"
            ),
            {
                "bank": "SBI",
                "amount": 230.0,
                "transaction_type": "debit",
                "merchant_raw": "BANK DEBIT",
                "date": date(2026, 5, 5),
                "account_last4": "1234",
                "confidence_score": 0.8,
            },
        ),
        (
            "alerts@icicibank.com",
            "ICICI Bank Alert",
            (
                "INR 499.00 has been debited from your ICICI Bank Account XX5678 "
                "on 05-May-2026 towards NETFLIX.COM on UPI"
            ),
            {
                "bank": "ICICI",
                "amount": 499.0,
                "transaction_type": "debit",
                "merchant_raw": "NETFLIX",
                "date": date(2026, 5, 5),
                "account_last4": "5678",
                "confidence_score": 1.0,
            },
        ),
        (
            "alerts@axisbank.com",
            "Axis Bank Debit Card Transaction",
            (
                "INR 1,500.00 spent on your Axis Bank Debit Card ending 9012 "
                "at BESCOM BANGALORE on 03-05-2026."
            ),
            {
                "bank": "AXIS",
                "amount": 1500.0,
                "transaction_type": "debit",
                "merchant_raw": "BESCOM BANGALORE",
                "date": date(2026, 5, 3),
                "account_last4": "9012",
                "confidence_score": 1.0,
            },
        ),
    ],
)
def test_parser_fixtures_for_supported_bank_and_fallback_formats(sender, subject, body, expected):
    registry = get_parser_registry()

    result = registry.parse_email(sender, subject, body)

    assert result.is_valid is True
    assert result.bank == expected["bank"]
    assert result.amount == expected["amount"]
    assert result.transaction_type.value == expected["transaction_type"]
    assert result.merchant_raw == expected["merchant_raw"]
    assert result.date == expected["date"]
    assert result.account_last4 == expected["account_last4"]
    assert result.confidence_score >= expected["confidence_score"]


def test_unknown_sender_uses_generic_parser_fallback():
    registry = get_parser_registry()

    result = registry.parse_email(
        "alerts@example-payments.test",
        "Payment successful",
        "Payment of Rs.750.00 to BOOKMYSHOW via UPI on 07-05-2026. Ref No: 555555123456.",
    )

    assert result.is_valid is True
    assert result.bank == "GENERIC"
    assert result.amount == 750.0
    assert result.transaction_type.value == "debit"
    assert result.merchant_raw == "BOOKMYSHOW"
    assert result.date == date(2026, 5, 7)
    assert result.confidence_score >= 1.0


def test_low_confidence_valid_parse_is_explicitly_pinned():
    registry = get_parser_registry()

    result = registry.parse_email(
        "alerts@example-payments.test",
        "Debit alert",
        "Rs.99.00 has been debited.",
    )

    assert result.is_valid is True
    assert result.amount == 99.0
    assert result.transaction_type.value == "debit"
    assert result.merchant_raw == "BANK DEBIT"
    assert result.merchant_source == "generic"
    assert result.confidence_score == 0.6


@pytest.mark.parametrize(
    "sender, subject, body, expected_type, expected_bank",
    [
        (
            "alerts@hdfcbank.net",
            "HDFC Bank OTP",
            "Your OTP for online transaction is 4567. Do not share it.",
            EmailType.OTP,
            "HDFC",
        ),
        (
            "alerts@icicibank.com",
            "Exclusive Offer",
            "Congratulations, limited time offer for a pre-approved loan. Apply now.",
            EmailType.PROMOTION,
            "ICICI",
        ),
        (
            "alerts@hdfcbank.net",
            "View: Account update for your HDFC Bank A/c",
            "The available balance in your account ending XX1441 is Rs. INR 8,795.88.",
            EmailType.IGNORE,
            "HDFC",
        ),
        (
            "alerts@sbi.co.in",
            "SBI Account Statement",
            "Your monthly statement is now available for your account.",
            EmailType.STATEMENT,
            "SBI",
        ),
        (
            "someone@example.com",
            "Payment received",
            "Payment of Rs.500.00 received from RAVI by UPI.",
            EmailType.TRANSACTION,
            "UNKNOWN",
        ),
    ],
)
def test_email_classification_baseline_for_pipeline_skip_and_fallback_paths(
    sender, subject, body, expected_type, expected_bank
):
    email_type, bank_name, confidence = classify_email(sender, subject, body)

    assert email_type == expected_type
    assert bank_name == expected_bank
    assert 0.0 <= confidence <= 1.0


def test_parser_extracts_upi_handle_merchants():
    registry = get_parser_registry()
    subject = "ICICI UPI"
    body = (
        "Dear Customer, your ICICI Bank Acct XX5678 has been debited with INR 999.00 "
        "on 06-05-2026 towards UPI-ZOMATO-order@icici-ICIC. UPI Ref: 412399999991."
    )

    result = registry.parse_email("alerts@icicibank.com", subject, body)

    assert result.is_valid is True
    assert result.merchant_raw == "ZOMATO"
    assert result.confidence_score >= 1.0


def test_icici_credit_does_not_treat_the_owned_account_as_a_merchant():
    result = get_parser_registry().parse_email(
        "alerts@icicibank.com",
        "ICICI Credit",
        (
            "INR 2,500.00 credited to your Account XX5678 from UPI "
            "Ref 412345678914 on 09-May-2026."
        ),
    )

    assert result.transaction_type.value == "credit"
    assert result.merchant_raw == "UPI CREDIT"


def test_icici_card_used_language_establishes_debit_direction():
    result = get_parser_registry().parse_email(
        "creditcards@icicibank.com",
        "ICICI Card Alert",
        (
            "Your ICICI Bank Credit Card XX1234 has been used for Rs.1,299.00 "
            "at AMAZON on 10-May-2026."
        ),
    )

    assert result.transaction_type.value == "debit"
    assert result.payment_method == "credit_card"


def test_generic_parser_keeps_payment_wrappers_out_of_counterparties():
    pay_later = get_parser_registry().parse_email(
        "noreply@lazypay.in",
        "Pay Later transaction",
        "Payment of Rs.560.00 to SAMPLE DELIVERY using Pay Later on 23-05-2026.",
    )
    wallet_refund = get_parser_registry().parse_email(
        "noreply@paytm.com",
        "Refund credited",
        "Refund of Rs.185.00 has been credited to your wallet on 25-05-2026.",
    )

    assert pay_later.merchant_raw == "SAMPLE DELIVERY"
    assert wallet_refund.merchant_raw == "WALLET REFUND"


def test_generic_parser_separates_taxi_text_from_tax_and_atm_from_merchant():
    taxi = get_parser_registry().parse_email(
        "alerts@example-payments.test",
        "Wallet payment",
        "Payment of Rs.210.00 to SAMPLE TAXI using wallet on 30-05-2026.",
    )
    atm = get_parser_registry().parse_email(
        "alerts@example-payments.test",
        "ATM withdrawal",
        "Rs.3,000.00 has been withdrawn at ATM on 29-05-2026.",
    )

    assert taxi.merchant_raw == "SAMPLE TAXI"
    assert taxi.card_event == "none"
    assert atm.merchant_raw == "ATM cash withdrawal"
    assert atm.payment_rail == "atm"


def test_email_filter_ignores_balance_snapshots_and_application_updates():
    balance_type, _, _ = classify_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.net>",
        "View: Account update for your HDFC Bank A/c",
        (
            "Dear Customer, the available balance in your account ending XX1441 is "
            "Rs. INR 8,795.88 as of 23-MAR-26. For real-time balance updates, "
            "call us at 1800 270 3333. "
            "Thank you for banking with us!"
        ),
    )
    application_type, _, _ = classify_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.net>",
        "Your HDFC Bank Credit Card application reference no. D26C14116855S0AE is approved!",
        "Your HDFC Bank Credit Card application reference no. D26C14116855S0AE is approved.",
    )
    password_reset_type, _, _ = classify_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.net>",
        "View: Account update for your HDFC Bank A/c",
        "You have successfully reset your NetBanking password via HDFC Bank Online Banking.",
    )
    chat_banking_type, _, _ = classify_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.net>",
        "HDFC Bank ChatBanking Registration Successful",
        "Successful completion of your HDFC Bank ChatBanking registration.",
    )
    account_update_type, _, _ = classify_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.net>",
        "View: Account update for your HDFC Bank A/c",
        "Your mobile number and email ID have been successfully updated in our records.",
    )

    assert balance_type == EmailType.IGNORE
    assert application_type == EmailType.IGNORE
    assert password_reset_type == EmailType.IGNORE
    assert chat_banking_type == EmailType.IGNORE
    assert account_update_type == EmailType.IGNORE


@pytest.mark.parametrize(
    "sender, subject, body",
    [
        (
            "Tata Starbucks <news@members.sbuxin.com>",
            "Don't Miss out on Our Holiday Magic.",
            "Tata Starbucks Holiday delights! Grab a free reusable cup with your next purchase.",
        ),
        (
            "HDFC Bank Offers <offers@mailers.hdfcbank.bank.in>",
            "Rs.1000 voucher is waiting on Credit Card xx4349",
            "Tap for more details. Your Rs.1000 voucher is waiting. Redeem your reward now.",
        ),
        (
            "pdfFiller <mail@marketing.pdffiller.example>",
            "Send docs via USPS directly from pdfFiller",
            "Get all your document tasks done. Buy now and claim your free trial today.",
        ),
    ],
)
def test_email_filter_rejects_marketing_from_non_bank_senders(sender, subject, body):
    email_type, _, _ = classify_email(sender, subject, body)
    assert email_type == EmailType.PROMOTION


def test_email_filter_ignores_finance_newsletters_without_money_movement():
    email_type, _, _ = classify_email(
        "Groww Digest <noreply@digest.groww.in>",
        "What is adjusted EBITDA?",
        "Learn how a Rs. 5,000 investment can grow over time after a payment is received. Read the latest market update.",
    )

    assert email_type == EmailType.IGNORE


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        (
            "Planned System Maintenance: Service Impact Details",
            (
                "UPI transactions can be carried out up to applicable limits. "
                "Rs 5,000 will be kept aside for debit card usage while services are unavailable."
            ),
        ),
        (
            "Your IndiGo Itinerary - SAMPLE",
            (
                "PNR/Booking Ref: SAMPLE Status CONFIRMED. Payment Status Approved. "
                "Passenger itinerary and flight details."
            ),
        ),
    ],
)
def test_email_filter_rejects_service_notices_and_travel_documents_with_amount_words(subject, body):
    email_type, _, _ = classify_email("notices@example.test", subject, body)
    assert email_type == EmailType.IGNORE


def test_email_filter_does_not_treat_purchase_study_link_as_money_movement():
    email_type, _, _ = classify_email(
        "Prolific Team <no-reply@prolific.com>",
        "New Prolific study: Preference for Purchase-II",
        "A new research study is available. Open the study link to participate.",
    )

    assert email_type == EmailType.IGNORE


def test_email_filter_keeps_investment_transactions_with_money_movement():
    email_type, _, _ = classify_email(
        "Groww <noreply@groww.in>",
        "SIP investment successful",
        "Your SIP investment of \u20b95,000 has been debited on 09-07-2026. Order ID: SIP123456.",
    )

    assert email_type == EmailType.INVESTMENT


def test_parser_extracts_amount_with_indian_rupee_symbol():
    result = get_parser_registry().parse_email(
        "alerts@example-payments.test",
        "Payment successful",
        "\u20b91,250.50 has been debited on 09-07-2026.",
    )

    assert result.amount == 1250.50


@pytest.mark.parametrize(
    ("subject", "body", "expected_method"),
    [
        ("UPI payment", "Rs.500 has been debited via UPI on 09-07-2026.", "upi"),
        ("Debit card alert", "Your Debit Card was used for Rs.500 on 09-07-2026.", "debit_card"),
        ("Credit card alert", "Your Credit Card was charged Rs.500 on 09-07-2026.", "credit_card"),
    ],
)
def test_parser_detects_payment_method(subject, body, expected_method):
    result = get_parser_registry().parse_email("alerts@example-payments.test", subject, body)

    assert result.payment_method == expected_method


def test_parser_handles_live_hdfc_upi_alert_format():
    result = get_parser_registry().parse_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
        "You have done a UPI txn. Check details!",
        (
            "Rs.72.00 is debited from your account ending 1441 towards VPA shop@upi "
            "(SAMPLE MERCHANT) on 09-07-26. UPI transaction reference no.: 125997704118."
        ),
    )

    assert result.bank == "HDFC"
    assert result.payment_method == "upi"
    assert result.merchant_raw == "SAMPLE MERCHANT"
    assert result.reference_id == "125997704118"


def test_parser_does_not_find_atm_inside_a_upi_handle():
    result = get_parser_registry().parse_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
        "You have done a UPI txn. Check details!",
        (
            "Rs.56.00 has been debited from account 1441 to VPA "
            "kethavatmangya@ybl Mr KETHAVATH MANGYA on 21-03-26."
        ),
    )
    assert result.payment_rail == "upi"


def test_parser_captures_card_timestamp_and_pending_reversal_status():
    result = get_parser_registry().parse_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
        "Transaction reversal initiated",
        (
            "Transaction reversal of Rs.2.00 has been initiated to your HDFC Bank Credit Card "
            "ending 4349. From Merchant: SAMPLE STORE Date Time: 20 Mar, 2026 at 14:37:13."
        ),
    )

    assert result.payment_method == "credit_card"
    assert result.merchant_raw == "SAMPLE STORE"
    assert result.transaction_status == "reversal_pending"
    assert result.transaction_timestamp is not None
    assert result.transaction_timestamp.hour == 14


def test_parser_treats_atm_location_as_cash_movement_not_merchant_or_fee():
    result = get_parser_registry().parse_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
        "View: Account update for your HDFC Bank A/c",
        (
            "Thank you for using your HDFC Bank Debit Card ending 4017 for ATM withdrawal "
            "for Rs 20,000.00 in PUNE at BANER on 09-06-2026 19:16:57. "
            "For more details on Service charges and Fees, click here."
        ),
    )

    assert result.payment_rail == "atm"
    assert result.card_event == "none"
    assert result.merchant_raw == "ATM cash withdrawal"


def test_service_fee_footer_does_not_turn_a_card_purchase_into_a_fee():
    result = get_parser_registry().parse_email(
        "HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
        "A payment was made using your Credit Card",
        (
            "Rs. 642.00 has been debited from your HDFC Bank Credit Card ending 4349 "
            "towards RAZ*Swiggy on 16 Jun, 2026 at 12:45:10. "
            "For more details on Service charges and Fees, click here."
        ),
    )
    assert result.card_event == "purchase"


@pytest.mark.asyncio
async def test_full_text_alias_inference_finds_known_merchant(test_session_factory):
    async with test_session_factory() as db:
        merchant, category_id = await infer_merchant_from_text(
            db,
            "Dear Customer, your subscription renewal for NETFLIX.COM was processed successfully.",
        )

    assert merchant == "Netflix"
    assert category_id is not None
