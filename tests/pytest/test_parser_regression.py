"""Regression tests for parser accuracy and merchant inference edge cases."""

# pyright: reportMissingImports=false

from __future__ import annotations

import pytest

from app.services.gmail.demo_data import SAMPLE_EMAILS
from app.services.gmail.email_filter import EmailType, classify_email
from app.services.parser.registry import get_parser_registry
from app.services.parser.normalizer import infer_merchant_from_text


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
def test_parser_regression_on_known_formats(email_index, expected_type, expected_merchant, min_confidence):
    registry = get_parser_registry()
    email = SAMPLE_EMAILS[email_index]

    result = registry.parse_email(email["sender"], email["subject"], email["body"])

    assert result.is_valid is True
    assert result.transaction_type.value == expected_type
    assert result.merchant_raw == expected_merchant
    assert result.confidence_score >= min_confidence


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
            "Dear Customer, the available balance in your account ending XX1441 is Rs. INR 8,795.88 "
            "as of 23-MAR-26. For real-time balance updates, call us at 1800 270 3333. "
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