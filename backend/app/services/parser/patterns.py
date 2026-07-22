"""
Common Extraction Patterns
Shared regex patterns used across all bank parsers.
Centralizing these avoids duplication and makes improvement easier.
"""

import re
from datetime import date, datetime, timedelta, timezone

# ─── Amount Extraction ───

AMOUNT_PATTERNS = [
    # Rs. 450.00 / Rs.INR 1,200.00 / Rs 450
    re.compile(r"Rs\.?\s?(?:INR\s?)?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
    # INR 450.00 / INR 1,200
    re.compile(r"INR\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
    # Indian rupee symbol: ₹450.00 / ₹ 1,200
    re.compile(r"\u20B9\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
    # ₹450.00 / ₹ 1,200
    re.compile(r"₹\s?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
]


TRANSACTION_AMOUNT_PATTERNS = [
    re.compile(
        r"Rs\.?\s?(?:INR\s?)?([\d,]+(?:\.\d{1,2})?)\s+(?:has\s+been\s+)?(?:is\s+)?(?:debited|credited|charged)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:debited|credited|charged|spent|withdrawal\s+for)\s+(?:for\s+)?Rs\.?\s?(?:INR\s?)?([\d,]+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:payment\s+of|paid)\s+Rs\.?\s?(?:INR\s?)?([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE),
]


def extract_amount(text: str) -> float | None:
    """Extract the transaction amount, preferring transaction context."""
    for pattern in TRANSACTION_AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                return float(amount_str)
            except ValueError:
                continue

    for pattern in AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                return float(amount_str)
            except ValueError:
                continue
    return None


# ─── Transaction Type Detection ───

DEBIT_KEYWORDS = [
    r"\bdebited\b",
    r"\bspent\b",
    r"\bcharged\b",
    r"\bpurchase\b",
    r"\bpaid\b",
    r"\bwithdrawn\b",
    r"\bdebit\b",
    r"\btransferred\b",
    r"\bpayment\s+of\b",
    r"\bpayment\s+successful\b",
    r"\bis\s+debited\s+from\b",
    r"\bhas\s+been\s+debited\b",
]

CREDIT_KEYWORDS = [
    r"\bcredited\b",
    r"\breceived\b",
    r"\bdeposited\b",
    r"\bsuccessfully\s+added\s+to\s+your\s+account\b",
    r"\badded\s+to\s+your\s+account\b",
]

REFUND_KEYWORDS = [
    r"\brefund\b",
    r"\breversal\b",
    r"\breversed\b",
]


def detect_transaction_type(text: str) -> str | None:
    """Detect if transaction is debit, credit, or refund."""
    text_lower = text.lower()

    # Check refund first (takes priority over credit)
    for pattern in REFUND_KEYWORDS:
        if re.search(pattern, text_lower):
            return "refund"

    # Check debit FIRST (avoids 'Credit Card' matching credit)
    for pattern in DEBIT_KEYWORDS:
        if re.search(pattern, text_lower):
            return "debit"

    # Check credit
    for pattern in CREDIT_KEYWORDS:
        if re.search(pattern, text_lower):
            return "credit"

    return None


def detect_payment_method(text: str) -> str:
    """Identify the payment rail used by a transaction notification."""
    text_upper = text.upper()
    if "UPI" in text_upper or "VPA" in text_upper:
        return "upi"
    if "CREDIT CARD" in text_upper:
        return "credit_card"
    if "DEBIT CARD" in text_upper:
        return "debit_card"
    if "EMI" in text_upper:
        return "emi"
    if "LAZYPAY" in text_upper or "PAY LATER" in text_upper or "PAYLATER" in text_upper:
        return "pay_later"
    if "WALLET" in text_upper:
        return "wallet"
    if any(token in text_upper for token in ("NEFT", "IMPS", "RTGS")):
        return "bank_transfer"
    return "other"


def detect_transaction_status(text: str) -> str:
    text_lower = text.lower()
    if "reversal" in text_lower and any(
        token in text_lower for token in ("initiated", "allow up to", "pending")
    ):
        return "reversal_pending"
    if "refund" in text_lower and any(
        token in text_lower for token in ("initiated", "allow up to", "pending")
    ):
        return "refund_pending"
    return "completed"


# ─── Date Extraction ───

DATE_PATTERNS = [
    # 05-05-2026, 05/05/2026
    (re.compile(r"(\d{2})[-/](\d{2})[-/](\d{4})"), "dmy4"),
    # 01 Feb, 2026 / 01 February 2026
    (re.compile(r"(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})"), "dMonth"),
    # 05-May-2026, 05-May-26
    (re.compile(r"(\d{1,2})[-/](\w{3})[-/](\d{2,4})"), "dMy"),
    # 2026-05-05
    (re.compile(r"(\d{4})[-/](\d{2})[-/](\d{2})"), "ymd"),
    # 05-05-26
    (re.compile(r"(\d{2})[-/](\d{2})[-/](\d{2})\b"), "dmy2"),
]

MONTH_MAP = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _valid_year(year: int) -> bool:
    return 2000 <= year <= date.today().year + 1


def extract_date(text: str) -> date | None:
    """Extract transaction date from text."""
    for pattern, fmt in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                if fmt == "dmy4":
                    d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    if _valid_year(y):
                        return date(y, m, d)
                elif fmt == "dMonth":
                    d = int(match.group(1))
                    m_str = match.group(2).lower()[:3]
                    named_month = MONTH_MAP.get(m_str)
                    y = int(match.group(3))
                    if named_month and _valid_year(y):
                        return date(y, named_month, d)
                elif fmt == "dMy":
                    d = int(match.group(1))
                    m_str = match.group(2).lower()[:3]
                    named_month = MONTH_MAP.get(m_str)
                    if not named_month:
                        continue
                    y = int(match.group(3))
                    if y < 100:
                        y += 2000
                    if _valid_year(y):
                        return date(y, named_month, d)
                elif fmt == "ymd":
                    y, m, d = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    if _valid_year(y):
                        return date(y, m, d)
                elif fmt == "dmy2":
                    d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    y += 2000
                    if _valid_year(y):
                        return date(y, m, d)
            except (ValueError, OverflowError):
                continue
    return None


_DATETIME_PATTERN = re.compile(
    r"(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})\s+at\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
    re.IGNORECASE,
)


def extract_transaction_timestamp(text: str) -> datetime | None:
    """Extract a bank-supplied transaction time in India Standard Time."""
    match = _DATETIME_PATTERN.search(text)
    if not match:
        return None
    try:
        day, month_name, year, hour, minute, second = match.groups()
        month = MONTH_MAP.get(month_name.lower()[:3])
        if not month:
            return None
        ist = timezone(timedelta(hours=5, minutes=30))
        return datetime(
            int(year), month, int(day), int(hour), int(minute), int(second or 0), tzinfo=ist
        )
    except ValueError:
        return None


# ─── Account Number Extraction ───

ACCOUNT_PATTERNS = [
    # XX1234, XXXX1234, X1234
    re.compile(
        r"(?:A/?c|Acct?|Account|Card)[\s.:]*(?:No\.?\s*)?(?:XX?X*)?(\d{4})\b", re.IGNORECASE
    ),
    # ending 1234
    re.compile(r"ending\s+(\d{4})\b", re.IGNORECASE),
    # XXXXXXXX1234
    re.compile(r"X{4,}(\d{4})\b"),
]


def extract_account(text: str) -> str | None:
    """Extract last 4 digits of account/card number."""
    for pattern in ACCOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


# ─── Reference ID Extraction ───

REF_PATTERNS = [
    # UPI Ref No 412345678901 / Ref No. 123456
    re.compile(r"(?:UPI\s+)?Ref\.?\s*(?:No\.?\s*)?:?\s*(\d{6,20})", re.IGNORECASE),
    # "UPI transaction reference number is 609704956003"
    re.compile(r"UPI\s+transaction\s+reference\s+number\s+is\s+(\d{6,20})", re.IGNORECASE),
    re.compile(r"UPI\s+transaction\s+reference\s+no\.?\s*:\s*(\d{6,20})", re.IGNORECASE),
    re.compile(r"Payment\s+Id\s*:?\s*([A-Za-z0-9_]{6,100})", re.IGNORECASE),
    # Transaction ID: PHO412345678906
    re.compile(r"Transaction\s+ID:?\s*(\w{6,25})", re.IGNORECASE),
    # NEFT Ref No SBIN123456789012
    re.compile(r"(?:NEFT|IMPS|RTGS)\s+Ref\s*(?:No\.?)?\s*:?\s*(\w{8,25})", re.IGNORECASE),
]


def extract_reference_id(text: str) -> str | None:
    """Extract transaction reference ID."""
    for pattern in REF_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


# ─── Merchant Extraction ───

MERCHANT_PATTERNS = [
    # HDFC NEFT credit: "from NEFT Cr-BARC0INBBIR-RANDSTAD INDIA PRIVATE LIMITED-..."
    re.compile(r"\bfrom\s+NEFT\s+Cr-[^-]+-([A-Z][A-Z0-9\s.&]+?)-", re.IGNORECASE),
    # HDFC UPI: "to VPA payzomato@hdfcbank ZOMATO on ..."
    re.compile(r"\bto\s+VPA\s+\S+\s+([A-Z][A-Z0-9\s.&-]+?)\s+on\s+\d", re.IGNORECASE),
    re.compile(r"\btowards\s+VPA\s+\S+\s+\(([^)]+)\)\s+on\s+\d", re.IGNORECASE),
    # "at SWIGGY" / "at AMAZON PAY INDIA PV"
    re.compile(
        r"\bat\s+([A-Z][A-Z0-9\s.]+?)(?:\s+(?:via|on|for|UPI|Ref|If|Available|Avl))", re.IGNORECASE
    ),
    # "to BIGBASKET" / "to SPOTIFY INDIA"
    re.compile(r"\bto\s+([A-Z][A-Z0-9\s.]+?)(?:\s+(?:via|on|was|UPI|Ref|If))", re.IGNORECASE),
    # "towards NETFLIX.COM" / "towards UPI-SWIGGY"
    re.compile(
        r"towards\s+(?:UPI-)?([A-Z][A-Z0-9\s./-]+?)(?:\s*(?:on|UPI|-\w+@|\.|If))", re.IGNORECASE
    ),
    # "for FLIPKART INTERNET"
    re.compile(r"\bfor\s+([A-Z][A-Z0-9\s.]+?)(?:\s+(?:on|via|UPI|Ref|If))", re.IGNORECASE),
    # "from AMAZON PAY" (refund context)
    re.compile(
        r"(?:refund|reversal)\s+from\s+([A-Z][A-Z0-9\s.]+?)(?:\s*[.\-]|\s+Avl)", re.IGNORECASE
    ),
    # "paid Rs. 350.00 to BIGBASKET via"
    re.compile(
        r"paid\s+(?:Rs\.?\s?[\d,.]+\s+)?to\s+([A-Z][A-Z0-9\s.]+?)(?:\s+(?:via|on))", re.IGNORECASE
    ),
    # "charged for FLIPKART INTERNET on"
    re.compile(
        r"charged\s+for\s+([A-Z][A-Z0-9\s./-]+?)(?:\s+on|\s*\.|\s+Available)", re.IGNORECASE
    ),
    # "credited to ... as refund from AMAZON PAY"
    re.compile(r"as\s+refund\s+from\s+([A-Z][A-Z0-9\s./-]+?)(?:\s*[.\-]|\s+Avl)", re.IGNORECASE),
]

MERCHANT_NOISE = {
    "UPI",
    "POS",
    "NEFT",
    "IMPS",
    "RTGS",
    "TXN",
    "TRANSACTION",
    "PAYMENT",
    "PURCHASE",
    "CARD",
    "DEBIT",
    "CREDIT",
    "BANK",
    "ACCOUNT",
    "CUSTOMER",
    "AVAILABLE",
    "BALANCE",
    "LIMIT",
    "ALERT",
    "MORE DETAILS",
    "DETAILS",
    "SERVICE CHARGES",
    "FEES",
}


def _sanitize_merchant(merchant: str) -> str | None:
    merchant = re.sub(r"[-_]+", " ", merchant.upper())
    merchant = re.sub(r"\s+", " ", merchant).strip(" .:-")
    merchant = re.sub(r"\b(?:VPA|UTIB|HDFC|ICIC|SBIN)\b", "", merchant).strip()
    merchant = re.sub(r"\s+", " ", merchant).strip(" .:-")
    if not merchant:
        return None
    if merchant in MERCHANT_NOISE:
        return None
    if merchant.isdigit() or len(merchant) < 3:
        return None
    return merchant


def extract_merchant(text: str) -> str | None:
    """Extract merchant name from text."""
    for pattern in MERCHANT_PATTERNS:
        match = pattern.search(text)
        if match:
            merchant = match.group(1).strip().rstrip(".")
            # Skip if it's just numbers, too short, or looks like an amount
            if len(merchant) >= 2 and not merchant.isdigit():
                # Skip if it starts with Rs/INR/amount pattern
                if re.match(r"^(?:Rs|INR|\d)", merchant, re.IGNORECASE):
                    continue
                sanitized = _sanitize_merchant(merchant)
                if sanitized:
                    return sanitized
    return None


def infer_generic_merchant(text: str, txn_type: str | None) -> str | None:
    """Infer a best-effort generic counterparty when the email omits merchant details."""
    text_upper = text.upper()

    if "UPI" in text_upper:
        if txn_type == "refund":
            return "UPI REFUND"
        if txn_type == "credit":
            return "UPI CREDIT"
        return "UPI TRANSFER"

    if "NEFT" in text_upper:
        return "NEFT CREDIT" if txn_type == "credit" else "NEFT TRANSFER"

    if "IMPS" in text_upper:
        return "IMPS CREDIT" if txn_type == "credit" else "IMPS TRANSFER"

    if "RTGS" in text_upper:
        return "RTGS CREDIT" if txn_type == "credit" else "RTGS TRANSFER"

    if any(
        token in text_upper for token in ["POS", "DEBIT CARD", "CREDIT CARD", "CHARGED", "SPENT"]
    ):
        return "CARD PURCHASE"

    if txn_type == "credit":
        return "BANK CREDIT"
    if txn_type == "refund":
        return "BANK REFUND"
    if txn_type == "debit":
        return "BANK DEBIT"
    return None
