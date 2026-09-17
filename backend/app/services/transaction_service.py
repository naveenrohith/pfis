"""
Transaction Service
Business logic for creating, reading, and summarizing transactions.
Keeps routes thin — all logic lives here.
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import asc, delete, desc, extract, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import AccountLinkRule, FinancialAccount
from app.models.category import Category, UserMerchantRule
from app.models.email import RawEmail
from app.models.financial_position import (
    DepositStatementLine,
    DepositStatementLineReviewDecision,
    StatementLine,
    StatementLineMatch,
    StatementLineReviewDecision,
)
from app.models.knowledge import TemporalEventDecision
from app.models.summary import MonthlySummary
from app.models.sync import PipelineEvent, UserCorrection
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.schemas.account import TransferResponse
from app.schemas.transaction import (
    AtmCashLinkRequest,
    TransactionCreate,
    TransactionSplitReplace,
    TransactionSplitResponse,
    TransactionUpdate,
)
from app.services.ledger_currency import get_ledger_currency, require_ledger_currency
from app.services.temporal_source_history import (
    capture_financial_account_snapshot,
    capture_statement_line_snapshot,
    capture_transaction_snapshot,
)
from app.services.transaction_aggregates import (
    financial_activity_predicate,
    income_event_predicate,
    spend_effect_expression,
    spend_event_predicate,
)
from app.services.transaction_matching import (
    is_fuel_evidence,
    is_fuel_surcharge_amount_match,
    merchant_evidence_matches,
)

logger = logging.getLogger(__name__)
AUTO_REVIEW_THRESHOLD = 0.85
MONEY_QUANTUM = Decimal("0.01")


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
        amount: Decimal | float,
        transaction_date: date,
        merchant: str | None,
        reference_id: str | None,
        account_last4: str | None = None,
    ) -> str:
        """
        Compute SHA-256 fingerprint for deduplication.
        Uses: user + amount + date + merchant + ref_id + account
        """
        canonical_amount = Decimal(str(amount)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        raw = "|".join(
            [
                user_id,
                format(canonical_amount, "f"),
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

    async def create_transaction(
        self,
        user_id: str,
        data: TransactionCreate,
        *,
        commit: bool = True,
        is_accounting_adjustment: bool = False,
        ledger_subtype: str | None = None,
    ) -> Transaction:
        """Create a transaction, optionally joining the caller's unit of work."""

        await require_ledger_currency(
            self.db,
            user_id,
            data.currency,
            subject="Transaction",
        )
        if data.category_id is not None:
            category = await self.db.scalar(
                select(Category.id).where(Category.id == data.category_id)
            )
            if category is None:
                raise ValueError("Category not found")
        if data.source_email_id is not None:
            source_email = await self.db.scalar(
                select(RawEmail.id).where(
                    RawEmail.id == data.source_email_id,
                    RawEmail.user_id == user_id,
                )
            )
            if source_email is None:
                raise ValueError("Source email not found")

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
        account_link_needs_review = False
        if financial_account_id:
            account_result = await self.db.execute(
                select(FinancialAccount).where(
                    FinancialAccount.id == financial_account_id,
                    FinancialAccount.user_id == user_id,
                )
            )
            account = account_result.scalar_one_or_none()
            if account is None:
                raise ValueError("Financial account not found")
            if account.currency != data.currency:
                raise ValueError("Transaction currency must match the financial account currency")
        elif data.account_last4:
            masked_number = f"****{data.account_last4}"
            approved_account = await self.db.scalar(
                select(FinancialAccount)
                .join(
                    AccountLinkRule,
                    AccountLinkRule.financial_account_id == FinancialAccount.id,
                )
                .where(
                    AccountLinkRule.user_id == user_id,
                    AccountLinkRule.evidence_kind == "masked_suffix",
                    AccountLinkRule.evidence_value == data.account_last4,
                    AccountLinkRule.currency == data.currency,
                    AccountLinkRule.is_active.is_(True),
                    FinancialAccount.user_id == user_id,
                    FinancialAccount.is_active.is_(True),
                )
            )
            account_candidates: list[FinancialAccount] = []
            if approved_account is None:
                account_candidates = list(
                    (
                        await self.db.scalars(
                            select(FinancialAccount).where(
                                FinancialAccount.user_id == user_id,
                                FinancialAccount.is_active.is_(True),
                                FinancialAccount.currency == data.currency,
                                FinancialAccount.masked_number.like(f"%{data.account_last4}"),
                            )
                        )
                    ).all()
                )
            account = (
                approved_account
                if approved_account is not None
                else (account_candidates[0] if len(account_candidates) == 1 else None)
            )
            if account is None:
                account_result = await self.db.execute(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.institution_name == "Unknown",
                        FinancialAccount.account_type == "unknown",
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
                    identity_status="inferred" if data.account_last4 else "unresolved",
                    identity_confidence=(
                        Decimal("0.550") if data.account_last4 else Decimal("0.250")
                    ),
                    identity_evidence_json=json.dumps(
                        [
                            {
                                "source_type": "transaction_account_hint",
                                "source_id": f"{data.currency}:{masked_number}",
                                "role": "identity_hint",
                                "note": (
                                    "A masked suffix was observed, but the financial product "
                                    "type is not yet confirmed."
                                ),
                                "observed_at": datetime.now(UTC).isoformat(),
                            }
                        ],
                        sort_keys=True,
                    ),
                )
                self.db.add(account)
                await self.db.flush()
            elif account.currency != data.currency:
                raise ValueError("Transaction currency must match the financial account currency")
            financial_account_id = account.id
            # A masked identifier without a user-owned product match is evidence,
            # not permission to silently classify the instrument as a bank/card.
            account_link_needs_review = approved_account is None and (
                account.account_type == "unknown" or len(account_candidates) > 1
            )

        if (
            data.source_kind == "email"
            and data.source_email_id is not None
            and financial_account_id is not None
        ):
            await self._reconcile_email_with_statement(
                user_id=user_id,
                financial_account_id=financial_account_id,
                data=data,
            )

        txn = Transaction(
            user_id=user_id,
            amount=data.amount,
            currency=data.currency,
            transaction_type=data.transaction_type,
            payment_method=data.payment_method,
            payment_rail=data.payment_rail,
            card_event=data.card_event,
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
            reviewed_flag=data.confidence_score >= AUTO_REVIEW_THRESHOLD
            and not account_link_needs_review,
            reviewed_at=(
                datetime.now(UTC)
                if data.confidence_score >= AUTO_REVIEW_THRESHOLD and not account_link_needs_review
                else None
            ),
            source_email_id=data.source_email_id,
            source_kind=data.source_kind,
            source_identifier=data.source_identifier,
            review_outcome="needs_review" if account_link_needs_review else "newly_imported",
            fingerprint=fingerprint,
            financial_account_id=financial_account_id,
            is_accounting_adjustment=is_accounting_adjustment,
            ledger_subtype=ledger_subtype,
        )
        self.db.add(txn)
        await self._invalidate_monthly_summary(user_id, data.transaction_date)
        try:
            await self.db.flush()
            if financial_account_id is not None:
                account = await self.db.get(FinancialAccount, financial_account_id)
                if account is not None:
                    await capture_financial_account_snapshot(self.db, account)
            await capture_transaction_snapshot(self.db, txn)
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            duplicate = await self.db.scalar(
                select(Transaction.id).where(Transaction.fingerprint == fingerprint)
            )
            if duplicate is not None:
                raise DuplicateTransactionError("Duplicate transaction detected") from exc
            raise ValueError("Transaction conflicts with a database integrity rule") from exc
        if commit:
            await self.db.refresh(txn)
        logger.info(
            "Transaction created: %s amount=%s [confidence=%s]",
            txn.merchant_normalized,
            txn.amount,
            txn.confidence_score,
        )
        return txn

    async def link_atm_withdrawal_to_cash(
        self,
        user_id: str,
        transaction_id: str,
        data: AtmCashLinkRequest,
    ) -> TransferResponse:
        """Turn one observed ATM debit into an idempotent bank-to-cash transfer."""
        transaction = await self.db.scalar(
            select(Transaction)
            .where(Transaction.id == transaction_id, Transaction.user_id == user_id)
            .with_for_update()
        )
        if transaction is None:
            raise LookupError("Transaction not found")
        await require_ledger_currency(
            self.db,
            user_id,
            transaction.currency,
            subject="ATM withdrawal",
        )
        if transaction.is_transfer and transaction.transfer_group_id:
            transfer_rows = list(
                (
                    await self.db.scalars(
                        select(Transaction).where(
                            Transaction.user_id == user_id,
                            Transaction.transfer_group_id == transaction.transfer_group_id,
                        )
                    )
                ).all()
            )
            if len(transfer_rows) != 2:
                raise ValueError("The existing ATM transfer is incomplete")
            debit = next(
                (item for item in transfer_rows if item.transaction_type == TransactionType.DEBIT),
                None,
            )
            credit = next(
                (item for item in transfer_rows if item.transaction_type == TransactionType.CREDIT),
                None,
            )
            if debit is None or credit is None:
                raise ValueError("The existing ATM transfer does not have both ledger legs")
            return TransferResponse(
                transfer_group_id=transaction.transfer_group_id,
                debit_transaction_id=debit.id,
                credit_transaction_id=credit.id,
                amount=float(transaction.amount),
                currency=transaction.currency,
                transaction_date=transaction.transaction_date,
                payment_rail="atm",
            )
        if transaction.transaction_type != TransactionType.DEBIT:
            raise ValueError("Only an ATM debit can be moved into a cash pocket")
        if transaction.payment_rail != PaymentRail.ATM:
            raise ValueError("This transaction does not contain ATM withdrawal evidence")
        source_account = (
            await self.db.get(FinancialAccount, transaction.financial_account_id)
            if transaction.financial_account_id
            else None
        )
        if (
            source_account is None
            or source_account.user_id != user_id
            or source_account.account_type != "bank"
            or not source_account.is_active
        ):
            raise ValueError("Identify the funding instrument as an active bank account first")
        cash_account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == data.cash_account_id,
                FinancialAccount.user_id == user_id,
            )
        )
        if cash_account is None:
            raise LookupError("Cash account not found")
        if cash_account.account_type != "cash" or not cash_account.is_active:
            raise ValueError("Choose an active cash account")
        if cash_account.currency != transaction.currency:
            raise ValueError("Cross-currency transfers are not supported")

        transfer_group_id = str(uuid.uuid4())
        credit_reference = f"atm-link:{transaction.id}:credit"
        credit = Transaction(
            user_id=user_id,
            amount=transaction.amount,
            currency=transaction.currency,
            transaction_type=TransactionType.CREDIT,
            payment_method=PaymentMethod.BANK_TRANSFER,
            payment_rail=PaymentRail.ATM,
            card_event=CardEvent.NONE,
            transaction_status="completed",
            merchant_raw="ATM cash withdrawal",
            merchant_normalized="ATM cash withdrawal",
            transaction_date=transaction.transaction_date,
            reference_id=credit_reference,
            confidence_score=1.0,
            reviewed_flag=True,
            reviewed_at=datetime.now(UTC),
            fingerprint=self.compute_fingerprint(
                user_id,
                transaction.amount,
                transaction.transaction_date,
                "ATM cash withdrawal",
                credit_reference,
            ),
            financial_account_id=cash_account.id,
            transfer_group_id=transfer_group_id,
            is_transfer=True,
            ledger_subtype="atm_cash_transfer",
            source_kind="manual",
            source_identifier=f"atm-link:{transaction.id}",
            review_outcome="matched",
            merchant_resolution_source="system_transfer",
            merchant_resolution_confidence=1.0,
            merchant_resolver_version=3,
        )
        previous_merchant = transaction.merchant_normalized
        transaction.payment_rail = PaymentRail.ATM
        transaction.card_event = CardEvent.NONE
        transaction.merchant_normalized = "ATM cash withdrawal"
        transaction.merchant_resolution_source = "system_transfer"
        transaction.merchant_resolution_confidence = 1.0
        transaction.merchant_resolver_version = 3
        transaction.transfer_group_id = transfer_group_id
        transaction.is_transfer = True
        transaction.is_accounting_adjustment = False
        transaction.ledger_subtype = "atm_cash_transfer"
        transaction.review_outcome = "matched"
        transaction.reviewed_flag = True
        transaction.reviewed_at = datetime.now(UTC)
        self.db.add_all(
            [
                credit,
                UserCorrection(
                    transaction_id=transaction.id,
                    field_corrected="atm_cash_account",
                    old_value=None,
                    new_value=cash_account.id,
                ),
                UserCorrection(
                    transaction_id=transaction.id,
                    field_corrected="merchant_normalized",
                    old_value=previous_merchant,
                    new_value="ATM cash withdrawal",
                ),
            ]
        )
        await self._invalidate_monthly_summary(user_id, transaction.transaction_date)
        await self.db.flush()
        await capture_transaction_snapshot(self.db, transaction)
        await capture_transaction_snapshot(self.db, credit)
        await self.db.commit()
        await self.db.refresh(credit)
        return TransferResponse(
            transfer_group_id=transfer_group_id,
            debit_transaction_id=transaction.id,
            credit_transaction_id=credit.id,
            amount=float(transaction.amount),
            currency=transaction.currency,
            transaction_date=transaction.transaction_date,
            payment_rail="atm",
        )

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
        include_ignored: bool = False,
    ) -> list[Transaction]:
        """Fetch transactions with optional filters."""
        query = (
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.source_email))
            .where(Transaction.user_id == user_id)
        )
        if not include_ignored:
            query = query.where(Transaction.review_outcome != "ignored_by_rule")

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
        return list(result.scalars().all())

    async def get_transaction_by_id(self, txn_id: str) -> Transaction | None:
        """Get a single transaction by ID."""
        result = await self.db.execute(
            select(Transaction)
            .options(selectinload(Transaction.category), selectinload(Transaction.source_email))
            .where(Transaction.id == txn_id)
        )
        txn = result.scalar_one_or_none()
        return txn

    async def update_transaction(self, txn_id: str, data: TransactionUpdate) -> Transaction | None:
        """Update transaction fields (user correction)."""
        txn = await self.get_transaction_by_id(txn_id)
        if not txn:
            return None

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return txn

        protected_transfer_fields = {
            "amount",
            "transaction_type",
            "payment_method",
            "transaction_status",
        }
        attempted_transfer_fields = protected_transfer_fields.intersection(update_data)
        if txn.is_transfer and attempted_transfer_fields:
            fields = ", ".join(sorted(attempted_transfer_fields))
            raise ValueError(f"Transfer ledger fields cannot be edited individually: {fields}")

        category_id = update_data.get("category_id")
        if category_id is not None:
            category = await self.db.scalar(select(Category.id).where(Category.id == category_id))
            if category is None:
                raise ValueError("Category not found")
        financial_account_id = update_data.get("financial_account_id")
        if financial_account_id is not None:
            account = await self.db.scalar(
                select(FinancialAccount).where(
                    FinancialAccount.id == financial_account_id,
                    FinancialAccount.user_id == txn.user_id,
                    FinancialAccount.is_active.is_(True),
                )
            )
            if account is None:
                raise ValueError("Financial account not found")
            if account.currency != txn.currency:
                raise ValueError("Transaction currency must match the financial account currency")

        tags_provided = "tags" in update_data
        requested_tags = update_data.pop("tags", None)
        changed_fields: dict[str, tuple[object, object]] = {}
        now = datetime.now(UTC)
        for field, value in update_data.items():
            current_value = getattr(txn, field)
            if field == "reviewed_flag":
                value = bool(value)
            if current_value != value:
                changed_fields[field] = (current_value, value)
                setattr(txn, field, value)
        if tags_provided and txn.tags != requested_tags:
            changed_fields["tags"] = (txn.tags, requested_tags)
            txn.tags_json = json.dumps(requested_tags, ensure_ascii=False)

        if not changed_fields:
            return txn

        if "reviewed_flag" in changed_fields:
            txn.reviewed_at = now if txn.reviewed_flag else None
        if "financial_account_id" in changed_fields:
            txn.review_outcome = "matched"

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

        await self.db.flush()
        await capture_transaction_snapshot(self.db, txn)
        await self.db.commit()
        await self.db.refresh(txn)
        if txn.category_id:
            await self.db.refresh(txn, attribute_names=["category"])
        logger.info(f"Transaction updated: {txn_id} fields={list(changed_fields.keys())}")
        return txn

    async def _reconcile_email_with_statement(
        self,
        *,
        user_id: str,
        financial_account_id: str,
        data: TransactionCreate,
    ) -> None:
        """Suppress a second ledger event when statement evidence arrived first.

        Statement ingestion already performs the inverse match. This path makes
        reconciliation order-independent for later Gmail history syncs.
        """
        base_query = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.financial_account_id == financial_account_id,
            Transaction.source_kind == "statement",
            Transaction.source_email_id.is_(None),
            Transaction.transaction_type == data.transaction_type,
        )
        matched: Transaction | None = None
        match_method = "email_after_statement"
        confidence = Decimal("0.900")
        if data.reference_id:
            exact = list(
                (
                    await self.db.scalars(
                        base_query.where(Transaction.reference_id == data.reference_id)
                    )
                ).all()
            )
            if len(exact) == 1:
                matched = exact[0]
                match_method = "reference_email_after_statement"
                confidence = Decimal("1.000")

        lower_date = date.fromordinal(data.transaction_date.toordinal() - 5)
        upper_date = date.fromordinal(data.transaction_date.toordinal() + 5)
        date_candidates = list(
            (
                await self.db.scalars(
                    base_query.where(
                        Transaction.transaction_date >= lower_date,
                        Transaction.transaction_date <= upper_date,
                    )
                )
            ).all()
        )
        if matched is None:
            exact_candidates = [
                candidate
                for candidate in date_candidates
                if candidate.amount == data.amount
                and merchant_evidence_matches(
                    candidate.merchant_raw or candidate.merchant_normalized or "",
                    [data.merchant_raw, data.merchant_normalized],
                )
            ]
            if len(exact_candidates) == 1:
                matched = exact_candidates[0]
        else:
            exact_candidates = []

        fuel_candidates: list[Transaction] = []
        if matched is None:
            fuel_candidates = [
                candidate
                for candidate in date_candidates
                if is_fuel_surcharge_amount_match(candidate.amount, data.amount)
                and is_fuel_evidence(
                    candidate.merchant_raw,
                    candidate.merchant_normalized,
                    data.merchant_raw,
                    data.merchant_normalized,
                )
                and merchant_evidence_matches(
                    candidate.merchant_raw or candidate.merchant_normalized or "",
                    [data.merchant_raw, data.merchant_normalized],
                )
            ]
            if len(fuel_candidates) == 1:
                matched = fuel_candidates[0]
                match_method = "fuel_surcharge_email_after_statement"
                confidence = Decimal("0.940")

        if matched is not None:
            matched.source_email_id = data.source_email_id
            matched.review_outcome = "matched"
            line = await self.db.scalar(
                select(StatementLine).where(
                    StatementLine.user_id == user_id,
                    StatementLine.created_transaction_id == matched.id,
                )
            )
            if line is not None:
                line.review_outcome = "matched"
                existing_match = await self.db.scalar(
                    select(StatementLineMatch.id).where(
                        StatementLineMatch.statement_line_id == line.id
                    )
                )
                if existing_match is None:
                    self.db.add(
                        StatementLineMatch(
                            user_id=user_id,
                            statement_line_id=line.id,
                            transaction_id=matched.id,
                            match_method=match_method,
                            confidence=confidence,
                        )
                    )
                await capture_statement_line_snapshot(self.db, line)
            await self.db.flush()
            await capture_transaction_snapshot(self.db, matched)
            logger.info(
                "Email evidence reconciled with statement transaction id=%s",
                matched.id,
            )
            raise DuplicateTransactionError(
                "Email evidence matched an existing statement transaction"
            )

        relevant_candidates = exact_candidates + [
            candidate for candidate in fuel_candidates if candidate not in exact_candidates
        ]
        if relevant_candidates:
            candidate_ids = [candidate.id for candidate in relevant_candidates]
            for candidate in relevant_candidates:
                candidate.review_outcome = "needs_review"
            lines = await self.db.scalars(
                select(StatementLine).where(
                    StatementLine.user_id == user_id,
                    StatementLine.created_transaction_id.in_(candidate_ids),
                )
            )
            for line in lines:
                line.review_outcome = "needs_review"
                await capture_statement_line_snapshot(self.db, line)
            await self.db.flush()
            for candidate in relevant_candidates:
                await capture_transaction_snapshot(self.db, candidate)
            logger.info(
                "Email/statement evidence conflict held for review candidates=%s",
                len(candidate_ids),
            )
            raise DuplicateTransactionError(
                "Email evidence conflicts with existing statement activity"
            )

    async def replace_splits(
        self,
        user_id: str,
        txn_id: str,
        data: TransactionSplitReplace,
    ) -> list[TransactionSplitResponse]:
        txn = await self.get_transaction_by_id(txn_id)
        if txn is None or txn.user_id != user_id:
            raise LookupError("Transaction not found")
        if txn.is_transfer:
            raise ValueError("Transfer ledger entries cannot be split")
        split_total = sum((item.amount for item in data.splits), Decimal())
        if split_total.quantize(MONEY_QUANTUM) != txn.amount.quantize(MONEY_QUANTUM):
            raise ValueError("Split amounts must equal the transaction amount")
        category_ids = {item.category_id for item in data.splits if item.category_id}
        if category_ids:
            existing_ids = set(
                (
                    await self.db.scalars(select(Category.id).where(Category.id.in_(category_ids)))
                ).all()
            )
            if existing_ids != category_ids:
                raise ValueError("One or more split categories were not found")
        await self.db.execute(
            delete(TransactionSplit).where(
                TransactionSplit.user_id == user_id,
                TransactionSplit.transaction_id == txn_id,
            )
        )
        splits = [
            TransactionSplit(
                user_id=user_id,
                transaction_id=txn_id,
                label=item.label,
                amount=item.amount,
                category_id=item.category_id,
            )
            for item in data.splits
        ]
        self.db.add_all(splits)
        await self.db.commit()
        for split in splits:
            await self.db.refresh(split)
        return [TransactionSplitResponse.model_validate(split) for split in splits]

    async def list_splits(self, user_id: str, txn_id: str) -> list[TransactionSplitResponse]:
        txn = await self.get_transaction_by_id(txn_id)
        if txn is None or txn.user_id != user_id:
            raise LookupError("Transaction not found")
        rows = (
            await self.db.scalars(
                select(TransactionSplit)
                .where(
                    TransactionSplit.user_id == user_id,
                    TransactionSplit.transaction_id == txn_id,
                )
                .order_by(TransactionSplit.created_at, TransactionSplit.id)
            )
        ).all()
        return [TransactionSplitResponse.model_validate(split) for split in rows]

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
        category_ids = {value for value in (category_id, rule_category_id) if value is not None}
        for candidate_category_id in category_ids:
            category_result = await self.db.execute(
                select(Category.id).where(Category.id == candidate_category_id)
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
        changed_transactions: list[Transaction] = []
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
            changed_transactions.append(txn)

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

        await self.db.flush()
        for txn in changed_transactions:
            await capture_transaction_snapshot(self.db, txn)
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
        """Delete a transaction, including both legs when it is a transfer."""
        result = await self.db.execute(select(Transaction).where(Transaction.id == txn_id))
        txn = result.scalar_one_or_none()
        if not txn:
            return False

        transactions = [txn]
        if txn.is_transfer and txn.transfer_group_id:
            pair_result = await self.db.execute(
                select(Transaction).where(
                    Transaction.user_id == txn.user_id,
                    Transaction.transfer_group_id == txn.transfer_group_id,
                    Transaction.is_transfer.is_(True),
                )
            )
            transactions = list(pair_result.scalars().all())

        transaction_ids = [candidate.id for candidate in transactions]
        affected_periods = {
            (candidate.user_id, candidate.transaction_date) for candidate in transactions
        }
        try:
            for candidate in transactions:
                await capture_transaction_snapshot(self.db, candidate, deleted=True)
            await self.db.execute(
                update(PipelineEvent)
                .where(PipelineEvent.transaction_id.in_(transaction_ids))
                .values(transaction_id=None)
            )
            await self.db.execute(
                delete(UserCorrection).where(UserCorrection.transaction_id.in_(transaction_ids))
            )
            await self.db.execute(
                delete(TransactionSplit).where(TransactionSplit.transaction_id.in_(transaction_ids))
            )
            await self.db.execute(
                update(DepositStatementLine)
                .where(DepositStatementLine.created_transaction_id.in_(transaction_ids))
                .values(created_transaction_id=None)
            )
            await self.db.execute(
                update(DepositStatementLineReviewDecision)
                .where(
                    DepositStatementLineReviewDecision.created_transaction_id.in_(transaction_ids)
                )
                .values(created_transaction_id=None)
            )
            await self.db.execute(
                update(StatementLine)
                .where(StatementLine.created_transaction_id.in_(transaction_ids))
                .values(created_transaction_id=None)
            )
            await self.db.execute(
                delete(StatementLineMatch).where(
                    StatementLineMatch.transaction_id.in_(transaction_ids)
                )
            )
            await self.db.execute(
                update(StatementLineReviewDecision)
                .where(StatementLineReviewDecision.matched_transaction_id.in_(transaction_ids))
                .values(matched_transaction_id=None)
            )
            await self.db.execute(
                update(TemporalEventDecision)
                .where(TemporalEventDecision.transaction_id.in_(transaction_ids))
                .values(transaction_id=None)
            )
            await self.db.execute(delete(Transaction).where(Transaction.id.in_(transaction_ids)))
            for user_id, transaction_date in affected_periods:
                await self._invalidate_monthly_summary(user_id, transaction_date)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        logger.info(
            "Transaction deletion completed: requested_id=%s deleted_count=%d",
            txn_id,
            len(transaction_ids),
        )
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
        include_ignored: bool = False,
    ) -> int:
        """Get total count of transactions matching filters (for pagination)."""
        query = select(func.count(Transaction.id)).where(Transaction.user_id == user_id)
        if not include_ignored:
            query = query.where(Transaction.review_outcome != "ignored_by_rule")
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
        return int(result.scalar() or 0)

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

        ledger_currency = await get_ledger_currency(self.db, user_id)
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
                cached_summary = json.loads(cached_payload)
                if (
                    cached_summary.get("_aggregation_contract") == "single-ledger-v1"
                    and cached_summary.get("_ledger_currency") == ledger_currency
                ):
                    return cached_summary
                await self.db.execute(
                    delete(MonthlySummary).where(
                        MonthlySummary.user_id == user_id,
                        MonthlySummary.month == month,
                        MonthlySummary.year == year,
                    )
                )
                await self.db.flush()
            except json.JSONDecodeError:
                await self.db.execute(
                    delete(MonthlySummary).where(
                        MonthlySummary.user_id == user_id,
                        MonthlySummary.month == month,
                        MonthlySummary.year == year,
                    )
                )
                await self.db.flush()

        # Spending is net of refunds. Issuer accounting adjustments and paired
        # transfers remain visible in Activity but have no financial effect.
        spend_result = await self.db.execute(
            select(func.coalesce(func.sum(spend_effect_expression()), 0)).where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        total_spend = float(spend_result.scalar() or 0)

        # Total income (credits)
        income_result = await self.db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == user_id,
                income_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        total_income = float(income_result.scalar() or 0)

        # Transaction count
        count_result = await self.db.execute(
            select(func.count(Transaction.id)).where(
                Transaction.user_id == user_id,
                financial_activity_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
        )
        count = int(count_result.scalar() or 0)

        # Category breakdown
        cat_result = await self.db.execute(
            select(
                Category.id,
                Category.name,
                Category.icon,
                func.sum(spend_effect_expression()).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .join(Category, Transaction.category_id == Category.id, isouter=True)
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Category.id, Category.name, Category.icon)
            .having(func.sum(spend_effect_expression()) > 0)
            .order_by(func.sum(spend_effect_expression()).desc())
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
                func.sum(spend_effect_expression()).label("total"),
                func.count(Transaction.id).label("count"),
            )
            .where(
                Transaction.user_id == user_id,
                spend_event_predicate(),
                extract("month", Transaction.transaction_date) == month,
                extract("year", Transaction.transaction_date) == year,
            )
            .group_by(Transaction.merchant_normalized)
            .having(func.sum(spend_effect_expression()) > 0)
            .order_by(func.sum(spend_effect_expression()).desc())
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
            "_aggregation_contract": "single-ledger-v1",
            "_ledger_currency": ledger_currency,
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
