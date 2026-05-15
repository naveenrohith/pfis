"""
Email Filter Service
Classifies emails as financial (TRANSACTION) or non-financial (OTP, PROMO, IGNORE).

This is the gatekeeper: only financial emails proceed to the parsing engine.
"""

import html
import logging
import re
from enum import Enum

logger = logging.getLogger(__name__)


class EmailType(str, Enum):
    TRANSACTION = "transaction"
    OTP = "otp"
    PROMOTION = "promotion"
    STATEMENT = "statement"
    IGNORE = "ignore"


KNOWN_BANK_SENDERS = {
    "alerts@hdfcbank.net": "HDFC",
    "alerts@hdfcbank.com": "HDFC",
    "donotreply@hdfcbank.net": "HDFC",
    "alerts@sbi.co.in": "SBI",
    "donotreply@sbi.co.in": "SBI",
    "alerts@icicibank.com": "ICICI",
    "noreply@icicibank.com": "ICICI",
    "alerts@axisbank.com": "AXIS",
    "alerts@kotak.com": "KOTAK",
    "alerts@kotakbank.com": "KOTAK",
    "alerts@yesbank.in": "YES",
    "alerts@pnb.co.in": "PNB",
    "alerts@bfrpr.rbl.co.in": "RBL",
    "alerts@indusind.com": "INDUSIND",
    "alerts@federalbank.co.in": "FEDERAL",
    "noreply@paytm.com": "PAYTM",
    "noreply@phonepe.com": "PHONEPE",
    "noreply@googleplay.com": "GPAY",
    "notifications@amazonpay.in": "AMAZONPAY",
    "creditcard@hdfcbank.net": "HDFC_CC",
    "creditcards@icicibank.com": "ICICI_CC",
    "creditcard@axisbank.com": "AXIS_CC",
}

TRANSACTION_KEYWORDS = [
    r"debited",
    r"credited",
    r"spent",
    r"charged",
    r"transaction",
    r"transferred",
    r"withdrawn",
    r"deposited",
    r"payment\s+of",
    r"paid\s+to",
    r"received\s+from",
    r"UPI",
    r"NEFT",
    r"IMPS",
    r"RTGS",
    r"purchase",
    r"refund",
    r"reversal",
    r"successfully\s+added\s+to\s+your\s+account",
    r"added\s+to\s+your\s+account",
    r"is\s+debited\s+from",
    r"has\s+been\s+debited",
    r"has\s+been\s+credited",
]

OTP_KEYWORDS = [
    r"\bOTP\b",
    r"one.?time.?password",
    r"verification\s+code",
    r"security\s+code",
    r"\bCVV\b",
]

PROMO_KEYWORDS = [
    r"offer",
    r"discount",
    r"cashback\s+offer",
    r"pre.?approved\s+loan",
    r"upgrade\s+your",
    r"exclusive\s+deal",
    r"limited\s+time",
    r"congratulations.*selected",
    r"pre.?approved",
    r"apply\s+now",
]

NON_TRANSACTION_KEYWORDS = [
    r"available\s+balance",
    r"balance\s+in\s+your\s+account",
    r"credit\s+card\s+application",
    r"application\s+reference",
    r"successfully\s+set[-\s]?up",
    r"device\s+for\s+mobilebanking",
    r"biometric\s+login",
    r"login\s+pin",
    r"sms\s+banking\s+registration",
    r"validate\s+your\s+email\s+id",
    r"email\s+address\s+confirmation",
    r"card\s+usage\s+settings",
]

AMOUNT_PATTERN = re.compile(
    r"(?:Rs\.?\s?(?:INR\s?)?|INR)\s?[\d,]+(?:\.\d{1,2})?",
    re.IGNORECASE,
)


def _clean_text(text: str) -> str:
    """Strip email markup before signal detection."""
    text = html.unescape(text or "")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_known_sender(sender_email: str) -> tuple[bool, str]:
    """Check if sender is a known financial institution."""
    if not sender_email:
        return False, ""

    email_match = re.search(r"<([^>]+)>", sender_email)
    clean_email = email_match.group(1).lower() if email_match else sender_email.lower().strip()

    bank = KNOWN_BANK_SENDERS.get(clean_email, "")
    return bool(bank), bank


def classify_email(sender: str, subject: str, body: str) -> tuple[EmailType, str, float]:
    """
    Classify an email into a type.
    Returns (email_type, bank_name, confidence).
    """
    subject = subject or ""
    body = _clean_text(body)
    combined_text = _clean_text(f"{subject} {body}")

    is_known, bank_name = is_known_sender(sender)

    for pattern in OTP_KEYWORDS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            logger.debug("Email classified as OTP: %s", subject[:50])
            return EmailType.OTP, bank_name, 0.95

    promo_count = sum(
        1 for pattern in PROMO_KEYWORDS
        if re.search(pattern, combined_text, re.IGNORECASE)
    )
    txn_keyword_count = sum(
        1 for pattern in TRANSACTION_KEYWORDS
        if re.search(pattern, combined_text, re.IGNORECASE)
    )
    non_transaction_count = sum(
        1 for pattern in NON_TRANSACTION_KEYWORDS
        if re.search(pattern, combined_text, re.IGNORECASE)
    )
    has_amount = bool(AMOUNT_PATTERN.search(combined_text))

    if promo_count >= 2 and txn_keyword_count == 0:
        logger.debug("Email classified as PROMOTION: %s", subject[:50])
        return EmailType.PROMOTION, bank_name, 0.85

    if non_transaction_count and (txn_keyword_count == 0 or not has_amount):
        logger.debug("Email classified as IGNORE(non-transaction): %s", subject[:50])
        return EmailType.IGNORE, bank_name, 0.90

    if is_known and txn_keyword_count >= 1 and has_amount:
        return EmailType.TRANSACTION, bank_name, 0.95

    if txn_keyword_count >= 2 and has_amount:
        return EmailType.TRANSACTION, "UNKNOWN", 0.70

    if is_known:
        return EmailType.STATEMENT, bank_name, 0.50

    logger.debug("Email classified as IGNORE: %s", subject[:50])
    return EmailType.IGNORE, "", 0.0
