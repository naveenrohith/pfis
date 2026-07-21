# PFIS Deployment Runbook

PFIS is local/demo by default. Use this runbook only for production-candidate or shared environments.

## Required Production Settings

Set:

- `ENVIRONMENT=production`
- `AUTH_REQUIRED=true`
- `SECRET_KEY` to a unique high-entropy value
- `DATABASE_URL` to PostgreSQL, preferably with an explicit
  `postgresql+asyncpg://` URL (plain `postgres://` and `postgresql://` deployment
  URLs are normalized to the async driver)
- `CORS_ORIGINS` to explicit trusted HTTPS origins (no wildcard, path, query,
  fragment, or embedded credentials)
- `SESSION_COOKIE_NAME=__Host-pfis_session`
- `SESSION_COOKIE_SECURE=true`
- `ALLOW_DEMO_LOGIN=false`
- Google OAuth settings only for approved redirect URIs
- A completed `frontend/dist` production build

Production startup intentionally fails when these values are unsafe.

The live sync channel accepts at most `WS_MAX_CONNECTIONS_PER_USER` sockets per
user and closes client messages larger than `WS_MAX_MESSAGE_BYTES`. Keep the
defaults unless measured staging traffic demonstrates a specific need.

Build the canonical dashboard before starting the production API:

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..
```

FastAPI intentionally returns `503` in local mode and fails startup in production
when `frontend/dist/index.html` is missing. The retired static dashboard is not an
authentication or availability fallback.

## Database Operations

- Use Alembic migrations under `backend/alembic/versions` as the schema path.
- Do not rely on `Base.metadata.create_all` outside local/demo mode.
- Run `tests/pytest/test_migration_discipline.py` after model or migration changes.
- Keep the PostgreSQL migration/runtime CI job green; SQLite remains a local
  convenience and is not sufficient database validation for a release.
- Take a database backup before applying migrations to shared environments.
- Migration 009 safely removes an empty `_alembic_tmp_transactions` table left by an interrupted
  local SQLite batch migration, but refuses to remove it when it contains rows. Backfill inserts
  always populate `financial_accounts.created_at` for compatibility with ORM-initialized databases.
- Migration 015 intentionally stops if it finds duplicate budgets, duplicate
  Gmail ownership, or invalid monetary values. Reconcile those records from a
  backup-reviewed copy before retrying; the migration never deletes financial data.
- Migration 016 adds the durable job lease columns and indexes. Deploy migrations
  before starting new application instances so their worker pollers can safely
  claim queued work.
- Migration 017 adds nullable Gmail access-token expiry metadata. Existing
  connectors refresh once on their next sync and populate it without a data
  backfill or token exposure.

## Backup And Restore

Minimum production-candidate checklist:

- Schedule database backups outside the app process.
- Store backups separately from the application host.
- Test restoring a backup into a clean database before go-live.
- Record restore time and any manual commands used.

SQLite local/demo data can be backed up by copying the database file while the app is stopped. Server databases should use the provider's native backup tooling.

## Health And Monitoring

Use:

- `GET /api/health` for basic process liveness.
- `GET /api/health/ready` for database-backed readiness. Route traffic only
  while this endpoint returns `200`.
- `GET /api/health/ops` for non-secret runtime posture and job counters.

API responses expose `Server-Timing: app;dur=<milliseconds>` and an
`X-Request-ID` correlation header. PFIS writes a structured warning for API
responses taking at least one second; forward these application logs to the
deployment log store and alert on sustained latency rather than a single sample.

Monitor:

- API error rates and latency.
- Background jobs by status.
- Background job retry counts, exhausted attempts, and stale running leases.
- Gmail sync failures.
- Parse failures and retry counts.
- Generic parser fallback usage.
- Database backup success and restore drill status.

## Rollback

- Keep every schema change reversible or document why it is not.
- Restore from backup if migration rollback cannot safely recover data.
- Revert phase-scoped commits rather than mixing unrelated fixes.
- Keep local/demo settings separate from production controls.
