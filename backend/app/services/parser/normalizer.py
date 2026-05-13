"""
Merchant Normalization Service
Maps raw merchant names to clean, normalized versions.
"""

import json
import logging
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Merchant, Category

logger = logging.getLogger(__name__)

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
    for suffix in [" PV", " PVT", " LTD", " PRIVATE", " LIMITED",
                   " INDIA", " ONLINE", " INTERNET", " SERVICES"]:
        cleaned = cleaned.replace(suffix, "")
    return cleaned.strip().title()


def _candidate_aliases(merchant: Merchant) -> list[str]:
    candidates = [merchant.normalized_name]
    try:
        aliases = json.loads(merchant.aliases) if merchant.aliases else []
    except (json.JSONDecodeError, TypeError):
        aliases = []
    candidates.extend(alias for alias in aliases if isinstance(alias, str))
    return [candidate.strip() for candidate in candidates if candidate and candidate.strip()]


async def normalize_merchant(db: AsyncSession, raw_merchant: str) -> tuple[str, Optional[str]]:
    """Returns (normalized_name, category_id)."""
    if not raw_merchant:
        return "Unknown", None

    raw_upper = raw_merchant.strip().upper()
    result = await db.execute(select(Merchant))
    merchants = result.scalars().all()

    for merchant in merchants:
        if raw_upper == merchant.normalized_name.upper():
            return merchant.normalized_name, merchant.category_default_id
        try:
            aliases = json.loads(merchant.aliases) if merchant.aliases else []
        except (json.JSONDecodeError, TypeError):
            aliases = []
        for alias in aliases:
            if alias.upper() == raw_upper or alias.upper() in raw_upper:
                return merchant.normalized_name, merchant.category_default_id

    for merchant in merchants:
        if merchant.normalized_name.upper() in raw_upper:
            return merchant.normalized_name, merchant.category_default_id

    return _clean_merchant_name(raw_merchant), None


async def infer_merchant_from_text(
    db: AsyncSession,
    text: str,
) -> tuple[Optional[str], Optional[str]]:
    """Infer merchant by scanning the full email text for known aliases and merchant names."""
    if not text:
        return None, None

    normalized_text = re.sub(r"\s+", " ", text.upper())
    result = await db.execute(select(Merchant))
    merchants = result.scalars().all()

    best_match: tuple[str, Optional[str], int] | None = None
    for merchant in merchants:
        for candidate in _candidate_aliases(merchant):
            candidate_upper = candidate.upper()
            if candidate_upper in GENERIC_MERCHANTS or len(candidate_upper) < 4:
                continue
            if candidate_upper in normalized_text:
                candidate_len = len(candidate_upper)
                if best_match is None or candidate_len > best_match[2]:
                    best_match = (merchant.normalized_name, merchant.category_default_id, candidate_len)

    if not best_match:
        return None, None

    return best_match[0], best_match[1]


async def get_default_category_id(db: AsyncSession) -> Optional[str]:
    result = await db.execute(select(Category).where(Category.name == "Others"))
    cat = result.scalar_one_or_none()
    return cat.id if cat else None
