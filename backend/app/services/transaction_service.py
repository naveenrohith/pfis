"""
Transaction Service
Business logic for creating, reading, and summarizing transactions.
Keeps routes thin — all logic lives here.
"""

import json
import hashlib
import logging
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import select, func, extract
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionType
from app.models.category import Category, Merchant
from app.models.sync import UserCorrection
from app.schemas.transaction import TransactionCreate, TransactionUpdate

logger = logging.getLogger(__name__)
AUTO_REVIEW_THRESHOLD = 0.85


class TransactionService:
    """Service layer for transaction operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Fingerprint (Dedup) ---

    @staticmethod
    def compute_fingerprint(
        user_id: str,
        amount: float,
        transaction_date: date,
        merchant: Optional[str],
        reference_id: Optional[str],
        account_last4: Optional[str] = None,
    ) -> str:
        """
        Compute SHA-256 fingerprint for deduplication.
        Uses: user + amount + date + merchant + ref_id + account
        """
        raw = "|".join([
            user_id,
            str(amount),
            str(transaction_date),
            (merchant or "unknown").lower().strip(),
            reference_id or "",
            account_last4 or "",
        ])
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _serialize_correction_value(value) -> Optional[str]:
        """Serialize values consistently for correction history."""
        if value is None:
            return None
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    async def _record_corrections(
        self,
        txn_id: str,
        changes: dict[str, tuple[object, object]],
    ) -> None:
        """Persist a correction history row for every changed field."""
        for field, (old_value, new_value) in changes.items():
            if field == "reviewed_flag":
                continue
            self.db.add(
                UserCorrection(
                    transaction_id=txn_id,
                    field_corrected=field,
                    old_value=self._serialize_correction_value(old_value),
                    new_value=self._serialize_correction_value(new_value) or "",
                )
            )

    async def _learn_from_correction(
        self,
        txn: Transaction,
        changed_fields: set[str],
    ) -> None:
        """Feed merchant/category corrections back into normalization defaults."""
        if not ({"merchant_normalized", "category_id"} & changed_fields):
            return

        normalized_name = (txn.merchant_normalized or "").strip()
        if not normalized_name:
            return

        result = await self.db.execute(
            select(Merchant).where(func.lower(Merchant.normalized_name) == normalized_name.lower())
        )
        merchant = result.scalar_one_or_none()

        raw_alias = (txn.merchant_raw or "").strip()
        if merchant is None:
            aliases = [raw_alias] if raw_alias else []
            self.db.add(
                Merchant(
                    normalized_name=normalized_name,
                    aliases=json.dumps(aliases),
                    category_default_id=txn.category_id,
                )
            )
            return

        try:
            aliases = json.loads(merchant.aliases) if merchant.aliases else []
        except (TypeError, json.JSONDecodeError):
            aliases = []

        alias_keys = {
            alias.strip().upper()
            for alias in aliases
            if isinstance(alias, str) and alias.strip()
        }
        if raw_alias and raw_alias.upper() not in alias_keys and raw_alias.upper() != merchant.normalized_name.upper():
            aliases.append(raw_alias)
            merchant.aliases = json.dumps(aliases)

        if txn.category_id:
            merchant.category_default_id = txn.category_id

    # --- CRUD ---

    async def create_transaction(
        self, user_id: str, data: TransactionCreate
    ) -> Transaction:
        """Create a new transaction with dedup fingerprint."""

        fingerprint = self.compute_fingerprint(
            user_id=user_id,
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
            reviewed_flag=data.confidence_score >= AUTO_REVIEW_THRESHOLD,
            reviewed_at=datetime.now(timezone.utc) if data.confidence_score >= AUTO_REVIEW_THRESHOLD else None,
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
        query = (
            select(Transaction)
            .options(selectinload(Transaction.category))
            .where(Transaction.user_id == user_id)
        )

        if month and year:
            query = query.where(
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        if category_id:
            query = query.where(Transaction.category_id == category_id)

        query = query.order_by(Transaction.transaction_date.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())
        for txn in transactions:
            txn.category_name = txn.category.name if txn.category else None
        return transactions

    async def get_transaction_by_id(self, txn_id: str) -> Optional[Transaction]:
        """Get a single transaction by ID."""
        result = await self.db.execute(
            select(Transaction)
            .options(selectinload(Transaction.category))
            .where(Transaction.id == txn_id)
        )
        txn = result.scalar_one_or_none()
        if txn:
            txn.category_name = txn.category.name if txn.category else None
        return txn

    async def update_transaction(
        self, txn_id: str, data: TransactionUpdate
    ) -> Optional[Transaction]:
        """Update transaction fields (user correction)."""
        txn = await self.get_transaction_by_id(txn_id)
        if not txn:
            return None

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return txn

        changed_fields: dict[str, tuple[object, object]] = {}
        now = datetime.now(timezone.utc)
        for field, value in update_data.items():
            current_value = getattr(txn, field)
            if field == "reviewed_flag":
                value = bool(value)
            if current_value != value:
                changed_fields[field] = (current_value, value)
                setattr(txn, field, value)

        if not changed_fields:
            return txn

        if "reviewed_flag" in changed_fields:
            txn.reviewed_at = now if txn.reviewed_flag else None

        corrected_fields = set(changed_fields) - {"reviewed_flag"}
        if corrected_fields and "reviewed_flag" not in update_data and not txn.reviewed_flag:
            changed_fields["reviewed_flag"] = (txn.reviewed_flag, True)
            txn.reviewed_flag = True
            txn.reviewed_at = now

        if {"amount", "merchant_normalized"} & corrected_fields:
            new_fingerprint = self.compute_fingerprint(
                user_id=txn.user_id,
                amount=txn.amount,
                transaction_date=txn.transaction_date,
                merchant=txn.merchant_normalized or txn.merchant_raw,
                reference_id=txn.reference_id,
                account_last4=txn.account_last4,
            )
            if new_fingerprint != txn.fingerprint:
                existing = await self.db.execute(
                    select(Transaction).where(
                        Transaction.fingerprint == new_fingerprint,
                        Transaction.id != txn.id,
                    )
                )
                if existing.scalar_one_or_none():
                    raise ValueError("Correction would create a duplicate transaction")
                txn.fingerprint = new_fingerprint

        await self._record_corrections(txn.id, changed_fields)
        await self._learn_from_correction(txn, set(changed_fields))

        await self.db.commit()
        await self.db.refresh(txn)
        if txn.category_id:
            await self.db.refresh(txn, attribute_names=["category"])
        txn.category_name = txn.category.name if txn.category else None
        logger.info(f"Transaction updated: {txn_id} fields={list(changed_fields.keys())}")
        return txn

    async def bulk_update_transactions(
        self,
        user_id: str,
        data,
    ) -> dict:
        """Apply shared review updates across multiple transactions."""
        transaction_ids = list(dict.fromkeys(data.transaction_ids))
        payload = {
            key: value
            for key, value in data.model_dump(exclude_unset=True).items()
            if key != "transaction_ids"
        }

        if not payload:
            return {
                "requested_count": len(transaction_ids),
                "updated_count": 0,
                "failed": [{"transaction_id": txn_id, "error": "No update fields provided"} for txn_id in transaction_ids],
            }

        result = await self.db.execute(
            select(Transaction.id).where(
                Transaction.user_id == user_id,
                Transaction.id.in_(transaction_ids),
            )
        )
        available_ids = {row[0] for row in result.all()}

        failed: list[dict] = []
        updated_count = 0

        for txn_id in transaction_ids:
            if txn_id not in available_ids:
                failed.append({"transaction_id": txn_id, "error": "Transaction not found"})
                continue

            try:
                await self.update_transaction(txn_id, TransactionUpdate(**payload))
                updated_count += 1
            except ValueError as exc:
                failed.append({"transaction_id": txn_id, "error": str(exc)})

        return {
            "requested_count": len(transaction_ids),
            "updated_count": updated_count,
            "failed": failed,
        }

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
                Category.id,
                Category.name,
                Category.icon,
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
            .group_by(Category.id, Category.name, Category.icon)
            .order_by(func.sum(Transaction.amount).desc())
        )
        categories = [
            {
                "category_id": row.id,
                "name": row.name or "Uncategorized",
                "icon": row.icon or "📦",
                "total": float(row.total),
                "count": row.count,
            }
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
