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
MERCHANT_RESOLVER_VERSION = 1


@dataclass(frozen=True)
class MerchantResolution:
    """Explainable merchant resolution result used by ingestion and review flows."""

    normalized_name: str
    category_id: str | None
    source: str
    confidence: float
    rule_id: str | None = None
    resolver_version: int = MERCHANT_RESOLVER_VERSION


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
}


def _clean_merchant_name(raw: str) -> str:
    cleaned = raw.strip().upper()
    for suffix in [
        " PV",
        " PVT",
        " LTD",
        " PRIVATE",
        " LIMITED",
        " INDIA",
        " ONLINE",
        " INTERNET",
        " SERVICES",
    ]:
        cleaned = cleaned.replace(suffix, "")
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

    raw_upper = raw_merchant.strip().upper()
    merchants = await _get_cached_merchants(db)

    for merchant in merchants:
        if raw_upper == merchant.normalized_name.upper():
            return MerchantResolution(
                merchant.normalized_name,
                merchant.category_default_id,
                "canonical_name",
                1.0,
            )
        for alias in parse_merchant_aliases(merchant.aliases):
            if alias.upper() == raw_upper:
                return MerchantResolution(
                    merchant.normalized_name,
                    merchant.category_default_id,
                    "canonical_alias",
                    0.98,
                )

    for merchant in merchants:
        for alias in parse_merchant_aliases(merchant.aliases):
            if _contains_candidate(raw_merchant, alias):
                return MerchantResolution(
                    merchant.normalized_name,
                    merchant.category_default_id,
                    "canonical_alias_contains",
                    0.86,
                )
        if _contains_candidate(raw_merchant, merchant.normalized_name):
            return MerchantResolution(
                merchant.normalized_name,
                merchant.category_default_id,
                "canonical_contains",
                0.8,
            )

    return MerchantResolution(_clean_merchant_name(raw_merchant), None, "cleaned_fallback", 0.5)


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
