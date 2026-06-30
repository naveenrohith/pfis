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


@pytest.mark.asyncio
async def test_full_text_alias_inference_finds_known_merchant(test_session_factory):
    async with test_session_factory() as db:
        merchant, category_id = await infer_merchant_from_text(
            db,
            "Dear Customer, your subscription renewal for NETFLIX.COM was processed successfully.",
        )

    assert merchant == "Netflix"
    assert category_id is not None
