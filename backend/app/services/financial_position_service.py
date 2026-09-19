"""Business logic for verified positions, commitments, liabilities and HDFC statements."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, TypedDict, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import AccountBalanceSnapshot, AccountBalanceSource, FinancialAccount
from app.models.financial_position import (
    CardCalendarEvent,
    CardPaymentIntent,
    CardPositionObservation,
    CardPreference,
    CashPlan,
    Commitment,
    CreditCardStatement,
    DepositAccountStatement,
    DepositStatementLine,
    DepositStatementLineReviewDecision,
    Liability,
    LiabilityScheduleItem,
    ReservePlan,
    StatementImport,
    StatementLine,
    StatementLineMatch,
    StatementLineReviewDecision,
)
from app.models.summary import MonthlySummary
from app.models.sync import (
    BalanceProviderAccountMapping,
    SyncRun,
    SyncStatus,
    UserCorrection,
)
from app.models.transaction import (
    CardEvent,
    PaymentRail,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.schemas.account import TransferCreate
from app.schemas.financial_position import (
    AccountPositionResponse,
    CardActivitySignal,
    CardCalendarEventCreate,
    CardCalendarEventResponse,
    CardCalendarEventUpdate,
    CardEmiComponentResponse,
    CardEmiPlanResponse,
    CardOverviewResponse,
    CardPaymentIntentCreate,
    CardPaymentIntentResponse,
    CardPaymentIntentUpdate,
    CardPreferenceResponse,
    CardPreferenceUpsert,
    CardStatementHistoryItem,
    CashPlanResponse,
    CashPlanUpsert,
    CommitmentCreate,
    CommitmentResponse,
    CommitmentUpdate,
    CreditCardStatementResponse,
    DepositAccountStatementResponse,
    DepositStatementLineResponse,
    DepositStatementLineReviewRequest,
    DepositStatementLineReviewResponse,
    DepositStatementReviewItemResponse,
    FinancialIntelligenceRepairResponse,
    LiabilityCreate,
    LiabilityOverviewResponse,
    LiabilityResponse,
    LiabilityScheduleConfirm,
    LiabilityScheduleItemResponse,
    LiabilityScheduleItemUpdate,
    ReconciliationItem,
    ReservePlanCreate,
    ReservePlanResponse,
    ReservePlanUpdate,
    ReviewOutcome,
    StatementCardPaymentCandidateResponse,
    StatementLineResponse,
    StatementLineReviewRequest,
    StatementLineReviewResponse,
    StatementReviewCandidate,
    StatementReviewItemResponse,
    StatementTextImport,
)
from app.schemas.transaction import (
    CardEventEnum,
    PaymentMethodEnum,
    PaymentRailEnum,
    TransactionCreate,
    TransactionTypeEnum,
)
from app.services.account_service import AccountService
from app.services.card_refund_tracker_service import build_card_refund_tracker
from app.services.card_statement_projection_service import (
    CardRecurringChargeCandidate,
    HistoricalCycleMovements,
    build_card_statement_projection,
)
from app.services.classification import ClassificationType, classify_source_record
from app.services.deposit_statement_persistence import persist_deposit_statement
from app.services.financial_clock import user_financial_today
from app.services.generic_credit_card_statement_extractor import (
    EXTRACTOR_VERSION as GENERIC_CREDIT_CARD_EXTRACTOR_VERSION,
)
from app.services.generic_credit_card_statement_extractor import (
    extract_generic_credit_card_statement,
)
from app.services.generic_deposit_statement_extractor import (
    EXTRACTOR_VERSION as GENERIC_DEPOSIT_EXTRACTOR_VERSION,
)
from app.services.generic_deposit_statement_extractor import (
    extract_generic_deposit_statement,
)
from app.services.hdfc_deposit_statement_extractor import (
    EXTRACTOR_VERSION as DEPOSIT_EXTRACTOR_VERSION,
)
from app.services.hdfc_deposit_statement_extractor import (
    extract_hdfc_deposit_statement,
)
from app.services.hdfc_statement_extractor import (
    EXTRACTOR_VERSION,
    classify_emi_component,
    extract_hdfc_statement,
    is_legacy_layout,
    is_reviewed_layout,
)
from app.services.knowledge.recurring_knowledge import RecurringPatternService
from app.services.ledger_currency import get_ledger_currency
from app.services.parser.normalizer import (
    extract_descriptor_identity,
    infer_merchant_from_text,
    is_plausible_merchant_descriptor,
    resolve_merchant,
)
from app.services.parser.registry import get_parser_registry
from app.services.temporal_source_history import (
    capture_card_payment_intent_snapshot,
    capture_deposit_statement_line_snapshot,
    capture_statement_line_snapshot,
    capture_temporal_source_snapshot,
    capture_transaction_snapshot,
)
from app.services.transaction_aggregates import (
    balance_pending_effect,
    balance_transaction_eligible,
    is_pending_transaction_status,
    signed_balance_movement,
)
from app.services.transaction_matching import (
    is_fuel_evidence,
    is_fuel_surcharge_amount_match,
    merchant_evidence_matches,
    merchant_key,
)
from app.services.transaction_service import DuplicateTransactionError, TransactionService


class _CashPlanPositionFields(TypedDict):
    estimated_balance: float | None
    estimated_balance_as_of: date | None
    planning_balance: float | None
    planning_balance_as_of: date | None
    balance_basis: Literal["verified", "estimated"] | None
    position_status: Literal[
        "needs_observation", "observed", "estimated", "stale", "incomplete", "needs_review"
    ]
    position_confidence: float
    position_reason_codes: list[str]
    observed_source: str | None
    observed_at: datetime | None
    coverage_start: datetime | None
    coverage_end: datetime | None
    latest_sync_at: datetime | None
    coverage_complete: bool | None
    coverage_status: Literal["fresh", "due", "overdue", "unknown"]
    settled_movement_since_observation: float | None
    pending_increase: float
    pending_decrease: float


class FinancialPositionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _invalidate_monthly_summary(self, user_id: str, transaction_date: date) -> None:
        await self.db.execute(
            delete(MonthlySummary).where(
                MonthlySummary.user_id == user_id,
                MonthlySummary.month == transaction_date.month,
                MonthlySummary.year == transaction_date.year,
            )
        )

    async def account_position(
        self,
        user_id: str,
        account_id: str,
        period_start: date | None = None,
        period_end: date | None = None,
        *,
        as_of: date | None = None,
    ) -> AccountPositionResponse | None:
        account = await self._owned_account(user_id, account_id)
        if account is None:
            return None
        financial_today = as_of or await user_financial_today(self.db, user_id)
        snapshots = list(
            (
                await self.db.scalars(
                    select(AccountBalanceSnapshot)
                    .where(
                        AccountBalanceSnapshot.user_id == user_id,
                        AccountBalanceSnapshot.financial_account_id == account_id,
                        AccountBalanceSnapshot.as_of <= financial_today,
                    )
                    .order_by(
                        AccountBalanceSnapshot.as_of.desc(),
                        AccountBalanceSnapshot.effective_at.desc().nulls_last(),
                        AccountBalanceSnapshot.observed_at.desc(),
                        AccountBalanceSnapshot.created_at.desc(),
                    )
                )
            ).all()
        )
        verified_snapshots = [snapshot for snapshot in snapshots if snapshot.verified]
        latest = verified_snapshots[0] if verified_snapshots else None
        statement = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.financial_account_id == account_id,
            Transaction.review_outcome != "ignored_by_rule",
            Transaction.transaction_date <= financial_today,
        )
        all_transactions = list((await self.db.scalars(statement)).all())
        transactions = all_transactions
        if period_start:
            transactions = [
                transaction
                for transaction in transactions
                if transaction.transaction_date >= period_start
            ]
        if period_end:
            transactions = [
                transaction
                for transaction in transactions
                if transaction.transaction_date <= period_end
            ]
        financial_transactions = [
            transaction
            for transaction in transactions
            if transaction.currency == account.currency
            and balance_transaction_eligible(transaction)
        ]
        inflows = sum(
            (
                t.amount
                for t in financial_transactions
                if t.transaction_type in {TransactionType.CREDIT, TransactionType.REFUND}
            ),
            Decimal(),
        )
        outflows = sum(
            (
                t.amount
                for t in financial_transactions
                if t.transaction_type == TransactionType.DEBIT
            ),
            Decimal(),
        )
        rails: dict[str, Decimal] = {}
        for txn in financial_transactions:
            if txn.transaction_type == TransactionType.DEBIT:
                rails[txn.payment_rail.value] = (
                    rails.get(txn.payment_rail.value, Decimal()) + txn.amount
                )
        reconciliation_items: list[ReconciliationItem] = []
        unexplained: Decimal | None = None
        known_change: Decimal | None = None
        opening_balance: Decimal | None = None
        opening_as_of: date | None = None
        status: Literal["not_ready", "reconciled", "needs_review"] = "not_ready"
        anchor_transactions = [
            transaction
            for transaction in all_transactions
            if transaction.currency == account.currency
            and latest is not None
            and self._transaction_after_snapshot(transaction, latest)
        ]
        settled_since_observation = sum(
            (
                signed_balance_movement(transaction, account.balance_kind)
                for transaction in anchor_transactions
            ),
            Decimal("0"),
        )
        pending_effect = sum(
            (
                balance_pending_effect(transaction, account.balance_kind)
                for transaction in anchor_transactions
            ),
            Decimal("0"),
        )
        pending_increase = max(pending_effect, Decimal("0"))
        pending_decrease = max(-pending_effect, Decimal("0"))
        position_reason_codes: list[str] = []
        coverage_start: datetime | None = None
        coverage_end: datetime | None = None
        latest_sync_at: datetime | None = None
        coverage_complete: bool | None = None
        coverage_status: Literal["fresh", "due", "overdue", "unknown"] = "unknown"
        reconciliation_delta: Decimal | None = None
        last_reconciled_at: datetime | None = None
        estimated_balance: Decimal | None = None
        estimated_as_of: date | None = None
        position_status = "needs_observation"
        position_confidence = 0.0
        if latest is not None:
            estimated_balance = latest.amount + settled_since_observation
            estimated_as_of = financial_today
            position_status = "estimated" if settled_since_observation else "observed"
            position_confidence = 0.82
            if any(
                is_pending_transaction_status(item.transaction_status)
                for item in anchor_transactions
            ):
                position_reason_codes.append("pending_activity_excluded")
                position_confidence -= 0.12
            if any(
                item.review_outcome == "needs_review" or not item.reviewed_flag
                for item in anchor_transactions
                if balance_transaction_eligible(item)
            ):
                position_reason_codes.append("unreviewed_activity")
                position_confidence -= 0.20
            # A date-only observation has no reliable intra-day cutoff. Do not
            # silently claim that same-day activity was included merely because
            # a transaction happens to carry a timestamp; the observation's
            # effective timestamp is what establishes the boundary.
            if latest.effective_at is None and any(
                item.transaction_date == latest.as_of for item in all_transactions
            ):
                position_reason_codes.append("same_day_cutoff_unknown")
                position_confidence -= 0.12
            if any(
                item.payment_rail == PaymentRail.TRANSFER
                and item.card_event == CardEvent.PAYMENT
                and not item.is_transfer
                for item in anchor_transactions
            ):
                # A standalone card-payment event can describe the issuer leg
                # without proving the paying bank leg. It must not silently
                # reduce the bank's estimated spendable balance.
                position_reason_codes.append("unlinked_card_payment")
                position_confidence -= 0.20
            if as_of is None and await self._source_coverage_incomplete(
                user_id, account, anchor_transactions
            ):
                position_reason_codes.append("source_coverage_incomplete")
                position_confidence -= 0.18
            source_state = (
                await self._balance_source_state(user_id, account_id) if as_of is None else None
            )
            if source_state is not None:
                coverage_start = source_state.coverage_start
                coverage_end = source_state.coverage_end
                latest_sync_at = source_state.last_success_at
                coverage_complete = source_state.coverage_complete
                coverage_status = self._coverage_status(source_state)
                if not source_state.coverage_complete:
                    position_reason_codes.append("source_coverage_incomplete")
                    position_confidence -= 0.12
                if coverage_status == "overdue":
                    position_reason_codes.append("balance_observation_overdue")
                    position_confidence -= 0.18
                elif coverage_status == "due":
                    position_reason_codes.append("balance_observation_due")
                    position_confidence -= 0.08
            if position_reason_codes:
                position_status = "needs_review"
            position_confidence = max(0.0, min(position_confidence, 1.0))
        else:
            position_reason_codes.append("verified_observation_required")
        if latest and len(verified_snapshots) >= 2:
            previous = verified_snapshots[1]
            opening_balance = previous.amount
            opening_as_of = previous.as_of
            between = [
                transaction
                for transaction in all_transactions
                if transaction.currency == account.currency
                and self._transaction_between_snapshots(transaction, previous, latest)
            ]
            eligible_between = [
                transaction for transaction in between if balance_transaction_eligible(transaction)
            ]
            known_change = sum(
                (signed_balance_movement(t, account.balance_kind) for t in eligible_between),
                Decimal(),
            )
            unexplained = latest.amount - previous.amount - known_change
            reconciliation_delta = unexplained
            last_reconciled_at = latest.observed_at
            if unexplained != Decimal("0"):
                # A residual means the latest observed balance cannot be fully
                # explained by eligible settled ledger movement. It must block
                # spendability even when the current anchor itself is recent.
                position_reason_codes.append("unexplained_balance_movement")
                position_confidence -= 0.25
                position_status = "needs_review"
            for transaction in between:
                if (
                    not transaction.is_accounting_adjustment
                    and transaction.review_outcome != "ignored_by_rule"
                    and (
                        transaction.review_outcome == "needs_review"
                        or not transaction.reviewed_flag
                    )
                ):
                    reconciliation_items.append(
                        ReconciliationItem(
                            id=f"transaction-review:{transaction.id}",
                            kind="transaction_review",
                            title="Activity classification needs confirmation",
                            description=(
                                transaction.merchant_normalized
                                or transaction.merchant_raw
                                or "Unidentified account activity"
                            ),
                            amount=float(transaction.amount),
                            activity_date=transaction.transaction_date,
                            transaction_ids=[transaction.id],
                            basis="The ledger event is unreviewed or carries a needs-review outcome.",
                        )
                    )
                if (
                    transaction.payment_rail == PaymentRail.TRANSFER
                    and transaction.card_event == CardEvent.PAYMENT
                    and not transaction.is_transfer
                ):
                    reconciliation_items.append(
                        ReconciliationItem(
                            id=f"unlinked-transfer:{transaction.id}",
                            kind="unlinked_transfer",
                            title="Card payment is missing its other account",
                            description=(
                                transaction.merchant_normalized
                                or transaction.merchant_raw
                                or "Card payment"
                            ),
                            amount=float(transaction.amount),
                            activity_date=transaction.transaction_date,
                            transaction_ids=[transaction.id],
                            basis=(
                                "Explicit card-payment evidence exists, but no paired "
                                "account-to-card transfer has been recorded."
                            ),
                        )
                    )

            duplicate_groups: dict[tuple[date, Decimal, str, str], list[Transaction]] = {}
            for transaction in eligible_between:
                merchant = (
                    (transaction.merchant_normalized or transaction.merchant_raw or "")
                    .strip()
                    .casefold()
                )
                signature = (
                    transaction.transaction_date,
                    transaction.amount,
                    transaction.transaction_type.value,
                    merchant,
                )
                duplicate_groups.setdefault(signature, []).append(transaction)
            for signature, candidates in duplicate_groups.items():
                if len(candidates) < 2:
                    continue
                transaction_ids = sorted(candidate.id for candidate in candidates)
                reconciliation_items.append(
                    ReconciliationItem(
                        id=f"duplicate-candidate:{':'.join(transaction_ids)}",
                        kind="duplicate_candidate",
                        title="Possible duplicate activity",
                        description=(
                            candidates[0].merchant_normalized
                            or candidates[0].merchant_raw
                            or "Same account activity"
                        ),
                        amount=float(signature[1]),
                        activity_date=signature[0],
                        transaction_ids=transaction_ids,
                        basis=(
                            "Same account, date, direction, amount, and normalized merchant "
                            "appear more than once."
                        ),
                    )
                )
            if unexplained is not None and unexplained != Decimal("0"):
                direction = "higher" if unexplained > 0 else "lower"
                reconciliation_items.append(
                    ReconciliationItem(
                        id=f"unexplained-movement:{previous.id}:{latest.id}",
                        kind="unexplained_movement",
                        title="Snapshot movement is not fully explained",
                        description=(
                            f"The closing balance is {direction} than the opening balance "
                            "plus known ledger movement."
                        ),
                        amount=float(abs(unexplained)),
                        activity_date=latest.as_of,
                        basis=(
                            "Closing balance minus opening balance minus known ledger movement."
                        ),
                    )
                )
            status = "reconciled" if not reconciliation_items else "needs_review"
        position_confidence = max(0.0, min(position_confidence, 1.0))
        position_reason_codes = list(dict.fromkeys(position_reason_codes))
        return AccountPositionResponse(
            financial_account_id=account.id,
            currency=account.currency,
            balance_kind=cast(Literal["asset", "liability"], account.balance_kind),
            verified_balance=float(latest.amount) if latest and latest.verified else None,
            balance_as_of=latest.as_of if latest and latest.verified else None,
            balance_source=latest.source if latest and latest.verified else None,
            observed_balance=float(latest.amount) if latest else None,
            observed_as_of=latest.as_of if latest else None,
            observed_verified=latest.verified if latest else None,
            observed_source=latest.source if latest else None,
            observed_source_record_id=latest.source_record_id if latest else None,
            observed_at=latest.observed_at if latest else None,
            observed_effective_at=latest.effective_at if latest else None,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            latest_sync_at=latest_sync_at,
            coverage_complete=coverage_complete,
            coverage_status=coverage_status,
            reconciliation_delta=(
                float(reconciliation_delta) if reconciliation_delta is not None else None
            ),
            last_reconciled_at=last_reconciled_at,
            estimated_balance=float(estimated_balance) if estimated_balance is not None else None,
            estimated_as_of=estimated_as_of,
            settled_movement_since_observation=(
                float(settled_since_observation) if latest is not None else None
            ),
            pending_increase=float(pending_increase),
            pending_decrease=float(pending_decrease),
            position_status=cast(
                Literal[
                    "needs_observation",
                    "observed",
                    "estimated",
                    "stale",
                    "incomplete",
                    "needs_review",
                ],
                position_status,
            ),
            position_confidence=position_confidence,
            position_reason_codes=position_reason_codes,
            opening_balance=float(opening_balance) if opening_balance is not None else None,
            opening_as_of=opening_as_of,
            known_movement=float(known_change) if known_change is not None else None,
            inflows=float(inflows),
            outflows=float(outflows),
            rail_breakdown={key: float(value) for key, value in rails.items()},
            reconciliation_status=status,
            unexplained_amount=float(unexplained) if unexplained is not None else None,
            review_count=len(reconciliation_items),
            reconciliation_items=reconciliation_items,
        )

    @staticmethod
    def _transaction_after_snapshot(
        transaction: Transaction, snapshot: AccountBalanceSnapshot | None
    ) -> bool:
        """Use an effective timestamp when available; otherwise fail closed on the date."""

        if snapshot is None:
            return False
        if snapshot.effective_at is not None:
            if transaction.transaction_timestamp is not None:
                effective = transaction.transaction_timestamp
                if effective.tzinfo is None:
                    effective = effective.replace(tzinfo=UTC)
                anchor = snapshot.effective_at
                if anchor.tzinfo is None:
                    anchor = anchor.replace(tzinfo=UTC)
                return effective > anchor
            return transaction.transaction_date > snapshot.as_of
        return transaction.transaction_date > snapshot.as_of

    @classmethod
    def _transaction_between_snapshots(
        cls,
        transaction: Transaction,
        opening: AccountBalanceSnapshot,
        closing: AccountBalanceSnapshot,
    ) -> bool:
        """Return activity with a defensible opening/closing cutoff.

        When both the transaction and observation carry timestamps, the
        timestamps define the interval. A date-only row on a timestamped
        closing observation is excluded for that same day because its position
        relative to the cutoff is unknown; silently assigning it would make a
        reconciliation delta look explained when it is not.
        """

        if not cls._transaction_after_snapshot(transaction, opening):
            return False
        if closing.effective_at is None:
            return transaction.transaction_date <= closing.as_of
        if transaction.transaction_timestamp is None:
            return transaction.transaction_date < closing.as_of
        effective = transaction.transaction_timestamp
        if effective.tzinfo is None:
            effective = effective.replace(tzinfo=UTC)
        anchor = closing.effective_at
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        return effective <= anchor

    async def _source_coverage_incomplete(
        self,
        user_id: str,
        account: FinancialAccount,
        anchor_transactions: list[Transaction],
    ) -> bool:
        """Fail closed when connector-backed activity has an incomplete sync.

        A truncated or failed source run means unseen activity may exist after
        the balance anchor. Manual-only accounts are not blocked by an
        unrelated connector's coverage state.
        """

        provider_mapping_exists = await self.db.scalar(
            select(BalanceProviderAccountMapping.id)
            .where(
                BalanceProviderAccountMapping.user_id == user_id,
                BalanceProviderAccountMapping.financial_account_id == account.id,
            )
            .limit(1)
        )
        connector_backed = (
            account.connector_account_id is not None
            or provider_mapping_exists is not None
            or any(
                transaction.source_kind in {"email", "connector"}
                for transaction in anchor_transactions
            )
        )
        if not connector_backed:
            return False
        latest_sync = await self.db.scalar(
            select(SyncRun)
            .where(
                SyncRun.user_id == user_id,
                SyncRun.status.in_((SyncStatus.COMPLETED.value, SyncStatus.FAILED.value)),
            )
            .order_by(SyncRun.end_time.desc().nulls_last(), SyncRun.start_time.desc())
            .limit(1)
        )
        return latest_sync is not None and not latest_sync.coverage_complete

    async def _balance_source_state(
        self,
        user_id: str,
        account_id: str,
    ) -> AccountBalanceSource | None:
        """Return the latest provider balance coverage state for an account."""

        return await self.db.scalar(
            select(AccountBalanceSource)
            .where(
                AccountBalanceSource.user_id == user_id,
                AccountBalanceSource.financial_account_id == account_id,
                AccountBalanceSource.source == "connector",
            )
            .order_by(AccountBalanceSource.updated_at.desc())
            .limit(1)
        )

    @staticmethod
    def _coverage_status(
        state: AccountBalanceSource,
        *,
        now: datetime | None = None,
    ) -> Literal["fresh", "due", "overdue", "unknown"]:
        if state.last_success_at is None or not state.expected_cadence_minutes:
            return "unknown"
        instant = now or datetime.now(UTC)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        last_success = state.last_success_at
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=UTC)
        cadence = timedelta(minutes=state.expected_cadence_minutes)
        next_expected = last_success + cadence
        if instant <= next_expected:
            return "fresh"
        if instant <= next_expected + cadence:
            return "due"
        return "overdue"

    async def create_commitment(self, user_id: str, data: CommitmentCreate) -> CommitmentResponse:
        await self._validate_optional_account(user_id, data.financial_account_id)
        if data.liability_id is not None:
            liability_id = await self.db.scalar(
                select(Liability.id).where(
                    Liability.id == data.liability_id,
                    Liability.user_id == user_id,
                )
            )
            if liability_id is None:
                raise LookupError("Liability not found")
        commitment = Commitment(user_id=user_id, **data.model_dump())
        self.db.add(commitment)
        await self.db.flush()
        await self._snapshot_commitment(commitment)
        await self.db.commit()
        await self.db.refresh(commitment)
        return CommitmentResponse.model_validate(commitment)

    async def list_commitments(self, user_id: str) -> list[CommitmentResponse]:
        rows = await self.db.scalars(
            select(Commitment).where(Commitment.user_id == user_id).order_by(Commitment.due_date)
        )
        return [CommitmentResponse.model_validate(row) for row in rows]

    async def update_commitment(
        self, user_id: str, commitment_id: str, data: CommitmentUpdate
    ) -> CommitmentResponse | None:
        commitment = await self.db.scalar(
            select(Commitment).where(Commitment.id == commitment_id, Commitment.user_id == user_id)
        )
        if commitment is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(commitment, field, value)
        await self.db.flush()
        await self._snapshot_commitment(commitment)
        await self.db.commit()
        await self.db.refresh(commitment)
        return CommitmentResponse.model_validate(commitment)

    async def create_reserve(self, user_id: str, data: ReservePlanCreate) -> ReservePlanResponse:
        await self._require_account(user_id, data.financial_account_id)
        reserve = ReservePlan(user_id=user_id, **data.model_dump())
        self.db.add(reserve)
        await self.db.flush()
        await self._snapshot_reserve(reserve)
        await self.db.commit()
        await self.db.refresh(reserve)
        return ReservePlanResponse.model_validate(reserve)

    async def list_reserves(self, user_id: str) -> list[ReservePlanResponse]:
        rows = await self.db.scalars(
            select(ReservePlan).where(ReservePlan.user_id == user_id).order_by(ReservePlan.due_date)
        )
        return [ReservePlanResponse.model_validate(row) for row in rows]

    async def update_reserve(
        self, user_id: str, reserve_id: str, data: ReservePlanUpdate
    ) -> ReservePlanResponse | None:
        reserve = await self.db.scalar(
            select(ReservePlan).where(
                ReservePlan.id == reserve_id,
                ReservePlan.user_id == user_id,
            )
        )
        if reserve is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(reserve, field, value)
        await self.db.flush()
        await self._snapshot_reserve(reserve)
        await self.db.commit()
        await self.db.refresh(reserve)
        return ReservePlanResponse.model_validate(reserve)

    async def _snapshot_commitment(self, commitment: Commitment) -> None:
        await capture_temporal_source_snapshot(
            self.db,
            user_id=commitment.user_id,
            source_type="commitment",
            source_id=commitment.id,
            payload={
                "financial_account_id": commitment.financial_account_id,
                "liability_id": commitment.liability_id,
                "label": commitment.label,
                "commitment_type": commitment.commitment_type,
                "amount": commitment.amount,
                "due_date": commitment.due_date,
                "cadence": commitment.cadence,
                "source_kind": commitment.source_kind,
                "source_identifier": commitment.source_identifier,
                "confirmed": commitment.confirmed,
                "is_active": commitment.is_active,
            },
        )

    async def _snapshot_reserve(self, reserve: ReservePlan) -> None:
        await capture_temporal_source_snapshot(
            self.db,
            user_id=reserve.user_id,
            source_type="reserve_plan",
            source_id=reserve.id,
            payload={
                "financial_account_id": reserve.financial_account_id,
                "label": reserve.label,
                "target_amount": reserve.target_amount,
                "due_date": reserve.due_date,
                "monthly_allocation": reserve.monthly_allocation,
                "approved": reserve.approved,
                "is_active": reserve.is_active,
            },
        )

    async def _snapshot_liability_schedule_item(
        self, item: LiabilityScheduleItem, liability: Liability
    ) -> None:
        await capture_temporal_source_snapshot(
            self.db,
            user_id=item.user_id,
            source_type="liability_schedule",
            source_id=item.id,
            payload={
                "liability_id": item.liability_id,
                "financial_account_id": liability.financial_account_id,
                "label": liability.label,
                "due_date": item.due_date,
                "installment_amount": item.installment_amount,
                "principal_amount": item.principal_amount,
                "interest_amount": item.interest_amount,
                "tax_amount": item.tax_amount,
                "fee_amount": item.fee_amount,
                "source_kind": item.source_kind,
                "source_identifier": item.source_identifier,
                "confidence": item.confidence or liability.source_confidence,
                "status": item.status,
                "complete_schedule": liability.complete_schedule,
            },
        )

    async def create_liability(self, user_id: str, data: LiabilityCreate) -> LiabilityResponse:
        if data.complete_schedule:
            raise ValueError(
                "Confirm the instalment rows before marking a liability schedule complete"
            )
        account = None
        if data.financial_account_id is not None:
            account = await self._require_account(user_id, data.financial_account_id)
            expected_types = {
                "loan": {"loan"},
                "pay_later": {"pay_later"},
                "card_emi": {"credit_card"},
                "credit_card": {"credit_card"},
            }[data.liability_type]
            if account.account_type not in expected_types:
                raise ValueError(
                    f"{data.liability_type.replace('_', ' ')} liabilities require a "
                    f"{' or '.join(sorted(expected_types)).replace('_', ' ')} account"
                )
        liability = Liability(user_id=user_id, **data.model_dump())
        self.db.add(liability)
        await self.db.commit()
        await self.db.refresh(liability)
        return LiabilityResponse.model_validate(liability)

    async def liability_schedule(
        self, user_id: str, liability_id: str
    ) -> list[LiabilityScheduleItemResponse]:
        liability = await self.db.scalar(
            select(Liability).where(Liability.id == liability_id, Liability.user_id == user_id)
        )
        if liability is None:
            raise LookupError("Liability not found")
        rows = list(
            (
                await self.db.scalars(
                    select(LiabilityScheduleItem)
                    .where(
                        LiabilityScheduleItem.user_id == user_id,
                        LiabilityScheduleItem.liability_id == liability_id,
                    )
                    .order_by(LiabilityScheduleItem.due_date)
                )
            ).all()
        )
        return [LiabilityScheduleItemResponse.model_validate(row) for row in rows]

    async def confirm_liability_schedule(
        self,
        user_id: str,
        liability_id: str,
        data: LiabilityScheduleConfirm,
    ) -> list[LiabilityScheduleItemResponse]:
        liability = await self.db.scalar(
            select(Liability).where(Liability.id == liability_id, Liability.user_id == user_id)
        )
        if liability is None:
            raise LookupError("Liability not found")
        existing_count = await self.db.scalar(
            select(func.count(LiabilityScheduleItem.id)).where(
                LiabilityScheduleItem.user_id == user_id,
                LiabilityScheduleItem.liability_id == liability_id,
            )
        )
        if existing_count:
            raise ValueError("This schedule is already confirmed; existing evidence is append-only")
        dates = [item.due_date for item in data.items]
        if len(dates) != len(set(dates)):
            raise ValueError("A confirmed schedule can contain only one instalment per due date")
        if dates != sorted(dates):
            raise ValueError("Schedule instalments must be ordered by due date")

        schedule_rows: list[LiabilityScheduleItem] = []
        for item in data.items:
            if (
                any(
                    value is not None
                    for value in (
                        item.principal_amount,
                        item.interest_amount,
                        item.tax_amount,
                        item.fee_amount,
                    )
                )
                and sum(
                    (
                        value or Decimal()
                        for value in (
                            item.principal_amount,
                            item.interest_amount,
                            item.tax_amount,
                            item.fee_amount,
                        )
                    ),
                    Decimal(),
                )
                != item.installment_amount
            ):
                raise ValueError(
                    "Principal, interest, tax, and fee components must equal the instalment amount"
                )
            row = LiabilityScheduleItem(
                user_id=user_id,
                liability_id=liability.id,
                source_kind=data.source_kind,
                source_identifier=f"confirmed_schedule:{liability.id}:{item.due_date}",
                confidence=Decimal("1.000"),
                **item.model_dump(),
            )
            self.db.add(row)
            schedule_rows.append(row)
        await self.db.flush()

        today = await user_financial_today(self.db, user_id)
        upcoming = [row for row in schedule_rows if row.due_date >= today]
        generated_commitments: list[Commitment] = []
        for row in upcoming:
            commitment = Commitment(
                user_id=user_id,
                financial_account_id=liability.financial_account_id,
                liability_id=liability.id,
                label=f"{liability.label} instalment",
                commitment_type="emi",
                amount=row.installment_amount,
                due_date=row.due_date,
                cadence=None,
                source_kind=data.source_kind,
                source_identifier=f"liability_schedule:{row.id}",
                confirmed=True,
            )
            self.db.add(commitment)
            generated_commitments.append(commitment)

        liability.complete_schedule = True
        liability.schedule_status = "confirmed"
        liability.remaining_installments = len(upcoming)
        if upcoming:
            liability.next_due_date = upcoming[0].due_date
            liability.monthly_due = upcoming[0].installment_amount
        if data.source_kind == "statement":
            liability.source_kind = "statement"
            liability.source_confidence = Decimal("1.000")
        await self.db.flush()
        for row in schedule_rows:
            await self._snapshot_liability_schedule_item(row, liability)
        for commitment in generated_commitments:
            await self._snapshot_commitment(commitment)
        await self.db.commit()
        for row in schedule_rows:
            await self.db.refresh(row)
        return [LiabilityScheduleItemResponse.model_validate(row) for row in schedule_rows]

    async def update_liability_schedule_item(
        self,
        user_id: str,
        liability_id: str,
        item_id: str,
        data: LiabilityScheduleItemUpdate,
    ) -> LiabilityScheduleItemResponse | None:
        liability = await self.db.scalar(
            select(Liability).where(
                Liability.id == liability_id,
                Liability.user_id == user_id,
            )
        )
        if liability is None:
            raise LookupError("Liability not found")
        item = await self.db.scalar(
            select(LiabilityScheduleItem).where(
                LiabilityScheduleItem.id == item_id,
                LiabilityScheduleItem.liability_id == liability_id,
                LiabilityScheduleItem.user_id == user_id,
            )
        )
        if item is None:
            return None
        item.status = data.status
        commitment = await self.db.scalar(
            select(Commitment).where(
                Commitment.user_id == user_id,
                Commitment.liability_id == liability_id,
                Commitment.source_identifier == f"liability_schedule:{item.id}",
            )
        )
        if commitment is not None:
            commitment.is_active = data.status == "upcoming"
            commitment.confirmed = data.status == "upcoming"

        schedule = list(
            (
                await self.db.scalars(
                    select(LiabilityScheduleItem)
                    .where(
                        LiabilityScheduleItem.user_id == user_id,
                        LiabilityScheduleItem.liability_id == liability_id,
                    )
                    .order_by(LiabilityScheduleItem.due_date)
                )
            ).all()
        )
        upcoming = [row for row in schedule if row.status == "upcoming"]
        liability.remaining_installments = len(upcoming)
        liability.next_due_date = upcoming[0].due_date if upcoming else None
        liability.monthly_due = upcoming[0].installment_amount if upcoming else None
        await self.db.flush()
        await self._snapshot_liability_schedule_item(item, liability)
        if commitment is not None:
            await self._snapshot_commitment(commitment)
        await self.db.commit()
        await self.db.refresh(item)
        return LiabilityScheduleItemResponse.model_validate(item)

    async def card_overview(self, user_id: str, account_id: str) -> CardOverviewResponse:
        account = await self._require_card_account(user_id, account_id)
        position = await self.account_position(user_id, account_id)
        statements = list(
            (
                await self.db.scalars(
                    select(CreditCardStatement)
                    .where(
                        CreditCardStatement.user_id == user_id,
                        CreditCardStatement.financial_account_id == account_id,
                    )
                    .order_by(CreditCardStatement.statement_date.desc())
                )
            ).all()
        )
        statement = statements[0] if statements else None
        financial_today = await user_financial_today(self.db, user_id)
        provider_position = await self.db.scalar(
            select(CardPositionObservation)
            .where(
                CardPositionObservation.user_id == user_id,
                CardPositionObservation.financial_account_id == account_id,
            )
            .order_by(
                CardPositionObservation.as_of.desc(),
                CardPositionObservation.effective_at.desc().nulls_last(),
                CardPositionObservation.observed_at.desc(),
                CardPositionObservation.created_at.desc(),
            )
        )
        post_statement_transactions: list[Transaction] = []
        if statement is not None:
            post_statement_transactions = list(
                (
                    await self.db.scalars(
                        select(Transaction).where(
                            Transaction.user_id == user_id,
                            Transaction.financial_account_id == account_id,
                            Transaction.currency == account.currency,
                            Transaction.transaction_date > statement.statement_date,
                            Transaction.transaction_date <= financial_today,
                        )
                    )
                ).all()
            )
        paid_since_statement = sum(
            (
                transaction.amount
                for transaction in post_statement_transactions
                if balance_transaction_eligible(transaction)
                and transaction.card_event == CardEvent.PAYMENT
                and transaction.transaction_type in {TransactionType.CREDIT, TransactionType.REFUND}
            ),
            Decimal("0"),
        )
        unbilled_movements = [
            signed_balance_movement(transaction, "liability")
            for transaction in post_statement_transactions
            if balance_transaction_eligible(transaction)
            and transaction.card_event != CardEvent.PAYMENT
        ]
        unbilled_activity = sum(unbilled_movements, Decimal("0"))
        unbilled_activity_increase = sum(
            (movement for movement in unbilled_movements if movement > 0),
            Decimal("0"),
        )
        unbilled_activity_decrease = sum(
            (-movement for movement in unbilled_movements if movement < 0),
            Decimal("0"),
        )
        preference = await self.db.scalar(
            select(CardPreference).where(
                CardPreference.user_id == user_id, CardPreference.financial_account_id == account_id
            )
        )
        all_lines = (
            []
            if not statements
            else list(
                (
                    await self.db.scalars(
                        select(StatementLine)
                        .where(
                            StatementLine.credit_card_statement_id.in_(
                                [item.id for item in statements]
                            )
                        )
                        .order_by(
                            StatementLine.credit_card_statement_id,
                            StatementLine.line_number,
                        )
                    )
                ).all()
            )
        )
        lines_by_statement: dict[str, list[StatementLine]] = {item.id: [] for item in statements}
        for line in all_lines:
            lines_by_statement[line.credit_card_statement_id].append(line)
        lines = [] if statement is None else lines_by_statement[statement.id]
        coverage: dict[ReviewOutcome, int] = dict.fromkeys(
            ("matched", "newly_imported", "ignored_by_rule", "needs_review"), 0
        )
        for line in lines:
            outcome = cast(ReviewOutcome, line.review_outcome)
            coverage[outcome] = coverage.get(outcome, 0) + 1
        payments = list(
            (
                await self.db.scalars(
                    select(CardPaymentIntent)
                    .where(
                        CardPaymentIntent.user_id == user_id,
                        CardPaymentIntent.financial_account_id == account_id,
                    )
                    .order_by(
                        (CardPaymentIntent.status == "planned").desc(),
                        CardPaymentIntent.planned_for.desc(),
                    )
                )
            ).all()
        )
        calendar = list(
            (
                await self.db.scalars(
                    select(CardCalendarEvent)
                    .where(
                        CardCalendarEvent.user_id == user_id,
                        CardCalendarEvent.financial_account_id == account_id,
                    )
                    .order_by(CardCalendarEvent.event_date)
                )
            ).all()
        )
        pending_reversals = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.financial_account_id == account_id,
                        Transaction.card_event == CardEvent.REVERSAL,
                        Transaction.transaction_status != "completed",
                    )
                )
            ).all()
        )
        refund_transactions = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.financial_account_id == account_id,
                        Transaction.currency == account.currency,
                        Transaction.card_event == CardEvent.REFUND,
                    )
                )
            ).all()
        )
        refund_tracker = build_card_refund_tracker(
            as_of=financial_today,
            refunds=[
                (
                    transaction.transaction_date,
                    transaction.amount,
                    transaction.transaction_status,
                    transaction.review_outcome,
                )
                for transaction in refund_transactions
            ],
        )
        utilization = None
        if statement and statement.total_due is not None and statement.credit_limit:
            utilization = float(statement.total_due / statement.credit_limit * Decimal("100"))
        estimated_utilization = None
        if (
            position
            and position.estimated_balance is not None
            and statement
            and statement.credit_limit
        ):
            estimated_utilization = float(
                Decimal(str(position.estimated_balance)) / statement.credit_limit * Decimal("100")
            )
        projection_movements = [
            signed_balance_movement(transaction, "liability")
            for transaction in post_statement_transactions
            if balance_transaction_eligible(transaction)
            and transaction.card_event != CardEvent.PAYMENT
        ]
        historical_daily_paces: list[Decimal] = []
        historical_cycle_movements: list[HistoricalCycleMovements] = []
        if len(statements) > 2 and statement is not None:
            oldest_period_start = min(item.period_start for item in statements)
            historical_transactions = list(
                (
                    await self.db.scalars(
                        select(Transaction).where(
                            Transaction.user_id == user_id,
                            Transaction.financial_account_id == account_id,
                            Transaction.transaction_date >= oldest_period_start,
                            Transaction.transaction_date <= financial_today,
                        )
                    )
                ).all()
            )
            for historical_statement in statements[1:]:
                cycle_days = (
                    historical_statement.period_end - historical_statement.period_start
                ).days + 1
                if cycle_days < 21 or cycle_days > 45:
                    continue
                cycle_movements = [
                    signed_balance_movement(transaction, "liability")
                    for transaction in historical_transactions
                    if historical_statement.period_start
                    <= transaction.transaction_date
                    <= historical_statement.period_end
                    and balance_transaction_eligible(transaction)
                    and transaction.card_event != CardEvent.PAYMENT
                ]
                if len(cycle_movements) >= 3:
                    historical_daily_paces.append(
                        max(sum(cycle_movements, Decimal("0")), Decimal("0")) / Decimal(cycle_days)
                    )
                if len(cycle_movements) >= 2:
                    historical_cycle_movements.append(
                        (
                            historical_statement.period_start,
                            historical_statement.period_end,
                            [
                                (
                                    transaction.transaction_date,
                                    signed_balance_movement(transaction, "liability"),
                                )
                                for transaction in historical_transactions
                                if historical_statement.period_start
                                <= transaction.transaction_date
                                <= historical_statement.period_end
                                and balance_transaction_eligible(transaction)
                                and transaction.card_event != CardEvent.PAYMENT
                            ],
                        )
                    )
        future_scheduled_charges: list[tuple[date, Decimal, str]] = []
        future_recurring_charges: list[CardRecurringChargeCandidate] = []
        if statement is not None:
            future_emi_rows = list(
                (
                    await self.db.execute(
                        select(
                            LiabilityScheduleItem.due_date,
                            LiabilityScheduleItem.installment_amount,
                            Liability.issuer_plan_reference,
                        )
                        .join(Liability, Liability.id == LiabilityScheduleItem.liability_id)
                        .where(
                            Liability.user_id == user_id,
                            Liability.financial_account_id == account_id,
                            Liability.liability_type == "card_emi",
                            Liability.is_active.is_(True),
                            LiabilityScheduleItem.status == "upcoming",
                            LiabilityScheduleItem.due_date > financial_today,
                        )
                        .order_by(LiabilityScheduleItem.due_date)
                    )
                ).all()
            )
            future_scheduled_charges = [
                (
                    row.due_date,
                    row.installment_amount,
                    row.issuer_plan_reference or "card EMI",
                )
                for row in future_emi_rows
            ]
            recurring_patterns = await RecurringPatternService(self.db).analyze(
                user_id,
                as_of=financial_today,
                financial_account_id=account_id,
            )
            future_recurring_charges = [
                CardRecurringChargeCandidate(
                    expected_date=pattern.next_expected_date,
                    amount=Decimal(str(pattern.avg_amount)),
                    merchant=pattern.merchant,
                    cadence=pattern.cadence,
                    occurrences=pattern.occurrences,
                    confidence=Decimal(str(pattern.confidence)),
                    amount_low=Decimal(str(pattern.amount_low)),
                    amount_high=Decimal(str(pattern.amount_high)),
                    expected_date_low=pattern.next_expected_date_low,
                    expected_date_high=pattern.next_expected_date_high,
                )
                for pattern in recurring_patterns
                if (
                    pattern.status in {"early", "mature"}
                    and pattern.next_expected_date is not None
                    and pattern.next_expected_date > financial_today
                    and pattern.cadence is not None
                )
            ]
        next_statement_projection = build_card_statement_projection(
            today=(
                financial_today
                if statement is not None
                else await user_financial_today(self.db, user_id)
            ),
            statement_date=statement.statement_date if statement else None,
            period_start=statement.period_start if statement else None,
            period_end=statement.period_end if statement else None,
            current_balance=(
                Decimal(str(position.estimated_balance))
                if position and position.estimated_balance is not None
                else None
            ),
            credit_limit=statement.credit_limit if statement else None,
            balance_confidence=position.position_confidence if position else 0.0,
            eligible_movements=projection_movements,
            utilization_target_pct=preference.utilization_target_pct if preference else None,
            historical_daily_paces=historical_daily_paces,
            historical_cycle_movements=historical_cycle_movements,
            future_planned_payments=[
                (payment.planned_for, payment.amount)
                for payment in payments
                if payment.status == "planned" and payment.planned_for > financial_today
            ],
            future_scheduled_charges=future_scheduled_charges,
            future_recurring_charges=future_recurring_charges,
            pending_refund_amount=Decimal(str(refund_tracker.pending_amount)),
        )
        return CardOverviewResponse(
            financial_account_id=account.id,
            currency=account.currency,
            latest_statement_id=statement.id if statement else None,
            statement_date=statement.statement_date if statement else None,
            period_start=statement.period_start if statement else None,
            period_end=statement.period_end if statement else None,
            total_due=(
                float(statement.total_due)
                if statement and statement.total_due is not None
                else None
            ),
            billed_total_due=(
                float(statement.total_due)
                if statement and statement.total_due is not None
                else None
            ),
            billed_total_due_as_of=statement.statement_date if statement else None,
            paid_since_statement=(float(paid_since_statement) if statement is not None else None),
            unbilled_activity=(float(unbilled_activity) if statement is not None else None),
            unbilled_activity_increase=(
                float(unbilled_activity_increase) if statement is not None else None
            ),
            unbilled_activity_decrease=(
                float(unbilled_activity_decrease) if statement is not None else None
            ),
            minimum_due=(
                float(statement.minimum_due)
                if statement and statement.minimum_due is not None
                else None
            ),
            due_date=statement.due_date if statement else None,
            previous_due=(
                float(statement.previous_due)
                if statement and statement.previous_due is not None
                else None
            ),
            payments_credits=(
                float(statement.payments_credits)
                if statement and statement.payments_credits is not None
                else None
            ),
            purchases_debits=(
                float(statement.purchases_debits)
                if statement and statement.purchases_debits is not None
                else None
            ),
            finance_charges=(
                float(statement.finance_charges)
                if statement and statement.finance_charges is not None
                else None
            ),
            credit_limit=(
                float(statement.credit_limit)
                if statement and statement.credit_limit is not None
                else None
            ),
            available_credit_limit=(
                float(statement.available_credit_limit)
                if statement and statement.available_credit_limit is not None
                else None
            ),
            available_cash_limit=(
                float(statement.available_cash_limit)
                if statement and statement.available_cash_limit is not None
                else None
            ),
            observed_balance=position.observed_balance if position else None,
            observed_balance_as_of=position.observed_as_of if position else None,
            observed_source=position.observed_source if position else None,
            observed_source_record_id=position.observed_source_record_id if position else None,
            observed_at=position.observed_at if position else None,
            observed_effective_at=position.observed_effective_at if position else None,
            provider_current_outstanding=(
                float(provider_position.current_outstanding)
                if provider_position is not None
                else None
            ),
            provider_current_outstanding_as_of=(
                provider_position.as_of if provider_position is not None else None
            ),
            provider_billed_due=(
                float(provider_position.billed_due)
                if provider_position is not None and provider_position.billed_due is not None
                else None
            ),
            provider_pending_amount=(
                float(provider_position.pending_amount)
                if provider_position is not None and provider_position.pending_amount is not None
                else None
            ),
            provider_credit_limit=(
                float(provider_position.credit_limit)
                if provider_position is not None and provider_position.credit_limit is not None
                else None
            ),
            provider_available_credit=(
                float(provider_position.available_credit)
                if provider_position is not None and provider_position.available_credit is not None
                else None
            ),
            provider_source=provider_position.source if provider_position is not None else None,
            provider_source_record_id=(
                provider_position.source_record_id if provider_position is not None else None
            ),
            provider_observed_at=(
                provider_position.observed_at if provider_position is not None else None
            ),
            provider_effective_at=(
                provider_position.effective_at if provider_position is not None else None
            ),
            provider_coverage_start=(
                provider_position.coverage_start if provider_position is not None else None
            ),
            provider_coverage_end=(
                provider_position.coverage_end if provider_position is not None else None
            ),
            provider_coverage_complete=(
                provider_position.coverage_complete if provider_position is not None else None
            ),
            estimated_current_balance=position.estimated_balance if position else None,
            estimated_current_as_of=position.estimated_as_of if position else None,
            settled_movement_since_observation=(
                position.settled_movement_since_observation if position else None
            ),
            pending_increase=position.pending_increase if position else 0.0,
            pending_decrease=position.pending_decrease if position else 0.0,
            coverage_start=position.coverage_start if position else None,
            coverage_end=position.coverage_end if position else None,
            latest_sync_at=position.latest_sync_at if position else None,
            coverage_complete=position.coverage_complete if position else None,
            coverage_status=position.coverage_status if position else "unknown",
            reconciliation_delta=position.reconciliation_delta if position else None,
            last_reconciled_at=position.last_reconciled_at if position else None,
            estimated_utilization_pct=estimated_utilization,
            next_statement_projection=next_statement_projection,
            refund_tracker=refund_tracker,
            balance_status=position.position_status if position else "needs_observation",
            balance_confidence=position.position_confidence if position else 0.0,
            balance_reason_codes=position.position_reason_codes if position else [],
            statement_utilization_pct=utilization,
            utilization_target_pct=(
                float(preference.utilization_target_pct)
                if preference and preference.utilization_target_pct is not None
                else None
            ),
            preferred_payment_account_id=(
                preference.preferred_payment_account_id if preference else None
            ),
            reward_rules=(json.loads(preference.reward_rules_json) if preference else []),
            coverage=coverage,
            statement_lines=[
                StatementLineResponse.model_validate(line, from_attributes=True) for line in lines
            ],
            statement_history=[
                CardStatementHistoryItem(
                    id=item.id,
                    statement_date=item.statement_date,
                    period_start=item.period_start,
                    period_end=item.period_end,
                    due_date=item.due_date,
                    total_due=float(item.total_due) if item.total_due is not None else None,
                    minimum_due=float(item.minimum_due) if item.minimum_due is not None else None,
                    line_count=len(lines_by_statement[item.id]),
                    needs_review_count=sum(
                        1
                        for line in lines_by_statement[item.id]
                        if line.review_outcome == "needs_review"
                    ),
                )
                for item in statements
            ],
            planned_payments=[CardPaymentIntentResponse.model_validate(item) for item in payments],
            calendar=[CardCalendarEventResponse.model_validate(item) for item in calendar],
            activity_signals=_card_activity_signals(
                lines,
                statement.credit_limit if statement else None,
                pending_reversals,
            ),
            emi_plans=_build_card_emi_plans(statements, all_lines),
        )

    async def save_card_preference(
        self, user_id: str, account_id: str, data: CardPreferenceUpsert
    ) -> CardPreferenceResponse:
        await self._require_card_account(user_id, account_id)
        await self._validate_optional_account(user_id, data.preferred_payment_account_id)
        preference = await self.db.scalar(
            select(CardPreference).where(
                CardPreference.user_id == user_id, CardPreference.financial_account_id == account_id
            )
        )
        if preference is None:
            preference = CardPreference(user_id=user_id, financial_account_id=account_id)
            self.db.add(preference)
        preference.preferred_payment_account_id = data.preferred_payment_account_id
        preference.utilization_target_pct = data.utilization_target_pct
        preference.reward_rules_json = json.dumps(data.reward_rules, sort_keys=True)
        await self.db.commit()
        return CardPreferenceResponse(
            financial_account_id=account_id,
            preferred_payment_account_id=preference.preferred_payment_account_id,
            utilization_target_pct=preference.utilization_target_pct,
            reward_rules=json.loads(preference.reward_rules_json),
        )

    async def create_card_payment_intent(
        self, user_id: str, account_id: str, data: CardPaymentIntentCreate
    ) -> CardPaymentIntentResponse:
        await self._require_card_account(user_id, account_id)
        await self._validate_optional_account(user_id, data.paying_account_id)
        intent = CardPaymentIntent(
            user_id=user_id, financial_account_id=account_id, **data.model_dump()
        )
        self.db.add(intent)
        await self.db.flush()
        await capture_card_payment_intent_snapshot(self.db, intent)
        await self.db.commit()
        await self.db.refresh(intent)
        return CardPaymentIntentResponse.model_validate(intent)

    async def update_card_payment_intent(
        self,
        user_id: str,
        account_id: str,
        intent_id: str,
        data: CardPaymentIntentUpdate,
    ) -> CardPaymentIntentResponse:
        card_account = await self._require_card_account(user_id, account_id)
        intent = await self.db.scalar(
            select(CardPaymentIntent)
            .where(
                CardPaymentIntent.id == intent_id,
                CardPaymentIntent.user_id == user_id,
                CardPaymentIntent.financial_account_id == account_id,
            )
            .with_for_update()
        )
        if intent is None:
            raise LookupError("Card payment intention not found")
        if intent.status == data.status:
            return CardPaymentIntentResponse.model_validate(intent)
        if intent.status != "planned":
            raise ValueError("A completed or cancelled payment intention cannot be changed")
        if data.status == "cancelled":
            intent.status = "cancelled"
            await self.db.flush()
            await capture_card_payment_intent_snapshot(self.db, intent)
            await self.db.commit()
            await self.db.refresh(intent)
            return CardPaymentIntentResponse.model_validate(intent)
        if data.paying_account_id is not None:
            await self._validate_optional_account(user_id, data.paying_account_id)
            intent.paying_account_id = data.paying_account_id
        if intent.paying_account_id is None:
            raise ValueError("Choose the bank account used before recording this payment")
        paying_account = await self._require_account(user_id, intent.paying_account_id)
        if paying_account.account_type != "bank":
            raise ValueError("Card payments must originate from a bank account")
        transfer = await AccountService(self.db).create_transfer(
            user_id,
            TransferCreate(
                from_account_id=paying_account.id,
                to_account_id=card_account.id,
                amount=intent.amount,
                currency=card_account.currency,
                transaction_date=intent.planned_for,
                description="User-recorded credit card payment",
                payment_rail="transfer",
            ),
            commit=False,
        )
        card_transaction = await self.db.get(Transaction, transfer.credit_transaction_id)
        if card_transaction is None:
            raise RuntimeError("Card-payment transfer could not be created")
        card_transaction.card_event = CardEvent.PAYMENT
        await self.db.flush()
        await capture_transaction_snapshot(self.db, card_transaction)
        intent.status = "recorded"
        intent.transfer_group_id = transfer.transfer_group_id
        await self.db.flush()
        await capture_card_payment_intent_snapshot(self.db, intent)
        await self.db.commit()
        await self.db.refresh(intent)
        return CardPaymentIntentResponse.model_validate(intent)

    async def create_card_calendar_event(
        self, user_id: str, account_id: str, data: CardCalendarEventCreate
    ) -> CardCalendarEventResponse:
        await self._require_card_account(user_id, account_id)
        event = CardCalendarEvent(
            user_id=user_id,
            financial_account_id=account_id,
            source_kind="manual",
            **data.model_dump(),
        )
        self.db.add(event)
        await self.db.flush()
        await self._snapshot_card_calendar_event(event)
        await self.db.commit()
        await self.db.refresh(event)
        return CardCalendarEventResponse.model_validate(event)

    async def update_card_calendar_event(
        self,
        user_id: str,
        account_id: str,
        event_id: str,
        data: CardCalendarEventUpdate,
    ) -> CardCalendarEventResponse:
        await self._require_card_account(user_id, account_id)
        event = await self.db.scalar(
            select(CardCalendarEvent).where(
                CardCalendarEvent.id == event_id,
                CardCalendarEvent.user_id == user_id,
                CardCalendarEvent.financial_account_id == account_id,
            )
        )
        if event is None:
            raise LookupError("Card calendar event not found")
        for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(event, field, value)
        await self.db.flush()
        await self._snapshot_card_calendar_event(event)
        await self.db.commit()
        await self.db.refresh(event)
        return CardCalendarEventResponse.model_validate(event)

    async def delete_card_calendar_event(
        self,
        user_id: str,
        account_id: str,
        event_id: str,
    ) -> None:
        await self._require_card_account(user_id, account_id)
        event = await self.db.scalar(
            select(CardCalendarEvent).where(
                CardCalendarEvent.id == event_id,
                CardCalendarEvent.user_id == user_id,
                CardCalendarEvent.financial_account_id == account_id,
            )
        )
        if event is None:
            raise LookupError("Card calendar event not found")
        await self._snapshot_card_calendar_event(event, deleted=True)
        await self.db.delete(event)
        await self.db.commit()

    async def _snapshot_card_calendar_event(
        self, event: CardCalendarEvent, *, deleted: bool = False
    ) -> None:
        await capture_temporal_source_snapshot(
            self.db,
            user_id=event.user_id,
            source_type="card_calendar",
            source_id=event.id,
            payload={
                "financial_account_id": event.financial_account_id,
                "event_type": event.event_type,
                "label": event.label,
                "event_date": event.event_date,
                "source_kind": event.source_kind,
            },
            deleted=deleted,
        )

    async def _snapshot_transaction_mutations(self, user_id: str) -> None:
        """Persist temporal evidence for direct transaction edits in repair flows.

        Most transaction writes go through ``TransactionService``. The historical
        repair path intentionally performs several coordinated edits in one pass,
        so capture the session's dirty transaction set once the pass is complete.
        Explicit bulk deletes are snapshotted at their delete site because those
        rows do not reliably enter ``AsyncSession.deleted``.
        """
        deleted_ids = {
            transaction.id
            for transaction in self.db.deleted
            if isinstance(transaction, Transaction) and transaction.user_id == user_id
        }
        candidates = [
            transaction
            for transaction in self.db.dirty
            if isinstance(transaction, Transaction)
            and transaction.user_id == user_id
            and transaction.id not in deleted_ids
        ]
        await self.db.flush()
        for transaction in candidates:
            await capture_transaction_snapshot(self.db, transaction)

    async def _sync_card_emi_liabilities(
        self,
        user_id: str,
        *,
        account_id: str | None = None,
        persist: bool = True,
    ) -> int:
        """Materialize issuer EMI evidence without inventing a repayment schedule."""
        statement_query = select(CreditCardStatement).where(CreditCardStatement.user_id == user_id)
        if account_id is not None:
            statement_query = statement_query.where(
                CreditCardStatement.financial_account_id == account_id
            )
        statements = list((await self.db.scalars(statement_query)).all())
        statements_by_account: dict[str, list[CreditCardStatement]] = {}
        for statement in statements:
            statements_by_account.setdefault(statement.financial_account_id, []).append(statement)

        changed = 0
        for card_account_id, card_statements in statements_by_account.items():
            statement_ids = [statement.id for statement in card_statements]
            lines = list(
                (
                    await self.db.scalars(
                        select(StatementLine).where(
                            StatementLine.user_id == user_id,
                            StatementLine.credit_card_statement_id.in_(statement_ids),
                        )
                    )
                ).all()
            )
            plans = _build_card_emi_plans(card_statements, lines)
            existing_rows = list(
                (
                    await self.db.scalars(
                        select(Liability).where(
                            Liability.user_id == user_id,
                            Liability.financial_account_id == card_account_id,
                            Liability.liability_type == "card_emi",
                            Liability.issuer_plan_reference.is_not(None),
                        )
                    )
                ).all()
            )
            existing_by_reference = {row.issuer_plan_reference: row for row in existing_rows}
            active_plan_references = {plan.issuer_plan_reference for plan in plans}
            for stale in existing_rows:
                if (
                    stale.issuer_plan_reference not in active_plan_references
                    and stale.source_kind == "statement"
                    and not stale.complete_schedule
                    and stale.is_active
                ):
                    changed += 1
                    if persist:
                        stale.is_active = False
            for plan in plans:
                reference = plan.issuer_plan_reference
                latest_monthly = Decimal(str(plan.latest_installment_amount)).quantize(
                    Decimal("0.01")
                )
                observed_monthly = (
                    latest_monthly if latest_monthly > 0 and plan.status != "preclosed" else None
                )
                target_active = plan.status != "preclosed"
                latest_fee = Decimal(str(plan.latest_fees)).quantize(Decimal("0.01"))
                desired = {
                    "label": plan.merchant,
                    "source_kind": "statement",
                    "source_identifier": (f"card_emi:{card_account_id}:{reference}")[:160],
                    "source_confidence": (
                        Decimal("0.700") if reference.startswith("unlinked-") else Decimal("0.950")
                    ),
                    "observed_original_amount": (
                        Decimal(str(plan.original_amount)).quantize(Decimal("0.01"))
                        if plan.original_amount is not None
                        else None
                    ),
                    "observed_monthly_amount": observed_monthly,
                    "observed_principal_component": Decimal(str(plan.latest_principal)).quantize(
                        Decimal("0.01")
                    ),
                    "observed_interest_component": Decimal(str(plan.latest_interest)).quantize(
                        Decimal("0.01")
                    ),
                    "observed_tax_component": Decimal(str(plan.latest_tax)).quantize(
                        Decimal("0.01")
                    ),
                    "observed_fee_component": latest_fee,
                    "last_observed_statement_date": plan.latest_statement_date,
                    "evidence_line_count": plan.evidence_line_count,
                }
                liability = existing_by_reference.get(reference)
                if liability is None:
                    changed += 1
                    if persist:
                        liability = Liability(
                            user_id=user_id,
                            financial_account_id=card_account_id,
                            liability_type="card_emi",
                            issuer_plan_reference=reference,
                            monthly_due=desired["observed_monthly_amount"],
                            next_due_date=plan.latest_due_date,
                            complete_schedule=False,
                            schedule_status="observed_partial",
                            is_active=target_active,
                            **desired,
                        )
                        self.db.add(liability)
                    continue
                row_changed = any(
                    getattr(liability, field) != value for field, value in desired.items()
                )
                if not liability.complete_schedule:
                    row_changed = row_changed or (
                        liability.monthly_due != desired["observed_monthly_amount"]
                        or liability.next_due_date != plan.latest_due_date
                        or liability.schedule_status != "observed_partial"
                        or liability.is_active != target_active
                    )
                if not row_changed:
                    continue
                changed += 1
                if not persist:
                    continue
                for field, value in desired.items():
                    setattr(liability, field, value)
                if not liability.complete_schedule:
                    liability.monthly_due = observed_monthly
                    liability.next_due_date = plan.latest_due_date
                    liability.schedule_status = "observed_partial"
                    liability.is_active = target_active
        if persist and changed:
            await self.db.flush()
        return changed

    async def list_liabilities(self, user_id: str) -> list[LiabilityResponse]:
        rows = await self.db.scalars(
            select(Liability)
            .where(Liability.user_id == user_id, Liability.is_active.is_(True))
            .order_by(Liability.next_due_date)
        )
        return [LiabilityResponse.model_validate(row) for row in rows]

    async def liability_overview(self, user_id: str) -> LiabilityOverviewResponse:
        rows = list(
            (
                await self.db.scalars(
                    select(Liability)
                    .where(Liability.user_id == user_id, Liability.is_active.is_(True))
                    .order_by(Liability.next_due_date, Liability.created_at)
                )
            ).all()
        )
        confirmed = sum(
            (row.monthly_due or Decimal() for row in rows if row.schedule_status == "confirmed"),
            Decimal(),
        )
        observed = sum(
            (
                row.observed_monthly_amount or Decimal()
                for row in rows
                if row.schedule_status == "observed_partial"
            ),
            Decimal(),
        )
        manual_known = sum(
            (row.monthly_due or Decimal() for row in rows if row.schedule_status == "not_provided"),
            Decimal(),
        )
        next_rows = [
            row for row in rows if row.next_due_date is not None and row.monthly_due is not None
        ]
        next_row = (
            min(next_rows, key=lambda row: row.next_due_date or date.max) if next_rows else None
        )
        return LiabilityOverviewResponse(
            currency="INR",
            liabilities=[LiabilityResponse.model_validate(row) for row in rows],
            known_monthly_debt=float(confirmed + observed + manual_known),
            confirmed_monthly_debt=float(confirmed),
            observed_card_emi_monthly=float(observed),
            next_due_date=next_row.next_due_date if next_row else None,
            next_due_amount=(float(cast(Decimal, next_row.monthly_due)) if next_row else None),
            complete_schedule_count=sum(row.complete_schedule for row in rows),
            partial_evidence_count=sum(row.schedule_status == "observed_partial" for row in rows),
            assumptions=[
                "Observed card EMI amounts contain only the latest issuer-labelled principal, "
                "interest, and tax components; one-time fees are shown separately.",
                "Outstanding balance, annual rate, tenure, and remaining instalments stay "
                "unknown until an issuer or the user provides a complete schedule.",
            ],
        )

    async def upsert_cash_plan(self, user_id: str, data: CashPlanUpsert) -> CashPlanResponse:
        account = await self._require_account(user_id, data.primary_financial_account_id)
        if not account.is_active or account.account_type != "bank":
            raise ValueError("Cash Plan requires one active bank account")
        plan = await self.db.scalar(select(CashPlan).where(CashPlan.user_id == user_id))
        if plan is None:
            plan = CashPlan(user_id=user_id, **data.model_dump())
            self.db.add(plan)
        else:
            for field, value in data.model_dump().items():
                setattr(plan, field, value)
        await self.db.flush()
        await self._snapshot_cash_plan(plan)
        await self.db.commit()
        return await self.cash_plan(user_id)

    async def _snapshot_cash_plan(self, plan: CashPlan) -> None:
        await capture_temporal_source_snapshot(
            self.db,
            user_id=plan.user_id,
            source_type="cash_plan",
            source_id=plan.id,
            payload={
                "primary_financial_account_id": plan.primary_financial_account_id,
                "next_income_date": plan.next_income_date,
                "next_income_amount": plan.next_income_amount,
                "show_daily_allowance": plan.show_daily_allowance,
            },
        )

    async def cash_plan(self, user_id: str) -> CashPlanResponse:
        today = await user_financial_today(self.db, user_id)
        plan = await self.db.scalar(select(CashPlan).where(CashPlan.user_id == user_id))
        if plan is None:
            return CashPlanResponse(
                primary_financial_account_id="",
                currency=await get_ledger_currency(self.db, user_id),
                verified_balance=None,
                balance_as_of=None,
                next_income_date=None,
                confirmed_commitments=[],
                commitment_total=0,
                approved_reserve_total=0,
                flexible_money=None,
                daily_allowance=None,
                readiness="needs_verified_balance",
                assumptions=["Choose a primary bank account and record a verified balance."],
            )
        account = await self._require_account(user_id, plan.primary_financial_account_id)
        if not account.is_active or account.account_type != "bank":
            return CashPlanResponse(
                primary_financial_account_id="",
                currency=account.currency,
                verified_balance=None,
                balance_as_of=None,
                next_income_date=plan.next_income_date,
                confirmed_commitments=[],
                commitment_total=0,
                approved_reserve_total=0,
                flexible_money=None,
                daily_allowance=None,
                readiness="needs_verified_balance",
                assumptions=[
                    "Choose one active bank account before PFIS calculates flexible money."
                ],
            )
        position = await self.account_position(user_id, account.id)
        snapshot = await self.db.scalar(
            select(AccountBalanceSnapshot)
            .where(
                AccountBalanceSnapshot.user_id == user_id,
                AccountBalanceSnapshot.financial_account_id == account.id,
                AccountBalanceSnapshot.verified.is_(True),
            )
            .order_by(
                AccountBalanceSnapshot.as_of.desc(),
                AccountBalanceSnapshot.effective_at.desc().nulls_last(),
                AccountBalanceSnapshot.observed_at.desc(),
                AccountBalanceSnapshot.created_at.desc(),
            )
            .limit(1)
        )
        position_fields: _CashPlanPositionFields = {
            "estimated_balance": position.estimated_balance if position else None,
            "estimated_balance_as_of": position.estimated_as_of if position else None,
            "planning_balance": None,
            "planning_balance_as_of": None,
            "balance_basis": cast(
                Literal["verified", "estimated"] | None,
                (
                    "verified"
                    if position is not None and position.position_status == "observed"
                    else (
                        "estimated"
                        if position is not None and position.estimated_balance is not None
                        else None
                    )
                ),
            ),
            "position_status": position.position_status if position else "needs_observation",
            "position_confidence": position.position_confidence if position else 0.0,
            "position_reason_codes": list(position.position_reason_codes) if position else [],
            "observed_source": position.observed_source if position else None,
            "observed_at": position.observed_at if position else None,
            "coverage_start": position.coverage_start if position else None,
            "coverage_end": position.coverage_end if position else None,
            "latest_sync_at": position.latest_sync_at if position else None,
            "coverage_complete": position.coverage_complete if position else None,
            "coverage_status": position.coverage_status if position else "unknown",
            "settled_movement_since_observation": (
                position.settled_movement_since_observation if position else None
            ),
            "pending_increase": position.pending_increase if position else 0.0,
            "pending_decrease": position.pending_decrease if position else 0.0,
        }
        if snapshot is None:
            return CashPlanResponse(
                primary_financial_account_id=account.id,
                currency=account.currency,
                verified_balance=None,
                balance_as_of=None,
                next_income_date=plan.next_income_date,
                confirmed_commitments=[],
                commitment_total=0,
                approved_reserve_total=0,
                flexible_money=None,
                daily_allowance=None,
                readiness="needs_verified_balance",
                **position_fields,
                assumptions=["Record a verified balance before PFIS calculates flexible money."],
            )
        if snapshot.as_of < date.fromordinal(today.toordinal() - 7):
            return CashPlanResponse(
                primary_financial_account_id=account.id,
                currency=account.currency,
                verified_balance=float(snapshot.amount),
                balance_as_of=snapshot.as_of,
                next_income_date=plan.next_income_date,
                confirmed_commitments=[],
                commitment_total=0,
                approved_reserve_total=0,
                flexible_money=None,
                daily_allowance=None,
                readiness="needs_fresh_balance",
                **position_fields,
                assumptions=[
                    "The latest verified balance is more than seven days old; record a fresh observation."
                ],
            )
        if position is None or position.position_status not in {"observed", "estimated"}:
            return CashPlanResponse(
                primary_financial_account_id=account.id,
                currency=account.currency,
                verified_balance=float(snapshot.amount),
                balance_as_of=snapshot.as_of,
                next_income_date=plan.next_income_date,
                confirmed_commitments=[],
                commitment_total=0,
                approved_reserve_total=0,
                flexible_money=None,
                daily_allowance=None,
                readiness="needs_position_review",
                **position_fields,
                assumptions=[
                    "PFIS found unsettled, unreviewed, or cutoff-ambiguous activity after the balance anchor. "
                    "Review the account position before PFIS calculates flexible money."
                ],
            )
        if plan.next_income_date is None:
            return CashPlanResponse(
                primary_financial_account_id=account.id,
                currency=account.currency,
                verified_balance=float(snapshot.amount),
                balance_as_of=snapshot.as_of,
                next_income_date=None,
                confirmed_commitments=[],
                commitment_total=0,
                approved_reserve_total=0,
                flexible_money=None,
                daily_allowance=None,
                readiness="needs_next_income",
                **position_fields,
                assumptions=["Confirm the next income date; PFIS will not infer a salary date."],
            )
        if position.estimated_balance is None:
            return CashPlanResponse(
                primary_financial_account_id=account.id,
                currency=account.currency,
                verified_balance=float(snapshot.amount),
                balance_as_of=snapshot.as_of,
                next_income_date=plan.next_income_date,
                confirmed_commitments=[],
                commitment_total=0,
                approved_reserve_total=0,
                flexible_money=None,
                daily_allowance=None,
                readiness="needs_position_review",
                **position_fields,
                assumptions=[
                    "PFIS could not produce an eligible current position from the verified anchor."
                ],
            )
        commitments = list(
            (
                await self.db.scalars(
                    select(Commitment)
                    .where(
                        Commitment.user_id == user_id,
                        Commitment.is_active.is_(True),
                        Commitment.confirmed.is_(True),
                        Commitment.due_date <= plan.next_income_date,
                    )
                    .order_by(Commitment.due_date)
                )
            ).all()
        )
        reserves = list(
            (
                await self.db.scalars(
                    select(ReservePlan).where(
                        ReservePlan.user_id == user_id,
                        ReservePlan.financial_account_id == account.id,
                        ReservePlan.is_active.is_(True),
                        ReservePlan.approved.is_(True),
                    )
                )
            ).all()
        )
        commitment_total = sum((item.amount for item in commitments), Decimal())
        reserve_total = sum((item.monthly_allocation for item in reserves), Decimal())
        # Current planning starts from the canonical position read model, not
        # the stale anchor. ``position_status`` was gated above so this value
        # contains only the trusted anchor plus eligible settled movement.
        planning_balance = Decimal(str(position.estimated_balance))
        flexible = planning_balance - commitment_total - reserve_total
        days = max((plan.next_income_date - today).days, 1)
        allowance = flexible / days if plan.show_daily_allowance else None
        position_fields["planning_balance"] = float(planning_balance)
        position_fields["planning_balance_as_of"] = position.estimated_as_of
        return CashPlanResponse(
            primary_financial_account_id=account.id,
            currency=account.currency,
            verified_balance=float(snapshot.amount),
            balance_as_of=snapshot.as_of,
            next_income_date=plan.next_income_date,
            confirmed_commitments=[CommitmentResponse.model_validate(item) for item in commitments],
            commitment_total=float(commitment_total),
            approved_reserve_total=float(reserve_total),
            flexible_money=float(flexible),
            daily_allowance=float(allowance) if allowance is not None else None,
            readiness="ready",
            **position_fields,
            assumptions=[
                "Flexible money starts from the estimated current position, then subtracts only "
                "confirmed commitments due before the next confirmed income date and approved reserves."
            ],
        )

    async def import_hdfc_statement_text(
        self, user_id: str, data: StatementTextImport
    ) -> CreditCardStatementResponse:
        account = await self._require_account(user_id, data.financial_account_id)
        if account.account_type != "credit_card":
            raise ValueError("HDFC statements require a credit-card account")
        if account.currency != "INR":
            raise ValueError("HDFC statement imports currently support INR accounts only")
        if not (is_reviewed_layout(data.statement_text) or is_legacy_layout(data.statement_text)):
            raise ValueError("This is not the supported HDFC digital statement layout")
        existing_statement = await self._existing_credit_card_statement(user_id, data, account)
        if existing_statement is not None:
            return existing_statement
        extracted = extract_hdfc_statement(data.statement_text)
        if (
            extracted["statement_date"] is None
            or extracted["period_start"] is None
            or extracted["period_end"] is None
        ):
            raise ValueError("The HDFC statement billing period could not be verified")
        if is_reviewed_layout(data.statement_text):
            if extracted["card_last4"] is None:
                raise ValueError("The masked card identity could not be verified")
            account_last4 = re.sub(r"\D", "", account.masked_number or "")[-4:]
            if extracted["card_last4"] != account_last4:
                raise ValueError("This statement belongs to a different credit-card account")
        return await self._persist_credit_card_statement(
            user_id,
            data,
            account,
            extracted,
            issuer="HDFC",
            extractor_version=EXTRACTOR_VERSION,
        )

    async def import_generic_credit_card_statement_text(
        self, user_id: str, data: StatementTextImport
    ) -> CreditCardStatementResponse:
        """Atomically import the reviewed issuer-neutral card table profile."""

        account = await self._require_account(user_id, data.financial_account_id)
        if account.account_type != "credit_card":
            raise ValueError("Generic credit-card statements require a credit-card account")
        if not account.is_active:
            raise ValueError("Generic credit-card statements require an active account")
        existing_statement = await self._existing_credit_card_statement(user_id, data, account)
        if existing_statement is not None:
            return existing_statement
        extracted = extract_generic_credit_card_statement(data.statement_text)
        if extracted["currency"] not in {"unknown", account.currency}:
            raise ValueError(
                "The statement currency does not match the selected credit-card account"
            )
        account_last4 = re.sub(r"\D", "", account.masked_number or "")[-4:]
        if extracted["card_last4"] != account_last4:
            raise ValueError("This statement belongs to a different credit-card account")
        return await self._persist_credit_card_statement(
            user_id,
            data,
            account,
            extracted,
            issuer="GENERIC",
            extractor_version=GENERIC_CREDIT_CARD_EXTRACTOR_VERSION,
        )

    async def _existing_credit_card_statement(
        self,
        user_id: str,
        data: StatementTextImport,
        account: FinancialAccount,
    ) -> CreditCardStatementResponse | None:
        existing_import = await self.db.scalar(
            select(StatementImport).where(
                StatementImport.user_id == user_id,
                StatementImport.document_fingerprint == data.document_fingerprint,
            )
        )
        if existing_import is None:
            return None
        if existing_import.financial_account_id != account.id:
            raise ValueError("The statement fingerprint belongs to a different account")
        existing_statement = await self.db.scalar(
            select(CreditCardStatement).where(
                CreditCardStatement.statement_import_id == existing_import.id,
                CreditCardStatement.user_id == user_id,
            )
        )
        if existing_statement is None:
            raise ValueError("The existing statement import is incomplete")
        await self._capture_statement_balance_snapshot(account, existing_statement)
        await self.db.commit()
        return await self.statement(user_id, existing_statement.id)

    async def _persist_credit_card_statement(
        self,
        user_id: str,
        data: StatementTextImport,
        account: FinancialAccount,
        extracted: dict[str, Any],
        *,
        issuer: str,
        extractor_version: str,
    ) -> CreditCardStatementResponse:
        statement_import = StatementImport(
            user_id=user_id,
            financial_account_id=account.id,
            issuer=issuer,
            document_fingerprint=data.document_fingerprint,
            extractor_version=extractor_version,
        )
        self.db.add(statement_import)
        await self.db.flush()
        statement = CreditCardStatement(
            user_id=user_id,
            statement_import_id=statement_import.id,
            financial_account_id=account.id,
            **{
                key: value
                for key, value in extracted.items()
                if key not in {"lines", "card_last4", "layout_name", "currency"}
            },
            currency=account.currency,
        )
        self.db.add(statement)
        await self.db.flush()
        await self._capture_statement_balance_snapshot(account, statement)
        for line_number, line in enumerate(extracted["lines"], start=1):
            merchant = await resolve_merchant(self.db, line["description"], user_id=user_id)
            line_record = StatementLine(
                user_id=user_id,
                credit_card_statement_id=statement.id,
                line_number=line_number,
                merchant_normalized=merchant.normalized_name,
                merchant_confidence=merchant.confidence,
                **line,
            )
            self.db.add(line_record)
            await self.db.flush()
            match, has_conflict, match_method = await self._match_statement_line(
                user_id, account.id, line_record
            )
            if match:
                if match_method == "fuel_surcharge":
                    match.amount = line_record.amount
                line_record.review_outcome = "matched"
                self.db.add(
                    StatementLineMatch(
                        user_id=user_id,
                        statement_line_id=line_record.id,
                        transaction_id=match.id,
                        match_method=(
                            "reference"
                            if line_record.reference_id
                            else (
                                "fuel_surcharge_reconciliation"
                                if match_method == "fuel_surcharge"
                                else "amount_date_merchant"
                            )
                        ),
                        confidence=(
                            Decimal("1.000")
                            if line_record.reference_id
                            else (
                                Decimal("0.940")
                                if match_method == "fuel_surcharge"
                                else Decimal("0.900")
                            )
                        ),
                    )
                )
            elif has_conflict:
                line_record.review_outcome = "needs_review"
            elif line_record.card_event in {
                "purchase",
                "refund",
                "cashback",
                "fee",
                "tax",
                "interest",
                "reversal",
            }:
                try:
                    created = await TransactionService(self.db).create_transaction(
                        user_id,
                        TransactionCreate(
                            amount=line_record.amount,
                            currency=account.currency,
                            transaction_type=TransactionTypeEnum(line_record.transaction_type),
                            payment_method=PaymentMethodEnum.CREDIT_CARD,
                            payment_rail=PaymentRailEnum.OTHER,
                            card_event=CardEventEnum(line_record.card_event),
                            transaction_date=line_record.transaction_date,
                            source_email_id=None,
                            merchant_raw=line_record.description,
                            merchant_normalized=line_record.merchant_normalized,
                            category_id=merchant.category_id,
                            reference_id=line_record.reference_id,
                            # The owned account id is the statement identity. Keeping
                            # this unset lets a later email attach as source evidence
                            # before fingerprint deduplication treats it as final.
                            account_last4=None,
                            confidence_score=1.0,
                            financial_account_id=account.id,
                            source_kind="statement",
                            source_identifier=statement_import.id,
                            merchant_resolution_source=merchant.source,
                            merchant_resolution_confidence=merchant.confidence,
                            merchant_rule_id=merchant.rule_id,
                            merchant_resolver_version=merchant.resolver_version,
                        ),
                        commit=False,
                    )
                    line_record.created_transaction_id = created.id
                    line_record.review_outcome = "newly_imported"
                except DuplicateTransactionError:
                    line_record.review_outcome = "needs_review"
            # A card payment has no safe bank leg until the user picks one.
            await capture_statement_line_snapshot(
                self.db,
                line_record,
                financial_account_id=account.id,
            )
        # Apply the same deterministic historical-repair rules during import so
        # the user never has to click a separate cleanup action for new data.
        await self.repair_financial_intelligence(
            user_id,
            dry_run=False,
            commit=False,
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("The card statement conflicts with an existing statement") from exc
        return await self.statement(user_id, statement.id)

    async def import_hdfc_deposit_statement_text(
        self, user_id: str, data: StatementTextImport
    ) -> DepositAccountStatementResponse:
        """Atomically import one exact-profile HDFC bank statement.

        The pure extractor validates the entire running balance before any row
        is added.  Only rows with explicit rail evidence become transactions;
        other source rows remain durable review evidence.
        """

        account = await self._require_account(user_id, data.financial_account_id)
        self._validate_deposit_account(account, require_hdfc=True)
        extracted = extract_hdfc_deposit_statement(data.statement_text)
        account_last4 = re.sub(r"\D", "", account.masked_number or "")[-4:]
        if extracted["account_last4"] != account_last4:
            raise ValueError("This statement belongs to a different bank account")
        return await persist_deposit_statement(
            self,
            user_id,
            data,
            account,
            extracted,
            issuer="HDFC",
            extractor_version=DEPOSIT_EXTRACTOR_VERSION,
            account_last4=account_last4,
        )

    async def import_generic_deposit_statement_text(
        self, user_id: str, data: StatementTextImport
    ) -> DepositAccountStatementResponse:
        """Atomically import a strict issuer-neutral bank statement profile."""

        account = await self._require_account(user_id, data.financial_account_id)
        self._validate_deposit_account(account, require_hdfc=False)
        extracted = extract_generic_deposit_statement(data.statement_text)
        if extracted["currency"] not in {"unknown", account.currency}:
            raise ValueError("The statement currency does not match the selected bank account")
        account_last4 = re.sub(r"\D", "", account.masked_number or "")[-4:]
        if extracted["account_last4"] != account_last4:
            raise ValueError("This statement belongs to a different bank account")
        return await persist_deposit_statement(
            self,
            user_id,
            data,
            account,
            extracted,
            issuer="GENERIC",
            extractor_version=GENERIC_DEPOSIT_EXTRACTOR_VERSION,
            account_last4=account_last4,
        )

    @staticmethod
    def _validate_deposit_account(account: FinancialAccount, *, require_hdfc: bool) -> None:
        if account.account_type != "bank" or account.balance_kind != "asset":
            raise ValueError("Deposit statements require an asset bank account")
        if not account.is_active:
            raise ValueError("Deposit statements require an active bank account")
        if account.currency != "INR" and require_hdfc:
            raise ValueError("HDFC deposit statement imports currently support INR only")
        if account.identity_status != "confirmed":
            raise ValueError("Confirm the bank account identity before importing its statement")
        if require_hdfc and "HDFC" not in account.institution_name.upper():
            raise ValueError("The selected account is not identified as an HDFC bank account")

    async def _match_deposit_statement_line(
        self,
        user_id: str,
        financial_account_id: str,
        line: DepositStatementLine,
    ) -> tuple[Transaction | None, bool]:
        """Match only exact reference evidence; return ambiguity separately."""

        if not line.reference_id:
            return None, False
        matches = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.financial_account_id == financial_account_id,
                        Transaction.reference_id == line.reference_id,
                        Transaction.amount == line.amount,
                        Transaction.transaction_date == line.transaction_date,
                        Transaction.transaction_type == TransactionType(line.transaction_type),
                    )
                )
            ).all()
        )
        return (matches[0], False) if len(matches) == 1 else (None, len(matches) > 1)

    async def _create_deposit_statement_transaction(
        self,
        user_id: str,
        account: FinancialAccount,
        line: DepositStatementLine,
        *,
        account_last4: str,
        source_identifier: str,
    ) -> Transaction:
        """Create one explicitly classified bank-statement ledger event."""

        payment_rail = PaymentRailEnum(line.payment_rail)
        payment_method = {
            PaymentRailEnum.UPI: PaymentMethodEnum.UPI,
            PaymentRailEnum.DEBIT_CARD: PaymentMethodEnum.DEBIT_CARD,
            PaymentRailEnum.TRANSFER: PaymentMethodEnum.BANK_TRANSFER,
        }.get(payment_rail, PaymentMethodEnum.OTHER)
        merchant = await resolve_merchant(self.db, line.description, user_id=user_id)
        return await TransactionService(self.db).create_transaction(
            user_id,
            TransactionCreate(
                amount=line.amount,
                currency=account.currency,
                transaction_type=TransactionTypeEnum(line.transaction_type),
                payment_method=payment_method,
                payment_rail=payment_rail,
                transaction_date=line.transaction_date,
                source_email_id=None,
                merchant_raw=line.description,
                merchant_normalized=merchant.normalized_name,
                category_id=merchant.category_id,
                reference_id=line.reference_id,
                account_last4=account_last4,
                confidence_score=1.0,
                financial_account_id=account.id,
                source_kind="statement",
                source_identifier=source_identifier,
                merchant_resolution_source=merchant.source,
                merchant_resolution_confidence=merchant.confidence,
                merchant_rule_id=merchant.rule_id,
                merchant_resolver_version=merchant.resolver_version,
            ),
            commit=False,
        )

    async def deposit_statement_review_items(
        self, user_id: str
    ) -> list[DepositStatementReviewItemResponse]:
        """List owned deposit rows whose rail still needs explicit review."""

        rows = (
            await self.db.execute(
                select(
                    DepositStatementLine,
                    DepositAccountStatement,
                    FinancialAccount,
                    func.count(DepositStatementLineReviewDecision.id),
                )
                .join(
                    DepositAccountStatement,
                    DepositAccountStatement.id == DepositStatementLine.deposit_account_statement_id,
                )
                .join(
                    FinancialAccount,
                    FinancialAccount.id == DepositAccountStatement.financial_account_id,
                )
                .outerjoin(
                    DepositStatementLineReviewDecision,
                    DepositStatementLineReviewDecision.deposit_statement_line_id
                    == DepositStatementLine.id,
                )
                .where(
                    DepositStatementLine.user_id == user_id,
                    DepositStatementLine.review_outcome == "needs_review",
                )
                .group_by(
                    DepositStatementLine.id,
                    DepositAccountStatement.id,
                    FinancialAccount.id,
                )
                .order_by(
                    DepositAccountStatement.period_end.desc(),
                    DepositStatementLine.line_number,
                )
            )
        ).all()
        return [
            DepositStatementReviewItemResponse(
                **DepositStatementLineResponse.model_validate(
                    line, from_attributes=True
                ).model_dump(),
                financial_account_id=statement.financial_account_id,
                account_label=account.institution_name,
                masked_number=account.masked_number,
                period_start=statement.period_start,
                period_end=statement.period_end,
                decision_count=int(decision_count),
            )
            for line, statement, account, decision_count in rows
        ]

    async def review_deposit_statement_line(
        self,
        user_id: str,
        line_id: str,
        data: DepositStatementLineReviewRequest,
    ) -> DepositStatementLineReviewResponse:
        """Classify one unknown deposit row only after explicit user review."""

        row = (
            await self.db.execute(
                select(DepositStatementLine, DepositAccountStatement, FinancialAccount)
                .join(
                    DepositAccountStatement,
                    DepositAccountStatement.id == DepositStatementLine.deposit_account_statement_id,
                )
                .join(
                    FinancialAccount,
                    FinancialAccount.id == DepositAccountStatement.financial_account_id,
                )
                .where(
                    DepositStatementLine.id == line_id,
                    DepositStatementLine.user_id == user_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise LookupError("Deposit statement line not found")
        line, statement, account = row
        previous_outcome = line.review_outcome
        if previous_outcome != "needs_review":
            latest_decision = await self.db.scalar(
                select(DepositStatementLineReviewDecision)
                .where(
                    DepositStatementLineReviewDecision.user_id == user_id,
                    DepositStatementLineReviewDecision.deposit_statement_line_id == line.id,
                )
                .order_by(DepositStatementLineReviewDecision.created_at.desc())
                .limit(1)
            )
            if latest_decision is not None and (
                latest_decision.decision == data.decision
                and latest_decision.payment_rail == data.payment_rail
            ):
                return DepositStatementLineReviewResponse(
                    line=DepositStatementLineResponse.model_validate(line, from_attributes=True),
                    decision=data.decision,
                    previous_outcome=cast(ReviewOutcome, latest_decision.previous_outcome),
                    new_outcome=cast(ReviewOutcome, line.review_outcome),
                    payment_rail=line.payment_rail,
                    created_transaction_id=latest_decision.created_transaction_id,
                    decided_at=latest_decision.created_at,
                )
            raise ValueError("Deposit statement line is already resolved")

        selected_rail = data.payment_rail
        created_transaction_id: str | None = None
        if data.decision == "ignore":
            line.review_outcome = "ignored_by_rule"
        else:
            if selected_rail is None:
                raise ValueError("Choose the payment rail before importing this deposit row")
            line.payment_rail = selected_rail
            account_last4 = re.sub(r"\D", "", account.masked_number or "")[-4:]
            existing_transaction, has_conflict = await self._match_deposit_statement_line(
                user_id, account.id, line
            )
            if has_conflict:
                raise ValueError(
                    "This deposit row has multiple exact ledger matches and needs review"
                )
            if existing_transaction is not None:
                line.created_transaction_id = existing_transaction.id
                line.review_outcome = "matched"
                created_transaction_id = existing_transaction.id
            else:
                try:
                    created = await self._create_deposit_statement_transaction(
                        user_id,
                        account,
                        line,
                        account_last4=account_last4,
                        source_identifier=statement.statement_import_id,
                    )
                except DuplicateTransactionError as exc:
                    raise ValueError(
                        "A ledger event already has the same deterministic identity"
                    ) from exc
                line.created_transaction_id = created.id
                line.review_outcome = "newly_imported"
                created_transaction_id = created.id
                await capture_transaction_snapshot(self.db, created)

        self.db.add(
            DepositStatementLineReviewDecision(
                user_id=user_id,
                deposit_statement_line_id=line.id,
                decision=data.decision,
                previous_outcome=previous_outcome,
                new_outcome=line.review_outcome,
                payment_rail=selected_rail,
                created_transaction_id=created_transaction_id,
                note=data.note,
            )
        )
        await capture_deposit_statement_line_snapshot(
            self.db,
            line,
            financial_account_id=account.id,
        )
        await self.db.commit()
        return DepositStatementLineReviewResponse(
            line=DepositStatementLineResponse.model_validate(line, from_attributes=True),
            decision=data.decision,
            previous_outcome=cast(ReviewOutcome, previous_outcome),
            new_outcome=cast(ReviewOutcome, line.review_outcome),
            payment_rail=line.payment_rail,
            created_transaction_id=created_transaction_id,
            decided_at=datetime.now(UTC),
        )

    async def deposit_statement(
        self, user_id: str, statement_id: str
    ) -> DepositAccountStatementResponse:
        statement = await self.db.scalar(
            select(DepositAccountStatement).where(
                DepositAccountStatement.id == statement_id,
                DepositAccountStatement.user_id == user_id,
            )
        )
        if statement is None:
            raise LookupError("Deposit statement not found")
        lines = list(
            (
                await self.db.scalars(
                    select(DepositStatementLine)
                    .where(DepositStatementLine.deposit_account_statement_id == statement.id)
                    .order_by(DepositStatementLine.line_number)
                )
            ).all()
        )
        return DepositAccountStatementResponse(
            id=statement.id,
            financial_account_id=statement.financial_account_id,
            period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=float(statement.opening_balance),
            closing_balance=float(statement.closing_balance),
            currency=statement.currency,
            imported_transaction_count=sum(
                line.review_outcome in {"newly_imported", "matched"} for line in lines
            ),
            review_count=sum(line.review_outcome == "needs_review" for line in lines),
            lines=[
                DepositStatementLineResponse.model_validate(line, from_attributes=True)
                for line in lines
            ],
        )

    async def _capture_statement_balance_snapshot(
        self, account: FinancialAccount, statement: CreditCardStatement
    ) -> None:
        """Persist the issuer's billed total as a verified card liability anchor."""

        if statement.total_due is None:
            return
        source_record_id = f"credit-card-statement:{statement.id}"
        existing = await self.db.scalar(
            select(AccountBalanceSnapshot).where(
                AccountBalanceSnapshot.user_id == account.user_id,
                AccountBalanceSnapshot.financial_account_id == account.id,
                AccountBalanceSnapshot.source == "statement",
                AccountBalanceSnapshot.source_record_id == source_record_id,
            )
        )
        if existing is not None:
            return
        self.db.add(
            AccountBalanceSnapshot(
                user_id=account.user_id,
                financial_account_id=account.id,
                amount=statement.total_due,
                currency=statement.currency,
                as_of=statement.statement_date,
                source="statement",
                source_record_id=source_record_id,
                verified=True,
                observed_at=datetime.now(UTC),
            )
        )

    async def statement(self, user_id: str, statement_id: str) -> CreditCardStatementResponse:
        statement = await self.db.scalar(
            select(CreditCardStatement).where(
                CreditCardStatement.id == statement_id, CreditCardStatement.user_id == user_id
            )
        )
        if statement is None:
            raise LookupError("Statement not found")
        lines = list(
            (
                await self.db.scalars(
                    select(StatementLine)
                    .where(StatementLine.credit_card_statement_id == statement.id)
                    .order_by(StatementLine.line_number)
                )
            ).all()
        )
        payload = CreditCardStatementResponse.model_validate(
            statement, from_attributes=True
        ).model_dump()
        payload["lines"] = [
            StatementLineResponse.model_validate(line, from_attributes=True) for line in lines
        ]
        return CreditCardStatementResponse(**payload)

    async def statement_review_items(self, user_id: str) -> list[StatementReviewItemResponse]:
        rows = (
            await self.db.execute(
                select(
                    StatementLine,
                    CreditCardStatement,
                    FinancialAccount,
                    func.count(StatementLineReviewDecision.id),
                )
                .join(
                    CreditCardStatement,
                    CreditCardStatement.id == StatementLine.credit_card_statement_id,
                )
                .join(
                    FinancialAccount,
                    FinancialAccount.id == CreditCardStatement.financial_account_id,
                )
                .outerjoin(
                    StatementLineReviewDecision,
                    StatementLineReviewDecision.statement_line_id == StatementLine.id,
                )
                .where(
                    StatementLine.user_id == user_id,
                    StatementLine.review_outcome == "needs_review",
                )
                .group_by(
                    StatementLine.id,
                    CreditCardStatement.id,
                    FinancialAccount.id,
                )
                .order_by(
                    CreditCardStatement.statement_date.desc(),
                    StatementLine.line_number,
                )
            )
        ).all()
        items: list[StatementReviewItemResponse] = []
        for line, statement, account, decision_count in rows:
            candidates = list(
                (
                    await self.db.scalars(
                        select(Transaction)
                        .where(
                            Transaction.user_id == user_id,
                            Transaction.financial_account_id == account.id,
                            Transaction.amount == line.amount,
                            Transaction.transaction_type == TransactionType(line.transaction_type),
                            Transaction.transaction_date
                            >= date.fromordinal(line.transaction_date.toordinal() - 5),
                            Transaction.transaction_date
                            <= date.fromordinal(line.transaction_date.toordinal() + 5),
                        )
                        .order_by(Transaction.transaction_date, Transaction.id)
                    )
                ).all()
            )
            items.append(
                StatementReviewItemResponse(
                    **StatementLineResponse.model_validate(line, from_attributes=True).model_dump(),
                    financial_account_id=statement.financial_account_id,
                    account_label=account.institution_name,
                    masked_number=account.masked_number,
                    statement_date=statement.statement_date,
                    decision_count=int(decision_count),
                    candidate_transactions=[
                        StatementReviewCandidate(
                            id=candidate.id,
                            label=(
                                candidate.merchant_normalized
                                or candidate.merchant_raw
                                or "Ledger transaction"
                            ),
                            amount=float(candidate.amount),
                            transaction_date=candidate.transaction_date,
                            transaction_type=candidate.transaction_type.value,
                            source_kind=candidate.source_kind,
                        )
                        for candidate in candidates
                    ],
                )
            )
        return items

    async def card_payment_candidates(
        self, user_id: str, line_id: str
    ) -> list[StatementCardPaymentCandidateResponse]:
        """Rank owned bank debits that could fund one card-payment line.

        The query is deliberately read-only.  It requires explicit card-payment
        wording or a matching statement reference plus payment wording; amount
        and date alone are not enough to suggest a funding account.
        """

        row = (
            await self.db.execute(
                select(StatementLine, CreditCardStatement, FinancialAccount)
                .join(
                    CreditCardStatement,
                    CreditCardStatement.id == StatementLine.credit_card_statement_id,
                )
                .join(
                    FinancialAccount,
                    FinancialAccount.id == CreditCardStatement.financial_account_id,
                )
                .where(
                    StatementLine.id == line_id,
                    StatementLine.user_id == user_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise LookupError("Statement line not found")
        line, _statement, card_account = row
        if line.card_event != "payment":
            raise ValueError("Payment candidates are available only for card-payment lines")

        start_date = line.transaction_date - timedelta(days=5)
        end_date = line.transaction_date + timedelta(days=5)
        transactions = list(
            (
                await self.db.execute(
                    select(Transaction, FinancialAccount)
                    .join(
                        FinancialAccount,
                        FinancialAccount.id == Transaction.financial_account_id,
                    )
                    .where(
                        Transaction.user_id == user_id,
                        Transaction.transaction_type == TransactionType.DEBIT,
                        Transaction.amount == line.amount,
                        Transaction.transaction_date >= start_date,
                        Transaction.transaction_date <= end_date,
                        FinancialAccount.account_type == "bank",
                        FinancialAccount.is_active.is_(True),
                        FinancialAccount.currency == card_account.currency,
                    )
                )
            ).all()
        )
        candidates: list[StatementCardPaymentCandidateResponse] = []
        card_marker = re.compile(
            r"\b(?:CREDIT\s*CARD|CARD\s*(?:PAYMENT|BILL|SETTLEMENT)|" r"CC\s*(?:PAYMENT|BILL))\b",
            re.IGNORECASE,
        )
        payment_marker = re.compile(r"\b(?:PAYMENT|PAID|BILL|TRANSFER|SETTLEMENT)\b", re.IGNORECASE)
        line_reference = (line.reference_id or "").casefold()
        for transaction, paying_account in transactions:
            description = " ".join(
                (transaction.merchant_raw or transaction.merchant_normalized or "").split()
            )
            if not description:
                continue
            has_card_marker = bool(card_marker.search(description))
            has_payment_marker = bool(payment_marker.search(description))
            reference_match = bool(
                line_reference
                and transaction.reference_id
                and line_reference == transaction.reference_id.casefold()
            )
            if not has_card_marker and not (reference_match and has_payment_marker):
                continue
            day_delta = abs((transaction.transaction_date - line.transaction_date).days)
            evidence: list[str] = []
            score = Decimal("0.00")
            if reference_match:
                score += Decimal("0.55")
                evidence.append("statement_reference_match")
            if has_card_marker:
                score += Decimal("0.30")
                evidence.append("explicit_card_payment_wording")
            if has_payment_marker:
                score += Decimal("0.05")
                evidence.append("payment_wording")
            if day_delta == 0:
                score += Decimal("0.10")
                evidence.append("same_posting_date")
                match_method: Literal["reference", "same_day_amount", "near_day_amount"] = (
                    "same_day_amount"
                )
            else:
                score += Decimal("0.06") if day_delta <= 2 else Decimal("0.02")
                evidence.append("near_posting_date")
                match_method = "near_day_amount"
            if reference_match:
                match_method = "reference"
            candidates.append(
                StatementCardPaymentCandidateResponse(
                    transaction_id=transaction.id,
                    paying_account_id=paying_account.id,
                    account_label=paying_account.institution_name,
                    masked_number=paying_account.masked_number,
                    amount=float(transaction.amount),
                    transaction_date=transaction.transaction_date,
                    description=description,
                    reference_id=transaction.reference_id,
                    confidence=float(min(score, Decimal("0.99"))),
                    match_method=match_method,
                    evidence=evidence,
                )
            )
        candidates.sort(
            key=lambda candidate: (
                -candidate.confidence,
                candidate.transaction_date,
                candidate.transaction_id,
            )
        )
        return candidates[:10]

    async def review_statement_line(
        self,
        user_id: str,
        line_id: str,
        data: StatementLineReviewRequest,
    ) -> StatementLineReviewResponse:
        row = (
            await self.db.execute(
                select(StatementLine, CreditCardStatement, FinancialAccount)
                .join(
                    CreditCardStatement,
                    CreditCardStatement.id == StatementLine.credit_card_statement_id,
                )
                .join(
                    FinancialAccount,
                    FinancialAccount.id == CreditCardStatement.financial_account_id,
                )
                .where(
                    StatementLine.id == line_id,
                    StatementLine.user_id == user_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise LookupError("Statement line not found")
        line, statement, card_account = row
        previous_outcome = line.review_outcome
        matched_transaction_id: str | None = None
        paying_account_id: str | None = None

        if data.decision == "ignore":
            line.review_outcome = "ignored_by_rule"
        elif data.decision == "match":
            if data.matched_transaction_id is None:
                raise ValueError("Choose the existing ledger transaction to match")
            transaction = await self.db.scalar(
                select(Transaction).where(
                    Transaction.id == data.matched_transaction_id,
                    Transaction.user_id == user_id,
                    Transaction.financial_account_id == card_account.id,
                )
            )
            if transaction is None:
                raise LookupError("Matching card transaction not found")
            await self._record_statement_match(
                user_id,
                line,
                transaction.id,
                "user_confirmed",
                Decimal("1.000"),
            )
            line.review_outcome = "matched"
            matched_transaction_id = transaction.id
        elif data.decision == "import":
            if line.card_event not in {
                "purchase",
                "refund",
                "cashback",
                "fee",
                "tax",
                "interest",
                "reversal",
            }:
                raise ValueError("This statement event cannot be imported as standalone spending")
            if line.created_transaction_id is not None:
                transaction = await self.db.get(Transaction, line.created_transaction_id)
            else:
                merchant = await resolve_merchant(self.db, line.description, user_id=user_id)
                try:
                    transaction = await TransactionService(self.db).create_transaction(
                        user_id,
                        TransactionCreate(
                            amount=line.amount,
                            currency=card_account.currency,
                            transaction_type=TransactionTypeEnum(line.transaction_type),
                            payment_method=PaymentMethodEnum.CREDIT_CARD,
                            payment_rail=PaymentRailEnum.OTHER,
                            card_event=CardEventEnum(line.card_event),
                            transaction_date=line.transaction_date,
                            merchant_raw=line.description,
                            merchant_normalized=merchant.normalized_name,
                            category_id=merchant.category_id,
                            reference_id=line.reference_id,
                            account_last4=None,
                            confidence_score=1.0,
                            source_email_id=None,
                            financial_account_id=card_account.id,
                            source_kind="statement",
                            source_identifier=statement.statement_import_id,
                            merchant_resolution_source=merchant.source,
                            merchant_resolution_confidence=merchant.confidence,
                            merchant_rule_id=merchant.rule_id,
                            merchant_resolver_version=merchant.resolver_version,
                        ),
                        commit=False,
                    )
                except DuplicateTransactionError as exc:
                    raise ValueError(
                        "A ledger event already has the same deterministic identity"
                    ) from exc
                line.created_transaction_id = transaction.id
            line.review_outcome = "newly_imported"
            matched_transaction_id = transaction.id if transaction else None
        else:
            if line.card_event != "payment":
                raise ValueError("Only statement card-payment lines can create a paired transfer")
            if data.paying_account_id is None:
                raise ValueError("Choose the bank account used for this card payment")
            paying_account = await self._require_account(user_id, data.paying_account_id)
            if paying_account.account_type != "bank":
                raise ValueError("Card payments must originate from a bank account")
            transfer = await AccountService(self.db).create_transfer(
                user_id,
                TransferCreate(
                    from_account_id=paying_account.id,
                    to_account_id=card_account.id,
                    amount=line.amount,
                    currency=card_account.currency,
                    transaction_date=line.transaction_date,
                    description="Credit card payment",
                    payment_rail="transfer",
                ),
                commit=False,
            )
            card_transaction = await self.db.get(Transaction, transfer.credit_transaction_id)
            if card_transaction is None:
                raise RuntimeError("Card-payment transfer could not be created")
            card_transaction.card_event = CardEvent.PAYMENT
            await self.db.flush()
            await capture_transaction_snapshot(self.db, card_transaction)
            await self._record_statement_match(
                user_id,
                line,
                card_transaction.id,
                "user_confirmed_card_payment",
                Decimal("1.000"),
            )
            line.review_outcome = "matched"
            matched_transaction_id = card_transaction.id
            paying_account_id = paying_account.id

        decision = StatementLineReviewDecision(
            user_id=user_id,
            statement_line_id=line.id,
            decision=data.decision,
            previous_outcome=previous_outcome,
            new_outcome=cast(ReviewOutcome, line.review_outcome),
            matched_transaction_id=matched_transaction_id,
            paying_account_id=paying_account_id,
            note=data.note,
        )
        self.db.add(decision)
        if line.component_kind.startswith("emi_"):
            await self.db.flush()
            await self.repair_financial_intelligence(
                user_id,
                dry_run=False,
                commit=False,
            )
            matched_transaction_id = line.created_transaction_id or matched_transaction_id
            decision.matched_transaction_id = matched_transaction_id
        await capture_statement_line_snapshot(
            self.db,
            line,
            financial_account_id=card_account.id,
        )
        await self.db.commit()
        await self.db.refresh(line)
        await self.db.refresh(decision)
        return StatementLineReviewResponse(
            line=StatementLineResponse.model_validate(line, from_attributes=True),
            decision=decision.decision,
            previous_outcome=previous_outcome,
            new_outcome=cast(ReviewOutcome, line.review_outcome),
            matched_transaction_id=matched_transaction_id,
            paying_account_id=paying_account_id,
            decided_at=decision.created_at,
        )

    async def _record_statement_match(
        self,
        user_id: str,
        line: StatementLine,
        transaction_id: str,
        match_method: str,
        confidence: Decimal,
    ) -> None:
        existing = await self.db.scalar(
            select(StatementLineMatch).where(
                (StatementLineMatch.statement_line_id == line.id)
                | (StatementLineMatch.transaction_id == transaction_id)
            )
        )
        if existing is not None:
            if existing.statement_line_id == line.id and existing.transaction_id == transaction_id:
                return
            raise ValueError("That statement line or transaction is already matched elsewhere")
        self.db.add(
            StatementLineMatch(
                user_id=user_id,
                statement_line_id=line.id,
                transaction_id=transaction_id,
                match_method=match_method,
                confidence=confidence,
            )
        )
        await self.db.flush()

    async def _match_statement_line(
        self, user_id: str, account_id: str, line: StatementLine
    ) -> tuple[Transaction | None, bool, str | None]:
        query = (
            select(Transaction)
            .options(selectinload(Transaction.source_email))
            .where(
                Transaction.user_id == user_id,
                Transaction.financial_account_id == account_id,
                Transaction.transaction_type == TransactionType(line.transaction_type),
                Transaction.id.not_in(select(StatementLineMatch.transaction_id)),
            )
        )
        if line.reference_id:
            exact = await self.db.scalar(query.where(Transaction.reference_id == line.reference_id))
            if exact:
                return exact, False, "reference"
        amount_date_candidates = list(
            (
                await self.db.scalars(
                    query.where(
                        Transaction.transaction_date
                        >= date.fromordinal(line.transaction_date.toordinal() - 3),
                        Transaction.transaction_date
                        <= date.fromordinal(line.transaction_date.toordinal() + 3),
                    )
                )
            ).all()
        )
        candidates = [
            candidate
            for candidate in amount_date_candidates
            if candidate.amount == line.amount
            and merchant_evidence_matches(
                line.description, _transaction_merchant_evidence(candidate)
            )
        ]
        if len(candidates) == 1:
            return candidates[0], False, "exact_amount"

        fuel_candidates: list[Transaction] = []
        unsafe_fuel_evidence = False
        for candidate in amount_date_candidates:
            if candidate.source_email_id is None:
                continue
            evidence = _transaction_merchant_evidence(candidate)
            if not (
                is_fuel_surcharge_amount_match(line.amount, candidate.amount)
                and is_fuel_evidence(
                    line.description,
                    line.merchant_normalized,
                    *evidence,
                )
                and merchant_evidence_matches(line.description, evidence)
            ):
                continue
            has_splits = await self.db.scalar(
                select(func.count(TransactionSplit.id)).where(
                    TransactionSplit.transaction_id == candidate.id
                )
            )
            amount_correction = await self.db.scalar(
                select(UserCorrection.id).where(
                    UserCorrection.transaction_id == candidate.id,
                    UserCorrection.field_corrected == "amount",
                )
            )
            if candidate.is_transfer or has_splits or amount_correction:
                unsafe_fuel_evidence = True
                continue
            fuel_candidates.append(candidate)
        if len(fuel_candidates) == 1:
            return fuel_candidates[0], False, "fuel_surcharge"
        amount_conflicts = [
            candidate for candidate in amount_date_candidates if candidate.amount == line.amount
        ]
        return None, bool(amount_conflicts or fuel_candidates or unsafe_fuel_evidence), None

    async def _project_emi_ledger_events(
        self,
        user_id: str,
        lines: list[StatementLine],
        protected: dict[str, set[str]],
        stats: dict[str, int],
        *,
        dry_run: bool,
    ) -> None:
        """Project issuer EMI evidence onto ledger rows without changing raw evidence."""
        statement_ids = {line.credit_card_statement_id for line in lines}
        if not statement_ids:
            return
        statements = list(
            (
                await self.db.scalars(
                    select(CreditCardStatement).where(
                        CreditCardStatement.user_id == user_id,
                        CreditCardStatement.id.in_(statement_ids),
                    )
                )
            ).all()
        )
        plans = _build_card_emi_plans(statements, lines)
        plan_by_line_id = {
            component.statement_line_id: plan for plan in plans for component in plan.components
        }
        event_by_component = {
            "emi_conversion_purchase": CardEvent.NONE,
            "emi_conversion_credit": CardEvent.NONE,
            "emi_principal": CardEvent.PURCHASE,
            "emi_interest": CardEvent.INTEREST,
            "emi_tax": CardEvent.TAX,
            "emi_processing_fee": CardEvent.FEE,
            "emi_fee_reversal": CardEvent.REVERSAL,
            "emi_preclosure_principal": CardEvent.PURCHASE,
            "emi_preclosure_interest": CardEvent.INTEREST,
        }
        adjustment_kinds = {
            "emi_conversion_purchase",
            "emi_conversion_credit",
        }

        for line in lines:
            if line.created_transaction_id is None:
                continue
            transaction = await self.db.get(Transaction, line.created_transaction_id)
            if transaction is None:
                continue

            component_kind = line.component_kind if line.component_kind.startswith("emi_") else None
            target_adjustment = component_kind in adjustment_kinds
            corrected_fields = protected.get(transaction.id, set())
            target_event = (
                transaction.card_event
                if "card_event" in corrected_fields
                else event_by_component.get(
                    component_kind or "",
                    CardEvent(line.card_event),
                )
            )
            changed = (
                transaction.ledger_subtype != component_kind
                or transaction.is_accounting_adjustment != target_adjustment
                or transaction.card_event != target_event
            )
            if target_adjustment and not transaction.is_accounting_adjustment:
                stats["accounting_adjustments_marked"] += 1

            plan = plan_by_line_id.get(line.id)
            merchant_changed = False
            if (
                plan is not None
                and not plan.merchant.startswith("Card EMI")
                and not ({"merchant_normalized", "category_id"} & corrected_fields)
            ):
                resolution = await resolve_merchant(
                    self.db,
                    plan.merchant,
                    user_id=user_id,
                )
                merchant_changed = (
                    transaction.merchant_normalized != resolution.normalized_name
                    or line.merchant_normalized != resolution.normalized_name
                    or (
                        resolution.category_id is not None
                        and transaction.category_id != resolution.category_id
                    )
                )
                if not dry_run and merchant_changed:
                    transaction.merchant_normalized = resolution.normalized_name
                    line.merchant_normalized = resolution.normalized_name
                    line.merchant_confidence = resolution.confidence
                    if resolution.category_id is not None:
                        transaction.category_id = resolution.category_id
                    transaction.merchant_resolution_source = "emi_plan_evidence"
                    transaction.merchant_resolution_confidence = min(
                        max(resolution.confidence, 0.94),
                        1.0,
                    )
                    transaction.merchant_rule_id = resolution.rule_id
                    transaction.merchant_resolver_version = resolution.resolver_version

            if not changed and not merchant_changed:
                continue
            stats["emi_ledger_events_projected"] += 1
            if dry_run:
                continue
            transaction.ledger_subtype = component_kind
            transaction.is_accounting_adjustment = target_adjustment
            transaction.card_event = target_event
            await self._invalidate_monthly_summary(user_id, transaction.transaction_date)

    async def repair_financial_intelligence(
        self,
        user_id: str,
        *,
        dry_run: bool = True,
        commit: bool = True,
    ) -> FinancialIntelligenceRepairResponse:
        """Repair stale deterministic classifications without overwriting user choices."""
        stats = {
            "email_merchants_repaired": 0,
            "statement_merchants_repaired": 0,
            "source_provenance_repaired": 0,
            "transaction_semantics_repaired": 0,
            "emi_components_classified": 0,
            "emi_ledger_events_projected": 0,
            "accounting_adjustments_marked": 0,
            "non_spend_payments_classified": 0,
            "duplicates_merged": 0,
            "fuel_surcharge_duplicates_merged": 0,
            "amounts_reconciled_to_statement": 0,
            "liabilities_synced": 0,
            "false_positive_transactions_removed": 0,
            "conflicts_held_for_review": 0,
        }
        correction_rows = (
            await self.db.execute(
                select(UserCorrection.transaction_id, UserCorrection.field_corrected)
                .join(Transaction, Transaction.id == UserCorrection.transaction_id)
                .where(Transaction.user_id == user_id)
            )
        ).all()
        protected: dict[str, set[str]] = {}
        for transaction_id, field in correction_rows:
            protected.setdefault(transaction_id, set()).add(field)

        generic_merchants = {
            "",
            "UNKNOWN",
            "MORE DETAILS",
            "CARD PURCHASE",
            "UPI TRANSFER",
        }

        def has_explicit_merchant_identity(transaction: Transaction) -> bool:
            merchant = (transaction.merchant_normalized or "").strip().upper()
            if merchant in generic_merchants:
                return False
            return (
                transaction.source_kind == "manual"
                or transaction.merchant_resolution_source
                in {
                    "manual",
                    "user_rule",
                }
            )

        lines = list(
            (
                await self.db.scalars(
                    select(StatementLine)
                    .where(StatementLine.user_id == user_id)
                    .order_by(StatementLine.transaction_date, StatementLine.line_number)
                )
            ).all()
        )

        for line in lines:
            component = classify_emi_component(
                line.description, is_credit=line.transaction_type != "debit"
            )
            target_kind = str(component["component_kind"])
            target_reference = cast(str | None, component["issuer_plan_reference"])
            target_installment = cast(int | None, component["installment_number"])
            # Some issuer relationships are contextual rather than present on the
            # individual row. Tax and conversion relationships are resolved in
            # focused evidence passes below.
            defer_tax_classification = line.card_event == "tax" and target_kind == "ordinary"
            if (
                line.component_kind in {"emi_conversion_purchase", "emi_conversion_credit"}
                and target_kind == line.component_kind
                and target_reference is None
            ):
                target_reference = line.issuer_plan_reference
            if not defer_tax_classification and (
                line.component_kind != target_kind
                or line.issuer_plan_reference != target_reference
                or line.installment_number != target_installment
            ):
                stats["emi_components_classified"] += 1
                if not dry_run:
                    line.component_kind = target_kind
                    line.issuer_plan_reference = target_reference
                    line.installment_number = target_installment

            is_emi_evidence = line.component_kind.startswith("emi_") or target_kind.startswith(
                "emi_"
            )
            resolution = await resolve_merchant(self.db, line.description, user_id=user_id)
            if not is_emi_evidence and (
                line.merchant_normalized != resolution.normalized_name
                or line.merchant_confidence != resolution.confidence
            ):
                stats["statement_merchants_repaired"] += 1
                if not dry_run:
                    line.merchant_normalized = resolution.normalized_name
                    line.merchant_confidence = resolution.confidence
            if (
                not is_emi_evidence
                and line.created_transaction_id
                and not (
                    {"merchant_normalized", "category_id"}
                    & protected.get(line.created_transaction_id, set())
                )
            ):
                transaction = await self.db.get(Transaction, line.created_transaction_id)
                if (
                    transaction is not None
                    and not has_explicit_merchant_identity(transaction)
                    and (
                        transaction.merchant_normalized != resolution.normalized_name
                        or (
                            resolution.category_id is not None
                            and transaction.category_id != resolution.category_id
                        )
                    )
                ):
                    stats["statement_merchants_repaired"] += 1
                    if not dry_run:
                        transaction.merchant_normalized = resolution.normalized_name
                        if resolution.category_id is not None:
                            transaction.category_id = resolution.category_id
                        transaction.merchant_resolution_source = resolution.source
                        transaction.merchant_resolution_confidence = resolution.confidence
                        transaction.merchant_rule_id = resolution.rule_id
                        transaction.merchant_resolver_version = resolution.resolver_version

        # HDFC posts GST on EMI interest as a separate row in the next
        # statement, carrying the original interest posting Ref#. This is
        # stronger evidence than row adjacency and lets PFIS assign tax to the
        # correct loan even when several EMIs share a statement.
        posting_plan_references: dict[str, set[str]] = {}
        known_emi_references: set[str] = set()
        for line in lines:
            component = classify_emi_component(
                line.description,
                is_credit=line.transaction_type != "debit",
            )
            plan_reference = component["issuer_plan_reference"]
            if plan_reference:
                known_emi_references.add(str(plan_reference))
            if not line.reference_id:
                continue
            if component["component_kind"] not in {
                "emi_interest",
                "emi_preclosure_interest",
            }:
                continue
            if plan_reference:
                posting_plan_references.setdefault(line.reference_id, set()).add(
                    str(plan_reference)
                )
        for line in lines:
            if line.card_event != "tax":
                continue
            references = (
                posting_plan_references.get(line.reference_id, set())
                if line.reference_id
                else set()
            )
            if len(references) == 1:
                target_reference = next(iter(references))
                target_kind = "emi_tax"
            elif (
                line.component_kind == "emi_tax"
                and line.issuer_plan_reference
                and line.issuer_plan_reference not in known_emi_references
            ):
                target_reference = None
                target_kind = "ordinary"
            else:
                continue
            if line.component_kind != target_kind or line.issuer_plan_reference != target_reference:
                stats["emi_components_classified"] += 1
                if not dry_run:
                    line.component_kind = target_kind
                    line.issuer_plan_reference = target_reference

        previous_by_statement: dict[str, StatementLine] = {}
        for line in sorted(
            lines, key=lambda item: (item.credit_card_statement_id, item.line_number)
        ):
            previous = previous_by_statement.get(line.credit_card_statement_id)
            if (
                line.card_event == "tax"
                and previous is not None
                and previous.issuer_plan_reference
                and previous.component_kind
                in {
                    "emi_interest",
                    "emi_processing_fee",
                    "emi_preclosure_interest",
                }
                and (
                    line.component_kind != "emi_tax"
                    or line.issuer_plan_reference != previous.issuer_plan_reference
                )
            ):
                stats["emi_components_classified"] += 1
                if not dry_run:
                    line.component_kind = "emi_tax"
                    line.issuer_plan_reference = previous.issuer_plan_reference
            previous_by_statement[line.credit_card_statement_id] = line

        # Link a conversion debit/credit to the next explicit issuer loan key.
        used_fee_ids: set[str] = set()
        conversion_purchases = [
            line for line in lines if line.component_kind == "emi_conversion_purchase"
        ]
        conversion_credits = [
            line for line in lines if line.component_kind == "emi_conversion_credit"
        ]
        processing_fees = [
            line
            for line in lines
            if line.component_kind == "emi_processing_fee" and line.issuer_plan_reference
        ]
        for purchase in conversion_purchases:
            credits = [
                line
                for line in conversion_credits
                if line.amount == purchase.amount
                and 0 <= (line.transaction_date - purchase.transaction_date).days <= 7
            ]
            if len(credits) != 1:
                continue
            credit = credits[0]
            fees = [
                line
                for line in processing_fees
                if line.id not in used_fee_ids
                and 0 <= (line.transaction_date - credit.transaction_date).days <= 4
            ]
            if len(fees) != 1:
                continue
            fee = fees[0]
            used_fee_ids.add(fee.id)
            for linked_line in (purchase, credit):
                if linked_line.issuer_plan_reference != fee.issuer_plan_reference:
                    stats["emi_components_classified"] += 1
                    if not dry_run:
                        linked_line.issuer_plan_reference = fee.issuer_plan_reference

        email_transactions = list(
            (
                await self.db.scalars(
                    select(Transaction)
                    .options(selectinload(Transaction.source_email))
                    .where(
                        Transaction.user_id == user_id,
                        Transaction.source_email_id.is_not(None),
                    )
                )
            ).all()
        )
        email_account_ids = {
            item.financial_account_id
            for item in email_transactions
            if item.financial_account_id is not None
        }
        email_accounts = (
            {}
            if not email_account_ids
            else {
                account.id: account
                for account in (
                    await self.db.scalars(
                        select(FinancialAccount).where(
                            FinancialAccount.id.in_(email_account_ids),
                            FinancialAccount.user_id == user_id,
                        )
                    )
                ).all()
            }
        )
        registry = get_parser_registry()
        for transaction in email_transactions:
            if transaction.review_outcome == "ignored_by_rule":
                continue
            email = transaction.source_email
            if email is not None:
                classification = classify_source_record(
                    email.sender or "", email.subject or "", email.body or ""
                )
                generic_identity = (
                    transaction.merchant_normalized or ""
                ).strip().upper() in generic_merchants
                strong_newsletter_evidence = (
                    classification.classification == ClassificationType.IGNORE
                    and classification.reason == "newsletter sender or content signal"
                )
                strong_non_transaction_evidence = (
                    classification.classification == ClassificationType.IGNORE
                    and classification.reason == "strong non-transaction document/service signal"
                )
                removable_non_transaction = (
                    strong_newsletter_evidence
                    or strong_non_transaction_evidence
                    or (
                        classification.classification
                        in {ClassificationType.IGNORE, ClassificationType.PROMOTION}
                        and generic_identity
                        and not transaction.reviewed_flag
                    )
                )
                if (
                    removable_non_transaction
                    and not transaction.is_transfer
                    and not protected.get(transaction.id)
                ):
                    has_splits = await self.db.scalar(
                        select(func.count(TransactionSplit.id)).where(
                            TransactionSplit.transaction_id == transaction.id
                        )
                    )
                    has_statement_match = await self.db.scalar(
                        select(StatementLineMatch.id).where(
                            StatementLineMatch.transaction_id == transaction.id
                        )
                    )
                    if not has_splits and not has_statement_match:
                        stats["false_positive_transactions_removed"] += 1
                        if not dry_run:
                            await self._invalidate_monthly_summary(
                                user_id, transaction.transaction_date
                            )
                            previous_outcome = transaction.review_outcome
                            transaction.review_outcome = "ignored_by_rule"
                            transaction.reviewed_flag = True
                            self.db.add(
                                UserCorrection(
                                    transaction_id=transaction.id,
                                    field_corrected="review_outcome",
                                    old_value=previous_outcome,
                                    new_value="ignored_by_rule",
                                )
                            )
                        continue
            if transaction.source_kind != "email":
                stats["source_provenance_repaired"] += 1
                if not dry_run:
                    transaction.source_kind = "email"
                    if transaction.source_email is not None:
                        transaction.source_identifier = transaction.source_email.gmail_message_id
            if email is None:
                continue
            parsed = registry.parse_email(email.sender or "", email.subject or "", email.body or "")
            protected_fields = protected.get(transaction.id, set())
            rail_is_explicit = (
                parsed.payment_rail == "atm"
                or (parsed.payment_rail == "upi" and parsed.payment_method == "upi")
                or (parsed.payment_rail == "debit_card" and parsed.payment_method == "debit_card")
                or (parsed.payment_rail == "transfer" and parsed.payment_method == "bank_transfer")
                or (parsed.payment_rail == "wallet" and parsed.payment_method == "wallet")
            )
            target_rail = (
                PaymentRail(parsed.payment_rail)
                if rail_is_explicit and "payment_rail" not in protected_fields
                else transaction.payment_rail
            )
            target_event = transaction.card_event
            parsed_event = CardEvent(parsed.card_event)
            linked_account = (
                email_accounts.get(transaction.financial_account_id)
                if transaction.financial_account_id
                else None
            )
            if "card_event" not in protected_fields:
                if parsed.payment_rail == "atm":
                    target_event = CardEvent.NONE
                elif (
                    transaction.transaction_type == TransactionType.REFUND
                    and parsed_event
                    in {
                        CardEvent.REFUND,
                        CardEvent.CASHBACK,
                        CardEvent.REVERSAL,
                    }
                ) or (
                    not transaction.is_accounting_adjustment
                    and linked_account is not None
                    and linked_account.account_type == "credit_card"
                    and parsed.payment_method == "credit_card"
                ):
                    target_event = parsed_event
            target_status = (
                parsed.transaction_status
                if parsed.transaction_status != "completed"
                and "transaction_status" not in protected_fields
                else transaction.transaction_status
            )
            is_unlinked_atm = parsed.payment_rail == "atm" and not transaction.is_transfer
            semantics_changed = (
                transaction.payment_rail != target_rail
                or transaction.card_event != target_event
                or transaction.transaction_status != target_status
                or (
                    is_unlinked_atm
                    and (
                        not transaction.is_accounting_adjustment
                        or transaction.ledger_subtype != "unlinked_atm_withdrawal"
                        or transaction.review_outcome != "needs_review"
                        or transaction.reviewed_flag
                    )
                )
            )
            if semantics_changed:
                stats["transaction_semantics_repaired"] += 1
                if not dry_run:
                    transaction.payment_rail = target_rail
                    transaction.card_event = target_event
                    transaction.transaction_status = target_status
                    if is_unlinked_atm:
                        transaction.is_accounting_adjustment = True
                        transaction.ledger_subtype = "unlinked_atm_withdrawal"
                        transaction.review_outcome = "needs_review"
                        transaction.reviewed_flag = False
                    await self._invalidate_monthly_summary(user_id, transaction.transaction_date)
            if {"merchant_normalized", "category_id"} & protected_fields:
                continue
            if has_explicit_merchant_identity(transaction):
                continue
            if not parsed.merchant_raw:
                continue
            resolution_input = parsed.merchant_raw
            if not is_plausible_merchant_descriptor(resolution_input):
                inferred_merchant, _ = await infer_merchant_from_text(
                    self.db,
                    f"{email.subject or ''} {email.body or ''}",
                )
                if inferred_merchant:
                    resolution_input = inferred_merchant
            resolution = await resolve_merchant(
                self.db,
                resolution_input,
                user_id=user_id,
            )
            current_is_weak = (
                transaction.merchant_normalized or ""
            ).strip().upper() in generic_merchants or (
                transaction.merchant_resolution_confidence or 0
            ) < resolution.confidence
            if not current_is_weak:
                continue
            if (
                transaction.merchant_raw != parsed.merchant_raw
                or transaction.merchant_normalized != resolution.normalized_name
                or (
                    resolution.category_id is not None
                    and transaction.category_id != resolution.category_id
                )
            ):
                stats["email_merchants_repaired"] += 1
                if not dry_run:
                    transaction.merchant_raw = parsed.merchant_raw
                    transaction.merchant_normalized = resolution.normalized_name
                    if resolution.category_id is not None:
                        transaction.category_id = resolution.category_id
                    transaction.merchant_resolution_source = resolution.source
                    transaction.merchant_resolution_confidence = resolution.confidence
                    transaction.merchant_rule_id = resolution.rule_id
                    transaction.merchant_resolver_version = resolution.resolver_version

        ledger_transactions = list(
            (
                await self.db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == user_id,
                        Transaction.review_outcome != "ignored_by_rule",
                    )
                )
            ).all()
        )
        for transaction in ledger_transactions:
            if (
                transaction.is_transfer
                or transaction.transaction_type != TransactionType.DEBIT
                or transaction.card_event == CardEvent.PAYMENT
                or "card_event" in protected.get(transaction.id, set())
                or not _is_non_spend_payment_evidence(
                    transaction.merchant_raw,
                    transaction.merchant_normalized,
                )
            ):
                continue
            stats["non_spend_payments_classified"] += 1
            if dry_run:
                continue
            transaction.card_event = CardEvent.PAYMENT
            if (
                transaction.payment_rail == PaymentRail.OTHER
                and "payment_rail" not in protected.get(transaction.id, set())
            ):
                transaction.payment_rail = PaymentRail.TRANSFER
            await self._invalidate_monthly_summary(user_id, transaction.transaction_date)

        # Reconcile only unique email/statement pairs. Repeated same-merchant spend is
        # intentionally never merged without cross-source evidence.
        for line in lines:
            if line.created_transaction_id is None:
                continue
            statement_transaction = await self.db.get(Transaction, line.created_transaction_id)
            if (
                statement_transaction is None
                or statement_transaction.source_kind != "statement"
                or statement_transaction.is_transfer
                or protected.get(statement_transaction.id)
            ):
                continue
            candidate_query = (
                select(Transaction)
                .options(selectinload(Transaction.source_email))
                .where(
                    Transaction.user_id == user_id,
                    Transaction.id != statement_transaction.id,
                    Transaction.source_email_id.is_not(None),
                    Transaction.financial_account_id == statement_transaction.financial_account_id,
                    Transaction.transaction_type == statement_transaction.transaction_type,
                    Transaction.transaction_date
                    >= date.fromordinal(line.transaction_date.toordinal() - 3),
                    Transaction.transaction_date
                    <= date.fromordinal(line.transaction_date.toordinal() + 3),
                )
            )
            potential_candidates = list((await self.db.scalars(candidate_query)).all())
            match_kinds: dict[str, str] = {}
            for candidate in potential_candidates:
                evidence = _transaction_merchant_evidence(candidate)
                if not merchant_evidence_matches(line.description, evidence):
                    continue
                if candidate.amount == statement_transaction.amount:
                    match_kinds[candidate.id] = "exact_amount"
                elif is_fuel_surcharge_amount_match(
                    statement_transaction.amount, candidate.amount
                ) and is_fuel_evidence(
                    line.description,
                    line.merchant_normalized,
                    *evidence,
                ):
                    match_kinds[candidate.id] = "fuel_surcharge"
            candidates = [
                candidate for candidate in potential_candidates if candidate.id in match_kinds
            ]
            if len(candidates) != 1:
                if candidates:
                    stats["conflicts_held_for_review"] += 1
                    if not dry_run:
                        line.review_outcome = "needs_review"
                continue
            candidate = candidates[0]
            match_kind = match_kinds[candidate.id]
            statement_has_splits = await self.db.scalar(
                select(func.count(TransactionSplit.id)).where(
                    TransactionSplit.transaction_id == statement_transaction.id
                )
            )
            candidate_has_splits = await self.db.scalar(
                select(func.count(TransactionSplit.id)).where(
                    TransactionSplit.transaction_id == candidate.id
                )
            )
            existing_match = await self.db.scalar(
                select(StatementLineMatch.id).where(
                    (StatementLineMatch.statement_line_id == line.id)
                    | (StatementLineMatch.transaction_id == candidate.id)
                )
            )
            amount_is_protected = "amount" in protected.get(candidate.id, set())
            if (
                statement_has_splits
                or candidate_has_splits
                or existing_match
                or candidate.is_transfer
                or (match_kind == "fuel_surcharge" and amount_is_protected)
            ):
                stats["conflicts_held_for_review"] += 1
                if not dry_run:
                    line.review_outcome = "needs_review"
                continue
            stats["duplicates_merged"] += 1
            if match_kind == "fuel_surcharge":
                stats["fuel_surcharge_duplicates_merged"] += 1
                stats["amounts_reconciled_to_statement"] += 1
            if dry_run:
                continue
            old_id = statement_transaction.id
            alert_amount = candidate.amount
            line.created_transaction_id = candidate.id
            line.review_outcome = "matched"
            candidate.review_outcome = "matched"
            candidate.source_kind = "email"
            candidate.card_event = CardEvent(line.card_event)
            self.db.add(
                StatementLineMatch(
                    user_id=user_id,
                    statement_line_id=line.id,
                    transaction_id=candidate.id,
                    match_method=(
                        "historical_fuel_surcharge"
                        if match_kind == "fuel_surcharge"
                        else "historical_cross_source_repair"
                    ),
                    confidence=(
                        Decimal("0.940") if match_kind == "fuel_surcharge" else Decimal("0.900")
                    ),
                )
            )
            self.db.add(
                StatementLineReviewDecision(
                    user_id=user_id,
                    statement_line_id=line.id,
                    decision=(
                        "automatic_fuel_surcharge_merge"
                        if match_kind == "fuel_surcharge"
                        else "automatic_duplicate_merge"
                    ),
                    previous_outcome="newly_imported",
                    new_outcome="matched",
                    matched_transaction_id=candidate.id,
                    note=(
                        (
                            "Unique fuel evidence reconciled alert amount "
                            f"{alert_amount} to official statement amount "
                            f"{statement_transaction.amount}; removed duplicate "
                            f"statement ledger event {old_id}."
                        )
                        if match_kind == "fuel_surcharge"
                        else (
                            "Unique statement/email evidence merged; removed duplicate "
                            f"statement ledger event {old_id}."
                        )
                    ),
                )
            )
            await self._invalidate_monthly_summary(user_id, statement_transaction.transaction_date)
            await self._invalidate_monthly_summary(user_id, candidate.transaction_date)
            await self.db.flush()
            await capture_transaction_snapshot(self.db, statement_transaction, deleted=True)
            await self.db.execute(delete(Transaction).where(Transaction.id == old_id))
            if match_kind == "fuel_surcharge":
                candidate.amount = line.amount

        await self._project_emi_ledger_events(
            user_id,
            lines,
            protected,
            stats,
            dry_run=dry_run,
        )
        if not dry_run:
            account_ids = {
                statement.id: statement.financial_account_id
                for statement in (
                    await self.db.scalars(
                        select(CreditCardStatement).where(
                            CreditCardStatement.id.in_(
                                {line.credit_card_statement_id for line in lines}
                            )
                        )
                    )
                ).all()
            }
            for line in lines:
                await capture_statement_line_snapshot(
                    self.db,
                    line,
                    financial_account_id=account_ids.get(line.credit_card_statement_id),
                )
            await self._snapshot_transaction_mutations(user_id)
        stats["liabilities_synced"] = await self._sync_card_emi_liabilities(
            user_id,
            persist=not dry_run,
        )
        if not dry_run and commit:
            await self.db.commit()
        return FinancialIntelligenceRepairResponse(dry_run=dry_run, **stats)

    async def _owned_account(self, user_id: str, account_id: str) -> FinancialAccount | None:
        return await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id, FinancialAccount.user_id == user_id
            )
        )

    async def _require_account(self, user_id: str, account_id: str) -> FinancialAccount:
        account = await self._owned_account(user_id, account_id)
        if account is None:
            raise LookupError("Financial account not found")
        return account

    async def _require_card_account(self, user_id: str, account_id: str) -> FinancialAccount:
        account = await self._require_account(user_id, account_id)
        if account.account_type != "credit_card":
            raise ValueError("This action requires a credit-card account")
        return account

    async def _validate_optional_account(self, user_id: str, account_id: str | None) -> None:
        if account_id:
            await self._require_account(user_id, account_id)


def _transaction_merchant_evidence(transaction: Transaction) -> list[str]:
    """Return controlled merchant evidence without replacing a user's display label."""
    values = [
        transaction.merchant_normalized or "",
        transaction.merchant_raw or "",
    ]
    email = transaction.source_email
    if email is not None:
        parsed = get_parser_registry().parse_email(
            email.sender or "", email.subject or "", email.body or ""
        )
        if parsed.merchant_raw:
            values.append(parsed.merchant_raw)
    return [value for value in dict.fromkeys(values) if value]


def _is_non_spend_payment_evidence(*values: str | None) -> bool:
    """Identify explicit debt/card repayments without inferring the paying account."""
    text = " ".join(value or "" for value in values).upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return any(
        token in text
        for token in (
            "CC BILLPAY",
            "CC BILL PAY",
            "CREDIT CARD BILL PAYMENT",
            "CHEQ DIGITAL",
            "LAZYPAY REPAYMENT",
            "PAYLATER REPAYMENT",
        )
    )


def _build_card_emi_plans(
    statements: list[CreditCardStatement],
    lines: list[StatementLine],
) -> list[CardEmiPlanResponse]:
    """Build an evidence-only EMI read model from issuer-labelled components."""
    statement_dates = {item.id: item.statement_date for item in statements}
    effective_refs = {
        line.id: line.issuer_plan_reference for line in lines if line.issuer_plan_reference
    }

    purchases = [line for line in lines if line.component_kind == "emi_conversion_purchase"]
    credits = [line for line in lines if line.component_kind == "emi_conversion_credit"]
    fees = [
        line
        for line in lines
        if line.component_kind == "emi_processing_fee" and line.issuer_plan_reference
    ]
    used_fees: set[str] = set()
    for purchase in sorted(purchases, key=lambda item: item.transaction_date):
        matching_credits = [
            line
            for line in credits
            if line.amount == purchase.amount
            and 0 <= (line.transaction_date - purchase.transaction_date).days <= 7
        ]
        if len(matching_credits) != 1:
            continue
        credit = matching_credits[0]
        matching_fees = [
            line
            for line in fees
            if line.id not in used_fees
            and 0 <= (line.transaction_date - credit.transaction_date).days <= 4
        ]
        if len(matching_fees) != 1:
            continue
        fee = matching_fees[0]
        used_fees.add(fee.id)
        fee_reference = fee.issuer_plan_reference
        if not fee_reference:
            continue
        effective_refs[purchase.id] = fee_reference
        effective_refs[credit.id] = fee_reference

    groups: dict[str, list[StatementLine]] = {}
    for line in lines:
        if not line.component_kind.startswith("emi_"):
            continue
        reference = effective_refs.get(line.id)
        if not reference:
            if line.component_kind != "emi_conversion_purchase":
                continue
            reference = f"unlinked-{line.id[:8]}"
        groups.setdefault(reference, []).append(line)

    result: list[CardEmiPlanResponse] = []
    for reference, components in groups.items():
        ordered = sorted(components, key=lambda item: (item.transaction_date, item.line_number))
        conversion = next(
            (item for item in ordered if item.component_kind == "emi_conversion_purchase"),
            None,
        )
        conversion_identity = (
            extract_descriptor_identity(conversion.description) if conversion is not None else None
        )
        merchant = (
            conversion_identity.candidate.title()
            if conversion_identity is not None and conversion_identity.candidate != "Unknown"
            else f"Card EMI · {reference.replace('unlinked-', 'unlinked ')}"
        )
        kinds = {item.component_kind for item in ordered}
        installment_numbers = [
            item.installment_number for item in ordered if item.installment_number is not None
        ]
        status: Literal["observed", "active", "preclosed"] = (
            "preclosed"
            if {"emi_preclosure_principal", "emi_preclosure_interest"} & kinds
            else "active" if installment_numbers else "observed"
        )
        latest_statement_id = max(
            {item.credit_card_statement_id for item in ordered},
            key=lambda statement_id: statement_dates[statement_id],
        )
        latest_statement_components = [
            item for item in ordered if item.credit_card_statement_id == latest_statement_id
        ]

        def latest_total(
            component_kinds: tuple[str, ...],
            statement_components: list[StatementLine] = latest_statement_components,
        ) -> Decimal:
            return sum(
                (
                    item.amount
                    for item in statement_components
                    if item.component_kind in component_kinds
                ),
                Decimal(),
            )

        latest_principal = latest_total(("emi_principal", "emi_preclosure_principal"))
        latest_interest = latest_total(("emi_interest", "emi_preclosure_interest"))
        latest_tax = latest_total(("emi_tax",))
        latest_fees = latest_total(("emi_processing_fee",)) - latest_total(("emi_fee_reversal",))
        latest_installment_amount = latest_principal + latest_interest + latest_tax
        latest_statement = next(item for item in statements if item.id == latest_statement_id)
        result.append(
            CardEmiPlanResponse(
                issuer_plan_reference=reference,
                merchant=merchant,
                original_amount=float(conversion.amount) if conversion else None,
                conversion_date=conversion.transaction_date if conversion else None,
                latest_installment_number=(
                    max(installment_numbers) if installment_numbers else None
                ),
                latest_statement_date=latest_statement.statement_date,
                latest_due_date=latest_statement.due_date,
                latest_principal=float(latest_principal),
                latest_interest=float(latest_interest),
                latest_tax=float(latest_tax),
                latest_fees=float(latest_fees),
                latest_installment_amount=float(latest_installment_amount),
                evidence_line_count=len(ordered),
                observed_principal=float(
                    sum(
                        (
                            item.amount
                            for item in ordered
                            if item.component_kind in {"emi_principal", "emi_preclosure_principal"}
                        ),
                        Decimal(),
                    )
                ),
                observed_interest=float(
                    sum(
                        (
                            item.amount
                            for item in ordered
                            if item.component_kind in {"emi_interest", "emi_preclosure_interest"}
                        ),
                        Decimal(),
                    )
                ),
                observed_tax=float(
                    sum(
                        (item.amount for item in ordered if item.component_kind == "emi_tax"),
                        Decimal(),
                    )
                ),
                observed_fees=float(
                    sum(
                        (
                            item.amount
                            for item in ordered
                            if item.component_kind == "emi_processing_fee"
                        ),
                        Decimal(),
                    )
                    - sum(
                        (
                            item.amount
                            for item in ordered
                            if item.component_kind == "emi_fee_reversal"
                        ),
                        Decimal(),
                    )
                ),
                status=status,
                schedule_completeness="partial",
                limitation=(
                    "Issuer evidence separates observed principal, interest, tax, and "
                    "fees. Tenure, annual rate, and remaining instalments are not "
                    "shown unless supplied by a complete schedule."
                ),
                missing_fields=[
                    "annual_rate",
                    "tenure",
                    "remaining_installments",
                    "outstanding_balance",
                ],
                components=[
                    CardEmiComponentResponse(
                        statement_line_id=item.id,
                        statement_date=statement_dates[item.credit_card_statement_id],
                        transaction_date=item.transaction_date,
                        component_kind=item.component_kind,
                        amount=float(item.amount),
                        installment_number=item.installment_number,
                        description=item.description,
                    )
                    for item in ordered
                ],
            )
        )
    return sorted(
        result,
        key=lambda item: (item.conversion_date or date.min, item.issuer_plan_reference),
        reverse=True,
    )


def _card_activity_signals(
    lines: list[StatementLine],
    credit_limit: Decimal | None,
    pending_reversals: list[Transaction],
) -> list[CardActivitySignal]:
    signals: list[CardActivitySignal] = []
    duplicate_groups: dict[tuple[date, str, Decimal, str], list[StatementLine]] = {}
    for line in lines:
        key = (
            line.transaction_date,
            merchant_key(line.description),
            line.amount,
            line.transaction_type,
        )
        duplicate_groups.setdefault(key, []).append(line)
    for group in duplicate_groups.values():
        if len(group) < 2:
            continue
        first = group[0]
        signals.append(
            CardActivitySignal(
                id=f"duplicate:{first.id}",
                signal_type="duplicate_candidate",
                title="Possible duplicate statement lines",
                description=(
                    f"{len(group)} lines share the same date, normalized description, "
                    "amount, and direction. Review before treating either as a duplicate."
                ),
                amount=float(first.amount),
                activity_date=first.transaction_date,
                basis="Exact statement date, amount, normalized description, and direction.",
            )
        )
    if credit_limit and credit_limit > 0:
        threshold = credit_limit * Decimal("0.10")
        for line in lines:
            if line.transaction_type != "debit" or line.amount < threshold:
                continue
            signals.append(
                CardActivitySignal(
                    id=f"high-value:{line.id}",
                    signal_type="high_value",
                    title="High-value statement activity",
                    description="This line is at least 10% of the statement credit limit.",
                    amount=float(line.amount),
                    activity_date=line.transaction_date,
                    basis="Compared with the credit limit printed on this statement.",
                )
            )
    for transaction in pending_reversals:
        signals.append(
            CardActivitySignal(
                id=f"pending-reversal:{transaction.id}",
                signal_type="pending_reversal",
                title="Pending reversal needs follow-up",
                description=(
                    "PFIS has reversal evidence that is not completed. Check the issuer "
                    "before relying on the credit."
                ),
                amount=float(transaction.amount),
                activity_date=transaction.transaction_date,
                basis="Explicit reversal classification with a non-completed status.",
            )
        )
    return sorted(signals, key=lambda signal: (signal.activity_date, signal.id), reverse=True)
