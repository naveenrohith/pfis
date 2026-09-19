"""Irreversible owned-account deletion with shared-household tombstones."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base
from app.models.email import GmailAccount, RawEmail
from app.models.roadmap import Household, HouseholdMember, HouseholdSettlement
from app.models.sync import ConnectorAuditEvent, ParseFailure, UserCorrection
from app.models.transaction import Transaction
from app.models.user import User
from app.security import decrypt_secret, get_active_auth_session
from app.services.auto_sync_service import stop_auto_sync_for_account
from app.services.gmail.oauth_service import revoke_google_token
from app.services.ingestion.activity import stop_user_ingestions
from app.services.job_service import stop_user_jobs
from app.services.portable_export_service import (
    PORTABLE_EXPORT_EXCLUDED_TABLES,
    PORTABLE_EXPORT_TABLES,
)

logger = logging.getLogger(__name__)

ACCOUNT_DELETION_POLICY_VERSION = 1
RECENT_AUTHENTICATION_MINUTES = 15
_HOUSEHOLD_TABLES = {
    "households",
    "household_members",
    "household_expenses",
    "household_settlements",
}
_PRESERVED_TABLES = {"users", "categories", "merchants", *_HOUSEHOLD_TABLES}
_INDIRECT_TABLES = {"parse_failures", "user_corrections"}
ACCOUNT_DELETION_PRIVATE_TABLES = (
    PORTABLE_EXPORT_TABLES | set(PORTABLE_EXPORT_EXCLUDED_TABLES)
) - _PRESERVED_TABLES


async def has_recent_authentication(
    db: AsyncSession,
    raw_session_token: str | None,
    *,
    now: datetime | None = None,
) -> bool:
    if not raw_session_token:
        return False
    session = await get_active_auth_session(raw_session_token, db)
    if session is None or session.mode != "auth":
        return False
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    created_at = session.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at >= instant.astimezone(UTC) - timedelta(minutes=RECENT_AUTHENTICATION_MINUTES)


def account_deletion_inventory() -> dict[str, str]:
    inventory = dict.fromkeys(ACCOUNT_DELETION_PRIVATE_TABLES, "delete private rows")
    inventory.update(
        {
            "users": "retain non-login household participant tombstone",
            "categories": "retain global reference data",
            "merchants": "retain global reference data",
            "households": "delete sole household or transfer ownership",
            "household_members": "mark former membership while shared evidence exists",
            "household_expenses": "retain shared annotation evidence",
            "household_settlements": "retain shared settlement evidence",
        }
    )
    inventory["connector_audit_events"] = (
        "delete prior connector history, then append one non-secret deletion event"
    )
    return inventory


async def delete_owned_account(
    db: AsyncSession,
    user: User,
    *,
    deleted_at: datetime | None = None,
) -> dict[str, Any]:
    """Revoke the connector, remove private rows, and retain minimal shared lineage."""
    instant = deleted_at or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)

    account = await db.scalar(select(GmailAccount).where(GmailAccount.user_id == user.id))
    user.deletion_started_at = instant
    if account is not None:
        account.auto_sync_enabled = False
        account.auto_sync_status = "disconnecting"
        account.auto_sync_error = None
    await db.commit()

    try:
        await stop_user_jobs(user.id)
        if account is not None:
            await stop_auto_sync_for_account(account.id)
        await stop_user_ingestions(user.id)

        provider_revocation = await _revoke_gmail(account)
        household_result = await _leave_households(db, user.id, instant)
        deleted_counts = await _delete_private_rows(db, user.id)

        user.email = f"deleted-{user.id}@deleted.invalid"
        user.name = "Deleted participant"
        user.password_hash = None
        user.is_active = False
        user.timezone = "UTC"
        user.raw_email_retention_days = None
        user.deleted_at = instant
        user.deletion_started_at = None

        db.add(
            ConnectorAuditEvent(
                user_id=user.id,
                connector_type="account",
                connector_account_id=None,
                event_type="account_deleted",
                payload_json=json.dumps(
                    {
                        "policy_version": ACCOUNT_DELETION_POLICY_VERSION,
                        "provider_revocation": provider_revocation,
                        "private_rows_deleted": sum(deleted_counts.values()),
                        **household_result,
                    },
                    sort_keys=True,
                ),
                created_at=instant,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        persisted_user = await db.get(User, user.id)
        if persisted_user is not None and persisted_user.deleted_at is None:
            persisted_user.deletion_started_at = None
            await db.commit()
        raise
    return {
        "status": "deleted",
        "deleted_at": instant,
        "provider_revocation": provider_revocation,
        "private_rows_deleted": sum(deleted_counts.values()),
        **household_result,
    }


async def _revoke_gmail(account: GmailAccount | None) -> str:
    if account is None:
        return "not_connected"

    encrypted_token = account.refresh_token_ref or account.access_token_ref
    try:
        token = decrypt_secret(encrypted_token)
    except Exception as exc:
        logger.warning(
            "Gmail credential could not be read during account deletion exception=%s",
            type(exc).__name__,
        )
        token = None
    if not token:
        return "token_unavailable"
    try:
        return "revoked" if await revoke_google_token(token) else "provider_rejected"
    except Exception as exc:
        logger.warning(
            "Gmail revocation could not be confirmed during account deletion exception=%s",
            type(exc).__name__,
        )
        return "unconfirmed"


async def _leave_households(
    db: AsyncSession,
    user_id: str,
    instant: datetime,
) -> dict[str, int]:
    memberships = list(
        await db.scalars(
            select(HouseholdMember).where(
                HouseholdMember.user_id == user_id,
                HouseholdMember.left_at.is_(None),
            )
        )
    )
    households_deleted = 0
    ownership_transferred = 0
    memberships_closed = 0
    for membership in memberships:
        household = await db.get(Household, membership.household_id)
        if household is None:
            continue
        remaining = list(
            await db.scalars(
                select(HouseholdMember)
                .where(
                    HouseholdMember.household_id == household.id,
                    HouseholdMember.user_id != user_id,
                    HouseholdMember.left_at.is_(None),
                )
                .order_by(HouseholdMember.joined_at, HouseholdMember.user_id)
            )
        )
        if not remaining:
            await db.delete(household)
            households_deleted += 1
            continue
        if household.owner_user_id == user_id:
            new_owner = remaining[0]
            household.owner_user_id = new_owner.user_id
            new_owner.role = "owner"
            ownership_transferred += 1
        membership.role = "viewer"
        membership.left_at = instant
        memberships_closed += 1
        await db.execute(
            update(HouseholdSettlement)
            .where(
                HouseholdSettlement.household_id == household.id,
                HouseholdSettlement.status == "planned",
                (
                    (HouseholdSettlement.from_user_id == user_id)
                    | (HouseholdSettlement.to_user_id == user_id)
                ),
            )
            .values(
                status="cancelled",
                note="Cancelled when a participant deleted their PFIS account.",
            )
        )
    await db.flush()
    return {
        "households_deleted": households_deleted,
        "household_ownership_transferred": ownership_transferred,
        "household_memberships_closed": memberships_closed,
    }


async def _delete_private_rows(db: AsyncSession, user_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    raw_email_ids = select(RawEmail.id).where(RawEmail.user_id == user_id)
    transaction_ids = select(Transaction.id).where(Transaction.user_id == user_id)

    for table in reversed(Base.metadata.sorted_tables):
        table_name = table.name
        if table_name not in ACCOUNT_DELETION_PRIVATE_TABLES:
            continue
        if table_name == "parse_failures":
            statement = delete(ParseFailure).where(ParseFailure.email_id.in_(raw_email_ids))
        elif table_name == "user_corrections":
            statement = delete(UserCorrection).where(
                UserCorrection.transaction_id.in_(transaction_ids)
            )
        else:
            statement = table.delete().where(table.c.user_id == user_id)
        result = await db.execute(statement)
        counts[table_name] = max(int(result.rowcount or 0), 0)
    return counts
