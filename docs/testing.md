# PFIS Testing

## Test Root

`pytest.ini` points to `tests/pytest`.

Run all tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run the blocking backend static-analysis gates:

```powershell
.\.venv\Scripts\python.exe -m ruff check backend\app scripts tests
.\.venv\Scripts\python.exe -m black --check backend\app scripts tests
.\.venv\Scripts\python.exe -m mypy backend\app scripts\release_gate.py scripts\postgres_restore_drill.py scripts\migrate_sqlite_to_postgres.py
```

Mypy checks all 100 backend and operational-script source files in CI, including bodies of functions without
fully annotated signatures. New typing errors and unused suppressions fail the
build.

The full backend suite measures statement and branch coverage together and
enforces a 70% minimum. This is a regression floor, not a target: new work must
test its critical success, ownership, rollback, and failure paths rather than
adding untested code until the repository falls back to the threshold.

Audit pinned backend and frontend dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip_audit -r backend\requirements.txt
Set-Location frontend
npm audit --audit-level=high
```

Run targeted suites:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_auth_security.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_parser_regression.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_jobs_pipeline.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_budgets.py
.\.venv\Scripts\python.exe -m pytest tests/pytest/test_reports.py
```

All backend and browser regression jobs run against PostgreSQL 17. The migration
gate creates an isolated PostgreSQL database, applies every Alembic revision, and
compares the resulting schema, constraints, and indexes with ORM metadata.

The workspace regression suite also enforces a database-query budget for the
zero-data dashboard path. This guards against accidentally invoking every
analytics service during onboarding and for months without transactions.

In the managed Windows environment, set the test temp directory to a writable
path if the default user temp directory is blocked:

```powershell
New-Item -ItemType Directory -Force .test-run | Out-Null; $env:TEMP=(Resolve-Path .test-run).Path; $env:TMP=(Resolve-Path .test-run).Path; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .test-run\pytest
```

## Requirements

- Parser changes need sample emails and expected extraction assertions.
- API changes need success, validation, and ownership tests.
- Security changes need negative tests.
- Job/sync changes must not call real Gmail in tests.
- Job tests must cover atomic claims, restart recovery, bounded retries, and
  idempotent enqueue behavior.
- Tests must be deterministic and isolated.

## Browser Regression

The functional Playwright suite runs in CI after backend and frontend validation:

```powershell
Set-Location frontend
npm run test:e2e:ci
```

CI starts an isolated FastAPI process, seeds the demo identity, and runs functional,
responsive, keyboard, and axe coverage in Chromium. Visual tests are tagged
`@visual`; run the complete suite against the fixed clock and inspect every diff
before updating snapshots:

```powershell
npm run test:e2e
npm run test:e2e:update
```

Stable financial queries are refreshed after mutations, sync events, reconnect,
or window focus once stale; they are not continuously polled. Operational sync
and pipeline views poll once per minute only while mounted and visible.

Never update a visual baseline solely to make CI green. Confirm that changed copy,
financial meaning, hierarchy, and responsive layout are intentional first.
