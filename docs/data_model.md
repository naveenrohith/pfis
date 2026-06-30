# PFIS Data Model

> **Scope:** persistence layer (SQLAlchemy ORM entities and storage rules).
> For API/Pydantic request and response shapes, see
> [data-models.md](data-models.md).

PFIS uses async SQLAlchemy models under `backend/app/models`.

## Main Entities

- `User`: registered user profile, currency, auth status.
- `GmailAccount`: connected Gmail account and encrypted token references.
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

## Rules

- All user-owned entities must be queried with user scope or checked with ownership helpers.
- Tokens and OAuth secrets must be encrypted before storage.
- Raw emails are retained to support reprocessing.
- Transaction `fingerprint` protects deduplication.
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
