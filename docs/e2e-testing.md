# PFIS end-to-end testing

## What the suite proves

PFIS E2E runs exercise the built React application, FastAPI, and PostgreSQL together. Real
journeys use synthetic users, authenticated sessions, the application's normal HTTP routes, and
persisted records. They complement the focused unit and service suites, which remain responsible
for exhaustive parser, financial calculation, and failure-injection combinations.

The suite checks both pipelines:

1. **Financial processing:** source ingestion, classification, parsing, validation, normalization,
   categorization, deduplication, persistence, and refreshed views.
2. **CI execution:** dependency installation, static checks, migrations, application readiness,
   selected tests, reports, and cleanup.

The real browser pipeline journey starts the existing synthetic inbox sync, observes the job,
checks persisted source and ledger totals, corrects the low-confidence row, reloads Activity, and
checks the durable correction. The versioned source is
[`source-corpus-v1.json`](../tests/fixtures/e2e/source-corpus-v1.json). The current expected result
is 15 fetched messages, 12 new sources, 1 repeated source, 1 OTP and 1 promotion skipped, 13 stored
transactions, no pipeline duplicates or unresolved parse failures, and a ₹50,175.00 ledger total.
The fixture manifest records each user's financial day and the report compares persisted database
values with the corpus expectations.

The authenticated application journeys also cover registration, invalid-password feedback,
session restoration/logout, cross-user ownership rejection, quick add observed from a second
session, durable budget creation, non-persistent scenario preview, unsupported statement rejection,
portable export, retention confirmation, and the exact-text account-deletion safeguard. The
nightly-only restart path inserts one interrupted synthetic sync job while the app is running,
stops and restarts only that harness-owned FastAPI process, then verifies recovered job attempts,
source counts, one linked source transaction, ledger totals, and duplicate outcomes directly from
PostgreSQL.

## Local commands

Start a disposable PostgreSQL 17 service that listens on loopback, then provide a bootstrap URL
that can create databases and login roles. The runner never prints this URL and removes it from
the application, fixture, and browser child-process environments.

PowerShell:

```powershell
$env:PFIS_E2E_ADMIN_DATABASE_URL = 'postgresql://<user>:<password>@127.0.0.1:<port>/<bootstrap-database>'
python scripts/e2e_runner.py --mode smoke --allow-disposable-database
python scripts/e2e_runner.py --mode full --allow-disposable-database
python scripts/e2e_runner.py --mode full --test-grep "@planning|@statements|@privacy" --allow-disposable-database
python scripts/e2e_runner.py --mode explore --allow-disposable-database
# Run the scheduled restart-recovery scenario locally:
python scripts/e2e_runner.py --mode full --nightly-restart --allow-disposable-database
```

On the existing local test service, the bootstrap URL is typically
`postgresql://postgres:postgres@127.0.0.1:54322/postgres`. Use only a disposable local PostgreSQL
instance. `--allow-disposable-database` is a required explicit opt-in.

| Mode | Use | Selection |
|---|---|---|
| `smoke` | Local feedback and every PR | `@smoke`, desktop and 360px mobile, zero retries |
| `full` | Frontend-changing PRs and nightly runs | Broader browser suite, one diagnostic retry, flaky tests still fail |
| `explore` | Manual product exploration | Leaves the harness-owned app running until Ctrl+C |

`--nightly-restart` is accepted only with `full`. It prepares a synthetic running job after the
first application startup, then exercises the owned server process restart and verifies recovery
against the same disposable database.
`--test-grep` also requires `full` and selects matching Playwright titles for focused local
feedback; CI omits it so the configured full suite always runs.

The runner creates one run-scoped database named `pfis_e2e_<run-id>`, verifies the exact database
confirmation and marker before fixture writes, applies Alembic as the migration role, verifies
runtime privileges and migration parity, builds the frontend, waits for FastAPI readiness, starts
Playwright, and cleans up only its marked database and generated roles. `AUTH_REQUIRED=true` and
`ALLOW_DEMO_LOGIN=false` for these runs. Browser sessions are minted through PFIS's existing auth
service. Profiles and records are independent for each mutation.

For a standalone fixture CLI invocation, pass the exact run ID and database name and set
`PFIS_E2E=1`, `PFIS_E2E_RUN_ID`, and `PFIS_E2E_CONFIRM_DATABASE`. Fixture writes are refused unless
the database URL, loopback host, generated database name, marker, and confirmation agree.

## CI and evidence

- Pull requests and pushes to `main` run authenticated desktop smoke, the processing pipeline
  journey, selected mobile coverage, and focused pipeline transaction/concurrency regressions.
- A pull request that changes `frontend/` also runs the full functional browser suite, including
  responsive, keyboard, and serious/critical axe checks.
- Nightly starts at 02:00 IST (20:30 UTC) and runs smoke, the full browser suite, focused
  PostgreSQL regression tests, and one real app-process restart/recovery journey.
- Browser CI uses PostgreSQL 17. Alembic runs under a separate migration role; the app and fixture
  CLI use a DML-only runtime role. The app binds to loopback and the runner verifies both roles'
  privileges before starting it.
- Playwright uses one worker. Smoke retries are disabled. Full-suite retries are diagnostic only
  and `failOnFlakyTests` keeps a recovered failure red.
- HTML, JUnit, JSON, migration-parity, financial-pipeline, screenshot, and trace evidence is stored
  under `.test-run/e2e-<run-id>/`. Session cookies and fixture passwords are redacted before the
  CI upload sentinel is written. CI retains approved artifacts for 14 days. Bootstrap credentials,
  fixture credentials, and browser storage state are never uploaded.

The existing mocked/demo-oriented UI scenarios remain separate from the real financial pipeline
and authenticated ownership journeys. They use a service-created synthetic session and keep their
existing fixed visual clock; financial records use the backend's current user financial day.

## Manual exploration and MCP

The `explore` mode prints a local URL and the path to ignored, run-scoped test credentials. Use the
existing Brave profile for manual exploration, then convert confirmed defects into deterministic
Playwright tests. Do not use exploration to change assertions, financial expectations, or visual
baselines automatically.

No Playwright MCP is attached to this Codex session, so Brave-profile attachment could not be
verified. The repository's browser preference requires Brave; Chrome and Edge sessions are not
substitutes. Automated CI remains independent of interactive exploration.

## Current boundaries and follow-up gates

- Current real-browser statement coverage checks the rejected non-PDF path and no-ledger-write
  outcome. Supported PDF import, account mismatch, repeat-import, and uncertain-line review still
  need a versioned synthetic PDF fixture and authenticated browser journey; statement parser and
  persistence cases remain covered by focused backend tests.
- Real-browser period navigation and Ask PFIS evidence/limits still need journeys. Focused frontend
  and backend tests cover the current answer and evidence contracts.
- Existing Windows visual snapshots are not reused as Linux baselines. The Linux baseline matrix
  still needs generation and human review before snapshot comparison can become a required CI gate.
- Five consecutive successful nightly runs are required before calling the new suite stable; that
  evidence can only accumulate after the workflow runs nightly.
- A release-candidate run against a production build on staging still needs a disposable staging
  account and deployment-specific credentials.
- Interactive MCP attachment is unavailable here; continue with Brave for any manual exploration.

Do not add public reset routes, production fault switches, provider credentials, or browser-side
copies of financial calculations to make these tests pass.
