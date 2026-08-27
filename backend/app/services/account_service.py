"""User-owned accounts, identity evidence, balances, net worth, and transfers."""

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import AccountBalanceSnapshot, AccountLinkRule, FinancialAccount
from app.models.sync import UserCorrection
from app.models.temporal_history import TemporalSourceSnapshot
from app.models.transaction import PaymentMethod, PaymentRail, Transaction, TransactionType
from app.schemas.account import (
    AccountIdentityEvidence,
    AccountIdentitySnapshotResponse,
    AccountIdentityStatus,
    AccountLinkRuleCreate,
    AccountLinkRuleResponse,
    AccountProductType,
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
from app.services.ledger_currency import get_ledger_currency, require_ledger_currency
from app.services.temporal_source_history import (
    capture_financial_account_snapshot,
    capture_transaction_snapshot,
)
from app.services.transaction_service import TransactionService


def _expected_balance_kind(account_type: str) -> BalanceKind | None:
    if account_type in {"bank", "cash", "investment"}:
        return "asset"
    if account_type in {"credit_card", "loan", "pay_later"}:
        return "liability"
    return None


def _balance_kind_label(balance_kind: BalanceKind) -> str:
    return "assets" if balance_kind == "asset" else "liabilities"


def _parse_identity_evidence(value: str | None) -> list[dict[str, object]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _append_identity_evidence(
    account: FinancialAccount,
    *,
    source_type: str,
    source_id: str,
    role: str,
    note: str,
    status: AccountIdentityStatus | None = None,
    confidence: Decimal | None = None,
) -> None:
    entries = _parse_identity_evidence(account.identity_evidence_json)
    entry: dict[str, object] = {
        "source_type": source_type,
        "source_id": source_id,
        "role": role,
        "note": note,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    if not any(
        item.get("source_type") == source_type
        and item.get("source_id") == source_id
        and item.get("role") == role
        and item.get("note") == note
        for item in entries
    ):
        entries.append(entry)
    account.identity_evidence_json = json.dumps(entries, sort_keys=True)
    if status is not None:
        account.identity_status = status
    if confidence is not None:
        account.identity_confidence = confidence.quantize(Decimal("0.001"))


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

    async def list_link_rules(self, user_id: str) -> list[AccountLinkRuleResponse]:
        rows = list(
            (
                await self.db.scalars(
                    select(AccountLinkRule)
                    .where(AccountLinkRule.user_id == user_id)
                    .order_by(
                        AccountLinkRule.is_active.desc(),
                        AccountLinkRule.created_at.desc(),
                    )
                )
            ).all()
        )
        return [AccountLinkRuleResponse.model_validate(row, from_attributes=True) for row in rows]

    async def create_link_rule(
        self, user_id: str, data: AccountLinkRuleCreate
    ) -> AccountLinkRuleResponse:
        account = await self._owned_account(user_id, data.financial_account_id)
        if account is None:
            raise LookupError("Financial account not found")
        if not account.is_active:
            raise ValueError("Account-link rules require an active account")
        if account.currency != data.currency:
            raise ValueError("Rule currency must match the financial account")
        account_suffix = "".join(
            character for character in account.masked_number if character.isdigit()
        )[-4:]
        if account_suffix != data.evidence_value:
            raise ValueError("Masked suffix must match the selected account")

        existing = await self.db.scalar(
            select(AccountLinkRule).where(
                AccountLinkRule.user_id == user_id,
                AccountLinkRule.evidence_kind == data.evidence_kind,
                AccountLinkRule.evidence_value == data.evidence_value,
                AccountLinkRule.currency == data.currency,
            )
        )
        if existing is not None:
            if existing.financial_account_id != account.id:
                raise ValueError("This evidence is already approved for a different account")
            if existing.is_active:
                raise ValueError("This account-link rule already exists")
            existing.is_active = True
            rule = existing
        else:
            rule = AccountLinkRule(user_id=user_id, **data.model_dump())
            self.db.add(rule)
            await self.db.flush()

        candidates = list(
            (
                await self.db.scalars(
                    select(Transaction)
                    .outerjoin(
                        FinancialAccount,
                        FinancialAccount.id == Transaction.financial_account_id,
                    )
                    .where(
                        Transaction.user_id == user_id,
                        Transaction.currency == data.currency,
                        Transaction.account_last4 == data.evidence_value,
                        or_(
                            Transaction.financial_account_id.is_(None),
                            FinancialAccount.account_type == "unknown",
                        ),
                    )
                    .order_by(Transaction.created_at, Transaction.id)
                )
            ).all()
        )
        corrected_ids = set()
        if candidates:
            corrected_ids = set(
                (
                    await self.db.scalars(
                        select(UserCorrection.transaction_id).where(
                            UserCorrection.transaction_id.in_(
                                [transaction.id for transaction in candidates]
                            ),
                            UserCorrection.field_corrected == "financial_account_id",
                        )
                    )
                ).all()
            )
        repaired = 0
        repaired_transactions: list[Transaction] = []
        now = datetime.now(UTC)
        for transaction in candidates:
            if transaction.id in corrected_ids:
                continue
            old_account_id = transaction.financial_account_id
            transaction.financial_account_id = account.id
            transaction.reviewed_flag = True
            transaction.reviewed_at = now
            transaction.review_outcome = "matched"
            self.db.add(
                UserCorrection(
                    transaction_id=transaction.id,
                    field_corrected="financial_account_id",
                    old_value=old_account_id,
                    new_value=account.id,
                )
            )
            repaired += 1
            repaired_transactions.append(transaction)
        _append_identity_evidence(
            account,
            source_type="account_link_rule",
            source_id=rule.id,
            role="masked_suffix",
            note="A user-approved masked suffix links imported activity to this account.",
            status=("inferred" if account.identity_status == "unresolved" else None),
            confidence=(
                max(account.identity_confidence, Decimal("0.650"))
                if account.identity_status == "unresolved"
                else None
            ),
        )
        try:
            await self.db.flush()
            for transaction in repaired_transactions:
                await capture_transaction_snapshot(self.db, transaction)
            await capture_financial_account_snapshot(self.db, account)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("This account-link rule already exists") from exc
        await self.db.refresh(rule)
        return AccountLinkRuleResponse(
            **AccountLinkRuleResponse.model_validate(rule, from_attributes=True).model_dump(
                exclude={"repaired_transaction_count"}
            ),
            repaired_transaction_count=repaired,
        )

    async def deactivate_link_rule(self, user_id: str, rule_id: str) -> bool:
        rule = await self.db.scalar(
            select(AccountLinkRule).where(
                AccountLinkRule.id == rule_id, AccountLinkRule.user_id == user_id
            )
        )
        if rule is None:
            return False
        rule.is_active = False
        account = await self._owned_account(user_id, rule.financial_account_id)
        if account is not None:
            _append_identity_evidence(
                account,
                source_type="account_link_rule",
                source_id=rule.id,
                role="deactivated",
                note="The masked-suffix link is no longer used for future imports.",
            )
            await self.db.flush()
            await capture_financial_account_snapshot(self.db, account)
        await self.db.commit()
        return True

    async def create_account(
        self, user_id: str, data: FinancialAccountCreate
    ) -> FinancialAccountResponse:
        await require_ledger_currency(
            self.db,
            user_id,
            data.currency,
            subject="Account",
        )
        payload = data.model_dump()
        expected_kind = _expected_balance_kind(data.account_type)
        if expected_kind is not None:
            if "balance_kind" in data.model_fields_set and data.balance_kind != expected_kind:
                raise ValueError(
                    f"{data.account_type.replace('_', ' ').title()} accounts must be "
                    f"recorded as {_balance_kind_label(expected_kind)}"
                )
            payload["balance_kind"] = expected_kind
        existing = await self.db.scalar(
            select(FinancialAccount.id).where(
                FinancialAccount.user_id == user_id,
                FinancialAccount.institution_name == data.institution_name,
                FinancialAccount.account_type == data.account_type,
                FinancialAccount.masked_number == data.masked_number,
            )
        )
        if existing is not None:
            raise ValueError("This institution account already exists")
        masked_digits = "".join(
            character for character in data.masked_number if character.isdigit()
        )
        if data.account_type != "unknown" and masked_digits:
            legacy_candidates = list(
                (
                    await self.db.scalars(
                        select(FinancialAccount).where(
                            FinancialAccount.user_id == user_id,
                            FinancialAccount.account_type == "unknown",
                            FinancialAccount.currency == data.currency,
                            FinancialAccount.masked_number.like(f"%{masked_digits[-4:]}"),
                        )
                    )
                ).all()
            )
            if len(legacy_candidates) == 1:
                account = legacy_candidates[0]
                account.institution_name = data.institution_name
                account.account_type = data.account_type
                account.balance_kind = payload["balance_kind"]
                account.masked_number = data.masked_number
                _append_identity_evidence(
                    account,
                    source_type="user_confirmation",
                    source_id=account.id,
                    role="identity_update",
                    note="A user supplied the institution, product type, and masked identifier.",
                    status="confirmed",
                    confidence=Decimal("1.000"),
                )
                await self.db.flush()
                await capture_financial_account_snapshot(self.db, account)
                await self.db.commit()
                await self.db.refresh(account)
                return await self._account_response(account)
        explicit_identity = (
            data.account_type != "unknown" and data.institution_name.strip().casefold() != "unknown"
        )
        account = FinancialAccount(
            user_id=user_id,
            identity_status="confirmed" if explicit_identity else "unresolved",
            identity_confidence=Decimal("1.000") if explicit_identity else Decimal("0.350"),
            **payload,
        )
        self.db.add(account)
        try:
            await self.db.flush()
            _append_identity_evidence(
                account,
                source_type="user_confirmation",
                source_id=account.id,
                role="identity_creation",
                note=(
                    "A user created this account with an explicit institution and product type."
                    if explicit_identity
                    else "The account was created without a complete institution/product identity."
                ),
                status="confirmed" if explicit_identity else "unresolved",
                confidence=Decimal("1.000") if explicit_identity else Decimal("0.350"),
            )
            await capture_financial_account_snapshot(self.db, account)
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
        if "currency" in updates:
            await require_ledger_currency(
                self.db,
                user_id,
                updates["currency"],
                subject="Account",
            )
        resulting_type = updates.get("account_type", account.account_type)
        expected_kind = _expected_balance_kind(resulting_type)
        if expected_kind is not None:
            requested_kind = updates.get("balance_kind")
            if requested_kind is not None and requested_kind != expected_kind:
                raise ValueError(
                    f"{resulting_type.replace('_', ' ').title()} accounts must be "
                    f"recorded as {_balance_kind_label(expected_kind)}"
                )
            updates["balance_kind"] = expected_kind
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
        identity_fields_changed = bool(
            {"institution_name", "account_type", "masked_number"} & updates.keys()
        )
        was_active = account.is_active
        for field, value in updates.items():
            setattr(account, field, value)
        if identity_fields_changed:
            typed_identity = (
                account.account_type != "unknown"
                and account.institution_name.strip().casefold() != "unknown"
            )
            _append_identity_evidence(
                account,
                source_type="user_confirmation",
                source_id=account.id,
                role="identity_update",
                note="A user confirmed or refined the institution, product type, or masked identifier.",
                status="confirmed" if typed_identity else "unresolved",
                confidence=Decimal("1.000") if typed_identity else Decimal("0.350"),
            )
        if "is_active" in updates and account.is_active != was_active:
            _append_identity_evidence(
                account,
                source_type="account_lifecycle",
                source_id=account.id,
                role="status_change",
                note=(
                    "The account was activated for future evidence."
                    if account.is_active
                    else "The account was deactivated; historical evidence remains retained."
                ),
            )
        try:
            await self.db.flush()
            await capture_financial_account_snapshot(self.db, account)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ValueError("This institution account already exists") from exc
        await self.db.refresh(account)
        return await self._account_response(account)

    async def add_balance(
        self,
        user_id: str,
        account_id: str,
        data: BalanceSnapshotCreate,
        *,
        commit: bool = True,
    ) -> BalanceSnapshotResponse | None:
        account = await self._owned_account(user_id, account_id)
        if account is None:
            return None
        await require_ledger_currency(
            self.db,
            user_id,
            account.currency,
            subject="Account",
        )
        if not account.is_active:
            raise ValueError("Cannot add a balance to an inactive account")
        if data.currency is not None and data.currency != account.currency:
            raise ValueError("Balance currency must match the account currency")
        if data.source == "connector" and not data.source_record_id:
            raise ValueError("Connector balance observations require source_record_id")
        if data.source_record_id is not None:
            existing_source = await self.db.scalar(
                select(AccountBalanceSnapshot).where(
                    AccountBalanceSnapshot.financial_account_id == account_id,
                    AccountBalanceSnapshot.source == data.source,
                    AccountBalanceSnapshot.source_record_id == data.source_record_id,
                )
            )
            if existing_source is not None:
                # Connector retries are expected. Return the original
                # append-only observation instead of creating a second fact or
                # mutating the first one.
                from app.services.balance_reconciliation_service import (
                    BalanceReconciliationService,
                )

                await BalanceReconciliationService(self.db).ensure_for_closing_snapshot(
                    user_id,
                    account_id,
                    existing_source.id,
                )
                return BalanceSnapshotResponse.model_validate(existing_source, from_attributes=True)
        same_day = list(
            (
                await self.db.scalars(
                    select(AccountBalanceSnapshot)
                    .where(
                        AccountBalanceSnapshot.financial_account_id == account_id,
                        AccountBalanceSnapshot.as_of == data.as_of,
                    )
                    .order_by(AccountBalanceSnapshot.created_at)
                )
            ).all()
        )
        if same_day and not data.source_record_id:
            raise ValueError("A balance snapshot already exists for this account and date")
        if same_day and any(
            snapshot.source == data.source and snapshot.source_record_id == data.source_record_id
            for snapshot in same_day
        ):
            raise ValueError("A balance snapshot already exists for this account and source")
        snapshot = AccountBalanceSnapshot(
            user_id=user_id,
            financial_account_id=account_id,
            amount=data.amount,
            currency=data.currency or account.currency,
            as_of=data.as_of,
            source=data.source,
            source_record_id=data.source_record_id,
            verified=data.verified,
            observed_at=data.observed_at or datetime.now(UTC),
            effective_at=data.effective_at,
        )
        self.db.add(snapshot)
        try:
            await self.db.flush()
            from app.services.balance_reconciliation_service import (
                BalanceReconciliationService,
            )

            await BalanceReconciliationService(self.db).ensure_for_closing_snapshot(
                user_id,
                account_id,
                snapshot.id,
            )
            if commit:
                await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if data.source_record_id is not None:
                persisted = await self.db.scalar(
                    select(AccountBalanceSnapshot).where(
                        AccountBalanceSnapshot.financial_account_id == account_id,
                        AccountBalanceSnapshot.source == data.source,
                        AccountBalanceSnapshot.source_record_id == data.source_record_id,
                    )
                )
                if persisted is not None:
                    return BalanceSnapshotResponse.model_validate(
                        persisted,
                        from_attributes=True,
                    )
            raise ValueError("A balance snapshot conflicts with an existing observation") from exc
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
            return NetWorthSeries(currency=await get_ledger_currency(self.db, user_id))
        currencies = {account.currency for account in accounts}
        if len(currencies) != 1:
            raise ValueError("Net worth cannot combine currencies without exchange rates")
        ledger_currency = await get_ledger_currency(self.db, user_id)
        if currencies != {ledger_currency}:
            raise ValueError(
                "Existing account currency does not match the user ledger currency; "
                "correct the account before calculating net worth"
            )
        today: date | None = None
        if as_of is None:
            # Current net worth must use the user's financial day rather than
            # the host machine's calendar day. Historical requests remain
            # snapshot-only and are never rewritten by the current read model.
            from app.services.financial_clock import user_financial_today

            today = await user_financial_today(self.db, user_id)
        account_ids = [account.id for account in accounts]
        snapshot_cutoff = as_of if as_of is not None else today
        snapshots_result = await self.db.execute(
            select(AccountBalanceSnapshot)
            .where(
                AccountBalanceSnapshot.user_id == user_id,
                AccountBalanceSnapshot.financial_account_id.in_(account_ids),
            )
            .order_by(
                AccountBalanceSnapshot.as_of,
                AccountBalanceSnapshot.effective_at.asc().nulls_last(),
                AccountBalanceSnapshot.observed_at,
                AccountBalanceSnapshot.created_at,
            )
        )
        snapshots = [
            s
            for s in snapshots_result.scalars().all()
            if s.verified and (snapshot_cutoff is None or s.as_of <= snapshot_cutoff)
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
        current_position_status: Literal[
            "observed",
            "estimated",
            "partial",
            "needs_review",
            "stale",
            "not_available",
            "historical",
        ] = (
            "historical" if as_of is not None else "not_available"
        )
        current_position_confidence = 0.0
        current_position_reason_codes: list[str] = []
        current_position_as_of: date | None = None
        if as_of is None and today is not None:
            # Keep this read model server-owned: net worth consumes the same
            # account position policy used by Cash Plan and the account UI.
            from app.services.financial_position_service import FinancialPositionService

            position_service = FinancialPositionService(self.db)
            positions = [
                await position_service.account_position(user_id, account.id) for account in accounts
            ]
            stale_cutoff = date.fromordinal(today.toordinal() - 7)
            eligible_positions = []
            for position in positions:
                if position is None:
                    current_position_reason_codes.append("account_position_unavailable")
                    continue
                if position.observed_as_of is None:
                    current_position_reason_codes.extend(position.position_reason_codes)
                    continue
                if position.observed_as_of < stale_cutoff:
                    current_position_reason_codes.append("stale_verified_observation")
                    continue
                if position.position_status not in {"observed", "estimated"}:
                    current_position_reason_codes.extend(position.position_reason_codes)
                    continue
                if position.estimated_balance is None:
                    current_position_reason_codes.append("estimated_position_unavailable")
                    continue
                if position.position_reason_codes:
                    current_position_reason_codes.extend(position.position_reason_codes)
                    continue
                eligible_positions.append(position)
            current_position_reason_codes = list(dict.fromkeys(current_position_reason_codes))
            if len(eligible_positions) == len(accounts):
                assets = sum(
                    (
                        Decimal(str(position.estimated_balance))
                        for account, position in zip(accounts, eligible_positions, strict=True)
                        if account.balance_kind == "asset"
                    ),
                    Decimal("0"),
                )
                liabilities = sum(
                    (
                        Decimal(str(position.estimated_balance))
                        for account, position in zip(accounts, eligible_positions, strict=True)
                        if account.balance_kind == "liability"
                    ),
                    Decimal("0"),
                )
                current_point = NetWorthPoint(
                    date=today,
                    assets=float(round(assets, 2)),
                    liabilities=float(round(liabilities, 2)),
                    net_worth=float(round(assets - liabilities, 2)),
                )
                if points and points[-1].date == today:
                    points[-1] = current_point
                else:
                    points.append(current_point)
                current_position_status = (
                    "estimated"
                    if any(
                        position.position_status == "estimated" for position in eligible_positions
                    )
                    else "observed"
                )
                current_position_confidence = min(
                    position.position_confidence for position in eligible_positions
                )
                current_position_as_of = today
            else:
                current_position_status = (
                    "stale"
                    if "stale_verified_observation" in current_position_reason_codes
                    and len(current_position_reason_codes) == 1
                    else "needs_review" if current_position_reason_codes else "not_available"
                )
                current_position_confidence = min(
                    (
                        position.position_confidence
                        for position in positions
                        if position is not None
                    ),
                    default=0.0,
                )
        latest = points[-1] if points else None
        return NetWorthSeries(
            currency=currency,
            as_of=latest.date if latest else None,
            assets=latest.assets if latest else 0.0,
            liabilities=latest.liabilities if latest else 0.0,
            net_worth=latest.net_worth if latest else 0.0,
            points=points,
            current_position_status=current_position_status,
            current_position_confidence=current_position_confidence,
            current_position_reason_codes=current_position_reason_codes,
            current_position_as_of=current_position_as_of,
        )

    async def create_transfer(
        self,
        user_id: str,
        data: TransferCreate,
        *,
        commit: bool = True,
    ) -> TransferResponse:
        await require_ledger_currency(
            self.db,
            user_id,
            data.currency,
            subject="Transfer",
        )
        from_account = await self._owned_account(user_id, data.from_account_id)
        to_account = await self._owned_account(user_id, data.to_account_id)
        if from_account is None or to_account is None:
            raise LookupError("Account not found")
        if not from_account.is_active or not to_account.is_active:
            raise ValueError("Transfers require active accounts")
        if from_account.currency != data.currency or to_account.currency != data.currency:
            raise ValueError("Cross-currency transfers are not supported")
        if data.payment_rail == "atm" and (
            from_account.account_type != "bank" or to_account.account_type != "cash"
        ):
            raise ValueError(
                "ATM withdrawals must move money from a bank account to a cash account"
            )

        transfer_group_id = str(uuid.uuid4())
        default_description = (
            "ATM cash withdrawal" if data.payment_rail == "atm" else "Account transfer"
        )
        description = (data.description or default_description).strip()
        debit_reference = f"transfer:{transfer_group_id}:debit"
        credit_reference = f"transfer:{transfer_group_id}:credit"
        debit = Transaction(
            user_id=user_id,
            amount=data.amount,
            currency=data.currency,
            transaction_type=TransactionType.DEBIT,
            payment_method=PaymentMethod.BANK_TRANSFER,
            payment_rail=PaymentRail(data.payment_rail),
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
            payment_rail=PaymentRail(data.payment_rail),
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
            await self.db.flush()
            await capture_transaction_snapshot(self.db, debit)
            await capture_transaction_snapshot(self.db, credit)
            if commit:
                await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        if commit:
            await self.db.refresh(debit)
            await self.db.refresh(credit)
        return TransferResponse(
            transfer_group_id=transfer_group_id,
            debit_transaction_id=debit.id,
            credit_transaction_id=credit.id,
            amount=float(data.amount),
            currency=data.currency,
            transaction_date=data.transaction_date,
            payment_rail=data.payment_rail,
        )

    async def identity_history(
        self, user_id: str, account_id: str
    ) -> list[AccountIdentitySnapshotResponse] | None:
        """Return the append-only identity/lifecycle evidence for one account."""

        account = await self._owned_account(user_id, account_id)
        if account is None:
            return None
        rows = list(
            (
                await self.db.scalars(
                    select(TemporalSourceSnapshot)
                    .where(
                        TemporalSourceSnapshot.user_id == user_id,
                        TemporalSourceSnapshot.source_type == "financial_account",
                        TemporalSourceSnapshot.source_id == account_id,
                    )
                    .order_by(TemporalSourceSnapshot.captured_at, TemporalSourceSnapshot.id)
                )
            ).all()
        )
        if not rows:
            return [
                self._identity_snapshot_from_account(
                    account,
                    captured_at=account.updated_at or account.created_at,
                    effective_date=(account.updated_at or account.created_at).date(),
                )
            ]
        snapshots: list[AccountIdentitySnapshotResponse] = []
        for row in rows:
            try:
                payload = json.loads(row.payload_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            effective_value = payload.get("effective_date")
            try:
                effective_date = date.fromisoformat(str(effective_value))
            except (TypeError, ValueError):
                effective_date = row.captured_at.date()
            try:
                snapshots.append(
                    AccountIdentitySnapshotResponse(
                        financial_account_id=account.id,
                        captured_at=row.captured_at,
                        effective_date=effective_date,
                        institution_name=str(
                            payload.get("institution_name") or account.institution_name
                        ),
                        account_type=cast(
                            AccountProductType,
                            str(payload.get("account_type") or account.account_type),
                        ),
                        balance_kind=cast(
                            BalanceKind,
                            str(payload.get("balance_kind") or account.balance_kind),
                        ),
                        masked_number=str(payload.get("masked_number") or account.masked_number),
                        currency=str(payload.get("currency") or account.currency),
                        is_active=bool(payload.get("is_active", account.is_active)),
                        identity_status=cast(
                            AccountIdentityStatus,
                            str(payload.get("identity_status") or account.identity_status),
                        ),
                        identity_confidence=float(
                            payload.get("identity_confidence", account.identity_confidence)
                        ),
                        identity_evidence=[
                            AccountIdentityEvidence.model_validate(item)
                            for item in payload.get("identity_evidence", [])
                            if isinstance(item, dict)
                        ],
                    )
                )
            except (TypeError, ValueError):
                continue
        return snapshots or [
            self._identity_snapshot_from_account(
                account,
                captured_at=account.updated_at or account.created_at,
                effective_date=(account.updated_at or account.created_at).date(),
            )
        ]

    async def _owned_account(self, user_id: str, account_id: str) -> FinancialAccount | None:
        result = await self.db.execute(
            select(FinancialAccount).where(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _identity_snapshot_from_account(
        account: FinancialAccount,
        *,
        captured_at: datetime,
        effective_date: date,
    ) -> AccountIdentitySnapshotResponse:
        return AccountIdentitySnapshotResponse(
            financial_account_id=account.id,
            captured_at=captured_at,
            effective_date=effective_date,
            institution_name=account.institution_name,
            account_type=cast(AccountProductType, account.account_type),
            balance_kind=cast(BalanceKind, account.balance_kind),
            masked_number=account.masked_number,
            currency=account.currency,
            is_active=account.is_active,
            identity_status=cast(AccountIdentityStatus, account.identity_status),
            identity_confidence=float(account.identity_confidence),
            identity_evidence=[
                AccountIdentityEvidence.model_validate(item)
                for item in _parse_identity_evidence(account.identity_evidence_json)
            ],
        )

    async def _account_response(self, account: FinancialAccount) -> FinancialAccountResponse:
        result = await self.db.execute(
            select(AccountBalanceSnapshot)
            .where(AccountBalanceSnapshot.financial_account_id == account.id)
            .order_by(
                AccountBalanceSnapshot.as_of.desc(),
                AccountBalanceSnapshot.effective_at.desc().nulls_last(),
                AccountBalanceSnapshot.observed_at.desc(),
                AccountBalanceSnapshot.created_at.desc(),
            )
            .limit(1)
        )
        latest_observed = result.scalar_one_or_none()
        verified_result = await self.db.execute(
            select(AccountBalanceSnapshot)
            .where(
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
        latest_verified = verified_result.scalar_one_or_none()
        # Keep account-list consumers on the same server-owned position policy
        # as Net Worth, Cash Plan, and the dedicated position endpoint.  The
        # verified snapshot fields above remain immutable observed evidence;
        # current_balance is only the settlement-aware read-model estimate.
        from app.services.financial_position_service import FinancialPositionService

        current_position = await FinancialPositionService(self.db).account_position(
            account.user_id, account.id
        )
        return FinancialAccountResponse(
            id=account.id,
            user_id=account.user_id,
            institution_name=account.institution_name,
            account_type=cast(AccountProductType, account.account_type),
            balance_kind=cast(BalanceKind, account.balance_kind),
            masked_number=account.masked_number,
            currency=account.currency,
            is_active=account.is_active,
            identity_status=cast(AccountIdentityStatus, account.identity_status),
            identity_confidence=float(account.identity_confidence),
            identity_evidence=[
                AccountIdentityEvidence.model_validate(item)
                for item in _parse_identity_evidence(account.identity_evidence_json)
            ],
            latest_balance=float(latest_verified.amount) if latest_verified else None,
            balance_as_of=latest_verified.as_of if latest_verified else None,
            current_balance=(
                current_position.estimated_balance if current_position is not None else None
            ),
            current_balance_as_of=(
                current_position.estimated_as_of if current_position is not None else None
            ),
            current_balance_status=(
                current_position.position_status
                if current_position is not None
                else "needs_observation"
            ),
            current_balance_confidence=(
                current_position.position_confidence if current_position is not None else 0.0
            ),
            current_balance_reason_codes=(
                current_position.position_reason_codes if current_position is not None else []
            ),
            latest_observed_balance=float(latest_observed.amount) if latest_observed else None,
            latest_observed_as_of=latest_observed.as_of if latest_observed else None,
            latest_observed_verified=latest_observed.verified if latest_observed else None,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
