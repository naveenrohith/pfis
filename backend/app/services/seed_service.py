"""
Seed Service
Seeds the database with default categories and sample merchants.
"""

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.category import Category, Merchant
from app.models.user import User

logger = logging.getLogger(__name__)

# Default categories with icons
DEFAULT_CATEGORIES = [
    {"name": "Food", "icon": "🍔"},
    {"name": "Shopping", "icon": "🛍️"},
    {"name": "Travel", "icon": "✈️"},
    {"name": "Transport", "icon": "🚕"},
    {"name": "Bills", "icon": "📄"},
    {"name": "Subscription", "icon": "🔁"},
    {"name": "Entertainment", "icon": "🎬"},
    {"name": "Health", "icon": "🏥"},
    {"name": "Education", "icon": "📚"},
    {"name": "Groceries", "icon": "🥦"},
    {"name": "Fuel", "icon": "⛽"},
    {"name": "Others", "icon": "📦"},
]

# Default merchant → category mappings
DEFAULT_MERCHANTS = [
    {"name": "Swiggy", "aliases": '["SWIGGY", "SWIGGY INDIA", "SWIGGY ONLINE"]', "category": "Food"},
    {"name": "Zomato", "aliases": '["ZOMATO", "ZOMATO ORDER", "ZOMATO ONLINE"]', "category": "Food"},
    {"name": "Amazon", "aliases": '["AMAZON", "AMAZON.IN", "AMAZON PAY", "AMZN"]', "category": "Shopping"},
    {"name": "Flipkart", "aliases": '["FLIPKART", "FLIPKART INDIA"]', "category": "Shopping"},
    {"name": "Uber", "aliases": '["UBER", "UBER INDIA", "UBER TRIP"]', "category": "Transport"},
    {"name": "Ola", "aliases": '["OLA", "OLA CABS", "ANI TECHNOLOGIES"]', "category": "Transport"},
    {"name": "Netflix", "aliases": '["NETFLIX", "NETFLIX.COM"]', "category": "Subscription"},
    {"name": "Spotify", "aliases": '["SPOTIFY", "SPOTIFY INDIA"]', "category": "Subscription"},
    {"name": "Myntra", "aliases": '["MYNTRA", "MYNTRA.COM"]', "category": "Shopping"},
    {"name": "BigBasket", "aliases": '["BIGBASKET", "BIG BASKET"]', "category": "Groceries"},
    {"name": "PharmEasy", "aliases": '["PHARMEASY", "PHARM EASY"]', "category": "Health"},
    {"name": "Jio", "aliases": '["JIO", "RELIANCE JIO"]', "category": "Bills"},
    {"name": "Airtel", "aliases": '["AIRTEL", "BHARTI AIRTEL"]', "category": "Bills"},
    {"name": "IRCTC", "aliases": '["IRCTC", "IRCTC RAIL"]', "category": "Travel"},
]


async def seed_categories(db: AsyncSession) -> dict[str, str]:
    """Seed default categories, returns name→id mapping."""
    category_map = {}

    for cat_data in DEFAULT_CATEGORIES:
        result = await db.execute(
            select(Category).where(Category.name == cat_data["name"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            category_map[cat_data["name"]] = existing.id
        else:
            cat = Category(name=cat_data["name"], icon=cat_data["icon"])
            db.add(cat)
            await db.flush()
            category_map[cat_data["name"]] = cat.id
            logger.info(f"Seeded category: {cat_data['name']}")

    await db.commit()
    return category_map


async def seed_merchants(db: AsyncSession, category_map: dict[str, str]):
    """Seed default merchants with category mappings."""
    for merch_data in DEFAULT_MERCHANTS:
        result = await db.execute(
            select(Merchant).where(Merchant.normalized_name == merch_data["name"])
        )
        existing = result.scalar_one_or_none()

        if not existing:
            cat_id = category_map.get(merch_data["category"])
            merch = Merchant(
                normalized_name=merch_data["name"],
                aliases=merch_data["aliases"],
                category_default_id=cat_id,
            )
            db.add(merch)
            logger.info(f"Seeded merchant: {merch_data['name']} → {merch_data['category']}")

    await db.commit()


async def seed_demo_user(db: AsyncSession) -> str:
    """Create a demo user for testing. Returns user ID."""
    result = await db.execute(
        select(User).where(User.email == "demo@pfis.local")
    )
    existing = result.scalar_one_or_none()

    if existing:
        return existing.id

    user = User(email="demo@pfis.local", name="Demo User", currency="INR")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"Seeded demo user: {user.email} (id={user.id})")
    return user.id


async def run_seeds(db: AsyncSession):
    """Run all seed operations."""
    logger.info("🌱 Seeding database...")
    category_map = await seed_categories(db)
    await seed_merchants(db, category_map)
    demo_user_id = await seed_demo_user(db)
    logger.info(f"✅ Seeding complete. Demo user ID: {demo_user_id}")
    return demo_user_id
