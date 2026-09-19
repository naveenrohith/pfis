"""De-identified contract tests for the reviewed HDFC digital layout."""

from decimal import Decimal
from pathlib import Path

import pytest
from app.services.hdfc_statement_extractor import (
    classify_emi_component,
    detect_hdfc_statement_document,
    extract_hdfc_statement,
)
from app.services.parser.normalizer import (
    extract_descriptor_identity,
    is_plausible_merchant_descriptor,
)
from app.services.statement_detection import detect_statement
from app.services.transaction_matching import (
    is_fuel_surcharge_amount_match,
    merchants_match,
)

HDFC_DEPOSIT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "hdfc_deposit_statement_reviewed.txt"
).read_text(encoding="utf-8")


def _fixed_width(*values: tuple[int, str], width: int = 92) -> str:
    row = [" "] * width
    for position, value in values:
        row[position : position + len(value)] = value
    return "".join(row).rstrip()


def _reviewed_statement(rows: list[str]) -> str:
    return "\n".join(
        [
            "HDFC BANK",
            "DUPLICATE Millennia Credit Card Statement",
            "Credit Card No. 123456XXXXXX9911",
            "Statement Date 22 Jul, 2026",
            "Billing Period 23 Jun, 2026 - 22 Jul, 2026",
            "                     PAYMENTS/CREDITS PURCHASES/DEBIT",
            "     PREVIOUS STATEMENT DUES                     FINANCE CHARGES TOTAL AMOUNT DUE",
            "                         RECEIVED   (Current Billing Cycle)",
            _fixed_width((62, "C1,150.00")),
            _fixed_width(
                (9, "C2,000.00"),
                (23, "C1,500.00"),
                (37, "C650.00"),
                (51, "C0.00"),
            ),
            "          TOTAL CREDIT LIMIT",
            "           (Including Cash) AVAILABLE CREDIT LIMIT "
            "AVAILABLE CASH LIMIT MINIMUM DUE DUE DATE",
            _fixed_width((62, "C120.00"), (72, "11 Aug, 2026")),
            _fixed_width(
                (11, "C100,000"),
                (28, "C98,850"),
                (47, "C40,000"),
            ),
            "Domestic Transactions",
            "DATE & TIME TRANSACTION DESCRIPTION AMOUNT PI",
            *rows,
        ]
    )


def test_reviewed_layout_extracts_billing_anatomy_and_classifies_lines():
    text = _reviewed_statement(
        [
            "  25/06/2026| 11:11 DE-IDENTIFIED SHOP C 500.00 l",
            "  28/06/2026| 08:41 PAYMENT RECEIVED + C 300.00 l",
            "  01/07/2026| 00:00 IGST-VPS2717-RATE 18.0 C 9.00 l",
            "  02/07/2026| 09:10 ANNUAL FEE C 100.00 l",
            "  03/07/2026| 10:20 MERCHANT REFUND + C 50.00 l",
            "  04/07/2026| 11:30 CASHBACK + C 10.00 l",
            "  05/07/2026| 12:40 FINANCE CHARGE C 1.00 l",
            "  06/07/2026| 13:50 TRANSACTION REVERSAL + C 20.00 l",
            "  07/07/2026| 14:00 STORE EMI PURCHASE C 200.00 l",
        ]
    )

    extracted = extract_hdfc_statement(text)

    assert extracted["layout_name"] == "hdfc-millennia-duplicate-v1"
    assert extracted["card_last4"] == "9911"
    assert str(extracted["statement_date"]) == "2026-07-22"
    assert str(extracted["period_start"]) == "2026-06-23"
    assert str(extracted["period_end"]) == "2026-07-22"
    assert str(extracted["due_date"]) == "2026-08-11"
    assert extracted["previous_due"] == Decimal("2000.00")
    assert extracted["payments_credits"] == Decimal("1500.00")
    assert extracted["purchases_debits"] == Decimal("650.00")
    assert extracted["finance_charges"] == Decimal("0.00")
    assert extracted["total_due"] == Decimal("1150.00")
    assert extracted["minimum_due"] == Decimal("120.00")
    assert extracted["credit_limit"] == Decimal("100000")
    assert extracted["available_credit_limit"] == Decimal("98850")
    assert extracted["available_cash_limit"] == Decimal("40000")
    assert [line["card_event"] for line in extracted["lines"]] == [
        "purchase",
        "payment",
        "tax",
        "fee",
        "refund",
        "cashback",
        "interest",
        "reversal",
        "purchase",
    ]
    assert extracted["lines"][-1]["card_event"] == "purchase"


def test_reviewed_zero_spend_statement_keeps_empty_ledger():
    text = _reviewed_statement([]).replace("C1,150.00", "C500.00").replace("C650.00", "C0.00")
    extracted = extract_hdfc_statement(text)

    assert extracted["lines"] == []
    assert extracted["purchases_debits"] == Decimal("0.00")


def test_statement_detector_recognizes_reviewed_hdfc_credit_card_layout():
    detection = detect_statement(
        _reviewed_statement(["  25/06/2026| 11:11 DE-IDENTIFIED SHOP C 500.00 l"])
    )

    assert detection.institution == "hdfc"
    assert detection.product_type == "credit_card"
    assert detection.format_id == "hdfc-credit-card-digital"
    assert detection.support_status == "supported"
    assert detection.confidence >= 0.9


def test_hdfc_document_detector_returns_redacted_card_import_contract():
    detection = detect_hdfc_statement_document(
        _reviewed_statement(["  25/06/2026| 11:11 DE-IDENTIFIED SHOP C 500.00 l"])
    )

    assert detection.status == "recognized"
    assert detection.issuer == "hdfc"
    assert detection.document_kind == "credit_card_statement"
    assert detection.format_id == "hdfc-credit-card-digital"
    assert detection.import_supported is True
    assert detection.import_endpoint == "/api/statements/hdfc/upload"
    assert detection.reason_code == "recognized_hdfc_credit_card"
    assert "card_last4" not in detection.matched_signal_codes


def test_hdfc_document_detector_recognizes_reviewed_deposit_import_contract():
    detection = detect_hdfc_statement_document(HDFC_DEPOSIT_FIXTURE)

    assert detection.status == "recognized"
    assert detection.issuer == "hdfc"
    assert detection.document_kind == "deposit_account_statement"
    assert detection.format_id == "hdfc-deposit-pipe-v1"
    assert detection.import_supported is True
    assert detection.import_endpoint == "/api/statements/import/upload"
    assert detection.reason_code == "recognized_hdfc_deposit_account"


def test_hdfc_document_detector_fails_closed_for_unknown_issuer_and_layouts():
    other_bank = detect_hdfc_statement_document(
        _reviewed_statement(["  25/06/2026| 11:11 DE-IDENTIFIED SHOP C 500.00 l"]).replace(
            "HDFC BANK", "ICICI BANK"
        )
    )
    hdfc_notification = detect_hdfc_statement_document(
        "HDFC BANK your monthly statement is ready. Sign in to view it."
    )

    assert other_bank.status == "unknown"
    assert other_bank.issuer == "unknown"
    assert other_bank.reason_code == "unsupported_issuer"
    assert hdfc_notification.status == "unknown"
    assert hdfc_notification.issuer == "hdfc"
    assert hdfc_notification.document_kind == "unknown"
    assert hdfc_notification.reason_code == "unrecognized_hdfc_layout"

    counterparty_mention = detect_hdfc_statement_document(
        """
        ICICI BANK ACCOUNT STATEMENT
        ACCOUNT NO: XXXXXXXX7788
        DATE | NARRATION | CHQ./REF.NO. | VALUE DT | WITHDRAWAL AMT. | DEPOSIT AMT. | CLOSING BALANCE
        01/08/2026 | TRANSFER TO HDFC BANK | X1 | 01/08/2026 | 500.00 | | 9500.00
        """
    )
    assert counterparty_mention.status == "unknown"
    assert counterparty_mention.issuer == "unknown"
    assert counterparty_mention.reason_code == "unsupported_issuer"


def test_hdfc_document_detector_marks_mixed_product_document_ambiguous():
    detection = detect_hdfc_statement_document(
        _reviewed_statement(["  25/06/2026| 11:11 DE-IDENTIFIED SHOP C 500.00 l"])
        + "\n"
        + HDFC_DEPOSIT_FIXTURE
    )

    assert detection.status == "ambiguous"
    assert detection.issuer == "hdfc"
    assert detection.document_kind == "unknown"
    assert detection.import_supported is False
    assert detection.reason_code == "ambiguous_hdfc_statement"


def test_statement_detector_does_not_write_enable_marker_only_card_layout():
    detection = detect_statement(
        """
        HDFC BANK CREDIT CARD STATEMENT
        CREDIT CARD NO XX9911
        TOTAL AMOUNT DUE 500.00
        MINIMUM AMOUNT DUE 50.00
        TOTAL CREDIT LIMIT 100000.00
        PAYMENT DUE DATE 10/09/2026
        """
    )

    assert detection.product_type == "credit_card"
    assert detection.format_id == "hdfc-credit-card-candidate"
    assert detection.support_status == "recognized_not_supported"
    assert "reviewed_import_profile" not in detection.reason_codes


def test_statement_detector_recognizes_hdfc_deposit_candidate_without_claiming_import():
    detection = detect_statement(
        """
        HDFC BANK LTD ACCOUNT STATEMENT
        ACCOUNT NO: XX0011
        DATE NARRATION CHQ./REF.NO. VALUE DT WITHDRAWAL AMT. DEPOSIT AMT. CLOSING BALANCE
        01/08/2026 UPI-MERCHANT-ONE 01/08/2026 500.00 0.00 9500.00
        02/08/2026 POS DEBIT CARD STORE 02/08/2026 250.00 0.00 9250.00
        03/08/2026 ATM CASH WDL 03/08/2026 1000.00 0.00 8250.00
        04/08/2026 NEFT SALARY 04/08/2026 0.00 50000.00 58250.00
        """
    )

    assert detection.institution == "hdfc"
    assert detection.product_type == "deposit_account"
    assert detection.format_id == "hdfc-deposit-account-tabular"
    assert detection.support_status == "recognized_not_supported"
    assert detection.activity_types == ("upi", "debit_card", "atm", "bank_transfer")


def test_statement_detector_fails_closed_for_ambiguous_or_unrecognized_documents():
    ambiguous = detect_statement(
        """
        HDFC BANK CREDIT CARD STATEMENT CREDIT CARD NO XX9911 TOTAL AMOUNT DUE 500.00
        MINIMUM AMOUNT DUE 50.00 TOTAL CREDIT LIMIT 100000 PAYMENT DUE DATE 10/09/2026
        ACCOUNT STATEMENT ACCOUNT NO XX0011 NARRATION VALUE DT WITHDRAWAL AMT.
        DEPOSIT AMT. CLOSING BALANCE
        """
    )
    notification = detect_statement(
        "HDFC BANK your monthly statement is ready. Sign in to the official portal to view it."
    )
    other_bank = detect_statement(
        "OTHER BANK ACCOUNT STATEMENT ACCOUNT NO XX0011 NARRATION WITHDRAWAL AMT. "
        "DEPOSIT AMT. CLOSING BALANCE"
    )

    assert ambiguous.support_status == "ambiguous"
    assert ambiguous.product_type == "unknown"
    assert notification.support_status == "unsupported"
    assert notification.reason_codes == ("hdfc_layout_not_recognized",)
    assert other_bank.product_type == "deposit_account"
    assert other_bank.format_id == "generic-deposit-account-candidate"
    assert other_bank.support_status == "recognized_not_supported"
    assert "generic_deposit_account_signature" in other_bank.reason_codes


def test_statement_detector_classifies_non_hdfc_credit_card_as_read_only_candidate():
    detection = detect_statement(
        """
        ICICI BANK CREDIT CARD STATEMENT
        CREDIT CARD NUMBER XXXX9911
        BILLING PERIOD 01/07/2026 - 31/07/2026
        TOTAL AMOUNT DUE 500.00
        MINIMUM PAYMENT 50.00
        PAYMENT DUE DATE 20/08/2026
        CREDIT LIMIT 100000.00
        TRANSACTION DATE TRANSACTION DESCRIPTION AMOUNT
        04/07/2026 DE-IDENTIFIED SHOP 500.00
        """
    )

    assert detection.institution is None
    assert detection.product_type == "credit_card"
    assert detection.format_id == "generic-credit-card-candidate"
    assert detection.support_status == "recognized_not_supported"
    assert detection.activity_types == ("credit_card",)


def test_statement_detector_reports_generic_product_ambiguity_without_picking_a_parser():
    detection = detect_statement(
        """
        OTHER BANK ACCOUNT STATEMENT ACCOUNT NUMBER XX0011
        NARRATION DATE DEBIT CREDIT BALANCE CLOSING BALANCE
        CREDIT CARD STATEMENT CREDIT CARD NUMBER XXXX9911
        TOTAL AMOUNT DUE 500.00 MINIMUM DUE 50.00
        BILLING PERIOD 01/07/2026 - 31/07/2026
        TRANSACTION DESCRIPTION
        """
    )

    assert detection.institution is None
    assert detection.product_type == "unknown"
    assert detection.support_status == "ambiguous"
    assert detection.reason_codes == ("multiple_generic_product_signatures",)


def test_statement_merchant_normalization_accepts_only_controlled_suffixes():
    assert merchants_match("DE-IDENTIFIED SHOP GURGAON", "De Identified Shop")
    assert merchants_match("DE-IDENTIFIED SHOP", "DE-IDENTIFIED SHOP")
    assert not merchants_match("SHOP", "SHOPPING CENTRE")
    assert not merchants_match("FIRST MERCHANT", "SECOND MERCHANT")


def test_merchant_descriptor_rejects_email_prose_without_guessing():
    prose = (
        "THE BOARDING POINT AT LEAST 15 MINUTES BEFORE THE SCHEDULED "
        "TIME OF DEPARTURE IS NOT RESPONSIBLE"
    )
    assert not is_plausible_merchant_descriptor(prose)
    assert extract_descriptor_identity(prose).candidate == "Unknown"
    assert is_plausible_merchant_descriptor("MAKE MY TRIP INDIA PVT")


def test_fuel_surcharge_amount_matching_is_bounded_and_directional():
    assert is_fuel_surcharge_amount_match(Decimal("511.80"), Decimal("500.00"))
    assert is_fuel_surcharge_amount_match(Decimal("1011.80"), Decimal("1000.00"))
    assert not is_fuel_surcharge_amount_match(Decimal("500.00"), Decimal("500.00"))
    assert not is_fuel_surcharge_amount_match(Decimal("500.00"), Decimal("511.80"))
    assert not is_fuel_surcharge_amount_match(Decimal("540.00"), Decimal("500.00"))


def test_statement_descriptor_identity_removes_payment_wrappers_not_evidence():
    flipkart = extract_descriptor_identity("EMI FLIPKART PAYMENTSBANGALORE")
    amazon = extract_descriptor_identity("EMI AMAZONGURGAON")
    platform = extract_descriptor_identity("GYFTR VIA SMARTBUYNEW DELHI")

    assert flipkart.candidate == "FLIPKART"
    assert flipkart.context == "EMI purchase"
    assert amazon.candidate == "AMAZON"
    assert platform.candidate == "GYFTR"
    assert extract_descriptor_identity("More Details").candidate == "Unknown"


@pytest.mark.parametrize(
    ("description", "kind", "reference", "installment"),
    [
        ("EMI FLIPKART PAYMENTSBANGALORE", "emi_conversion_purchase", None, None),
        ("AGGREGATOR EMI - OFFUS CREDIT", "emi_conversion_credit", None, None),
        ("OFFUS EMI,PROCNG FEE,00000000001397", "emi_processing_fee", "1397", None),
        ("OFFUS EMI,PRIN NB:02,00000139775674", "emi_principal", "1397", 2),
        ("OFFUS EMI,INT NBR:02,00000139775674", "emi_interest", "1397", 2),
        (
            "OFFUS EMI,PRIN NB:03,00000140364891 (Ref# 09999999980722005447115)",
            "emi_principal",
            "1403",
            3,
        ),
        (
            "OFFUS EMI,INT NBR:02,00000140815845 (Ref# 09999999980722005447149)",
            "emi_interest",
            "1408",
            2,
        ),
        ("MER EMI ,PRECLO INT,00000138979638", "emi_preclosure_interest", "1389", None),
        ("MER EMI ,LOAN PRECL,00000000001389", "emi_preclosure_principal", "1389", None),
    ],
)
def test_emi_component_classifier_preserves_issuer_anatomy(
    description, kind, reference, installment
):
    component = classify_emi_component(description, is_credit="CREDIT" in description)
    assert component == {
        "component_kind": kind,
        "issuer_plan_reference": reference,
        "installment_number": installment,
    }
