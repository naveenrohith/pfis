"""
Parser Registry
Routes emails to the correct bank-specific parser based on sender.
Fallback to GenericParser when no specific parser matches.
"""

import logging

from app.services.gmail.email_filter import is_known_sender
from app.services.parser.bank_parsers import (
    GenericParser,
    HDFCParser,
    ICICIParser,
    SBIParser,
)
from app.services.parser.base_parser import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class ParserRegistry:
    """
    Registry of bank-specific parsers.
    Routes emails to the right parser based on sender domain.
    """

    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}
        self._fallback = GenericParser()
        self._register_defaults()

    def _register_defaults(self):
        """Register all known bank parsers."""
        hdfc = HDFCParser()
        sbi = SBIParser()
        icici = ICICIParser()

        # Map bank names to parsers
        self._parsers["HDFC"] = hdfc
        self._parsers["HDFC_CC"] = hdfc
        self._parsers["SBI"] = sbi
        self._parsers["ICICI"] = icici
        self._parsers["ICICI_CC"] = icici

        # All others use generic
        for bank in [
            "AXIS",
            "KOTAK",
            "YES",
            "PNB",
            "RBL",
            "INDUSIND",
            "FEDERAL",
            "PAYTM",
            "PHONEPE",
            "GPAY",
            "AMAZONPAY",
        ]:
            self._parsers[bank] = self._fallback

        logger.info(f"Parser registry initialized: {len(self._parsers)} bank mappings")

    def get_parser(self, bank_name: str) -> BaseParser:
        """Get the parser for a given bank name."""
        return self._parsers.get(bank_name, self._fallback)

    def parse_email(self, sender: str, subject: str, body: str) -> ParseResult:
        """
        Route an email to the correct parser and return structured result.
        """
        # Identify the bank from sender
        is_known, bank_name = is_known_sender(sender)

        # Get the right parser
        parser = self.get_parser(bank_name) if is_known else self._fallback

        # Parse
        result = parser.parse(subject, body)
        result.used_fallback = parser is self._fallback
        result.parser_name = parser.__class__.__name__
        result.parser_version = getattr(parser, "VERSION", result.parser_version)

        # Override bank name if we know it
        if is_known:
            result.bank = bank_name

        # Avoid logging merchant names at INFO (spending data is PII-adjacent).
        logger.info(
            f"Parsed [{result.bank}]: amount={result.amount}, "
            f"type={result.transaction_type}, conf={result.confidence_score:.2f}"
        )
        logger.debug("Parsed merchant detail [%s]: %s", result.bank, result.merchant_raw)

        return result


# Singleton
_registry: ParserRegistry = None


def get_parser_registry() -> ParserRegistry:
    """Get or create the parser registry singleton."""
    global _registry
    if _registry is None:
        _registry = ParserRegistry()
    return _registry
