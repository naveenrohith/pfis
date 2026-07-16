# PFIS Deployment Runbook

PFIS is local/demo by default. Use this runbook only for production-candidate or shared environments.

## Required Production Settings

Set:

- `ENVIRONMENT=production`
- `AUTH_REQUIRED=true`
- `SECRET_KEY` to a unique high-entropy value
- `DATABASE_URL` to a non-SQLite database
- `CORS_ORIGINS` to explicit trusted origins
- Google OAuth settings only for approved redirect URIs

Production startup intentionally fails when these values are unsafe.

## Database Operations

- Use Alembic migrations under `backend/alembic/versions` as the schema path.
- Do not rely on `Base.metadata.create_all` outside local/demo mode.
- Run `tests/pytest/test_migration_discipline.py` after model or migration changes.
- Take a database backup before applying migrations to shared environments.
- Migration 009 safely removes an empty `_alembic_tmp_transactions` table left by an interrupted
  local SQLite batch migration, but refuses to remove it when it contains rows. Backfill inserts
  always populate `financial_accounts.created_at` for compatibility with ORM-initialized databases.

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
- `GET /api/health/ops` for non-secret runtime posture and job counters.

Monitor:

- API error rates and latency.
- Background jobs by status.
- Gmail sync failures.
- Parse failures and retry counts.
- Generic parser fallback usage.
- Database backup success and restore drill status.

## Rollback

- Keep every schema change reversible or document why it is not.
- Restore from backup if migration rollback cannot safely recover data.
- Revert phase-scoped commits rather than mixing unrelated fixes.
- Keep local/demo settings separate from production controls.
