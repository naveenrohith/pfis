"""
Bank-Specific Parsers
Each parser implements bank-specific regex patterns optimized for that bank's alert format.
Falls back to GenericParser logic for unmatched fields.
"""

import logging
import re

from app.services.parser import patterns
from app.services.parser.base_parser import BaseParser, ParseResult, TransactionTypeEnum

logger = logging.getLogger(__name__)


class GenericParser(BaseParser):
    """
    Generic fallback parser using common Indian bank email patterns.
    Works reasonably well for most banks but bank-specific parsers are preferred.
    """

    BANK_NAME = "GENERIC"
    VERSION = 1

    def parse(self, subject: str, body: str) -> ParseResult:
        """Parse using generic patterns."""
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        # Extract all fields
        result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)
        result.account_last4 = patterns.extract_account(combined)
        result.reference_id = patterns.extract_reference_id(combined)
        result.merchant_raw = patterns.extract_merchant(combined)
        if result.merchant_raw:
            result.merchant_source = "exact"
        else:
            inferred = patterns.infer_generic_merchant(combined, txn_type)
            if inferred:
                result.merchant_raw = inferred
                result.merchant_source = "generic"

        # Compute confidence
        result.compute_confidence()

        logger.debug(
            f"[{self.BANK_NAME}] Parsed: amount={result.amount}, "
            f"merchant={result.merchant_raw}, type={result.transaction_type}, "
            f"date={result.date}, conf={result.confidence_score:.2f}"
        )

        return result


class HDFCParser(BaseParser):
    """
    HDFC Bank specific parser.
    HDFC formats:
    - "Rs.1,500.00 has been debited from a/c **1234 on 05-05-26 to VPA payzomato@hdfcbank (ZOMATO)"
    - "You have done a UPI txn. From A/c XX1234 on 05-May-26, amt debited INR1500.00"
    - NEFT: "from NEFT Cr-BARC0INBBIR-RANDSTAD INDIA PRIVATE LIMITED-..."
    """

    BANK_NAME = "HDFC"
    VERSION = 4

    # HDFC-specific amount patterns
    _HDFC_AMOUNT = [
        re.compile(
            r"Rs\.?\s?([\d,]+(?:\.\d{1,2})?)\s+(?:has\s+been\s+)?(?:debited|credited)",
            re.IGNORECASE,
        ),
        re.compile(
            r"amt\s+(?:debited|credited)\s+(?:INR|Rs\.?)\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE
        ),
        re.compile(
            r"INR\s?([\d,]+(?:\.\d{1,2})?)\s+(?:has\s+been\s+)?(?:debited|credited)", re.IGNORECASE
        ),
    ]

    # HDFC-specific merchant patterns
    _HDFC_MERCHANT = [
        # Reversal/refund alerts carry an explicit counterparty label.
        re.compile(
            r"From\s+Merchant:\s*([A-Z][A-Z0-9\s.&_-]+?)(?:\s+Date\s+Time:|\s+Date:|$)",
            re.IGNORECASE,
        ),
        # "to VPA payzomato@hdfcbank (ZOMATO)" or "to VPA payzomato@hdfcbank ZOMATO on"
        re.compile(r"to\s+VPA\s+\S+\s+\(?([A-Z][A-Z0-9\s.&-]+?)\)?\s+on\s+\d", re.IGNORECASE),
        # Credits name the counterparty after the VPA.
        re.compile(r"by\s+VPA\s+\S+\s+([A-Z][A-Z0-9\s.&-]+?)\s+on\s+\d", re.IGNORECASE),
        # Card gateways/acquirers prefix the display merchant with a short code.
        re.compile(
            r"towards\s+(?:[A-Z0-9]{2,6}\*)?([A-Z][A-Z0-9\s.&_-]+?)\s+on\s+\d",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bat\s+(?:[A-Z0-9]{2,6}\*)?([A-Z][A-Z0-9\s.&_-]+?)\s+on\s+\d",
            re.IGNORECASE,
        ),
        # "from NEFT Cr-BARC0INBBIR-RANDSTAD INDIA PRIVATE LIMITED-..."
        re.compile(r"NEFT\s+Cr-[^-]+-([A-Z][A-Z0-9\s.&]+?)(?:-|\s+on\s+)", re.IGNORECASE),
        # "at SWIGGY on"
        re.compile(r"\bat\s+([A-Z][A-Z0-9\s.]+?)(?:\s+on\s+\d|\s+via)", re.IGNORECASE),
    ]

    # HDFC account: "a/c **1234" or "A/c XX1234"
    _HDFC_ACCOUNT = re.compile(r"[Aa]/?c\s*[\*X]+(\d{4})", re.IGNORECASE)

    def parse(self, subject: str, body: str) -> ParseResult:
        """Parse HDFC Bank email with bank-specific patterns."""
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        # HDFC-specific amount extraction
        result.amount = self._match_amount(self._HDFC_AMOUNT, combined)
        if result.amount is None:
            result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)

        # HDFC-specific account extraction
        acct_match = self._HDFC_ACCOUNT.search(combined)
        result.account_last4 = (
            acct_match.group(1) if acct_match else patterns.extract_account(combined)
        )

        result.reference_id = patterns.extract_reference_id(combined)

        # An ATM location is evidence, not a merchant. Keep the raw source
        # email for the location and expose the movement accurately.
        if re.search(r"\b(?:ATM|cash)\s+withdrawal\b", combined, re.IGNORECASE):
            result.merchant_raw = "ATM cash withdrawal"
            result.merchant_source = "exact"
        else:
            result.merchant_raw = self._match_merchant(self._HDFC_MERCHANT, combined)
        if result.merchant_raw:
            result.merchant_source = "exact"
        else:
            result.merchant_raw = patterns.extract_merchant(combined)
            if result.merchant_raw:
                result.merchant_source = "exact"
            else:
                inferred = patterns.infer_generic_merchant(combined, txn_type)
                if inferred:
                    result.merchant_raw = inferred
                    result.merchant_source = "generic"

        result.compute_confidence()
        return result


class SBIParser(BaseParser):
    """
    SBI specific parser.
    SBI formats:
    - "Your a/c no. XXXXXXXX1234 is debited for Rs.230.00 on 05-05-2026"
    - "Rs. 5,000.00 credited to your a/c XXXXXXXX1234"
    - "Dear Customer, Rs.500.00 debited from your A/C X1234 on 05May26 Ref No 412345678901"
    """

    BANK_NAME = "SBI"
    VERSION = 2

    # SBI-specific amount: "debited for Rs.230.00" or "Rs. 5,000.00 credited"
    _SBI_AMOUNT = [
        re.compile(
            r"(?:debited|credited)\s+(?:for\s+)?Rs\.?\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE
        ),
        re.compile(r"Rs\.?\s?([\d,]+(?:\.\d{1,2})?)\s+(?:debited|credited)", re.IGNORECASE),
    ]

    # SBI account: "a/c no. XXXXXXXX1234" or "A/C X1234"
    _SBI_ACCOUNT = re.compile(r"[Aa]/?[Cc]\s*(?:[Nn]o\.?\s*)?X+(\d{4})", re.IGNORECASE)

    # SBI merchant: "transfer to BIGBASKET" or "to beneficiary FLIPKART"
    _SBI_MERCHANT = [
        re.compile(r"transfer\s+to\s+([A-Z][A-Z0-9\s.]+?)(?:\s+on|\s+Ref|\s*\.)", re.IGNORECASE),
        re.compile(r"beneficiary\s+([A-Z][A-Z0-9\s.]+?)(?:\s+on|\s+Ref|\s*\.)", re.IGNORECASE),
        re.compile(r"UPI-([A-Z][A-Z0-9\s./-]+?)(?:\s+on|\s+Ref|-\w+@)", re.IGNORECASE),
    ]

    def parse(self, subject: str, body: str) -> ParseResult:
        """Parse SBI email with bank-specific patterns."""
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        # SBI-specific amount
        result.amount = self._match_amount(self._SBI_AMOUNT, combined)
        if result.amount is None:
            result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)

        # SBI-specific account
        acct_match = self._SBI_ACCOUNT.search(combined)
        result.account_last4 = (
            acct_match.group(1) if acct_match else patterns.extract_account(combined)
        )

        result.reference_id = patterns.extract_reference_id(combined)

        # SBI-specific merchant
        result.merchant_raw = self._match_merchant(self._SBI_MERCHANT, combined)
        if result.merchant_raw:
            result.merchant_source = "exact"
        else:
            result.merchant_raw = patterns.extract_merchant(combined)
            if result.merchant_raw:
                result.merchant_source = "exact"
            else:
                inferred = patterns.infer_generic_merchant(combined, txn_type)
                if inferred:
                    result.merchant_raw = inferred
                    result.merchant_source = "generic"

        result.compute_confidence()
        return result


class ICICIParser(BaseParser):
    """
    ICICI Bank specific parser.
    Formats:
    - "INR 499.00 has been debited from your ICICI Bank Account XX5678 on 05-May-2026"
    - "Your ICICI Bank Credit Card XX1234 has been used for Rs.1,299.00 at AMAZON"
    - "INR 2,500.00 credited to your account 5678 from UPI Ref 412345678901"
    """

    BANK_NAME = "ICICI"
    VERSION = 2

    # ICICI-specific amount patterns
    _ICICI_AMOUNT = [
        re.compile(
            r"INR\s?([\d,]+(?:\.\d{1,2})?)\s+(?:has\s+been\s+)?(?:debited|credited)", re.IGNORECASE
        ),
        re.compile(r"(?:used\s+for|charged)\s+Rs\.?\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
        re.compile(
            r"Rs\.?\s?([\d,]+(?:\.\d{1,2})?)\s+(?:has\s+been\s+)?(?:debited|credited)",
            re.IGNORECASE,
        ),
    ]

    # ICICI account: "Account XX5678" or "Card XX1234"
    _ICICI_ACCOUNT = re.compile(r"(?:Account|Card)\s+XX?(\d{4})", re.IGNORECASE)

    # ICICI merchant: "at AMAZON" or "to BIGBASKET via"
    _ICICI_MERCHANT = [
        re.compile(r"\bat\s+([A-Z][A-Z0-9\s.]+?)(?:\s+on|\s+via|\s*\.)", re.IGNORECASE),
        re.compile(
            r"\bto\s+(?!your\s+(?:account|acct|card)\b)"
            r"([A-Z][A-Z0-9\s.]+?)(?:\s+via|\s+on|\s+UPI)",
            re.IGNORECASE,
        ),
        re.compile(r"towards\s+([A-Z][A-Z0-9\s./-]+?)(?:\s+on|\s*\.)", re.IGNORECASE),
    ]

    def parse(self, subject: str, body: str) -> ParseResult:
        """Parse ICICI email with bank-specific patterns."""
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        # ICICI-specific amount
        result.amount = self._match_amount(self._ICICI_AMOUNT, combined)
        if result.amount is None:
            result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)

        # ICICI-specific account
        acct_match = self._ICICI_ACCOUNT.search(combined)
        result.account_last4 = (
            acct_match.group(1) if acct_match else patterns.extract_account(combined)
        )

        result.reference_id = patterns.extract_reference_id(combined)

        # ICICI-specific merchant
        result.merchant_raw = self._match_merchant(self._ICICI_MERCHANT, combined)
        if result.merchant_raw:
            result.merchant_source = "exact"
        else:
            result.merchant_raw = patterns.extract_merchant(combined)
            if result.merchant_raw:
                result.merchant_source = "exact"
            else:
                inferred = patterns.infer_generic_merchant(combined, txn_type)
                if inferred:
                    result.merchant_raw = inferred
                    result.merchant_source = "generic"

        result.compute_confidence()
        return result


class StructuredAlertParser(BaseParser):
    """Shared parser for institution templates that expose stable labels.

    Many non-HDFC/SBI/ICICI alerts use the same small family of templates, but
    routing them through :class:`GenericParser` loses an important provenance
    signal: we cannot tell whether the institution format was understood or
    merely happened to match a broad expression.  This class keeps the common
    extraction fallback while allowing each institution to contribute its
    amount, account, and counterparty patterns.
    """

    _AMOUNT_PATTERNS: list[re.Pattern[str]] = []
    _ACCOUNT_PATTERN: re.Pattern[str] | None = None
    _MERCHANT_PATTERNS: list[re.Pattern[str]] = []

    def parse(self, subject: str, body: str) -> ParseResult:
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        result.amount = self._match_amount(self._AMOUNT_PATTERNS, combined)
        if result.amount is None:
            result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)
        account_match = self._ACCOUNT_PATTERN.search(combined) if self._ACCOUNT_PATTERN else None
        result.account_last4 = (
            account_match.group(1) if account_match else patterns.extract_account(combined)
        )
        result.reference_id = patterns.extract_reference_id(combined)

        result.merchant_raw = self._match_merchant(self._MERCHANT_PATTERNS, combined)
        if result.merchant_raw:
            result.merchant_source = "exact"
        else:
            result.merchant_raw = patterns.extract_merchant(combined)
            if result.merchant_raw:
                result.merchant_source = "exact"
            else:
                inferred = patterns.infer_generic_merchant(combined, txn_type)
                if inferred:
                    result.merchant_raw = inferred
                    result.merchant_source = "generic"

        result.compute_confidence()
        return result


class AxisParser(StructuredAlertParser):
    """Axis Bank and Axis credit-card alert parser."""

    BANK_NAME = "AXIS"
    VERSION = 1
    _AMOUNT_PATTERNS = [
        re.compile(
            r"(?:INR|Rs\.?)\s?([\d,]+(?:\.\d{1,2})?)\s+(?:was\s+)?(?:spent|debited|credited|charged)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:spent|debited|charged|paid)\s+(?:for\s+)?(?:INR|Rs\.?)\s?([\d,]+(?:\.\d{1,2})?)",
            re.IGNORECASE,
        ),
    ]
    _ACCOUNT_PATTERN = re.compile(
        r"(?:ending|(?:A/?c|account|card)\s*(?:no\.?\s*)?)[\s:*X]*(\d{4})\b",
        re.IGNORECASE,
    )
    _MERCHANT_PATTERNS = [
        re.compile(
            r"\bat\s+(?:[A-Z0-9]{2,8}\*)?([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:on|using|via|with|for)|[.]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\btowards\s+(?:[A-Z0-9]{2,8}\*)?([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:on|via|using)|[.]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bto\s+(?!your\s+(?:account|card|wallet)\b)([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:via|using|on)|[.]|$)",
            re.IGNORECASE,
        ),
    ]


class KotakParser(StructuredAlertParser):
    """Kotak Bank alert parser with account, UPI, and IMPS context."""

    BANK_NAME = "KOTAK"
    VERSION = 1
    _AMOUNT_PATTERNS = [
        re.compile(
            r"(?:INR|Rs\.?)\s?([\d,]+(?:\.\d{1,2})?)\s+(?:has\s+been\s+)?(?:debited|credited)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:debited|credited|charged)\s+(?:for\s+)?(?:INR|Rs\.?)\s?([\d,]+(?:\.\d{1,2})?)",
            re.IGNORECASE,
        ),
    ]
    _ACCOUNT_PATTERN = re.compile(
        r"(?:A/?c|account|card)\s*(?:no\.?\s*)?[\s:*X]*(\d{4})\b",
        re.IGNORECASE,
    )
    _MERCHANT_PATTERNS = [
        re.compile(
            r"\bfor\s+(?!your\s+(?:account|card)\b)([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:via|using|on|Ref)|[.]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bto\s+(?!your\s+(?:account|card)\b)([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:via|using|on|Ref)|[.]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"UPI[-:]([A-Z][A-Z0-9\s.&_-]+?)(?:[-]\S+|\s+on|\s+Ref|[.]|$)",
            re.IGNORECASE,
        ),
    ]


class DigitalPaymentParser(StructuredAlertParser):
    """Parser for wallet/payment-network receipts with no bank account suffix."""

    BANK_NAME = "DIGITAL_PAYMENT"
    VERSION = 1
    _AMOUNT_PATTERNS = [
        re.compile(
            r"(?:payment\s+of|paid|charged|spent)\s+(?:INR|Rs\.?)\s?([\d,]+(?:\.\d{1,2})?)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:INR|Rs\.?)\s?([\d,]+(?:\.\d{1,2})?)\s+(?:was\s+)?(?:paid|charged|spent|credited)",
            re.IGNORECASE,
        ),
    ]
    _MERCHANT_PATTERNS = [
        re.compile(
            r"\brefund\b.*?\bfrom\s+([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:on|via|using)|[.]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:paid|payment\s+of|payment)\s+(?:for\s+)?(?:INR|Rs\.?\s?[\d,.]+\s+)?to\s+([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:was\s+)?(?:successful|completed|approved|declined|via|using|on)|[.]|$)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bto\s+([A-Z][A-Z0-9\s.&_-]+?)(?:\s+(?:was\s+)?(?:successful|completed|approved|declined|via|using|on)|[.]|$)",
            re.IGNORECASE,
        ),
    ]

    def parse(self, subject: str, body: str) -> ParseResult:
        result = super().parse(subject, body)
        combined = self._clean_text(f"{subject} {body}")
        if (
            result.transaction_type == TransactionTypeEnum.REFUND
            and re.search(r"\bcredited\s+to\s+your\s+wallet\b", combined, re.IGNORECASE)
            and not re.search(r"\brefund\b.*?\bfrom\s+\S+", combined, re.IGNORECASE)
        ):
            result.merchant_raw = "WALLET REFUND"
            result.merchant_source = "exact"
            result.compute_confidence()
        return result
