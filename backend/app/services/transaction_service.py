"""
Transaction Service
Business logic for creating, reading, and summarizing transactions.
Keeps routes thin — all logic lives here.
"""

import hashlib
import logging
from datetime import date
from typing import Optional
from sqlalchemy import select, func, extract
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionType
from app.models.category import Category
from app.schemas.transaction import TransactionCreate, TransactionUpdate

logger = logging.getLogger(__name__)


class TransactionService:
    """Service layer for transaction operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Fingerprint (Dedup) ---

    @staticmethod
    def compute_fingerprint(
        amount: float,
        transaction_date: date,
        merchant: Optional[str],
        reference_id: Optional[str],
        account_last4: Optional[str] = None,
    ) -> str:
        """
        Compute SHA-256 fingerprint for deduplication.
        Uses: amount + date + merchant + ref_id + account
        """
        raw = "|".join([
            str(amount),
            str(transaction_date),
            (merchant or "unknown").lower().strip(),
            reference_id or "",
            account_last4 or "",
        ])
        return hashlib.sha256(raw.encode()).hexdigest()

    # --- CRUD ---

    async def create_transaction(
        self, user_id: str, data: TransactionCreate
    ) -> Transaction:
        """Create a new transaction with dedup fingerprint."""

        fingerprint = self.compute_fingerprint(
            amount=data.amount,
            transaction_date=data.transaction_date,
            merchant=data.merchant_normalized or data.merchant_raw,
            reference_id=data.reference_id,
            account_last4=data.account_last4,
        )

        # Check for duplicate
        existing = await self.db.execute(
            select(Transaction).where(Transaction.fingerprint == fingerprint)
        )
        if existing.scalar_one_or_none():
            logger.info(f"Duplicate transaction detected: fingerprint={fingerprint[:16]}...")
            raise ValueError("Duplicate transaction detected")

        txn = Transaction(
            user_id=user_id,
            amount=data.amount,
            currency=data.currency,
            transaction_type=data.transaction_type,
            merchant_raw=data.merchant_raw,
            merchant_normalized=data.merchant_normalized,
            category_id=data.category_id,
            transaction_date=data.transaction_date,
            account_last4=data.account_last4,
            reference_id=data.reference_id,
            confidence_score=data.confidence_score,
            source_email_id=data.source_email_id,
            fingerprint=fingerprint,
        )

        self.db.add(txn)
        await self.db.commit()
        await self.db.refresh(txn)

        logger.info(
            f"Transaction created: {txn.merchant_normalized} ₹{txn.amount} "
            f"[confidence={txn.confidence_score}]"
        )
        return txn

    async def get_transactions(
        self,
        user_id: str,
        month: Optional[int] = None,
        year: Optional[int] = None,
        category_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Transaction]:
        """Fetch transactions with optional filters."""
        query = select(Transaction).where(Transaction.user_id == user_id)

        if month and year:
            query = query.where(
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        if category_id:
            query = query.where(Transaction.category_id == category_id)

        query = query.order_by(Transaction.transaction_date.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_transaction_by_id(self, txn_id: str) -> Optional[Transaction]:
        """Get a single transaction by ID."""
        result = await self.db.execute(
            select(Transaction).where(Transaction.id == txn_id)
        )
        return result.scalar_one_or_none()

    async def update_transaction(
        self, txn_id: str, data: TransactionUpdate
    ) -> Optional[Transaction]:
        """Update transaction fields (user correction)."""
        txn = await self.get_transaction_by_id(txn_id)
        if not txn:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(txn, field, value)

        await self.db.commit()
        await self.db.refresh(txn)
        logger.info(f"Transaction updated: {txn_id} fields={list(update_data.keys())}")
        return txn

    # --- Aggregations ---

    async def get_monthly_summary(
        self, user_id: str, month: int, year: int
    ) -> dict:
        """Compute monthly spending summary."""

        # Total spend (debits)
        spend_result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        total_spend = float(spend_result.scalar())

        # Total income (credits)
        income_result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.CREDIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        total_income = float(income_result.scalar())

        # Transaction count
        count_result = await self.db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user_id,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        count = int(count_result.scalar())

        # Category breakdown
        cat_result = await self.db.execute(
            select(
                Category.name,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Category.name)
            .order_by(func.sum(Transaction.amount).desc())
        )
        categories = [
            {"name": row.name or "Uncategorized", "total": float(row.total), "count": row.count}
            for row in cat_result.all()
        ]

        # Top merchants
        merchant_result = await self.db.execute(
            select(
                Transaction.merchant_normalized,
                func.sum(Transaction.amount).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.merchant_normalized)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(10)
        )
        merchants = [
            {"name": row.merchant_normalized or "Unknown", "total": float(row.total), "count": row.count}
            for row in merchant_result.all()
        ]

        return {
            "total_spend": total_spend,
            "total_income": total_income,
            "net": total_income - total_spend,
            "transaction_count": count,
            "month": f"{year}-{month:02d}",
            "category_breakdown": categories,
            "top_merchants": merchants,
        }
