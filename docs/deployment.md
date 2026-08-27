# PFIS Deployment Runbook

PFIS uses PostgreSQL in local, CI, and hosted environments. Use this runbook for
production-candidate or shared deployments.

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

### Optional statement OCR runtime

Statement uploads prefer embedded PDF text. To accept image-only/scanned PDFs,
install the pinned Python `PyMuPDF` dependency from
`backend/requirements.txt` and the host `tesseract` executable with the
English language pack. PFIS invokes Tesseract through stdin/stdout; PDF bytes,
rendered pages, and OCR text stay in memory and are discarded after the request.
The fallback is bounded by these settings:

- `STATEMENT_OCR_ENABLED` (default `true`)
- `STATEMENT_OCR_MAX_PAGES` (default `8`, maximum `20`)
- `STATEMENT_OCR_DPI` (default `160`)
- `STATEMENT_OCR_PAGE_TIMEOUT_SECONDS` (default `8`)

If the executable is unavailable, the PDF exceeds the page limit, or OCR cannot
recover enough text, the route fails closed and the existing text/review path
remains available. OCR never bypasses strict statement identity, direction,
currency, and running-balance reconciliation gates.

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
- Do not rely on `Base.metadata.create_all`; Alembic owns every environment.
- Run `tests/pytest/test_migration_discipline.py` after model or migration changes.
- Keep the PostgreSQL migration/runtime CI jobs green.
- Verify the committed migration head against every configured local/E2E database
  before integration: `python scripts/check_migration_parity.py`. The command
  can write a protected JSON receipt with `--output`; a mismatch is a release
  blocker, not a reason to apply ad-hoc SQL.
- Take a database backup before applying migrations to shared environments.
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

Use Supabase/PostgreSQL-native backup tooling. The ignored `backend/pfis.db`
file is a quarantined rollback artifact from the completed legacy cutover. It
must not be used by the app and may be deleted only after the agreed backup
retention period and a successful PostgreSQL restore drill.

### Executable restore drill

Install the PostgreSQL client tools (`pg_dump` and `pg_restore`), create an empty
disposable restore database, and set:

- `DATABASE_URL` to the source PostgreSQL database.
- `RESTORE_DATABASE_URL` to the disposable restore database.
- `RESTORE_DATABASE_NAME` to the exact disposable database name as destructive confirmation.
- `RELEASE_EVIDENCE_DIR` to a protected artifact directory.

Then run `make restore-drill`, or invoke `scripts/postgres_restore_drill.py`
directly on Windows. The command refuses a restore target matching the source,
never prints connection URLs, restores with owner/privilege portability, and
uses a single restore transaction with fail-fast error handling. It compares
the Alembic revision and critical table row counts. Run it during a quiescent
window: it fails if the source revision or critical row counts change while
the backup is created. A passing run writes `restore-evidence.json`; retain it
with the release record. The final release gate accepts evidence only for the
named production database and only when the drill completed within the previous
24 hours.

## Health And Monitoring

Use:

- `GET /api/health` for basic process liveness.
- `GET /api/health/ready` for database-backed readiness. Route traffic only
  while this endpoint returns `200`.
- `GET /api/health/metrics` for bounded process request counts, status errors,
  latency percentiles, and low-cardinality route buckets. Counters reset on
  process restart and contain no user or source data.
- `GET /api/health/ops` for non-secret runtime posture and job counters.

API responses expose `Server-Timing: app;dur=<milliseconds>` and an
`X-Request-ID` correlation header. PFIS writes a structured warning for API
responses taking at least one second; forward these application logs to the
deployment log store and alert on sustained latency rather than a single sample.

Monitor:

- API error rates and latency.
- `/api/health/metrics` request totals, 4xx/5xx rates, p50/p95 latency, slow
  requests, and route-level buckets; forward these values to a durable hosted
  metrics system for multi-instance alerting.
- Background jobs by status.
- Background job retry counts, exhausted attempts, and stale running leases.
- Gmail sync failures.
- Parse failures and retry counts.
- Generic parser fallback usage.
- Operational status reasons, statement-layout rejection drift, and provider
  completeness warnings from `/api/health/ops`.
- Database backup success and restore drill status.

The repository `ops-contract` check covers the health, bounded metrics, readiness,
security-header, restore-evidence, and release-threshold contracts in CI. The
browser job also verifies migration parity after applying its disposable database
migrations. These checks prove the contract and fail-closed thresholds; they do not
replace a hosted load run, durable metrics sink, alert owner, or restore drill.

## Rollback

- Keep every schema change reversible or document why it is not.
- Restore from backup if migration rollback cannot safely recover data.
- Revert phase-scoped commits rather than mixing unrelated fixes.
- Keep local/demo settings separate from production controls.

## Final Release Gate

Set `INCIDENT_OWNER`, `DATA_RECOVERY_OWNER`, and `SECURITY_OWNER` to real,
deployment-owned contacts. Set `DATABASE_RESOURCE_ID`, `BACKUP_POLICY_ID`,
`MONITORING_DASHBOARD_ID`, `ALERT_POLICY_ID`, `TLS_POLICY_ID`, and
`NETWORK_POLICY_ID` to the corresponding provider resource identifiers. Set
`PRODUCTION_DATABASE_NAME` to the exact source database named in the restore
evidence. Also set `PFIS_PRODUCTION_URL` and `RELEASE_EVIDENCE_DIR`. Run:

```powershell
.\.venv\Scripts\python.exe scripts\release_gate.py `
  --base-url $env:PFIS_PRODUCTION_URL `
  --restore-evidence "$env:RELEASE_EVIDENCE_DIR\restore-evidence.json" `
  --output "$env:RELEASE_EVIDENCE_DIR\release-evidence.json"
```

The gate fails unless the target uses HTTPS with a valid certificate, liveness,
database readiness, and operational health return their documented healthy
payloads, required security headers including HSTS are present, fresh restore
evidence matches the production database, all operational owners are named,
the probe sends at least 200 requests, errors stay at or below 0.5%, and
readiness p95 stays at or below 750 ms. The CLI permits more traffic and tighter
thresholds but rejects weaker release criteria.

## Intelligence release evidence

Operational readiness does not prove that the intelligence rules are ready for
real users. Before promoting a new parser, forecast, or recommendation ruleset,
collect the corresponding machine-readable reports and run the strict evidence
join. Generate the parser report with an independently reviewed cohort manifest
when representative parser evidence is available:

```powershell
python scripts/evaluate_parser_corpus.py `
  --cohort-manifest "$env:RELEASE_EVIDENCE_DIR\parser-cohort-manifest.json" `
  --output "$env:RELEASE_EVIDENCE_DIR\parser-quality-report.json"
```

The manifest pins the corpus SHA-256, lists opaque case IDs, and attests that
the sample is de-identified and independently reviewed. Without a verified
manifest, representative parser coverage remains deferred even if fixture
labels claim a production cohort.

Generate protected forecast backtests from the release database with a reviewed
user roster. The roster may contain user IDs only inside the protected evidence
directory; the export replaces them with a keyed hash and emits no spend or
projection amounts:

```powershell
python scripts/export_forecast_evidence.py `
  --cohort-manifest "$env:RELEASE_EVIDENCE_DIR\forecast-cohort-manifest.json" `
  --output "$env:RELEASE_EVIDENCE_DIR\forecast-production-safe.json"
```

The roster uses the following protected shape (the IDs never enter the export):

```json
{
  "version": 1,
  "users": [
    {"id": "internal-user-id", "cohort": "production_safe"}
  ],
  "attestation": {
    "deidentified": true,
    "reviewed": true,
    "reviewer_id": "privacy-review-ticket",
    "reviewed_at": "2026-08-02T00:00:00Z"
  }
}
```

Pass the resulting artifact with `--forecast-report
"$env:RELEASE_EVIDENCE_DIR\forecast-production-safe.json"` (or the glob below)
to the strict join. A missing or invalid roster leaves all reports outside the
`production_safe` cohort, so it cannot inflate representative-user coverage.

Generate protected balance-reconciliation evidence from the same release
database. Use a separately reviewed roster for this product cohort; the export
keeps only keyed user membership and aggregate interval residuals. Raw balances,
movement amounts, transaction IDs, institution names, and user IDs remain in
the protected database:

```powershell
python scripts/export_balance_reconciliation_evidence.py `
  --cohort-manifest "$env:RELEASE_EVIDENCE_DIR\balance-cohort-manifest.json" `
  --output "$env:RELEASE_EVIDENCE_DIR\balance-reconciliation.json"
```

The strict balance gate requires at least 10 manifest-attested
`production_safe` users, 100 immutable verified-observation intervals across
at least 6 institutions, a median absolute residual of at most 1% of known
movement, and a 95th-percentile residual of at most 5%. These are initial
operational floors, not a claim that a provider-backed live-balance contract
already exists. Missing or invalid roster evidence is deferred (or fails
closed under `--strict`).

Export recommendation effectiveness from the same protected database with:

```powershell
python scripts/export_recommendation_evidence.py `
  --output "$env:RELEASE_EVIDENCE_DIR\recommendation-effectiveness.json"
```

The exporter preserves the service's minimum outcome/user suppression and emits
only aggregate cohorts and suppression counts; it never exports decision IDs,
notes, or user identities.

```powershell
python scripts/intelligence_release_gate.py --strict `
  --parser-report "$env:RELEASE_EVIDENCE_DIR\parser-quality-report.json" `
  --forecast-report-glob "$env:RELEASE_EVIDENCE_DIR\forecast-*.json" `
  --balance-reconciliation-report "$env:RELEASE_EVIDENCE_DIR\balance-reconciliation.json" `
  --anomaly-report "$env:RELEASE_EVIDENCE_DIR\anomaly-quality-report.json" `
  --recommendation-report "$env:RELEASE_EVIDENCE_DIR\recommendation-effectiveness.json" `
  --output "$env:RELEASE_EVIDENCE_DIR\intelligence-release-evidence.json"
```

The gate enforces the documented parser thresholds, requires at least 100
manifest-attested `sanitized_production`/`production_safe` parser cases across
10 formats and 6 institutions (unlabelled fixtures or self-declared labels
cannot satisfy that gate),
checks every eligible forecast horizon against the 20% median absolute
percentage error limit and a 70% minimum interval-coverage floor toward the 80%
calibration target, requires at least 5 distinct `production_safe` forecast users
identified only by a non-empty protected hash (raw user IDs are rejected),
historical transaction-state coverage of at least 95%, and temporal-evidence
flags on eligible forecast reports,
requires the protected balance artifact to carry at least 10 attested
`production_safe` users, 100 intervals, 6 institutions, and residual quality
within the 1% median/5% p95 floors,
requires adjudicated anomaly evidence from at least 5 contributing users with
both category and merchant cases, at least 90% precision, 80% recall, at most
10% false-positive rate, and both alert/non-alert and material/expected anomaly
cases before those rates are considered available.
It also requires privacy-safe recommendation
cohorts with at least 10 outcomes from 5 active users. Missing or
still-insufficient balance/forecast/anomaly/recommendation evidence is reported as
`deferred` in audit mode and fails closed under `--strict`; it is never treated
as a passing placeholder. The default `make check` intentionally
does not run this strict gate because local repositories do not contain
production user evidence. Use `make intelligence-release-gate
INTELLIGENCE_RELEASE_ARGS='...'` from a protected release-evidence directory.

Pull-request CI also runs the same gate in non-strict posture mode after the
parser score and uploads `intelligence-release-report.json`. That artifact is
intended to make deferred forecast, anomaly, recommendation, and
representative-cohort evidence visible during development; it does not grant
release approval. Promotion still requires the protected strict command above.

As the final handoff step, assemble a hash-addressed promotion manifest:

```powershell
python scripts/build_promotion_manifest.py `
  --scorecard-report "$env:RELEASE_EVIDENCE_DIR\intelligence-scorecard-report.json" `
  --evidence-root "$env:RELEASE_EVIDENCE_DIR" `
  --output "$env:RELEASE_EVIDENCE_DIR\promotion-manifest.json"
```

The manifest records the repository commit, Alembic head, scorecard digest, named
evidence digests, intelligence and delivery-flow scores, and every missing gate.
It emits `deferred` unless the scorecard was produced in strict mode, its promotion
decision is approved, and every named evidence artifact is present. Hash presence is
not semantic approval: the parser/forecast/reconciliation/operations gates must still
validate the artifact contents before a release owner signs off.

The anomaly artifact is version 1 JSON with a `cases` array. Each case contains
`kind` (`category` or `merchant`), `predicted_alert`, and
`adjudicated_material` booleans. Build it with
`make anomaly-evidence-export ANOMALY_EVIDENCE=...` from the protected database,
then run `make anomaly-eval ANOMALY_EVIDENCE=...`. The export deduplicates to the
latest eligible label per sampled case, excludes `insufficient_evidence`, and
contains no transaction descriptions or user identifiers. It carries only an
aggregate contributing-user count and category/merchant coverage so the strict
gate cannot credit 50 labels from one user or one anomaly kind. Keep both the
export and evaluator report in a protected release-evidence directory.

TLS termination, firewall/network policy, managed backup schedules, hosted log
shipping, and alert routing remain provider controls. The release gate requires
their identifiers in its evidence so they cannot be silently omitted; never
commit credentials or fabricated ownership names.
