"""
Email Filter Service
Classifies emails as financial (TRANSACTION) or non-financial (OTP, PROMO, IGNORE).

This is the gatekeeper — only financial emails proceed to the parsing engine.
"""

import re
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class EmailType(str, Enum):
    TRANSACTION = "transaction"
    OTP = "otp"
    PROMOTION = "promotion"
    STATEMENT = "statement"
    IGNORE = "ignore"


# Known financial email senders (Indian banks + UPI apps)
KNOWN_BANK_SENDERS = {
    # Banks
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
    # UPI Apps
    "noreply@paytm.com": "PAYTM",
    "noreply@phonepe.com": "PHONEPE",
    "noreply@googleplay.com": "GPAY",
    "notifications@amazonpay.in": "AMAZONPAY",
    # Credit Cards
    "creditcard@hdfcbank.net": "HDFC_CC",
    "creditcards@icicibank.com": "ICICI_CC",
    "creditcard@axisbank.com": "AXIS_CC",
}

# Keywords that indicate a transaction email
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
]

# Keywords that indicate OTP (ignore these)
OTP_KEYWORDS = [
    r"\bOTP\b",
    r"one.?time.?password",
    r"verification\s+code",
    r"security\s+code",
    r"\bCVV\b",
]

# Keywords that indicate promotional email (ignore these)
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

# Amount pattern — strong signal of financial email
AMOUNT_PATTERN = re.compile(
    r"(?:Rs\.?|INR|₹)\s?[\d,]+(?:\.\d{2})?",
    re.IGNORECASE,
)


def is_known_sender(sender_email: str) -> tuple[bool, str]:
    """
    Check if sender is a known financial institution.
    Returns (is_known, bank_name).
    """
    if not sender_email:
        return False, ""

    # Extract email from "Name <email>" format
    email_match = re.search(r"<([^>]+)>", sender_email)
    clean_email = email_match.group(1).lower() if email_match else sender_email.lower().strip()

    bank = KNOWN_BANK_SENDERS.get(clean_email, "")
    return bool(bank), bank


def classify_email(
    sender: str,
    subject: str,
    body: str,
) -> tuple[EmailType, str, float]:
    """
    Classify an email into a type.
    Returns (email_type, bank_name, confidence).
    
    Classification logic:
    1. Check sender against known banks → high confidence
    2. Check for OTP keywords → skip
    3. Check for promo keywords → skip
    4. Check for transaction keywords + amount → process
    """
    subject = subject or ""
    body = body or ""
    combined_text = f"{subject} {body}"

    # Step 1: Check known sender
    is_known, bank_name = is_known_sender(sender)

    # Step 2: Check for OTP (even from known senders)
    for pattern in OTP_KEYWORDS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            logger.debug(f"Email classified as OTP: {subject[:50]}")
            return EmailType.OTP, bank_name, 0.95

    # Step 3: Check for promotions (even from known senders)
    promo_count = sum(
        1 for p in PROMO_KEYWORDS
        if re.search(p, combined_text, re.IGNORECASE)
    )

    # Step 4: Check for transaction signals
    has_amount = bool(AMOUNT_PATTERN.search(combined_text))
    txn_keyword_count = sum(
        1 for kw in TRANSACTION_KEYWORDS
        if re.search(kw, combined_text, re.IGNORECASE)
    )

    # Promo with weak/no transaction signals → promotion (even from known sender)
    if promo_count >= 2 and txn_keyword_count == 0:
        logger.debug(f"Email classified as PROMOTION: {subject[:50]}")
        return EmailType.PROMOTION, bank_name, 0.85

    # Known sender + transaction keywords = high confidence
    if is_known and txn_keyword_count >= 1:
        return EmailType.TRANSACTION, bank_name, 0.95

    # Known sender + amount mentioned = good confidence
    if is_known and has_amount:
        return EmailType.TRANSACTION, bank_name, 0.85

    # Unknown sender but strong transaction signals
    if txn_keyword_count >= 2 and has_amount:
        return EmailType.TRANSACTION, "UNKNOWN", 0.70

    # Known sender but no clear signals (might be statement or other)
    if is_known:
        return EmailType.STATEMENT, bank_name, 0.5

    # Nothing matched
    logger.debug(f"Email classified as IGNORE: {subject[:50]}")
    return EmailType.IGNORE, "", 0.0
