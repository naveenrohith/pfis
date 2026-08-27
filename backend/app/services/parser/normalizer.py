"""
Merchant Normalization Service
Maps raw merchant names to clean, normalized versions.
Includes TTL-based caching to avoid full table scans on every parse.
"""

import logging
import re
import time
import unicodedata
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category, Merchant, UserMerchantRule, parse_merchant_aliases

logger = logging.getLogger(__name__)

# Cache for merchant data (TTL-based)
_merchant_cache: list = []
_merchant_cache_time: float = 0.0
_user_rule_cache: dict[str, tuple[float, list[UserMerchantRule]]] = {}
_MERCHANT_CACHE_TTL: float = 60.0  # seconds
_USER_RULE_CACHE_MAX_USERS = 256
MERCHANT_RESOLVER_VERSION = 3


@dataclass(frozen=True)
class MerchantResolution:
    """Explainable merchant resolution result used by ingestion and review flows."""

    normalized_name: str
    category_id: str | None
    source: str
    confidence: float
    rule_id: str | None = None
    resolver_version: int = MERCHANT_RESOLVER_VERSION


@dataclass(frozen=True)
class DescriptorIdentity:
    """A deterministic identity candidate extracted from noisy financial evidence."""

    candidate: str
    context: str | None
    confidence: float


GENERIC_MERCHANTS = {
    "UNKNOWN",
    "UPI TRANSFER",
    "UPI CREDIT",
    "UPI REFUND",
    "NEFT TRANSFER",
    "NEFT CREDIT",
    "IMPS TRANSFER",
    "IMPS CREDIT",
    "RTGS TRANSFER",
    "RTGS CREDIT",
    "BANK CREDIT",
    "BANK REFUND",
    "BANK DEBIT",
    "CARD PURCHASE",
    "WALLET CREDIT",
    "WALLET REFUND",
    "WALLET TRANSFER",
    "MORE DETAILS",
    "HDFC CARD EMI",
}

_LOCATION_SUFFIXES = (
    "BANGALORE",
    "BENGALURU",
    "GURGAON",
    "GURUGRAM",
    "NEW DELHI",
    "DELHI",
    "MUMBAI",
    "HYDERABAD",
    "CHENNAI",
    "PUNE",
    "NOIDA",
)

_STATEMENT_NOISE = re.compile(
    r"\b(?:PAYMENTS?|PAYMENT SERVICES|ONLINE|INTERNET|ECOM|E-COM|POS)\b",
    re.IGNORECASE,
)


def is_plausible_merchant_descriptor(raw: str | None) -> bool:
    """Reject prose and issuer boilerplate without guessing a replacement."""
    value = re.sub(r"\s+", " ", raw or "").strip()
    if not value:
        return False
    words = value.split()
    upper = value.upper()
    if len(value) > 110 or len(words) > 14:
        return False
    if re.search(
        r"\b(?:INFORM YOU THAT|BOARDING POINT|TERMS AND CONDITIONS|"
        r"DAILY DIGEST|MARKETS? (?:WERE|WAS)|IS NOT RESPONSIBLE)\b",
        upper,
    ):
        return False
    return not (
        re.search(r"\b(?:RS\.?|INR|\u20b9)\s*[\d,]+", upper)
        and re.search(r"\b(?:DEBITED|CREDITED|SPENT|CHARGED)\b", upper)
    )


def extract_descriptor_identity(raw: str) -> DescriptorIdentity:
    """Extract a merchant candidate while retaining the original descriptor as evidence.

    This is deliberately rule based. It removes issuer/payment wrappers and location
    suffixes, but never invents a merchant from unrelated message text.
    """
    value = unicodedata.normalize("NFKC", raw or "")
    value = re.sub(r"\s+", " ", value).strip(" -|,")
    if not value:
        return DescriptorIdentity("Unknown", None, 0.0)
    if not is_plausible_merchant_descriptor(value):
        return DescriptorIdentity("Unknown", "Rejected message prose", 0.0)

    upper = value.upper()
    # Old HDFC templates sometimes yielded the footer rather than the counterparty.
    # A parenthesized VPA owner is explicit evidence and outranks that footer.
    parenthesized = re.findall(r"\(([^()]{2,80})\)", value)
    if "MORE DETAILS" in upper and parenthesized:
        candidate = parenthesized[-1].strip()
        if not re.fullmatch(r"(?:REF|RRN|UPI)?\s*\d+", candidate, re.IGNORECASE):
            return DescriptorIdentity(candidate, "UPI counterparty", 0.94)
    if upper in GENERIC_MERCHANTS or upper == "MORE DETAILS":
        return DescriptorIdentity("Unknown", "Unresolved descriptor", 0.0)

    context: str | None = None
    confidence = 0.72
    if re.match(r"^EMI\b", value, re.IGNORECASE):
        value = re.sub(r"^EMI\b[\s:-]*", "", value, flags=re.IGNORECASE)
        context = "EMI purchase"
        confidence = 0.88

    if re.search(r"\s+VIA\s+", value, re.IGNORECASE):
        value = re.split(r"\s+VIA\s+", value, maxsplit=1, flags=re.IGNORECASE)[0]
        context = context or "Payment platform"
        confidence = max(confidence, 0.82)

    # Remove glued issuer locations first so wrappers such as
    # ``PAYMENTSBANGALORE`` become independently recognizable.
    for location in sorted(_LOCATION_SUFFIXES, key=len, reverse=True):
        value = re.sub(
            rf"(?:\s+|(?<=[A-Za-z])){re.escape(location)}$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()

    value = _STATEMENT_NOISE.sub(" ", value)
    value = re.sub(
        r"\b(?:REF(?:ERENCE)?|RRN|UTR|TXN)\s*#?\s*[A-Z0-9-]{6,}\b",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\(\s*REF\s*#?\s*[A-Z0-9-]+\s*\)", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\(\s*\)", " ", value)
    value = re.sub(r"\b\d{8,}\b", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -|,")

    for location in sorted(_LOCATION_SUFFIXES, key=len, reverse=True):
        value = re.sub(
            rf"(?:\s+|(?<=[A-Za-z])){re.escape(location)}$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()

    if not value or value.upper() in GENERIC_MERCHANTS:
        return DescriptorIdentity("Unknown", context or "Unresolved descriptor", 0.0)
    return DescriptorIdentity(value, context, confidence)


def _clean_merchant_name(raw: str) -> str:
    cleaned = raw.strip().upper()
    # Strip only trailing legal/channel suffixes. Substring replacement corrupted
    # names such as ``PVT LTD`` into a trailing ``T`` and removed meaningful words
    # such as ``INDIA`` or ``SERVICES`` from the middle of an identity.
    cleaned = re.sub(
        r"(?:\s+(?:PVT\.?|PV|PRIVATE|LTD\.?|LIMITED|ONLINE|INTERNET))+$",
        "",
        cleaned,
    )
    return cleaned.strip().title()


def normalize_descriptor_key(raw: str) -> str:
    """Build a deterministic exact-match key without retaining separator noise."""
    normalized = unicodedata.normalize("NFKC", raw or "").casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


async def _get_cached_merchants(db: AsyncSession) -> list:
    """Return cached merchant list, refreshing if TTL expired."""
    global _merchant_cache, _merchant_cache_time
    now = time.time()
    if _merchant_cache and (now - _merchant_cache_time) < _MERCHANT_CACHE_TTL:
        return _merchant_cache
    result = await db.execute(select(Merchant))
    _merchant_cache = list(result.scalars().all())
    _merchant_cache_time = now
    return _merchant_cache


def invalidate_merchant_cache() -> None:
    """Invalidate global and user-scoped merchant caches for deterministic refresh."""
    global _merchant_cache, _merchant_cache_time, _user_rule_cache
    _merchant_cache = []
    _merchant_cache_time = 0.0
    _user_rule_cache = {}


def invalidate_user_merchant_rule_cache(user_id: str) -> None:
    """Invalidate learned rules only for the user whose preferences changed."""
    _user_rule_cache.pop(user_id, None)


async def _get_cached_user_rules(db: AsyncSession, user_id: str) -> list[UserMerchantRule]:
    now = time.time()
    cached = _user_rule_cache.get(user_id)
    if cached and (now - cached[0]) < _MERCHANT_CACHE_TTL:
        return cached[1]
    result = await db.execute(select(UserMerchantRule).where(UserMerchantRule.user_id == user_id))
    rules = list(result.scalars().all())
    if user_id not in _user_rule_cache and len(_user_rule_cache) >= _USER_RULE_CACHE_MAX_USERS:
        oldest_user_id = min(_user_rule_cache, key=lambda key: _user_rule_cache[key][0])
        _user_rule_cache.pop(oldest_user_id, None)
    _user_rule_cache[user_id] = (now, rules)
    return rules


def _candidate_aliases(merchant: Merchant) -> list[str]:
    candidates = [merchant.normalized_name]
    candidates.extend(parse_merchant_aliases(merchant.aliases))
    return [candidate.strip() for candidate in candidates if candidate and candidate.strip()]


def _contains_candidate(raw_value: str, candidate: str) -> bool:
    """Match a catalog candidate on token boundaries, never inside another word."""
    return bool(
        re.search(
            rf"(?<!\w){re.escape(candidate.strip())}(?!\w)",
            raw_value,
            flags=re.IGNORECASE,
        )
    )


async def resolve_merchant(
    db: AsyncSession,
    raw_merchant: str,
    *,
    user_id: str | None = None,
) -> MerchantResolution:
    """Resolve a merchant with user rules taking precedence over shared catalog data."""
    if not raw_merchant:
        return MerchantResolution("Unknown", None, "fallback", 0.0)

    identity = extract_descriptor_identity(raw_merchant)
    descriptor_key = normalize_descriptor_key(raw_merchant)
    if user_id and descriptor_key:
        for rule in await _get_cached_user_rules(db, user_id):
            if rule.descriptor_key == descriptor_key:
                return MerchantResolution(
                    normalized_name=rule.normalized_name,
                    category_id=rule.category_id,
                    source="user_rule",
                    confidence=rule.confidence,
                    rule_id=rule.id,
                )

    candidate_value = identity.candidate
    candidate_key = normalize_descriptor_key(candidate_value)
    raw_upper = candidate_value.strip().upper()
    merchants = await _get_cached_merchants(db)

    # A canonical identity always outranks aliases, independent of database
    # row order. The old per-row loop allowed a stale alias on one merchant to
    # steal another merchant's exact canonical name.
    for merchant in merchants:
        if raw_upper == merchant.normalized_name.upper():
            return MerchantResolution(
                merchant.normalized_name,
                merchant.category_default_id,
                "canonical_name",
                1.0,
            )

    exact_alias_matches = [
        merchant
        for merchant in merchants
        if any(alias.upper() == raw_upper for alias in parse_merchant_aliases(merchant.aliases))
    ]
    if len(exact_alias_matches) == 1:
        merchant = exact_alias_matches[0]
        return MerchantResolution(
            merchant.normalized_name,
            merchant.category_default_id,
            "canonical_alias",
            0.98,
        )
    if len(exact_alias_matches) > 1:
        return MerchantResolution(
            _clean_merchant_name(candidate_value),
            None,
            "ambiguous_catalog_alias",
            0.0,
        )

    contained_matches: dict[str, tuple[Merchant, float, str]] = {}
    for merchant in merchants:
        for alias in parse_merchant_aliases(merchant.aliases):
            if _contains_candidate(candidate_value, alias):
                contained_matches[merchant.id] = (
                    merchant,
                    0.86,
                    "canonical_alias_contains",
                )
        if _contains_candidate(candidate_value, merchant.normalized_name):
            contained_matches.setdefault(
                merchant.id,
                (merchant, 0.8, "canonical_contains"),
            )
    if contained_matches:
        best_confidence = max(match[1] for match in contained_matches.values())
        best_matches = [
            match for match in contained_matches.values() if match[1] == best_confidence
        ]
        if len(best_matches) == 1:
            merchant, confidence, source = best_matches[0]
            return MerchantResolution(
                merchant.normalized_name,
                merchant.category_default_id,
                source,
                confidence,
            )
        return MerchantResolution(
            _clean_merchant_name(candidate_value),
            None,
            "ambiguous_catalog_contains",
            0.0,
        )

    if candidate_value == "Unknown" or not candidate_key:
        return MerchantResolution("Unknown", None, "unresolved_descriptor", 0.0)
    return MerchantResolution(
        _clean_merchant_name(candidate_value),
        None,
        "descriptor_rules",
        identity.confidence,
    )


async def normalize_merchant(
    db: AsyncSession,
    raw_merchant: str,
    *,
    user_id: str | None = None,
) -> tuple[str, str | None]:
    """Compatibility wrapper returning ``(normalized_name, category_id)``."""
    resolution = await resolve_merchant(db, raw_merchant, user_id=user_id)
    return resolution.normalized_name, resolution.category_id


async def infer_merchant_from_text(
    db: AsyncSession,
    text: str,
) -> tuple[str | None, str | None]:
    """Infer merchant by scanning the full email text for known aliases and merchant names."""
    if not text:
        return None, None

    normalized_text = re.sub(r"\s+", " ", text.upper())
    merchants = await _get_cached_merchants(db)

    best_match: tuple[str, str | None, int] | None = None
    for merchant in merchants:
        for candidate in _candidate_aliases(merchant):
            candidate_upper = candidate.upper()
            if candidate_upper in GENERIC_MERCHANTS or len(candidate_upper) < 4:
                continue
            if candidate_upper in normalized_text:
                candidate_len = len(candidate_upper)
                if best_match is None or candidate_len > best_match[2]:
                    best_match = (
                        merchant.normalized_name,
                        merchant.category_default_id,
                        candidate_len,
                    )

    if not best_match:
        return None, None

    return best_match[0], best_match[1]


async def get_default_category_id(db: AsyncSession) -> str | None:
    result = await db.execute(select(Category).where(Category.name == "Others"))
    cat = result.scalar_one_or_none()
    return cat.id if cat else None
