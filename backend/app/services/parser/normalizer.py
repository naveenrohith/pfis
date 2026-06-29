"""
Merchant Normalization Service
Maps raw merchant names to clean, normalized versions.
Includes TTL-based caching to avoid full table scans on every parse.
"""

import logging
import re
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category, Merchant, parse_merchant_aliases

logger = logging.getLogger(__name__)

# Cache for merchant data (TTL-based)
_merchant_cache: list = []
_merchant_cache_time: float = 0.0
_MERCHANT_CACHE_TTL: float = 60.0  # seconds

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
    """Invalidate the merchant cache (call after merchant table mutations)."""
    global _merchant_cache, _merchant_cache_time
    _merchant_cache = []
    _merchant_cache_time = 0.0


def _candidate_aliases(merchant: Merchant) -> list[str]:
    candidates = [merchant.normalized_name]
    candidates.extend(parse_merchant_aliases(merchant.aliases))
    return [candidate.strip() for candidate in candidates if candidate and candidate.strip()]


async def normalize_merchant(db: AsyncSession, raw_merchant: str) -> tuple[str, str | None]:
    """Returns (normalized_name, category_id)."""
    if not raw_merchant:
        return "Unknown", None

    raw_upper = raw_merchant.strip().upper()
    merchants = await _get_cached_merchants(db)

    for merchant in merchants:
        if raw_upper == merchant.normalized_name.upper():
            return merchant.normalized_name, merchant.category_default_id
        for alias in parse_merchant_aliases(merchant.aliases):
            if alias.upper() == raw_upper or alias.upper() in raw_upper:
                return merchant.normalized_name, merchant.category_default_id

    for merchant in merchants:
        if merchant.normalized_name.upper() in raw_upper:
            return merchant.normalized_name, merchant.category_default_id

    return _clean_merchant_name(raw_merchant), None


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
