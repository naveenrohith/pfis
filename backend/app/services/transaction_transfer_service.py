"""Reviewable matching for imported transfer and card-payment ledger legs.

Imported sources often expose the two sides of an internal movement separately.
This service keeps discovery deterministic and non-mutating; only an explicit
confirmation links two existing rows into a transfer group.  That preserves
the append-only source evidence while allowing balance positions to stop
counting a confirmed movement as spend or income.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.sync import UserCorrection
from app.models.transaction import (
    CardEvent,
    PaymentMethod,
    PaymentRail,
    Transaction,
    TransactionType,
)
from app.schemas.account import TransferResponse
from app.schemas.transaction import TransferMatchCandidate
from app.services.ledger_currency import require_ledger_currency
from app.services.temporal_source_history import capture_transaction_snapshot
from app.services.transaction_aggregates import balance_transaction_eligible

TRANSFER_MATCH_WINDOW_DAYS = 7
TRANSFER_MATCH_LIMIT = 200
TransferMatchKind = Literal["card_payment", "account_transfer"]

_ASSET_ACCOUNT_TYPES = {"bank", "cash", "investment"}
_TRANSFER_TERMS = (
    "transfer",
    "neft",
    "rtgs",
    "imps",
    "self transfer",
    "fund transfer",
    "own account",
    "to own",
    "from own",
)


class TransactionTransferService:
    """Find and explicitly link two already-imported transaction rows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_candidates(
        self,
        user_id: str,
        *,
        account_id: str | None = None,
        limit: int = 100,
    ) -> list[TransferMatchCandidate]:
        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.is_active.is_(True),
                    )
                )
            ).all()
        )
        account_by_id = {account.id: account for account in accounts}
        if account_id is not None and account_id not in account_by_id:
            raise LookupError("Financial account not found")
        # A filtered view still needs both sides of a pair in the query.  The
        # account ID is applied to the returned pairs below, not to the
        # transaction source set, so a bank leg can be matched to its card
        # counterparty.
        account_ids = list(account_by_id)
        if not account_ids:
            return []

        transactions = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.financial_account_id.in_(account_ids),
                        Transaction.transfer_group_id.is_(None),
                        Transaction.is_transfer.is_(False),
                    )
                )
            ).all()
        )
        eligible = [
            transaction
            for transaction in transactions
            if transaction.financial_account_id in account_by_id
            and balance_transaction_eligible(transaction)
        ]
        debits = [item for item in eligible if item.transaction_type == TransactionType.DEBIT]
        credits = [item for item in eligible if item.transaction_type == TransactionType.CREDIT]

        pairs: list[
            tuple[
                Transaction,
                Transaction,
                FinancialAccount,
                FinancialAccount,
                TransferMatchKind,
                float,
                list[str],
            ]
        ] = []
        for debit in debits:
            debit_account = account_by_id[debit.financial_account_id]  # type: ignore[index]
            for credit in credits:
                if (
                    debit.id == credit.id
                    or debit.financial_account_id == credit.financial_account_id
                ):
                    continue
                if debit.currency != credit.currency or debit.amount != credit.amount:
                    continue
                day_delta = abs((debit.transaction_date - credit.transaction_date).days)
                if day_delta > TRANSFER_MATCH_WINDOW_DAYS:
                    continue
                credit_account = account_by_id[credit.financial_account_id]  # type: ignore[index]
                classification = self._classify_pair(
                    debit,
                    credit,
                    debit_account,
                    credit_account,
                )
                if classification is None:
                    continue
                if account_id is not None and account_id not in {
                    debit.financial_account_id,
                    credit.financial_account_id,
                }:
                    continue
                kind, confidence, reasons = classification
                if day_delta == 0:
                    reasons = [*reasons, "same_day"]
                else:
                    reasons = [*reasons, "date_within_seven_days"]
                pairs.append(
                    (
                        debit,
                        credit,
                        debit_account,
                        credit_account,
                        kind,
                        max(0.0, min(confidence - (day_delta * 0.02), 1.0)),
                        reasons,
                    )
                )

        debit_counts = Counter(item[0].id for item in pairs)
        credit_counts = Counter(item[1].id for item in pairs)
        candidates: list[TransferMatchCandidate] = []
        for (
            debit,
            credit,
            debit_account,
            credit_account,
            kind,
            confidence,
            reasons,
        ) in pairs:
            ambiguous = debit_counts[debit.id] > 1 or credit_counts[credit.id] > 1
            if ambiguous:
                confidence = max(0.0, confidence - 0.20)
                reasons = [*reasons, "ambiguous_counterparty"]
            candidates.append(
                TransferMatchCandidate(
                    candidate_id=f"transfer-candidate:{debit.id}:{credit.id}",
                    debit_transaction_id=debit.id,
                    credit_transaction_id=credit.id,
                    debit_account_id=debit_account.id,
                    debit_account_label=self._account_label(debit_account),
                    credit_account_id=credit_account.id,
                    credit_account_label=self._account_label(credit_account),
                    amount=float(debit.amount),
                    currency=debit.currency,
                    debit_date=debit.transaction_date,
                    credit_date=credit.transaction_date,
                    date_difference_days=abs(
                        (debit.transaction_date - credit.transaction_date).days
                    ),
                    kind=kind,
                    confidence=confidence,
                    ambiguous=ambiguous,
                    reason_codes=list(dict.fromkeys(reasons)),
                )
            )
        candidates.sort(
            key=lambda item: (
                item.ambiguous,
                -item.confidence,
                item.debit_date,
                item.debit_transaction_id,
            )
        )
        return candidates[: max(1, min(limit, TRANSFER_MATCH_LIMIT))]

    async def link_pair(
        self,
        user_id: str,
        debit_transaction_id: str,
        credit_transaction_id: str,
        *,
        kind: TransferMatchKind,
    ) -> TransferResponse:
        """Link two imported rows after recomputing the safety invariants."""

        if debit_transaction_id == credit_transaction_id:
            raise ValueError("A transfer requires two different transactions")
        transactions = list(
            (
                await self.db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.user_id == user_id,
                        Transaction.id.in_((debit_transaction_id, credit_transaction_id)),
                    )
                    .with_for_update()
                )
            ).all()
        )
        by_id = {item.id: item for item in transactions}
        debit = by_id.get(debit_transaction_id)
        credit = by_id.get(credit_transaction_id)
        if debit is None or credit is None:
            raise LookupError("Transfer transactions not found")
        if debit.transaction_type != TransactionType.DEBIT:
            raise ValueError("The debit transaction must be a debit")
        if credit.transaction_type != TransactionType.CREDIT:
            raise ValueError("The counterparty transaction must be a credit")
        if debit.financial_account_id is None or credit.financial_account_id is None:
            raise ValueError("Both transactions must belong to financial accounts")

        accounts = list(
            (
                await self.db.scalars(
                    select(FinancialAccount).where(
                        FinancialAccount.user_id == user_id,
                        FinancialAccount.id.in_(
                            (debit.financial_account_id, credit.financial_account_id)
                        ),
                    )
                )
            ).all()
        )
        account_by_id = {account.id: account for account in accounts}
        debit_account = account_by_id.get(debit.financial_account_id)
        credit_account = account_by_id.get(credit.financial_account_id)
        if debit_account is None or credit_account is None:
            raise LookupError("Transfer account not found")

        if debit.transfer_group_id or credit.transfer_group_id:
            if (
                debit.transfer_group_id
                and debit.transfer_group_id == credit.transfer_group_id
                and debit.is_transfer
                and credit.is_transfer
            ):
                return self._response_for_pair(debit, credit)
            raise ValueError("One of these transactions is already linked to another transfer")
        if debit.is_accounting_adjustment or credit.is_accounting_adjustment:
            raise ValueError("Accounting adjustments cannot be linked as transfers")
        if debit.review_outcome == "ignored_by_rule" or credit.review_outcome == "ignored_by_rule":
            raise ValueError("Ignored activity cannot be linked as a transfer")
        if not balance_transaction_eligible(debit) or not balance_transaction_eligible(credit):
            raise ValueError("Only settled transactions can be linked as transfers")
        if debit.currency != credit.currency or debit.amount != credit.amount:
            raise ValueError("Transfer legs must have the same currency and amount")
        if debit.financial_account_id == credit.financial_account_id:
            raise ValueError("Transfer legs must belong to different accounts")
        if (
            abs((debit.transaction_date - credit.transaction_date).days)
            > TRANSFER_MATCH_WINDOW_DAYS
        ):
            raise ValueError("Transfer legs must be within seven days")
        await require_ledger_currency(self.db, user_id, debit.currency, subject="Transfer")

        classification = self._classify_pair(debit, credit, debit_account, credit_account)
        if classification is None or classification[0] != kind:
            raise ValueError("The selected transactions do not support this transfer type")

        transfer_group_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        updates: list[tuple[Transaction, str, object, object]] = []

        def set_field(transaction: Transaction, field: str, value: object) -> None:
            old = getattr(transaction, field)
            if old != value:
                updates.append((transaction, field, old, value))
                setattr(transaction, field, value)

        for transaction in (debit, credit):
            set_field(transaction, "transfer_group_id", transfer_group_id)
            set_field(transaction, "is_transfer", True)
            set_field(transaction, "payment_rail", PaymentRail.TRANSFER)
            set_field(transaction, "payment_method", PaymentMethod.BANK_TRANSFER)
            set_field(transaction, "review_outcome", "matched")
            set_field(transaction, "reviewed_flag", True)
            set_field(transaction, "reviewed_at", now)

        set_field(
            debit,
            "ledger_subtype",
            "matched_card_payment" if kind == "card_payment" else "matched_account_transfer",
        )
        set_field(
            credit,
            "ledger_subtype",
            "matched_card_payment" if kind == "card_payment" else "matched_account_transfer",
        )
        if kind == "card_payment":
            set_field(credit, "card_event", CardEvent.PAYMENT)
            set_field(debit, "card_event", CardEvent.NONE)
        else:
            set_field(debit, "card_event", CardEvent.NONE)
            set_field(credit, "card_event", CardEvent.NONE)

        try:
            for transaction, field, old, new in updates:
                self.db.add(
                    UserCorrection(
                        transaction_id=transaction.id,
                        field_corrected=field,
                        old_value=None if old is None else str(getattr(old, "value", old)),
                        new_value=str(getattr(new, "value", new)),
                    )
                )
            await self.db.flush()
            await capture_transaction_snapshot(self.db, debit)
            await capture_transaction_snapshot(self.db, credit)
            await self.db.commit()
            await self.db.refresh(debit)
            await self.db.refresh(credit)
        except Exception:
            await self.db.rollback()
            raise
        return self._response_for_pair(debit, credit)

    @classmethod
    def _classify_pair(
        cls,
        debit: Transaction,
        credit: Transaction,
        debit_account: FinancialAccount,
        credit_account: FinancialAccount,
    ) -> tuple[TransferMatchKind, float, list[str]] | None:
        if debit_account.account_type == "bank" and credit_account.account_type == "credit_card":
            if credit.transaction_type != TransactionType.CREDIT or credit.card_event not in {
                CardEvent.NONE,
                CardEvent.PAYMENT,
            }:
                return None
            reasons = ["bank_to_card_counterparty", "exact_amount"]
            confidence = 0.84
            if credit.card_event == CardEvent.PAYMENT:
                reasons.append("card_payment_event")
                confidence += 0.10
            if credit.payment_rail == PaymentRail.TRANSFER:
                reasons.append("transfer_rail_evidence")
                confidence += 0.04
            return "card_payment", min(confidence, 0.99), reasons

        if (
            debit_account.balance_kind == "asset"
            and credit_account.balance_kind == "asset"
            and debit_account.account_type in _ASSET_ACCOUNT_TYPES
            and credit_account.account_type in _ASSET_ACCOUNT_TYPES
            and cls._has_transfer_evidence(debit, credit)
        ):
            reasons = ["asset_counterparty", "exact_amount", "transfer_evidence"]
            confidence = 0.78
            return "account_transfer", confidence, reasons
        return None

    @staticmethod
    def _has_transfer_evidence(debit: Transaction, credit: Transaction) -> bool:
        if (
            debit.payment_rail == PaymentRail.TRANSFER
            or credit.payment_rail == PaymentRail.TRANSFER
        ):
            return True
        if (
            debit.payment_method == PaymentMethod.BANK_TRANSFER
            or credit.payment_method == PaymentMethod.BANK_TRANSFER
        ):
            return True
        text = " ".join(
            value or ""
            for value in (
                debit.merchant_raw,
                debit.merchant_normalized,
                credit.merchant_raw,
                credit.merchant_normalized,
            )
        ).casefold()
        return any(term in text for term in _TRANSFER_TERMS)

    @staticmethod
    def _account_label(account: FinancialAccount) -> str:
        return f"{account.institution_name} · {account.masked_number}"

    @staticmethod
    def _response_for_pair(debit: Transaction, credit: Transaction) -> TransferResponse:
        return TransferResponse(
            transfer_group_id=debit.transfer_group_id or credit.transfer_group_id or "",
            debit_transaction_id=debit.id,
            credit_transaction_id=credit.id,
            amount=float(debit.amount),
            currency=debit.currency,
            transaction_date=min(debit.transaction_date, credit.transaction_date),
            payment_rail="transfer",
        )
