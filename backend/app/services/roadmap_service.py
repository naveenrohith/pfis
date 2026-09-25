"""Business rules for bills, disputes, household privacy, and payoff options."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import FinancialAccount
from app.models.financial_position import (
    CardCalendarEvent,
    CreditCardStatement,
    Liability,
    StatementLine,
)
from app.models.roadmap import (
    CardDispute,
    HealthChecklistItem,
    Household,
    HouseholdExpense,
    HouseholdMember,
    HouseholdSettlement,
    RoadmapBill,
)
from app.models.transaction import CardEvent, Transaction, TransactionType
from app.models.user import User
from app.schemas.roadmap import (
    BillCreate,
    BillResponse,
    BillUpdate,
    CardCalendarItemCreate,
    CardCalendarItemResponse,
    CardCalendarItemUpdate,
    CardCalendarMilestoneProgress,
    CardCalendarTransactionEvidence,
    CardDisputeCreate,
    CardDisputeResponse,
    CardDisputeUpdate,
    HealthChecklistResponse,
    HealthChecklistUpsert,
    HouseholdCreate,
    HouseholdExpenseCreate,
    HouseholdExpenseResponse,
    HouseholdMemberCreate,
    HouseholdMemberResponse,
    HouseholdMemberUpdate,
    HouseholdSettlementCreate,
    HouseholdSettlementResponse,
    HouseholdSettlementUpdate,
    HouseholdSummary,
    PayoffComparisonResponse,
    PayoffDebt,
    PayoffScenario,
)
from app.services.ledger_currency import (
    require_ledger_currency,
    require_shared_ledger_currency,
)
from app.services.temporal_source_history import (
    capture_card_dispute_snapshot,
    capture_temporal_source_snapshot,
)


class RoadmapService:
    def __init__(self, db: AsyncSession):
        self.db = db

    _SETTLED_TRANSACTION_STATUSES = {"completed", "posted", "settled", "captured"}

    async def list_bills(self, user_id: str) -> list[BillResponse]:
        rows = await self.db.scalars(
            select(RoadmapBill)
            .where(RoadmapBill.user_id == user_id)
            .order_by(RoadmapBill.due_date, RoadmapBill.created_at)
        )
        return [BillResponse.model_validate(row) for row in rows]

    async def create_bill(self, user_id: str, data: BillCreate) -> BillResponse:
        if data.financial_account_id:
            await self._require_account(user_id, data.financial_account_id)
        bill = RoadmapBill(user_id=user_id, **data.model_dump())
        self.db.add(bill)
        await self.db.flush()
        await self._snapshot_bill(bill)
        await self.db.commit()
        await self.db.refresh(bill)
        return BillResponse.model_validate(bill)

    async def update_bill(
        self, user_id: str, bill_id: str, data: BillUpdate
    ) -> BillResponse | None:
        bill = await self.db.scalar(
            select(RoadmapBill).where(RoadmapBill.id == bill_id, RoadmapBill.user_id == user_id)
        )
        if bill is None:
            return None
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(bill, field, value)
        if updates.get("status") == "paid":
            bill.paid_at = datetime.now(UTC)
        elif "status" in updates:
            bill.paid_at = None
        await self.db.flush()
        await self._snapshot_bill(bill)
        await self.db.commit()
        await self.db.refresh(bill)
        return BillResponse.model_validate(bill)

    async def _snapshot_bill(self, bill: RoadmapBill) -> None:
        await capture_temporal_source_snapshot(
            self.db,
            user_id=bill.user_id,
            source_type="bill",
            source_id=bill.id,
            payload={
                "financial_account_id": bill.financial_account_id,
                "label": bill.label,
                "bill_type": bill.bill_type,
                "amount": bill.amount,
                "due_date": bill.due_date,
                "cadence": bill.cadence,
                "status": bill.status,
                "source_kind": bill.source_kind,
                "source_identifier": bill.source_identifier,
                "confirmed": bill.confirmed,
                "paid_at": bill.paid_at,
            },
        )

    async def list_health(self, user_id: str) -> list[HealthChecklistResponse]:
        rows = await self.db.scalars(
            select(HealthChecklistItem)
            .where(HealthChecklistItem.user_id == user_id)
            .order_by(HealthChecklistItem.item_type)
        )
        return [HealthChecklistResponse.model_validate(row) for row in rows]

    async def upsert_health(
        self, user_id: str, data: HealthChecklistUpsert
    ) -> HealthChecklistResponse:
        item = await self.db.scalar(
            select(HealthChecklistItem).where(
                HealthChecklistItem.user_id == user_id,
                HealthChecklistItem.item_type == data.item_type,
            )
        )
        if item is None:
            item = HealthChecklistItem(user_id=user_id, **data.model_dump())
            self.db.add(item)
        else:
            for field, value in data.model_dump().items():
                setattr(item, field, value)
            item.reviewed_at = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(item)
        return HealthChecklistResponse.model_validate(item)

    async def list_disputes(self, user_id: str, account_id: str) -> list[CardDisputeResponse]:
        await self._require_card(user_id, account_id)
        rows = await self.db.scalars(
            select(CardDispute)
            .where(
                CardDispute.user_id == user_id,
                CardDispute.financial_account_id == account_id,
            )
            .order_by(CardDispute.complaint_date.desc())
        )
        return [CardDisputeResponse.model_validate(row) for row in rows]

    async def create_dispute(
        self, user_id: str, account_id: str, data: CardDisputeCreate
    ) -> CardDisputeResponse:
        await self._require_card(user_id, account_id)
        if data.statement_line_id:
            line = await self.db.scalar(
                select(StatementLine)
                .join(
                    CreditCardStatement,
                    CreditCardStatement.id == StatementLine.credit_card_statement_id,
                )
                .where(
                    StatementLine.id == data.statement_line_id,
                    StatementLine.user_id == user_id,
                    CreditCardStatement.financial_account_id == account_id,
                )
            )
            if line is None:
                raise LookupError("Statement line not found")
        dispute = CardDispute(user_id=user_id, financial_account_id=account_id, **data.model_dump())
        self.db.add(dispute)
        await self.db.flush()
        await capture_card_dispute_snapshot(self.db, dispute)
        await self.db.commit()
        await self.db.refresh(dispute)
        return CardDisputeResponse.model_validate(dispute)

    async def update_dispute(
        self, user_id: str, dispute_id: str, data: CardDisputeUpdate
    ) -> CardDisputeResponse | None:
        dispute = await self.db.scalar(
            select(CardDispute).where(CardDispute.id == dispute_id, CardDispute.user_id == user_id)
        )
        if dispute is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(dispute, field, value)
        await self.db.flush()
        await capture_card_dispute_snapshot(self.db, dispute)
        await self.db.commit()
        await self.db.refresh(dispute)
        return CardDisputeResponse.model_validate(dispute)

    async def list_card_calendar(
        self, user_id: str, account_id: str
    ) -> list[CardCalendarItemResponse]:
        await self._require_card(user_id, account_id)
        rows = await self.db.scalars(
            select(CardCalendarEvent)
            .where(
                CardCalendarEvent.user_id == user_id,
                CardCalendarEvent.financial_account_id == account_id,
            )
            .order_by(CardCalendarEvent.event_date, CardCalendarEvent.created_at)
        )
        return [await self._card_calendar_response(row) for row in rows]

    async def create_card_calendar(
        self, user_id: str, account_id: str, data: CardCalendarItemCreate
    ) -> CardCalendarItemResponse:
        await self._require_card(user_id, account_id)
        event = CardCalendarEvent(
            user_id=user_id,
            financial_account_id=account_id,
            **data.model_dump(),
        )
        self.db.add(event)
        await self.db.flush()
        await self._snapshot_card_calendar(event)
        await self.db.commit()
        await self.db.refresh(event)
        return await self._card_calendar_response(event)

    async def update_card_calendar(
        self,
        user_id: str,
        account_id: str,
        event_id: str,
        data: CardCalendarItemUpdate,
    ) -> CardCalendarItemResponse | None:
        await self._require_card(user_id, account_id)
        event = await self.db.scalar(
            select(CardCalendarEvent).where(
                CardCalendarEvent.id == event_id,
                CardCalendarEvent.user_id == user_id,
                CardCalendarEvent.financial_account_id == account_id,
            )
        )
        if event is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(event, field, value)
        self._validate_card_calendar_event(event)
        await self.db.flush()
        await self._snapshot_card_calendar(event)
        await self.db.commit()
        await self.db.refresh(event)
        return await self._card_calendar_response(event)

    async def delete_card_calendar(self, user_id: str, account_id: str, event_id: str) -> bool:
        await self._require_card(user_id, account_id)
        event = await self.db.scalar(
            select(CardCalendarEvent).where(
                CardCalendarEvent.id == event_id,
                CardCalendarEvent.user_id == user_id,
                CardCalendarEvent.financial_account_id == account_id,
            )
        )
        if event is None:
            return False
        await self._snapshot_card_calendar(event, deleted=True)
        await self.db.delete(event)
        await self.db.commit()
        return True

    def _validate_card_calendar_event(self, event: CardCalendarEvent) -> None:
        CardCalendarItemCreate.model_validate(
            {
                "event_type": event.event_type,
                "label": event.label,
                "event_date": event.event_date,
                "source_kind": event.source_kind,
                "source_label": event.source_label,
                "source_identifier": event.source_identifier,
                "annual_fee_amount": event.annual_fee_amount,
                "fee_reversal_condition": event.fee_reversal_condition,
                "fee_reversal_status": event.fee_reversal_status,
                "milestone_spend_target": event.milestone_spend_target,
                "milestone_period_start": event.milestone_period_start,
                "milestone_period_end": event.milestone_period_end,
            }
        )

    async def _card_calendar_response(self, event: CardCalendarEvent) -> CardCalendarItemResponse:
        progress = None
        if event.event_type in {"milestone_spend", "milestone"}:
            progress = await self._milestone_progress(event)
        return CardCalendarItemResponse(
            id=event.id,
            user_id=event.user_id,
            financial_account_id=event.financial_account_id,
            event_type=cast(
                Literal["renewal", "annual_fee", "fee_reversal", "milestone_spend", "milestone"],
                event.event_type,
            ),
            label=event.label,
            event_date=event.event_date,
            source_kind=cast(Literal["manual", "statement"], event.source_kind),
            source_label=event.source_label,
            source_identifier=event.source_identifier,
            annual_fee_amount=event.annual_fee_amount,
            fee_reversal_condition=event.fee_reversal_condition,
            fee_reversal_status=cast(
                Literal["unknown", "pending", "waived", "reversed", "not_eligible"] | None,
                event.fee_reversal_status,
            ),
            milestone_spend_target=event.milestone_spend_target,
            milestone_period_start=event.milestone_period_start,
            milestone_period_end=event.milestone_period_end,
            created_at=event.created_at,
            milestone_progress=progress,
        )

    async def _milestone_progress(self, event: CardCalendarEvent) -> CardCalendarMilestoneProgress:
        if (
            event.milestone_spend_target is None
            or event.milestone_period_start is None
            or event.milestone_period_end is None
        ):
            return CardCalendarMilestoneProgress(
                status="insufficient",
                counted_amount=Decimal("0.00"),
                target_amount=event.milestone_spend_target,
                remaining_amount=None,
                reason="Milestone target and period are required before progress can be computed.",
            )
        rows = list(
            (
                await self.db.scalars(
                    select(Transaction)
                    .where(
                        Transaction.user_id == event.user_id,
                        Transaction.financial_account_id == event.financial_account_id,
                        Transaction.transaction_date >= event.milestone_period_start,
                        Transaction.transaction_date <= event.milestone_period_end,
                        Transaction.transaction_status.in_(self._SETTLED_TRANSACTION_STATUSES),
                        Transaction.is_transfer.is_(False),
                        Transaction.is_accounting_adjustment.is_(False),
                        Transaction.review_outcome != "ignored_by_rule",
                        Transaction.card_event.in_([CardEvent.PURCHASE, CardEvent.REFUND]),
                    )
                    .order_by(Transaction.transaction_date, Transaction.created_at, Transaction.id)
                )
            ).all()
        )
        counted = Decimal("0.00")
        evidence = []
        for row in rows:
            direction: Literal["spend", "refund"]
            if row.card_event == CardEvent.REFUND or row.transaction_type == TransactionType.REFUND:
                direction = "refund"
                counted -= row.amount
            else:
                direction = "spend"
                counted += row.amount
            evidence.append(
                CardCalendarTransactionEvidence(
                    transaction_id=row.id,
                    transaction_date=row.transaction_date,
                    amount=row.amount,
                    direction=direction,
                    merchant=row.merchant_normalized or row.merchant_raw,
                    source_kind=row.source_kind,
                    source_identifier=row.source_identifier,
                )
            )
        remaining = max(event.milestone_spend_target - counted, Decimal("0.00"))
        return CardCalendarMilestoneProgress(
            status="ready",
            counted_amount=counted,
            target_amount=event.milestone_spend_target,
            remaining_amount=remaining,
            period_start=event.milestone_period_start,
            period_end=event.milestone_period_end,
            evidence=evidence,
        )

    async def _snapshot_card_calendar(
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
                "source_label": event.source_label,
                "source_identifier": event.source_identifier,
                "annual_fee_amount": event.annual_fee_amount,
                "fee_reversal_condition": event.fee_reversal_condition,
                "fee_reversal_status": event.fee_reversal_status,
                "milestone_spend_target": event.milestone_spend_target,
                "milestone_period_start": event.milestone_period_start,
                "milestone_period_end": event.milestone_period_end,
            },
            deleted=deleted,
        )

    async def create_household(self, user_id: str, data: HouseholdCreate) -> HouseholdSummary:
        household = Household(owner_user_id=user_id, name=data.name)
        self.db.add(household)
        await self.db.flush()
        self.db.add(
            HouseholdMember(
                household_id=household.id,
                user_id=user_id,
                role="owner",
                visibility="annotations_only",
            )
        )
        await self.db.commit()
        await self.db.refresh(household)
        return await self._household_summary(household)

    async def list_households(self, user_id: str) -> list[HouseholdSummary]:
        households = list(
            (
                await self.db.scalars(
                    select(Household)
                    .join(
                        HouseholdMember,
                        HouseholdMember.household_id == Household.id,
                    )
                    .where(
                        HouseholdMember.user_id == user_id,
                        HouseholdMember.left_at.is_(None),
                    )
                    .order_by(Household.created_at)
                )
            ).all()
        )
        return [await self._household_summary(item) for item in households]

    async def add_household_member(
        self,
        user_id: str,
        household_id: str,
        data: HouseholdMemberCreate,
    ) -> HouseholdSummary:
        household = await self._require_household_member(user_id, household_id)
        if household.owner_user_id != user_id:
            raise PermissionError("Only the household owner can add members")
        target = await self.db.scalar(
            select(User.id).where(User.id == data.user_id, User.deleted_at.is_(None))
        )
        if target is None:
            raise LookupError("User not found")
        await require_shared_ledger_currency(
            self.db,
            {household.owner_user_id, data.user_id},
            subject="Household",
        )
        existing = await self.db.scalar(
            select(HouseholdMember).where(
                HouseholdMember.household_id == household_id,
                HouseholdMember.user_id == data.user_id,
            )
        )
        if existing is None:
            self.db.add(HouseholdMember(household_id=household_id, **data.model_dump()))
        else:
            existing.left_at = None
            existing.role = data.role
            existing.visibility = data.visibility
        await self.db.commit()
        return await self._household_summary(household)

    async def list_household_members(
        self, user_id: str, household_id: str
    ) -> list[HouseholdMemberResponse]:
        await self._require_household_member(user_id, household_id)
        rows = await self.db.scalars(
            select(HouseholdMember)
            .where(HouseholdMember.household_id == household_id)
            .order_by(HouseholdMember.joined_at, HouseholdMember.user_id)
        )
        return [HouseholdMemberResponse.model_validate(row) for row in rows]

    async def update_household_member(
        self,
        user_id: str,
        household_id: str,
        member_user_id: str,
        data: HouseholdMemberUpdate,
    ) -> HouseholdMemberResponse:
        household = await self._require_household_member(user_id, household_id)
        if household.owner_user_id != user_id:
            raise PermissionError("Only the household owner can change member access")
        if member_user_id == household.owner_user_id:
            raise ValueError("The household owner's role cannot be changed")
        member = await self.db.scalar(
            select(HouseholdMember).where(
                HouseholdMember.household_id == household_id,
                HouseholdMember.user_id == member_user_id,
                HouseholdMember.left_at.is_(None),
            )
        )
        if member is None:
            raise LookupError("Household member not found")
        member.role = data.role
        member.visibility = data.visibility
        await self.db.commit()
        await self.db.refresh(member)
        return HouseholdMemberResponse.model_validate(member)

    async def remove_household_member(
        self, user_id: str, household_id: str, member_user_id: str
    ) -> None:
        household = await self._require_household_member(user_id, household_id)
        if member_user_id == household.owner_user_id:
            raise ValueError("The household owner cannot be removed")
        if household.owner_user_id != user_id and member_user_id != user_id:
            raise PermissionError("Only the owner can remove another member")
        member = await self.db.scalar(
            select(HouseholdMember).where(
                HouseholdMember.household_id == household_id,
                HouseholdMember.user_id == member_user_id,
            )
        )
        if member is None:
            raise LookupError("Household member not found")
        planned = await self.db.scalar(
            select(func.count())
            .select_from(HouseholdSettlement)
            .where(
                HouseholdSettlement.household_id == household_id,
                HouseholdSettlement.status == "planned",
                (
                    (HouseholdSettlement.from_user_id == member_user_id)
                    | (HouseholdSettlement.to_user_id == member_user_id)
                ),
            )
        )
        if planned:
            raise ValueError("Record or cancel this member's planned settlements before removal")
        member.left_at = datetime.now(UTC)
        member.role = "viewer"
        await self.db.commit()

    async def delete_household(self, user_id: str, household_id: str) -> None:
        household = await self._require_household_member(user_id, household_id)
        if household.owner_user_id != user_id:
            raise PermissionError("Only the household owner can delete it")
        planned = await self.db.scalar(
            select(func.count())
            .select_from(HouseholdSettlement)
            .where(
                HouseholdSettlement.household_id == household_id,
                HouseholdSettlement.status == "planned",
            )
        )
        if planned:
            raise ValueError("Record or cancel planned settlements before deleting the household")
        await self.db.delete(household)
        await self.db.commit()

    async def create_household_expense(
        self,
        user_id: str,
        household_id: str,
        data: HouseholdExpenseCreate,
    ) -> HouseholdExpenseResponse:
        await self._require_household_editor(user_id, household_id)
        member_ids = await self._household_member_ids(household_id)
        household_currency = await require_shared_ledger_currency(
            self.db,
            member_ids,
            subject="Household expense",
        )
        await require_ledger_currency(
            self.db,
            user_id,
            data.currency,
            subject="Household expense",
        )
        if data.currency != household_currency:
            raise ValueError(
                f"Household expense currency {data.currency} does not match "
                f"household ledger currency {household_currency}"
            )
        participants = set(data.splits)
        if data.payer_user_id not in member_ids or not participants <= member_ids:
            raise ValueError("Every payer and split participant must be a household member")
        expense = HouseholdExpense(
            household_id=household_id,
            created_by_user_id=user_id,
            payer_user_id=data.payer_user_id,
            label=data.label,
            amount=data.amount,
            currency=data.currency,
            expense_date=data.expense_date,
            splits_json=json.dumps(
                {key: str(value) for key, value in sorted(data.splits.items())},
                sort_keys=True,
            ),
        )
        self.db.add(expense)
        await self.db.commit()
        await self.db.refresh(expense)
        return self._expense_response(expense)

    async def list_household_expenses(
        self, user_id: str, household_id: str
    ) -> list[HouseholdExpenseResponse]:
        await self._require_household_member(user_id, household_id)
        rows = await self.db.scalars(
            select(HouseholdExpense)
            .where(HouseholdExpense.household_id == household_id)
            .order_by(HouseholdExpense.expense_date.desc())
        )
        return [self._expense_response(row) for row in rows]

    async def create_household_settlement(
        self,
        user_id: str,
        household_id: str,
        data: HouseholdSettlementCreate,
    ) -> HouseholdSettlementResponse:
        await self._require_household_editor(user_id, household_id)
        member_ids = await self._household_member_ids(household_id)
        household_currency = await require_shared_ledger_currency(
            self.db,
            member_ids,
            subject="Household settlement",
        )
        await require_ledger_currency(
            self.db,
            user_id,
            data.currency,
            subject="Household settlement",
        )
        if data.currency != household_currency:
            raise ValueError(
                f"Household settlement currency {data.currency} does not match "
                f"household ledger currency {household_currency}"
            )
        if data.from_user_id not in member_ids or data.to_user_id not in member_ids:
            raise ValueError("Both settlement parties must be household members")
        settlement = HouseholdSettlement(
            household_id=household_id,
            created_by_user_id=user_id,
            **data.model_dump(),
        )
        self.db.add(settlement)
        await self.db.commit()
        await self.db.refresh(settlement)
        return HouseholdSettlementResponse.model_validate(settlement)

    async def list_household_settlements(
        self, user_id: str, household_id: str
    ) -> list[HouseholdSettlementResponse]:
        await self._require_household_member(user_id, household_id)
        rows = await self.db.scalars(
            select(HouseholdSettlement)
            .where(HouseholdSettlement.household_id == household_id)
            .order_by(HouseholdSettlement.settlement_date.desc())
        )
        return [HouseholdSettlementResponse.model_validate(row) for row in rows]

    async def update_household_settlement(
        self,
        user_id: str,
        household_id: str,
        settlement_id: str,
        data: HouseholdSettlementUpdate,
    ) -> HouseholdSettlementResponse | None:
        await self._require_household_editor(user_id, household_id)
        settlement = await self.db.scalar(
            select(HouseholdSettlement).where(
                HouseholdSettlement.id == settlement_id,
                HouseholdSettlement.household_id == household_id,
            )
        )
        if settlement is None:
            return None
        settlement.status = data.status
        settlement.note = data.note
        await self.db.commit()
        await self.db.refresh(settlement)
        return HouseholdSettlementResponse.model_validate(settlement)

    async def payoff_comparison(
        self, user_id: str, monthly_budget: Decimal
    ) -> PayoffComparisonResponse:
        liabilities = list(
            (
                await self.db.scalars(
                    select(Liability).where(
                        Liability.user_id == user_id,
                        Liability.is_active.is_(True),
                    )
                )
            ).all()
        )
        eligible = [
            item
            for item in liabilities
            if item.outstanding_principal is not None
            and item.interest_rate is not None
            and item.monthly_due is not None
            and item.outstanding_principal > 0
        ]
        excluded = [item.id for item in liabilities if item not in eligible]
        debts = []
        for item in eligible:
            starting_balance = cast(Decimal, item.outstanding_principal)
            annual_interest_rate = cast(Decimal, item.interest_rate)
            minimum_payment = cast(Decimal, item.monthly_due)
            debts.append(
                PayoffDebt(
                    liability_id=item.id,
                    label=item.label,
                    starting_balance=float(starting_balance),
                    annual_interest_rate=float(annual_interest_rate),
                    minimum_payment=float(minimum_payment),
                )
            )
        assumptions = [
            "Uses only explicit balances, annual rates, and minimum payments.",
            "Interest accrues monthly; rates and payments are assumed unchanged.",
            "No fees, new borrowing, missed payments, or issuer actions are modelled.",
        ]
        if not eligible:
            return PayoffComparisonResponse(
                readiness="needs_complete_liabilities",
                monthly_budget=float(monthly_budget),
                debts=[],
                excluded_liability_ids=excluded,
                scenarios=[],
                assumptions=assumptions,
            )
        minimum_total = sum(
            (cast(Decimal, item.monthly_due) for item in eligible),
            Decimal(),
        )
        if monthly_budget < minimum_total:
            return PayoffComparisonResponse(
                readiness="insufficient_budget",
                monthly_budget=float(monthly_budget),
                debts=debts,
                excluded_liability_ids=excluded,
                scenarios=[],
                assumptions=[
                    *assumptions,
                    "The monthly budget is below the explicit minimum-payment total.",
                ],
            )
        scenarios = [
            self._simulate_payoff(eligible, monthly_budget, "highest_interest_first"),
            self._simulate_payoff(eligible, monthly_budget, "smallest_balance_first"),
        ]
        return PayoffComparisonResponse(
            readiness="ready",
            monthly_budget=float(monthly_budget),
            debts=debts,
            excluded_liability_ids=excluded,
            scenarios=scenarios,
            assumptions=assumptions,
        )

    @staticmethod
    def _simulate_payoff(
        liabilities: list[Liability],
        monthly_budget: Decimal,
        method: Literal["highest_interest_first", "smallest_balance_first"],
    ) -> PayoffScenario:
        balances = {item.id: cast(Decimal, item.outstanding_principal) for item in liabilities}
        rates = {
            item.id: cast(Decimal, item.interest_rate) / Decimal("1200") for item in liabilities
        }
        minimums = {item.id: cast(Decimal, item.monthly_due) for item in liabilities}
        labels = {item.id: item.label for item in liabilities}
        if method == "highest_interest_first":
            ordered = sorted(
                liabilities,
                key=lambda item: (
                    -cast(Decimal, item.interest_rate),
                    cast(Decimal, item.outstanding_principal),
                    item.id,
                ),
            )
        else:
            ordered = sorted(
                liabilities,
                key=lambda item: (
                    cast(Decimal, item.outstanding_principal),
                    -cast(Decimal, item.interest_rate),
                    item.id,
                ),
            )
        order_ids = [item.id for item in ordered]
        interest_total = Decimal()
        months = 0
        while any(value > 0 for value in balances.values()) and months < 600:
            months += 1
            for item_id, balance in list(balances.items()):
                interest = balance * rates[item_id]
                balances[item_id] += interest
                interest_total += interest
            remaining_budget = monthly_budget
            for item_id in order_ids:
                if balances[item_id] <= 0:
                    continue
                payment = min(minimums[item_id], balances[item_id], remaining_budget)
                balances[item_id] -= payment
                remaining_budget -= payment
            for item_id in order_ids:
                if remaining_budget <= 0:
                    break
                if balances[item_id] <= 0:
                    continue
                payment = min(balances[item_id], remaining_budget)
                balances[item_id] -= payment
                remaining_budget -= payment
        return PayoffScenario(
            method=method,
            payoff_order=[labels[item_id] for item_id in order_ids],
            estimated_months=months if months < 600 else None,
            estimated_interest=(
                float(interest_total.quantize(Decimal("0.01"))) if months < 600 else None
            ),
        )

    async def _require_account(self, user_id: str, account_id: str) -> FinancialAccount:
        account = await self.db.scalar(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
        if account is None:
            raise LookupError("Financial account not found")
        return account

    async def _require_card(self, user_id: str, account_id: str) -> FinancialAccount:
        account = await self._require_account(user_id, account_id)
        if account.account_type != "credit_card":
            raise ValueError("This action requires a credit-card account")
        return account

    async def _require_household_member(self, user_id: str, household_id: str) -> Household:
        household = await self.db.scalar(
            select(Household)
            .join(HouseholdMember, HouseholdMember.household_id == Household.id)
            .where(
                Household.id == household_id,
                HouseholdMember.user_id == user_id,
                HouseholdMember.left_at.is_(None),
            )
        )
        if household is None:
            raise LookupError("Household not found")
        return household

    async def _require_household_editor(self, user_id: str, household_id: str) -> Household:
        household = await self._require_household_member(user_id, household_id)
        role = await self.db.scalar(
            select(HouseholdMember.role).where(
                HouseholdMember.household_id == household_id,
                HouseholdMember.user_id == user_id,
            )
        )
        if role not in {"owner", "member"}:
            raise PermissionError("This household membership is read-only")
        return household

    async def _household_member_ids(self, household_id: str) -> set[str]:
        return set(
            (
                await self.db.scalars(
                    select(HouseholdMember.user_id).where(
                        HouseholdMember.household_id == household_id,
                        HouseholdMember.left_at.is_(None),
                    )
                )
            ).all()
        )

    async def _household_summary(self, household: Household) -> HouseholdSummary:
        member_count = await self.db.scalar(
            select(func.count())
            .select_from(HouseholdMember)
            .where(
                HouseholdMember.household_id == household.id,
                HouseholdMember.left_at.is_(None),
            )
        )
        expense_count = await self.db.scalar(
            select(func.count())
            .select_from(HouseholdExpense)
            .where(HouseholdExpense.household_id == household.id)
        )
        settlement_count = await self.db.scalar(
            select(func.count())
            .select_from(HouseholdSettlement)
            .where(
                HouseholdSettlement.household_id == household.id,
                HouseholdSettlement.status == "planned",
            )
        )
        return HouseholdSummary(
            id=household.id,
            owner_user_id=household.owner_user_id,
            name=household.name,
            member_count=int(member_count or 0),
            expense_count=int(expense_count or 0),
            open_settlement_count=int(settlement_count or 0),
            created_at=household.created_at,
        )

    @staticmethod
    def _expense_response(expense: HouseholdExpense) -> HouseholdExpenseResponse:
        return HouseholdExpenseResponse(
            id=expense.id,
            household_id=expense.household_id,
            created_by_user_id=expense.created_by_user_id,
            payer_user_id=expense.payer_user_id,
            label=expense.label,
            amount=expense.amount,
            currency=expense.currency,
            expense_date=expense.expense_date,
            splits={key: Decimal(value) for key, value in json.loads(expense.splits_json).items()},
            created_at=expense.created_at,
        )
