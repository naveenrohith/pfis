# PFIS Data Model

> **Scope:** persistence layer (SQLAlchemy ORM entities and storage rules).
> For API/Pydantic request and response shapes, see
> [data-models.md](data-models.md).

PFIS uses async SQLAlchemy models under `backend/app/models`.

## Main Entities

- `User`: registered user profile, currency, auth status.
- `GmailAccount`: connected Gmail account and encrypted token references.
- `FinancialAccount`: user-owned account identity inferred from connector metadata.
- `AccountBalanceSnapshot`: append-only dated balance for an asset or liability account.
- `DashboardPreference`: versioned, user-owned widget layout, theme, density, favorites, and onboarding goal.
- `RecommendationState`: user-owned dismissal or snooze state keyed by stable recommendation id.
- `MonthlySummary`: persisted dashboard/report aggregate cache for one user and month.
- `RawEmail`: stored email subject/body/sender/received timestamp for traceability.
- `Transaction`: parsed financial transaction with confidence, parser version, fingerprint, and optional source email.
- `Category`: category hierarchy for spending groups.
- `Merchant`: normalized merchant name, aliases, and default category.
- `Budget`: user/category monthly budget limit.
- `SyncRun`: Gmail sync observability record.
- `ParseFailure`: dead-letter queue for failed parser attempts.
- `UserCorrection`: feedback loop for corrected merchant/category/amount fields.
- `BackgroundJob`: async job tracking.
- `OAuthState`: persisted OAuth state with expiry.

Transactions may reference a `FinancialAccount` through the nullable
`financial_account_id` field. Migration `009_financial_accounts` backfills
accounts from existing four-digit account metadata; new ingestion reuses the
user-scoped account record and never stores full account numbers.

Migration `011_premium_workspace` adds asset/liability classification, balance
snapshots, dashboard preferences, recommendation state, and linked transfer
metadata. Balance snapshots are immutable after creation and unique per account
and date. Net worth carries forward each account's most recent snapshot and
calculates assets minus liabilities. It does not infer balances from cash flow.

An atomic transfer creates debit and credit transactions with one
`transfer_group_id`. Both rows have `is_transfer=true`, remain auditable in the
transaction ledger, and are excluded from income/spend aggregates.

`MonthlySummary` is invalidated within the same transaction-service commit as
transaction creation, correction, or deletion. The next dashboard or report
read recomputes and persists the snapshot, keeping request-time aggregations
bounded without introducing a worker or broker.

## Operational access paths

In addition to the transaction reporting indexes, the persistence layer keeps
composite user/time indexes on `RawEmail(user_id, received_at)` and
`SyncRun(user_id, start_time)`. These support incremental ingestion history,
sync-run timelines, and user-scoped operational queries without scanning all
users' records. The indexes are managed by Alembic migration
`008_operational_indexes` for shared and production databases.

## Rules

- All user-owned entities must be queried with user scope or checked with ownership helpers.
- Tokens and OAuth secrets must be encrypted before storage.
- Raw emails are retained to support reprocessing.
- Transaction `fingerprint` protects deduplication.
- Transfer legs must be created together and excluded from financial aggregates.
- Dashboard preferences, recommendation state, accounts, and balances are always user scoped.
- Parser changes must preserve `parser_version` traceability.
- Model changes require tests and migration review.
- Local/demo startup may create tables automatically for convenience, but shared or production environments must use Alembic migrations as the schema control path.

## Migration Discipline

PFIS keeps `Base.metadata.create_all` as a local/demo startup convenience only. It is not the production schema authority.

For shared or production-like databases:

- Apply schema changes through Alembic migrations under `backend/alembic/versions`.
- Keep Alembic migrations aligned with SQLAlchemy models in `backend/app/models`.
- Add or update tests before changing deduplication, ownership, or nullable field behavior.
- Run `tests/pytest/test_migration_discipline.py` when a model or migration changes.
