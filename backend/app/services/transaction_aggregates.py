"""Shared financial-effect semantics for every PFIS read model.

Ledger visibility and financial effect are deliberately different. Transfers
and issuer accounting adjustments remain visible in Activity, while neither
changes spending or income. Refunds reduce spending rather than masquerading
as income.
"""

from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.models.transaction import CardEvent, Transaction, TransactionType
from app.models.user import User

SETTLED_TRANSACTION_STATUSES = frozenset(
    {"completed", "posted", "settled", "succeeded", "success", "captured"}
)
PENDING_TRANSACTION_STATUSES = frozenset(
    {"pending", "authorized", "authorised", "processing", "initiated", "in_progress"}
)


def is_settled_transaction_status(value: object) -> bool:
    """Return whether a source status represents settled money movement."""

    normalized = str(getattr(value, "value", value) or "completed").strip().lower()
    return normalized in SETTLED_TRANSACTION_STATUSES


def is_pending_transaction_status(value: object) -> bool:
    """Return whether a source status is a pending, not-yet-settled movement."""

    normalized = str(getattr(value, "value", value) or "").strip().lower()
    return normalized in PENDING_TRANSACTION_STATUSES


def balance_transaction_eligible(transaction: Transaction) -> bool:
    """Return whether a transaction can change an account balance position.

    Account positions include internal transfers and card payments because they
    change the individual account. They still exclude ignored, accounting, and
    non-settled source rows. Spending predicates intentionally remain narrower.
    """

    return (
        is_settled_transaction_status(transaction.transaction_status)
        and not transaction.is_accounting_adjustment
        and transaction.review_outcome != "ignored_by_rule"
    )


def balance_pending_effect(transaction: Transaction, balance_kind: str) -> Decimal:
    """Return the signed pending account movement, or zero when not pending."""

    if (
        not is_pending_transaction_status(transaction.transaction_status)
        or transaction.is_accounting_adjustment
        or transaction.review_outcome == "ignored_by_rule"
    ):
        return Decimal("0")
    return _signed_balance_movement(transaction.amount, transaction.transaction_type, balance_kind)


def signed_balance_movement(transaction: Transaction, balance_kind: str) -> Decimal:
    """Return a settled transaction's signed movement for an account position."""

    if not balance_transaction_eligible(transaction):
        return Decimal("0")
    return _signed_balance_movement(transaction.amount, transaction.transaction_type, balance_kind)


def _signed_balance_movement(
    amount: Decimal, transaction_type: object, balance_kind: str
) -> Decimal:
    """Apply account-product sign semantics to one transaction amount."""

    transaction_value = str(getattr(transaction_type, "value", transaction_type) or "").lower()
    if transaction_value not in {"credit", "refund", "debit"}:
        return Decimal("0")
    sign = Decimal("1") if transaction_value in {"credit", "refund"} else Decimal("-1")
    if balance_kind == "liability":
        sign *= Decimal("-1")
    return amount * sign


def financial_activity_predicate() -> ColumnElement[bool]:
    """Return settled activity that contributes to spend/income read models.

    Pending, failed, declined, and reversed source rows remain visible in the
    ledger and temporal evidence, but they are not settled money movement.
    """
    ledger_currency = select(User.currency).where(User.id == Transaction.user_id).scalar_subquery()
    return and_(
        Transaction.currency == ledger_currency,
        Transaction.is_transfer.is_(False),
        Transaction.is_accounting_adjustment.is_(False),
        Transaction.review_outcome != "ignored_by_rule",
        Transaction.card_event != CardEvent.PAYMENT,
        func.lower(func.coalesce(Transaction.transaction_status, "completed")).in_(
            SETTLED_TRANSACTION_STATUSES
        ),
    )


def spend_event_predicate() -> ColumnElement[bool]:
    """Return activity that contributes positively or negatively to spend."""
    return and_(
        financial_activity_predicate(),
        Transaction.transaction_type.in_((TransactionType.DEBIT, TransactionType.REFUND)),
    )


def debit_event_predicate() -> ColumnElement[bool]:
    """Return real outgoing events, excluding transfers and bookkeeping."""
    return and_(
        financial_activity_predicate(),
        Transaction.transaction_type == TransactionType.DEBIT,
    )


def income_event_predicate() -> ColumnElement[bool]:
    """Return real credits; refunds are intentionally not income."""
    return and_(
        financial_activity_predicate(),
        Transaction.transaction_type == TransactionType.CREDIT,
    )


def spend_effect_expression() -> ColumnElement:
    """Return signed spend: debit is positive and refund is negative."""
    return case(
        (Transaction.transaction_type == TransactionType.DEBIT, Transaction.amount),
        (Transaction.transaction_type == TransactionType.REFUND, -Transaction.amount),
        else_=0,
    )


def income_effect_expression() -> ColumnElement:
    """Return income only for real credit events."""
    return case(
        (Transaction.transaction_type == TransactionType.CREDIT, Transaction.amount),
        else_=0,
    )
