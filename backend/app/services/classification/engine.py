"""Connector-neutral financial source classification."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ClassificationType(str, Enum):
    TRANSACTION = "transaction"
    OTP = "otp"
    PROMOTION = "promotion"
    STATEMENT = "statement"
    INVESTMENT = "investment"
    SALARY = "salary"
    REFUND = "refund"
    FAILED_PAYMENT = "failed_payment"
    SUBSCRIPTION = "subscription"
    LOAN = "loan"
    IGNORE = "ignore"


@dataclass(frozen=True)
class ClassificationResult:
    classification: ClassificationType
    institution: str
    confidence: float
    matched_signals: tuple[str, ...]
    reason: str


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
    r"voucher",
    r"redeem",
    r"reward\s+points",
    r"gift\s+card",
    r"free\s+(?:gift|cup|coupon|voucher|trial|delivery)",
    r"limited\s+edition",
    r"claim\s+your",
    r"don.?t\s+miss",
    r"last\s+chance",
    r"giveaway",
    r"coupon\s+code",
    r"promo\s+code",
    r"shop\s+now",
    r"buy\s+now",
    r"sale\s+is\s+live",
    r"flat\s+\d+%\s+off",
    r"\d+%\s+off",
    r"holiday\s+(?:magic|delights|offer|sale)",
    r"festive\s+(?:offer|sale)",
]

NON_TRANSACTION_KEYWORDS = [
    r"account\s+update",
    r"available\s+balance",
    r"balance\s+in\s+your\s+account",
    r"available\s+balance.*\bas\s+of\b",
    r"credit\s+card\s+application",
    r"application\s+reference",
    r"credit\s+card\s+application.*\bapproved\b",
    r"credit\s+card\s+application.*successfully\s+submitted",
    r"successfully\s+set[-\s]?up",
    r"device\s+for\s+mobilebanking",
    r"biometric\s+login",
    r"login\s+pin",
    r"sms\s+banking\s+registration",
    r"chatbanking\s+registration",
    r"netbanking\s+password",
    r"reset\s+your\s+netbanking\s+password",
    r"modified\s+card\s+usage",
    r"via\s+online\s+banking",
    r"mobile\s+number.*email\s+id.*successfully\s+updated",
    r"aadhaar\s+has\s+been\s+updated",
    r"secure\s+usage\s+tips",
    r"accepted\s+the\s+terms\s+and\s+conditions",
    r"third\s+party\s+funds\s+transfer\s+facility",
    r"registered\s+your\s+device",
    r"set\s+your\s+4\s+digit\s+pin",
    r"validate\s+your\s+email\s+id",
    r"email\s+address\s+confirmation",
    r"card\s+usage\s+settings",
    r"real[-\s]?time\s+balance\s+updates?",
    r"thank\s+you\s+for\s+banking\s+with\s+us",
]

SPECIAL_PATTERNS: list[tuple[ClassificationType, list[str], str]] = [
    (
        ClassificationType.FAILED_PAYMENT,
        [r"payment\s+(?:failed|declined|unsuccessful)", r"transaction\s+(?:failed|declined)"],
        "failed payment signal",
    ),
    (
        ClassificationType.SALARY,
        [r"\bsalary\b", r"\bpayroll\b", r"salary\s+credited"],
        "salary credit signal",
    ),
    (
        ClassificationType.REFUND,
        [r"\brefund(?:ed)?\b", r"\breversal\b", r"credited.*refund"],
        "refund signal",
    ),
    (
        ClassificationType.SUBSCRIPTION,
        [r"\bsubscription\b", r"\bauto[-\s]?pay\b", r"\bstanding\s+instruction\b"],
        "subscription signal",
    ),
    (
        ClassificationType.INVESTMENT,
        [r"\bmutual\s+fund\b", r"\bSIP\b", r"\bdemat\b", r"\binvestment\b"],
        "investment signal",
    ),
    (
        ClassificationType.LOAN,
        [r"\bEMI\b", r"\bloan\b", r"loan\s+account"],
        "loan signal",
    ),
]

AMOUNT_PATTERN = re.compile(
    r"(?:Rs\.?\s?(?:INR\s?)?|INR)\s?[\d,]+(?:\.\d{1,2})?",
    re.IGNORECASE,
)


def _clean_text(text: str) -> str:
    from app.utils.text import clean_html_to_text

    return clean_html_to_text(text)


def _matches(patterns: list[str], text: str) -> tuple[str, ...]:
    return tuple(pattern for pattern in patterns if re.search(pattern, text, re.IGNORECASE))


def is_known_sender(sender_email: str) -> tuple[bool, str]:
    if not sender_email:
        return False, ""

    email_match = re.search(r"<([^>]+)>", sender_email)
    clean_email = email_match.group(1).lower() if email_match else sender_email.lower().strip()
    bank = KNOWN_BANK_SENDERS.get(clean_email, "")
    return bool(bank), bank


def classify_source_record(sender: str, subject: str, body: str) -> ClassificationResult:
    subject = subject or ""
    body = _clean_text(body)
    combined_text = _clean_text(f"{subject} {body}")
    is_known, institution = is_known_sender(sender)

    otp_matches = _matches(OTP_KEYWORDS, combined_text)
    if otp_matches:
        logger.debug("Source classified as OTP: %s", subject[:50])
        return ClassificationResult(
            ClassificationType.OTP,
            institution,
            0.95,
            otp_matches,
            "otp/security signal",
        )

    promo_matches = _matches(PROMO_KEYWORDS, combined_text)
    txn_matches = _matches(TRANSACTION_KEYWORDS, combined_text)
    non_transaction_matches = _matches(NON_TRANSACTION_KEYWORDS, combined_text)
    has_amount = bool(AMOUNT_PATTERN.search(combined_text))

    if len(promo_matches) >= 2 and not txn_matches:
        return ClassificationResult(
            ClassificationType.PROMOTION,
            institution,
            0.85,
            promo_matches,
            "multiple promotion signals",
        )

    if not is_known and promo_matches:
        return ClassificationResult(
            ClassificationType.PROMOTION,
            institution,
            0.80,
            promo_matches,
            "unknown sender marketing signal",
        )

    if non_transaction_matches and (not txn_matches or not has_amount):
        return ClassificationResult(
            ClassificationType.IGNORE,
            institution,
            0.90,
            non_transaction_matches,
            "non-transaction account/service signal",
        )

    for classification, patterns, reason in SPECIAL_PATTERNS:
        matches = _matches(patterns, combined_text)
        if matches and (has_amount or classification == ClassificationType.FAILED_PAYMENT):
            confidence = 0.90 if is_known else 0.72
            return ClassificationResult(classification, institution or "UNKNOWN", confidence, matches, reason)

    if is_known and txn_matches and has_amount:
        return ClassificationResult(
            ClassificationType.TRANSACTION,
            institution,
            0.95,
            txn_matches,
            "known financial sender with transaction and amount signals",
        )

    if len(txn_matches) >= 2 and has_amount and not promo_matches:
        return ClassificationResult(
            ClassificationType.TRANSACTION,
            "UNKNOWN",
            0.70,
            txn_matches,
            "generic transaction and amount signals",
        )

    if is_known:
        return ClassificationResult(
            ClassificationType.STATEMENT,
            institution,
            0.50,
            tuple(),
            "known financial sender without transaction amount signal",
        )

    return ClassificationResult(ClassificationType.IGNORE, "", 0.0, tuple(), "no financial signal")
