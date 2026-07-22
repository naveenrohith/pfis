"""User-owned accounts, balance history, net worth, and linked transfers."""

import uuid
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSnapshot, FinancialAccount
from app.models.transaction import PaymentMethod, Transaction, TransactionType
from app.schemas.account import (
    BalanceKind,
    BalanceSnapshotCreate,
    BalanceSnapshotResponse,
    FinancialAccountCreate,
    FinancialAccountResponse,
    FinancialAccountUpdate,
    NetWorthPoint,
    NetWorthSeries,
    TransferCreate,
    TransferResponse,
)
from app.services.transaction_service import TransactionService


class AccountService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_accounts(self, user_id: str) -> list[FinancialAccountResponse]:
        result = await self.db.execute(
            select(FinancialAccount)
            .where(FinancialAccount.user_id == user_id)
            .order_by(FinancialAccount.is_active.desc(), FinancialAccount.institution_name)
        )
        return [await self._account_response(account) for account in result.scalars().all()]

    async def create_account(
        self, user_id: str, data: FinancialAccountCreate
    ) -> FinancialAccountResponse:
        existing = await self.db.execute(
            select(FinancialAccount).where(
                FinancialAccount.user_id == user_id,
                FinancialAccount.institution_name == data.institution_name,
                FinancialAccount.account_type == data.account_type,
                FinancialAccount.masked_number == data.masked_number,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("This institution account already exists")
        account = FinancialAccount(user_id=user_id, **data.model_dump())
        self.db.add(account)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("This institution account already exists") from exc
        await self.db.refresh(account)
        return await self._account_response(account)

    async def update_account(
        self, user_id: str, account_id: str, data: FinancialAccountUpdate
    ) -> FinancialAccountResponse | None:
        account = await self._owned_account(user_id, account_id)
        if account is None:
            return None
        updates = data.model_dump(exclude_unset=True)
        requested_currency = updates.get("currency")
        if requested_currency is not None and requested_currency != account.currency:
            history_exists = await self.db.scalar(
                select(AccountBalanceSnapshot.id)
                .where(AccountBalanceSnapshot.financial_account_id == account_id)
                .limit(1)
            )
            transaction_exists = await self.db.scalar(
                select(Transaction.id)
                .where(Transaction.financial_account_id == account_id)
                .limit(1)
            )
            if history_exists is not None or transaction_exists is not None:
                raise ValueError("Account currency cannot change after financial history exists")
        identity = {
            "institution_name": updates.get("institution_name", account.institution_name),
            "account_type": updates.get("account_type", account.account_type),
            "masked_number": updates.get("masked_number", account.masked_number),
        }
        duplicate = await self.db.scalar(
            select(FinancialAccount.id).where(
                FinancialAccount.user_id == user_id,
                FinancialAccount.institution_name == identity["institution_name"],
                FinancialAccount.account_type == identity["account_type"],
                FinancialAccount.masked_number == identity["masked_number"],
                FinancialAccount.id != account_id,
            )
        )
        if duplicate is not None:
            raise ValueError("This institution account already exists")
        for field, value in updates.items():
            setattr(account, field, value)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("This institution account already exists") from exc
        await self.db.refresh(account)
        return await self._account_response(account)

    async def add_balance(
        self, user_id: str, account_id: str, data: BalanceSnapshotCreate
    ) -> BalanceSnapshotResponse | None:
        account = await self._owned_account(user_id, account_id)
        if account is None:
            return None
        if not account.is_active:
            raise ValueError("Cannot add a balance to an inactive account")
        if data.currency is not None and data.currency != account.currency:
            raise ValueError("Balance currency must match the account currency")
        existing = await self.db.execute(
            select(AccountBalanceSnapshot.id).where(
                AccountBalanceSnapshot.financial_account_id == account_id,
                AccountBalanceSnapshot.as_of == data.as_of,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("A balance snapshot already exists for this account and date")
        snapshot = AccountBalanceSnapshot(
            user_id=user_id,
            financial_account_id=account_id,
            amount=data.amount,
            currency=data.currency or account.currency,
            as_of=data.as_of,
            source="manual",
        )
        self.db.add(snapshot)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("A balance snapshot already exists for this account and date") from exc
        await self.db.refresh(snapshot)
        return BalanceSnapshotResponse.model_validate(snapshot, from_attributes=True)

    async def net_worth(self, user_id: str, as_of: date | None = None) -> NetWorthSeries:
        accounts_result = await self.db.execute(
            select(FinancialAccount).where(
                FinancialAccount.user_id == user_id,
                FinancialAccount.is_active.is_(True),
            )
        )
        accounts = list(accounts_result.scalars().all())
        if not accounts:
            return NetWorthSeries(currency="INR")
        currencies = {account.currency for account in accounts}
        if len(currencies) != 1:
            raise ValueError("Net worth cannot combine currencies without exchange rates")
        account_ids = [account.id for account in accounts]
        snapshots_result = await self.db.execute(
            select(AccountBalanceSnapshot)
            .where(
                AccountBalanceSnapshot.user_id == user_id,
                AccountBalanceSnapshot.financial_account_id.in_(account_ids),
            )
            .order_by(AccountBalanceSnapshot.as_of, AccountBalanceSnapshot.created_at)
        )
        snapshots = [
            s for s in snapshots_result.scalars().all() if as_of is None or s.as_of <= as_of
        ]
        kinds = {account.id: account.balance_kind for account in accounts}
        currency = accounts[0].currency
        running: dict[str, Decimal] = {}
        points: list[NetWorthPoint] = []
        by_date: dict[date, list[AccountBalanceSnapshot]] = {}
        for snapshot in snapshots:
            by_date.setdefault(snapshot.as_of, []).append(snapshot)
        for snapshot_date, day_snapshots in by_date.items():
            for snapshot in day_snapshots:
                running[snapshot.financial_account_id] = snapshot.amount
            assets = sum(
                (value for key, value in running.items() if kinds.get(key) == "asset"),
                Decimal("0"),
            )
            liabilities = sum(
                (value for key, value in running.items() if kinds.get(key) == "liability"),
                Decimal("0"),
            )
            points.append(
                NetWorthPoint(
                    date=snapshot_date,
                    assets=float(round(assets, 2)),
                    liabilities=float(round(liabilities, 2)),
                    net_worth=float(round(assets - liabilities, 2)),
                )
            )
        latest = points[-1] if points else None
        return NetWorthSeries(
            currency=currency,
            as_of=latest.date if latest else None,
            assets=latest.assets if latest else 0.0,
            liabilities=latest.liabilities if latest else 0.0,
            net_worth=latest.net_worth if latest else 0.0,
            points=points,
        )

    async def create_transfer(self, user_id: str, data: TransferCreate) -> TransferResponse:
        from_account = await self._owned_account(user_id, data.from_account_id)
        to_account = await self._owned_account(user_id, data.to_account_id)
        if from_account is None or to_account is None:
            raise LookupError("Account not found")
        if not from_account.is_active or not to_account.is_active:
            raise ValueError("Transfers require active accounts")
        if from_account.currency != data.currency or to_account.currency != data.currency:
            raise ValueError("Cross-currency transfers are not supported")

        transfer_group_id = str(uuid.uuid4())
        description = (data.description or "Account transfer").strip()
        debit_reference = f"transfer:{transfer_group_id}:debit"
        credit_reference = f"transfer:{transfer_group_id}:credit"
        debit = Transaction(
            user_id=user_id,
            amount=data.amount,
            currency=data.currency,
            transaction_type=TransactionType.DEBIT,
            payment_method=PaymentMethod.BANK_TRANSFER,
            transaction_status="completed",
            merchant_raw=f"Transfer to {to_account.institution_name}",
            merchant_normalized=description,
            transaction_date=data.transaction_date,
            reference_id=debit_reference,
            confidence_score=1.0,
            reviewed_flag=True,
            fingerprint=TransactionService.compute_fingerprint(
                user_id, data.amount, data.transaction_date, description, debit_reference
            ),
            financial_account_id=from_account.id,
            transfer_group_id=transfer_group_id,
            is_transfer=True,
        )
        credit = Transaction(
            user_id=user_id,
            amount=data.amount,
            currency=data.currency,
            transaction_type=TransactionType.CREDIT,
            payment_method=PaymentMethod.BANK_TRANSFER,
            transaction_status="completed",
            merchant_raw=f"Transfer from {from_account.institution_name}",
            merchant_normalized=description,
            transaction_date=data.transaction_date,
            reference_id=credit_reference,
            confidence_score=1.0,
            reviewed_flag=True,
            fingerprint=TransactionService.compute_fingerprint(
                user_id, data.amount, data.transaction_date, description, credit_reference
            ),
            financial_account_id=to_account.id,
            transfer_group_id=transfer_group_id,
            is_transfer=True,
        )
        self.db.add_all([debit, credit])
        try:
            await TransactionService(self.db)._invalidate_monthly_summary(
                user_id, data.transaction_date
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        await self.db.refresh(debit)
        await self.db.refresh(credit)
        return TransferResponse(
            transfer_group_id=transfer_group_id,
            debit_transaction_id=debit.id,
            credit_transaction_id=credit.id,
            amount=float(data.amount),
            currency=data.currency,
            transaction_date=data.transaction_date,
        )

    async def _owned_account(self, user_id: str, account_id: str) -> FinancialAccount | None:
        result = await self.db.execute(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _account_response(self, account: FinancialAccount) -> FinancialAccountResponse:
        result = await self.db.execute(
            select(AccountBalanceSnapshot)
            .where(AccountBalanceSnapshot.financial_account_id == account.id)
            .order_by(AccountBalanceSnapshot.as_of.desc(), AccountBalanceSnapshot.created_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        return FinancialAccountResponse(
            id=account.id,
            user_id=account.user_id,
            institution_name=account.institution_name,
            account_type=account.account_type,
            balance_kind=cast(BalanceKind, account.balance_kind),
            masked_number=account.masked_number,
            currency=account.currency,
            is_active=account.is_active,
            latest_balance=float(latest.amount) if latest else None,
            balance_as_of=latest.as_of if latest else None,
            created_at=account.created_at,
        )
