"""
Transaction Service
Business logic for creating, reading, and summarizing transactions.
Keeps routes thin — all logic lives here.
"""

import hashlib
import json
import logging
from datetime import UTC, date, datetime

from sqlalchemy import asc, delete, desc, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import FinancialAccount
from app.models.category import Category, UserMerchantRule
from app.models.summary import MonthlySummary
from app.models.sync import UserCorrection
from app.models.transaction import Transaction, TransactionType
from app.schemas.transaction import TransactionCreate, TransactionUpdate

logger = logging.getLogger(__name__)
AUTO_REVIEW_THRESHOLD = 0.85


class DuplicateTransactionError(ValueError):
    """Raised when a transaction (or correction) collides with an existing row.

    Subclasses ``ValueError`` so existing callers that map ``ValueError`` to an
    HTTP 409 keep working, while letting the pipeline distinguish a genuine
    duplicate from an unrelated value error.
    """


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
        merchant: str | None,
        reference_id: str | None,
        account_last4: str | None = None,
    ) -> str:
        """
        Compute SHA-256 fingerprint for deduplication.
        Uses: user + amount + date + merchant + ref_id + account
        """
        raw = "|".join(
            [
                user_id,
                str(amount),
                str(transaction_date),
                (merchant or "unknown").lower().strip(),
                reference_id or "",
                account_last4 or "",
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _serialize_correction_value(value) -> str | None:
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

    async def upsert_user_merchant_rule(
        self,
        *,
        user_id: str,
        raw_descriptor: str,
        normalized_name: str,
        category_id: str | None,
        source: str,
        source_transaction_id: str | None = None,
    ) -> UserMerchantRule | None:
        """Create or refresh an exact user-owned merchant normalization rule."""
        from app.services.parser.normalizer import (
            invalidate_user_merchant_rule_cache,
            normalize_descriptor_key,
        )

        raw_descriptor = raw_descriptor.strip()
        normalized_name = normalized_name.strip()
        descriptor_key = normalize_descriptor_key(raw_descriptor)
        if not descriptor_key or not normalized_name:
            return None

        result = await self.db.execute(
            select(UserMerchantRule).where(
                UserMerchantRule.user_id == user_id,
                UserMerchantRule.descriptor_key == descriptor_key,
            )
        )
        rule = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if rule is None:
            rule = UserMerchantRule(
                user_id=user_id,
                raw_descriptor=raw_descriptor,
                descriptor_key=descriptor_key,
                normalized_name=normalized_name,
                category_id=category_id,
                source=source,
                confidence=1.0,
                source_transaction_id=source_transaction_id,
                created_at=now,
                updated_at=now,
            )
            self.db.add(rule)
        else:
            rule.raw_descriptor = raw_descriptor
            rule.normalized_name = normalized_name
            rule.category_id = category_id
            rule.source = source
            rule.confidence = 1.0
            if source_transaction_id is not None:
                rule.source_transaction_id = source_transaction_id
            rule.updated_at = now

        await self.db.flush()
        invalidate_user_merchant_rule_cache(user_id)
        return rule

    async def _learn_from_correction(
        self,
        txn: Transaction,
        changed_fields: set[str],
    ) -> UserMerchantRule | None:
        """Feed merchant/category corrections into an exact user-owned rule."""
        if not ({"merchant_normalized", "category_id"} & changed_fields):
            return None

        normalized_name = (txn.merchant_normalized or "").strip()
        if not normalized_name:
            return None

        raw_alias = (txn.merchant_raw or "").strip()
        if not raw_alias:
            return None
        return await self.upsert_user_merchant_rule(
            user_id=txn.user_id,
            raw_descriptor=raw_alias,
            normalized_name=normalized_name,
            category_id=txn.category_id,
            source="transaction_correction",
            source_transaction_id=txn.id,
        )

    async def _invalidate_monthly_summary(self, user_id: str, transaction_date: date) -> None:
        """Remove the affected aggregate snapshot before committing a mutation."""
        await self.db.execute(
            delete(MonthlySummary).where(
                MonthlySummary.user_id == user_id,
                MonthlySummary.month == transaction_date.month,
                MonthlySummary.year == transaction_date.year,
            )
        )

    # --- CRUD ---

    async def create_transaction(self, user_id: str, data: TransactionCreate) -> Transaction:
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
            raise DuplicateTransactionError("Duplicate transaction detected")

        financial_account_id = data.financial_account_id
        if financial_account_id:
            account_result = await self.db.execute(
                select(FinancialAccount).where(
                    FinancialAccount.id == financial_account_id,
                    FinancialAccount.user_id == user_id,
                )
            )
            if account_result.scalar_one_or_none() is None:
                raise ValueError("Financial account not found")
        elif data.account_last4:
            masked_number = f"****{data.account_last4}"
            account_result = await self.db.execute(
                select(FinancialAccount).where(
                    FinancialAccount.user_id == user_id,
                    FinancialAccount.masked_number == masked_number,
                )
            )
            account = account_result.scalar_one_or_none()
            if account is None:
                account = FinancialAccount(
                    user_id=user_id,
                    institution_name="Unknown",
                    account_type="unknown",
                    masked_number=masked_number,
                    currency=data.currency,
                )
                self.db.add(account)
                await self.db.flush()
            financial_account_id = account.id

        txn = Transaction(
            user_id=user_id,
            amount=data.amount,
            currency=data.currency,
            transaction_type=data.transaction_type,
            payment_method=data.payment_method,
            transaction_status=data.transaction_status,
            transaction_timestamp=data.transaction_timestamp,
            merchant_raw=data.merchant_raw,
            merchant_normalized=data.merchant_normalized,
            category_id=data.category_id,
            transaction_date=data.transaction_date,
            account_last4=data.account_last4,
            reference_id=data.reference_id,
            confidence_score=data.confidence_score,
            parser_version=data.parser_version,
            merchant_resolution_source=data.merchant_resolution_source,
            merchant_resolution_confidence=data.merchant_resolution_confidence,
            merchant_rule_id=data.merchant_rule_id,
            merchant_resolver_version=data.merchant_resolver_version,
            reviewed_flag=data.confidence_score >= AUTO_REVIEW_THRESHOLD,
            reviewed_at=(
                datetime.now(UTC) if data.confidence_score >= AUTO_REVIEW_THRESHOLD else None
            ),
            source_email_id=data.source_email_id,
            fingerprint=fingerprint,
            financial_account_id=financial_account_id,
        )

        self.db.add(txn)
        await self._invalidate_monthly_summary(user_id, data.transaction_date)
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
        month: int | None = None,
        year: int | None = None,
        category_id: str | None = None,
        q: str | None = None,
        transaction_type: str | None = None,
        payment_method: str | None = None,
        reviewed: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        sort: str = "transaction_date",
        direction: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Transaction]:
        """Fetch transactions with optional filters."""
        query = (
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.source_email))
            .where(Transaction.user_id == user_id)
        )

        if month and year:
            query = query.where(
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        if category_id:
            query = query.where(Transaction.category_id == category_id)
        query = self._apply_list_filters(
            query,
            q=q,
            transaction_type=transaction_type,
            payment_method=payment_method,
            reviewed=reviewed,
            date_from=date_from,
            date_to=date_to,
            amount_min=amount_min,
            amount_max=amount_max,
        )
        sort_columns = {
            "transaction_date": Transaction.transaction_date,
            "amount": Transaction.amount,
            "merchant": Transaction.merchant_normalized,
            "created_at": Transaction.created_at,
        }
        sort_column = sort_columns.get(sort, Transaction.transaction_date)
        order = asc(sort_column) if direction == "asc" else desc(sort_column)
        query = query.order_by(order, Transaction.id.desc()).limit(limit).offset(offset)
        result = await self.db.execute(query)
        transactions = list(result.scalars().all())
        for txn in transactions:
            txn.category_name = txn.category.name if txn.category else None
        return transactions

    async def get_transaction_by_id(self, txn_id: str) -> Transaction | None:
        """Get a single transaction by ID."""
        result = await self.db.execute(
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.source_email))
            .where(Transaction.id == txn_id)
        )
        txn = result.scalar_one_or_none()
        if txn:
            txn.category_name = txn.category.name if txn.category else None
        return txn

    async def update_transaction(self, txn_id: str, data: TransactionUpdate) -> Transaction | None:
        """Update transaction fields (user correction)."""
        txn = await self.get_transaction_by_id(txn_id)
        if not txn:
            return None

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return txn

        changed_fields: dict[str, tuple[object, object]] = {}
        now = datetime.now(UTC)
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
                    raise DuplicateTransactionError(
                        "Correction would create a duplicate transaction"
                    )
                txn.fingerprint = new_fingerprint

        await self._record_corrections(txn.id, changed_fields)
        learned_rule = await self._learn_from_correction(txn, set(changed_fields))
        if learned_rule is not None:
            txn.merchant_resolution_source = "user_rule"
            txn.merchant_resolution_confidence = learned_rule.confidence
            txn.merchant_rule_id = learned_rule.id
            txn.merchant_resolver_version = 1
        await self._invalidate_monthly_summary(txn.user_id, txn.transaction_date)

        await self.db.commit()
        await self.db.refresh(txn)
        if txn.category_id:
            await self.db.refresh(txn, attribute_names=["category"])
        txn.category_name = txn.category.name if txn.category else None
        logger.info(f"Transaction updated: {txn_id} fields={list(changed_fields.keys())}")
        return txn

    async def bulk_correct_merchant(
        self,
        *,
        user_id: str,
        current_name: str,
        normalized_name: str,
        category_id: str | None,
        rule_category_id: str | None,
        aliases: list[str],
        apply_existing: bool,
    ) -> int:
        """Apply a user-scoped merchant correction atomically and preserve ledger invariants."""
        normalized_name = normalized_name.strip()
        if not normalized_name:
            raise ValueError("Normalized merchant name is required")
        if rule_category_id is not None:
            category_result = await self.db.execute(
                select(Category.id).where(Category.id == rule_category_id)
            )
            if category_result.scalar_one_or_none() is None:
                raise ValueError("Category not found")

        transactions: list[Transaction] = []
        if apply_existing:
            result = await self.db.execute(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    or_(
                        func.lower(Transaction.merchant_normalized) == current_name.lower(),
                        func.lower(Transaction.merchant_raw) == current_name.lower(),
                    ),
                )
            )
            transactions = list(result.scalars().all())

        planned_fingerprints: dict[str, str] = {}
        for txn in transactions:
            if txn.merchant_normalized == normalized_name:
                continue
            fingerprint = self.compute_fingerprint(
                user_id=txn.user_id,
                amount=txn.amount,
                transaction_date=txn.transaction_date,
                merchant=normalized_name,
                reference_id=txn.reference_id,
                account_last4=txn.account_last4,
            )
            owner = planned_fingerprints.get(fingerprint)
            if owner is not None and owner != txn.id:
                raise DuplicateTransactionError(
                    "Merchant correction would create duplicate transactions"
                )
            planned_fingerprints[fingerprint] = txn.id

        if planned_fingerprints:
            existing = await self.db.execute(
                select(Transaction.id, Transaction.fingerprint).where(
                    Transaction.fingerprint.in_(planned_fingerprints),
                    Transaction.id.not_in([txn.id for txn in transactions]),
                )
            )
            if existing.first() is not None:
                raise DuplicateTransactionError(
                    "Merchant correction would create a duplicate transaction"
                )

        affected_periods: set[tuple[int, int]] = set()
        for txn in transactions:
            changes: dict[str, tuple[object, object]] = {}
            if txn.merchant_normalized != normalized_name:
                changes["merchant_normalized"] = (txn.merchant_normalized, normalized_name)
                txn.merchant_normalized = normalized_name
                txn.fingerprint = self.compute_fingerprint(
                    user_id=txn.user_id,
                    amount=txn.amount,
                    transaction_date=txn.transaction_date,
                    merchant=normalized_name,
                    reference_id=txn.reference_id,
                    account_last4=txn.account_last4,
                )
            if category_id is not None and txn.category_id != category_id:
                changes["category_id"] = (txn.category_id, category_id)
                txn.category_id = category_id
            if not changes:
                continue

            if not txn.reviewed_flag:
                changes["reviewed_flag"] = (False, True)
                txn.reviewed_flag = True
                txn.reviewed_at = datetime.now(UTC)
            await self._record_corrections(txn.id, changes)
            rule = await self.upsert_user_merchant_rule(
                user_id=user_id,
                raw_descriptor=txn.merchant_raw or current_name,
                normalized_name=normalized_name,
                category_id=txn.category_id,
                source="merchant_edit",
                source_transaction_id=txn.id,
            )
            if rule is not None:
                txn.merchant_resolution_source = "user_rule"
                txn.merchant_resolution_confidence = rule.confidence
                txn.merchant_rule_id = rule.id
                txn.merchant_resolver_version = 1
            affected_periods.add((txn.transaction_date.month, txn.transaction_date.year))

        rule_inputs = {current_name, *aliases}
        for raw_descriptor in sorted(value.strip() for value in rule_inputs if value.strip()):
            await self.upsert_user_merchant_rule(
                user_id=user_id,
                raw_descriptor=raw_descriptor,
                normalized_name=normalized_name,
                category_id=rule_category_id,
                source="merchant_edit",
            )

        for month, year in affected_periods:
            await self.db.execute(
                delete(MonthlySummary).where(
                    MonthlySummary.user_id == user_id,
                    MonthlySummary.month == month,
                    MonthlySummary.year == year,
                )
            )

        await self.db.commit()
        return len(transactions)

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
                "failed": [
                    {"transaction_id": txn_id, "error": "No update fields provided"}
                    for txn_id in transaction_ids
                ],
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

    async def delete_transaction(self, txn_id: str) -> bool:
        """Delete a transaction by ID. Returns True if deleted."""
        result = await self.db.execute(select(Transaction).where(Transaction.id == txn_id))
        txn = result.scalar_one_or_none()
        if not txn:
            return False
        await self._invalidate_monthly_summary(txn.user_id, txn.transaction_date)
        await self.db.delete(txn)
        await self.db.commit()
        logger.info(f"Transaction deleted: {txn_id}")
        return True

    async def get_transaction_count(
        self,
        user_id: str,
        month: int | None = None,
        year: int | None = None,
        category_id: str | None = None,
        q: str | None = None,
        transaction_type: str | None = None,
        payment_method: str | None = None,
        reviewed: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
    ) -> int:
        """Get total count of transactions matching filters (for pagination)."""
        query = select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
        if month and year:
            query = query.where(
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        if category_id:
            query = query.where(Transaction.category_id == category_id)
        query = self._apply_list_filters(
            query,
            q=q,
            transaction_type=transaction_type,
            payment_method=payment_method,
            reviewed=reviewed,
            date_from=date_from,
            date_to=date_to,
            amount_min=amount_min,
            amount_max=amount_max,
        )
        result = await self.db.execute(query)
        return int(result.scalar())

    @staticmethod
    def _apply_list_filters(
        query,
        *,
        q: str | None,
        transaction_type: str | None,
        payment_method: str | None,
        reviewed: bool | None,
        date_from: date | None,
        date_to: date | None,
        amount_min: float | None,
        amount_max: float | None,
    ):
        if q:
            term = f"%{q.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Transaction.merchant_normalized).like(term),
                    func.lower(Transaction.merchant_raw).like(term),
                    func.lower(Transaction.reference_id).like(term),
                    func.lower(Transaction.account_last4).like(term),
                )
            )
        if transaction_type:
            query = query.where(Transaction.transaction_type == transaction_type)
        if payment_method:
            query = query.where(Transaction.payment_method == payment_method)
        if reviewed is not None:
            query = query.where(Transaction.reviewed_flag.is_(reviewed))
        if date_from:
            query = query.where(Transaction.transaction_date >= date_from)
        if date_to:
            query = query.where(Transaction.transaction_date <= date_to)
        if amount_min is not None:
            query = query.where(Transaction.amount >= amount_min)
        if amount_max is not None:
            query = query.where(Transaction.amount <= amount_max)
        return query

    async def get_monthly_summary(self, user_id: str, month: int, year: int) -> dict:
        """Compute monthly spending summary."""

        cached = await self.db.execute(
            select(MonthlySummary.payload_json).where(
                MonthlySummary.user_id == user_id,
                MonthlySummary.month == month,
                MonthlySummary.year == year,
            )
        )
        cached_payload = cached.scalar_one_or_none()
        if cached_payload:
            try:
                return json.loads(cached_payload)
            except json.JSONDecodeError:
                await self.db.execute(
                    delete(MonthlySummary).where(
                        MonthlySummary.user_id == user_id,
                        MonthlySummary.month == month,
                        MonthlySummary.year == year,
                    )
                )

        # Total spend (debits)
        spend_result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == TransactionType.DEBIT,
                Transaction.is_transfer.is_(False),
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
                Transaction.is_transfer.is_(False),
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
                Transaction.is_transfer.is_(False),
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
                Transaction.is_transfer.is_(False),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.merchant_normalized)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(10)
        )
        merchants = [
            {
                "name": row.merchant_normalized or "Unknown",
                "total": float(row.total),
                "count": row.count,
            }
            for row in merchant_result.all()
        ]

        summary = {
            "total_spend": total_spend,
            "total_income": total_income,
            "net": total_income - total_spend,
            "transaction_count": count,
            "month": f"{year}-{month:02d}",
            "category_breakdown": categories,
            "top_merchants": merchants,
        }
        self.db.add(
            MonthlySummary(
                user_id=user_id,
                month=month,
                year=year,
                payload_json=json.dumps(summary),
            )
        )
        await self.db.commit()
        return summary
