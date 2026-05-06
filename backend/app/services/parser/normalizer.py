"""
Merchant Normalization Service
Maps raw merchant names to clean, normalized versions.
"""

import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Merchant, Category

logger = logging.getLogger(__name__)


def _clean_merchant_name(raw: str) -> str:
    cleaned = raw.strip().upper()
    for suffix in [" PV", " PVT", " LTD", " PRIVATE", " LIMITED",
                   " INDIA", " ONLINE", " INTERNET", " SERVICES"]:
        cleaned = cleaned.replace(suffix, "")
    return cleaned.strip().title()


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


async def get_default_category_id(db: AsyncSession) -> Optional[str]:
    result = await db.execute(select(Category).where(Category.name == "Others"))
    cat = result.scalar_one_or_none()
    return cat.id if cat else None
