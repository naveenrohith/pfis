"""
Generic Parser
Fallback parser that works across all banks using common patterns.
Used when no bank-specific parser matches or as a base for bank parsers.
"""

import logging
from app.services.parser.base_parser import BaseParser, ParseResult, TransactionTypeEnum
from app.services.parser import patterns

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
    Patterns optimized for HDFC alert email format.
    """

    BANK_NAME = "HDFC"
    VERSION = 1

    def parse(self, subject: str, body: str) -> ParseResult:
        """Parse HDFC Bank email."""
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)
        result.account_last4 = patterns.extract_account(combined)
        result.reference_id = patterns.extract_reference_id(combined)
        result.merchant_raw = patterns.extract_merchant(combined)

        result.compute_confidence()
        return result


class SBIParser(BaseParser):
    """
    SBI specific parser.
    SBI formats: "Your a/c no. XXXXXXXX1234 is debited for Rs.230.00"
    """

    BANK_NAME = "SBI"
    VERSION = 1

    def parse(self, subject: str, body: str) -> ParseResult:
        """Parse SBI email."""
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)
        result.account_last4 = patterns.extract_account(combined)
        result.reference_id = patterns.extract_reference_id(combined)
        result.merchant_raw = patterns.extract_merchant(combined)

        result.compute_confidence()
        return result


class ICICIParser(BaseParser):
    """
    ICICI Bank specific parser.
    Formats: "INR 499.00 has been debited from your ICICI Bank Account XX5678"
    """

    BANK_NAME = "ICICI"
    VERSION = 1

    def parse(self, subject: str, body: str) -> ParseResult:
        """Parse ICICI email."""
        combined = self._clean_text(f"{subject} {body}")
        result = ParseResult(bank=self.BANK_NAME, parser_version=self.VERSION)

        result.amount = patterns.extract_amount(combined)

        txn_type = patterns.detect_transaction_type(combined)
        if txn_type:
            result.transaction_type = TransactionTypeEnum(txn_type)

        result.date = patterns.extract_date(combined)
        result.account_last4 = patterns.extract_account(combined)
        result.reference_id = patterns.extract_reference_id(combined)
        result.merchant_raw = patterns.extract_merchant(combined)

        result.compute_confidence()
        return result
