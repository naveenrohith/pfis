"""Append durable dependency-change hints with authoritative ORM writes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from sqlalchemy import Table, event, func, inspect, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.financial_change import FinancialChangeCursor, FinancialChangeEvent

TRANSACTION_CHANGE_DOMAINS = frozenset(
    {"activity", "today", "insights", "accounts", "cards", "planning", "guidance"}
)

# This allowlist intentionally excludes read models such as MonthlySummary and
# forecast snapshots: recomputing a GET must never create another change event.
CHANGE_DOMAINS_BY_TABLE: dict[str, frozenset[str]] = {
    "anomaly_adjudications": frozenset({"insights", "data"}),
    "background_jobs": frozenset({"data"}),
    "transactions": TRANSACTION_CHANGE_DOMAINS,
    "transaction_splits": TRANSACTION_CHANGE_DOMAINS,
    "raw_emails": frozenset({"data"}),
    "gmail_accounts": frozenset({"data"}),
    "sync_runs": frozenset({"data"}),
    "parse_failures": frozenset({"data"}),
    "pipeline_events": frozenset({"data"}),
    "connector_audit_events": frozenset({"data"}),
    "financial_accounts": frozenset({"accounts", "planning", "today", "guidance"}),
    "account_link_rules": frozenset({"accounts", "statements"}),
    "account_balance_snapshots": frozenset({"accounts", "planning", "today", "guidance"}),
    "account_balance_sources": frozenset({"accounts", "data", "planning", "today"}),
    "account_balance_reconciliations": frozenset({"accounts", "planning", "today", "guidance"}),
    "balance_provider_connections": frozenset({"data"}),
    "balance_provider_account_mappings": frozenset({"accounts", "data"}),
    "card_position_observations": frozenset({"cards", "accounts", "planning", "today", "guidance"}),
    "statement_imports": frozenset(
        {"statements", "activity", "accounts", "cards", "planning", "today", "insights"}
    ),
    "statement_analysis_reviews": frozenset({"statements", "data"}),
    "credit_card_statements": frozenset({"statements", "cards", "planning", "today", "guidance"}),
    "deposit_account_statements": frozenset(
        {"statements", "activity", "accounts", "planning", "today", "insights"}
    ),
    "deposit_statement_lines": frozenset(
        {"statements", "activity", "accounts", "planning", "today", "insights"}
    ),
    "deposit_statement_line_review_decisions": frozenset(
        {"statements", "activity", "accounts", "planning", "today"}
    ),
    "statement_lines": frozenset(
        {"statements", "activity", "cards", "planning", "today", "insights"}
    ),
    "statement_line_matches": frozenset({"statements", "activity", "cards"}),
    "statement_line_review_decisions": frozenset(
        {"statements", "activity", "cards", "planning", "today"}
    ),
    "commitments": frozenset({"planning", "today", "guidance"}),
    "cash_plans": frozenset({"planning", "accounts", "today", "guidance"}),
    "reserve_plans": frozenset({"planning", "today", "guidance"}),
    "liabilities": frozenset({"planning", "cards", "today", "guidance"}),
    "liability_schedule_items": frozenset({"planning", "cards", "today", "guidance"}),
    "card_preferences": frozenset({"cards", "planning", "guidance"}),
    "card_payment_intents": frozenset({"cards", "planning", "today", "guidance"}),
    "card_calendar_events": frozenset({"cards", "planning", "today", "guidance"}),
    "roadmap_bills": frozenset({"planning", "today", "guidance"}),
    "budgets": frozenset({"planning", "today", "insights"}),
    "goals": frozenset({"planning", "today", "insights"}),
    "recommendation_states": frozenset({"today"}),
    "recommendation_outcomes": frozenset({"today", "insights"}),
    "card_disputes": frozenset({"cards", "data"}),
    "health_checklist_items": frozenset({"data"}),
    "temporal_event_decisions": frozenset({"planning", "today", "guidance"}),
    "user_merchant_rules": frozenset({"data", "activity"}),
}

# User-keyed tables not captured as sources are explicitly classified so a new
# financial table cannot silently bypass the change journal.
CHANGE_CAPTURE_EXCLUDED_TABLES: dict[str, str] = {
    "account_balance_forecast_outcomes": "Derived forecast evaluation; its source mutation emits the invalidation.",
    "account_balance_forecast_snapshots": "Derived forecast cache; its source mutation emits the invalidation.",
    "auth_identities": "Authentication identity metadata is not a financial view source.",
    "auth_sessions": "Authentication session and CSRF records are security state.",
    "cash_flow_forecast_outcomes": "Derived forecast evaluation; its source mutation emits the invalidation.",
    "cash_flow_forecast_snapshots": "Derived forecast cache; its source mutation emits the invalidation.",
    "dashboard_preferences": "Presentation preferences do not change financial source data.",
    "financial_change_cursors": "Journal control state must not recursively emit financial changes.",
    "financial_change_events": "Journal metadata must not recursively emit financial changes.",
    "household_expenses": "Shared household annotations require multi-member fan-out, outside the personal user stream.",
    "household_members": "Membership changes require multi-member fan-out, outside the personal user stream.",
    "household_settlements": "Shared household annotations require multi-member fan-out, outside the personal user stream.",
    "households": "Household ownership is shared scope, not a single-user financial source.",
    "monthly_summaries": "Derived aggregate cache; its source mutation emits the invalidation.",
    "oauth_states": "OAuth handshake state is transient authentication data.",
    "temporal_source_snapshots": "Derived source history is written alongside its source mutation.",
}

_EVENT_CACHE_KEY = "pfis_financial_change_events"
# A transaction-scoped lock preserves commit order for the global identity used
# by each worker's journal tailer. It is held only by transactions that append
# a change hint, and released automatically at commit/rollback.
_TAILER_ORDER_LOCK_ID = 0x50464953


def _transaction_key(session: Session) -> int:
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        transaction = session.begin()
    return id(transaction)


def _append_change(session: Session, user_id: str, domains: Iterable[str]) -> None:
    normalized = {domain for domain in domains if domain}
    if not user_id or not normalized:
        return

    transaction_key = _transaction_key(session)
    cache: dict[tuple[int, str], FinancialChangeEvent] = session.info.setdefault(
        _EVENT_CACHE_KEY, {}
    )
    key = (transaction_key, user_id)
    current = cache.get(key)
    if current is not None:
        current.domains = sorted(set(current.domains).union(normalized))
        return

    session.execute(select(func.pg_advisory_xact_lock(_TAILER_ORDER_LOCK_ID)))
    cursor_table: Table = cast(Table, FinancialChangeCursor.__table__)
    statement = (
        pg_insert(cursor_table)
        .values(user_id=user_id, current_sequence=1)
        .on_conflict_do_update(
            index_elements=[cursor_table.c.user_id],
            set_={
                "current_sequence": cursor_table.c.current_sequence + 1,
                "updated_at": func.now(),
            },
        )
        .returning(cursor_table.c.current_sequence)
    )
    sequence = int(session.connection().execute(statement).scalar_one())
    event_record = FinancialChangeEvent(
        user_id=user_id,
        sequence=sequence,
        event_type="financial_state_updated",
        domains=sorted(normalized),
    )
    session.add(event_record)
    cache[key] = event_record


async def queue_financial_change(db: AsyncSession, user_id: str, domains: Iterable[str]) -> None:
    """Record a Core/bulk-DML change inside its already-open transaction."""
    await db.run_sync(lambda session: _append_change(session, user_id, domains))


def _capture_orm_changes(session: Session, flush_context: object, instances: object) -> None:
    del flush_context, instances
    changed: dict[str, set[str]] = {}
    objects = set(session.new).union(session.dirty, session.deleted)
    for instance in objects:
        state = inspect(instance)
        table_domains = CHANGE_DOMAINS_BY_TABLE.get(state.mapper.local_table.name)
        if not table_domains:
            continue
        if (
            instance in session.dirty
            and instance not in session.new
            and not session.is_modified(instance, include_collections=True)
        ):
            continue
        user_id = getattr(instance, "user_id", None)
        if isinstance(user_id, str) and user_id:
            changed.setdefault(user_id, set()).update(table_domains)

    for user_id, user_domains in changed.items():
        _append_change(session, user_id, user_domains)


def _forget_transaction_events(session: Session, transaction: object) -> None:
    cache: dict[tuple[int, str], FinancialChangeEvent] | None = session.info.get(_EVENT_CACHE_KEY)
    if cache is None:
        return
    transaction_key = id(transaction)
    for key in [key for key in cache if key[0] == transaction_key]:
        cache.pop(key, None)
    if not cache:
        session.info.pop(_EVENT_CACHE_KEY, None)


event.listen(Session, "before_flush", _capture_orm_changes)
event.listen(Session, "after_transaction_end", _forget_transaction_events)
