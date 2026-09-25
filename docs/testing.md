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
.\.venv\Scripts\python.exe -m mypy backend\app scripts\release_gate.py scripts\postgres_restore_drill.py
```

Mypy checks the backend and production operational scripts in CI, including
bodies of functions without fully annotated signatures. New typing errors and
unused suppressions fail the build.

The full backend suite measures statement and branch coverage together and
enforces an 85% minimum. This is a regression floor, not a target: new work must
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

## Critical Read Query Budgets

`tests\pytest\test_query_budgets.py` enforces SQL statement ceilings for
representative critical reads. The helper in
`tests\pytest\query_budget_helpers.py` attaches a SQLAlchemy
`before_cursor_execute` listener to the sync engine underneath the async test
engine and counts statements only while the request is executing.

The representative fixture seeds one user with four financial accounts
(including two cards), current balance and card-position evidence, cash-plan
records, budgets, and 200 transactions. Budgets live in
`tests\pytest\fixtures\query_budgets.json`; each ceiling is the measured count
plus small headroom:

| Budget key | Observed statements | Ceiling |
| --- | ---: | ---: |
| `accounts_balance_list` | 39 | 43 |
| `account_position` | 8 | 10 |
| `net_worth` | 34 | 38 |
| `cash_plan` | 12 | 14 |
| `card_portfolio_payment_plan` | 104 | 112 |
| `card_overview` | 23 | 26 |
| `workspace_dashboard_summary` | 75 | 81 |
| `guidance_query` | 3 | 5 |
| `readiness` | 58 | 63 |

Run just this gate with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\pytest\test_query_budgets.py -p no:cacheprovider --basetemp .test-run\pytest-qb
```

Known hotspot to preserve for later work: account-list and current net-worth
reads call the account-position read model once per account, and the card
portfolio plan calls due-runway/forecast paths per active card. These are
obvious N+1-style shapes, but this gate intentionally records current behavior
without changing financial arithmetic in the financial-position or guidance
services.

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
