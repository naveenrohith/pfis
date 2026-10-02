"""Seed only generated synthetic financial records into a fresh lab database."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.roadmap import Household, HouseholdMember  # noqa: E402
from app.models.transaction import Transaction, TransactionType  # noqa: E402
from app.models.user import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402


async def seed() -> None:
    identities = {
        "owner": (os.environ["LAB_OWNER_EMAIL"], os.environ["LAB_OWNER_PASSWORD"]),
        "member": (os.environ["LAB_MEMBER_EMAIL"], os.environ["LAB_MEMBER_PASSWORD"]),
        "viewer": (os.environ["LAB_VIEWER_EMAIL"], os.environ["LAB_VIEWER_PASSWORD"]),
    }
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        users: dict[str, User] = {}
        for role, (email, password) in identities.items():
            user = await session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    name=f"Synthetic {role.title()}",
                    password_hash=hash_password(password),
                    currency="INR",
                    timezone="Asia/Kolkata",
                    is_active=True,
                )
                session.add(user)
                await session.flush()
            users[role] = user

        for index, (role, user) in enumerate(users.items(), start=1):
            marker = f"security-lab-{role}-{user.id}"
            exists = await session.scalar(
                select(Transaction.id).where(Transaction.reference_id == marker)
            )
            if exists is None:
                session.add(
                    Transaction(
                        user_id=user.id,
                        amount=Decimal(450 + index * 125),
                        currency="INR",
                        transaction_type=TransactionType.DEBIT,
                        transaction_date=date(2026, 9, index),
                        transaction_timestamp=datetime(2026, 9, index, 12, tzinfo=UTC),
                        merchant_raw=f"Synthetic Market {index}",
                        merchant_normalized=f"Synthetic Market {index}",
                        account_last4=f"00{index:02d}",
                        reference_id=marker,
                        source_kind="manual",
                        reviewed_flag=True,
                        confidence_score=1.0,
                    )
                )

        owner = users["owner"]
        household = await session.scalar(
            select(Household).where(Household.owner_user_id == owner.id)
        )
        if household is None:
            household = Household(owner_user_id=owner.id, name="Synthetic PFIS Test Household")
            session.add(household)
            await session.flush()
        existing_members = set(
            (
                await session.scalars(
                    select(HouseholdMember.user_id).where(
                        HouseholdMember.household_id == household.id,
                        HouseholdMember.left_at.is_(None),
                    )
                )
            ).all()
        )
        for role in ("owner", "member", "viewer"):
            user = users[role]
            if user.id not in existing_members:
                session.add(
                    HouseholdMember(
                        household_id=household.id,
                        user_id=user.id,
                        role=role,
                        visibility="annotations_only",
                    )
                )
        await session.commit()
    await engine.dispose()


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
