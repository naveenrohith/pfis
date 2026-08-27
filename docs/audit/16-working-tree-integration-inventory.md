# PFIS Working-Tree Integration Inventory

Status: active integration control  
Captured: 2026-08-10  
Parent roadmap: `15-intelligence-productivity-recovery-roadmap.md`  
Scope: Sprint 0 items S0-02 and S0-03

## Outcome

PFIS has broad, interdependent product work in one uncommitted working tree. The
executable inventory currently reports 328 changed or untracked files. The count
may move as generated test artifacts appear or disappear; the enforced invariant
is that every current file has one packet owner. No file is to be reset, deleted,
committed, or moved merely to make the tree look clean.

This inventory gives every changed file exactly one integration owner through
the ordered first-match rules below. It is an integration plan, not evidence
that the represented capabilities are production-ready. Report 15 remains the
canonical score and execution roadmap.

## Baseline evidence

| Check | Result | Meaning |
| --- | --- | --- |
| Expanded changed-file inventory | 328 current files; zero unassigned | `scripts/check_worktree_inventory.py` expands untracked directories and applies the same ordered ownership rules used by this document. |
| Alembic revision topology and runtime parity | Developer database and local `pfis_e2e` database reach `053_deposit_statement_ledger`; fresh PostgreSQL parity passed through 052 and remains a CI release gate for 053 | The E2E database was originally found at 017 and upgraded through the linear chain; both named local databases now include the additive deposit-statement tables. |
| Migration and financial-position focus | 45 passed | Migration discipline, HDFC extraction, card runway/refund tracking, balance reconciliation, balance forecast, and card API serialization passed. |
| Frontend unit tests | 30 files, 77 tests passed | Current React behavior is internally consistent under Vitest. |
| Frontend production build | Passed | TypeScript and Vite production compilation completed. |
| Full backend suite | 512 passed, 2 skipped | The integrated suite covers card recurring-charge candidates, the refund tracker, and the user-timezone paid-bill observation correction; no backend failures remain. |

The parity result covers the current local PostgreSQL environment. CI must still
repeat the fresh and E2E upgrades from committed migration files before a
release claim; local parity is not hosted-release evidence.

## Ordered integration packets

Rules are evaluated from IR-0 through IR-6. The first matching rule owns the
file, so shared hotspots have one landing owner rather than several competing
owners. Counts reflect the latest executable inventory run and can change as
generated files appear or disappear; zero unassigned is the enforced gate.

| Packet | Files | Capability boundary | Dependency | Landing proof |
| --- | ---: | --- | --- | --- |
| IR-0 | 38 | Measurement, release, operations, CI, API smoke, generated browser evidence, and audit control | None | Scorecard output is deterministic; API contracts and release checks are callable; this inventory validates with zero unassigned files. |
| IR-1 | 44 | Source records, Gmail, classification, parsers, statement extraction, and ingestion | IR-0 | Parser/classifier corpus and ingestion safety pass; unsupported statement formats fail closed; no raw secrets or document bytes appear in evidence artifacts. |
| IR-2 | 51 | Ledger, accounts, transaction lifecycle, ownership, deletion/retention, and portable export | IR-0, then IR-1 contracts | Account/transaction invariants, ownership, dedup, transfer, deletion, and export checks pass; migrations 018-029 plus compatibility revisions are reversible and data-safe. |
| IR-3 | 44 | Temporal knowledge, anomalies, forecasts, recommendations, and roadmap intelligence | IR-2 | Cutoff-safe tests pass; immutable histories/outcomes remain append-only; release evidence remains deferred when representative cohorts are missing. |
| IR-4 | 39 | Financial position, balance observations, reconciliation, provider mapping, statement-ledger evidence, card runway, refund tracking, and next-statement projection | IR-1 and IR-2 | Local PostgreSQL tracks reach migration 053; position/reconciliation/card/deposit/projection/refund checks pass; incomplete or ambiguous coverage blocks consequential guidance. |
| IR-5 | 103 | Cross-domain backend/API integration and the React product experience | IR-1 through IR-4 | Backend suite, frontend lint/tests/build, browser task flows, accessibility, API docs, and bundle gates pass against the integrated contracts. |
| IR-6 | 9 | Remaining canonical product, architecture, data, security, deployment, and UX documentation | IR-5 | Documents match the landed API/model/runtime behavior and do not promote fixture-only or estimated capability as live/verified. |

## First-match ownership rules

### IR-0 — measurement and integration control

- `.github/workflows/ci.yml`, `.github/mcp.json`, `.vscode/mcp.json`,
  `Makefile`, and `scripts/**`;
- `docs/audit/**`;
- `tests/pytest/test_release_gates.py`;
- `backend/app/observability.py`, `backend/app/api/routes/health.py`, and
  `backend/app/schemas/operational.py`.

### IR-1 — source and ingestion truth

- `tests/parser_corpus/**` and the reviewed de-identified HDFC deposit fixture;
- `backend/app/services/{classification,connectors,gmail,ingestion,parser}/**`;
- `backend/app/services/hdfc*_statement_extractor.py` and
  `backend/app/services/statement_detection.py`;
- `backend/app/models/{email,sync}.py`, `backend/app/api/routes/{gmail,jobs}.py`,
  and `backend/app/schemas/job.py`;
- migrations 030 and 042;
- pytest modules whose basename begins with `test_connector`, `test_gmail`,
  `test_ingestion`, `test_jobs`, `test_parser`, `test_pipeline`, or
  `test_hdfc_statement`;
- `docs/parser.md` and `docs/integrations.md`.

### IR-2 — ledger and lifecycle truth

- migrations 018-029 plus 034, 038, and 040;
- account, transaction, user, and workspace models/schemas and their account,
  auth, budget, transaction, and user routes;
- services beginning with `account_`, `transaction_`, or `retention_`, plus
  `portable_export_service.py`, `financial_clock.py`, `ledger_currency.py`,
  `auto_sync_service.py`, and `seed_service.py`;
- pytest modules beginning with `test_account`, `test_api_error`,
  `test_api_regression`, `test_auth`, `test_budgets`, `test_database`,
  `test_dedup`, `test_endpoints`, `test_portable_export`,
  `test_premium_workspace`, `test_raw_email_retention`, `test_transaction`, or
  `test_transfer`.

### IR-3 — temporal and decision intelligence

- migrations 031-033, 035-037, 039, and 041;
- anomaly, forecast, knowledge, roadmap, and temporal-history models;
- guidance, intelligence, roadmap, and temporal schemas;
- analytics, guidance, insights, knowledge, and roadmap routes;
- services beginning with `anomaly_`, `forecast_`, `guidance_`, `insights_`,
  `intelligence_`, `recommendation_`, `roadmap_`, or `temporal_`, plus
  `backend/app/services/knowledge/**`;
- pytest modules beginning with `test_anomaly`, `test_forecast`, `test_insights`,
  `test_intelligence`, `test_knowledge`, `test_recommendation`, `test_roadmap`,
  or `test_temporal`;
- `docs/feature-ideas-roadmap.md`.

### IR-4 — balance and card truth

- migrations 043-053;
- the financial-position model and balance-forecast/financial-position schemas;
- the financial-position route;
- services beginning with `balance_`, `card_`, `financial_position`, or
  `reconciliation_`;
- pytest modules beginning with `test_balance`, `test_card`, or
  `test_financial_position`;
- `docs/financial-position-roadmap-implementation.md`.

### IR-5 — integrated product and experience

- `frontend/**`;
- `backend/requirements.txt`;
- every remaining changed file under `backend/app/**`, `tests/pytest/**`, or
  `.github/**` not matched by IR-0 through IR-4.

Shared hotspots such as `backend/app/main.py`, model exports, API error
contracts, dashboard/report orchestration, frontend API/types, and the workspace
shell intentionally land here after their owning domain contracts stabilize.

### IR-6 — canonical documentation reconciliation

- every remaining changed file under `docs/**` not matched earlier.

## Landing order and stop conditions

```text
IR-0 -> IR-1 -> IR-2 -> IR-3
                    \-> IR-4
IR-3 + IR-4 -> IR-5 -> IR-6
```

Stop the landing sequence when any of these occurs:

- a packet depends on a model, migration, route, or schema still owned by a
  later packet;
- the clean PostgreSQL migration or ORM parity check fails;
- a user-ownership, sign, cutoff, duplicate, partial-write, or reconciliation
  invariant fails;
- a public API field must be removed or silently reinterpreted;
- a fixture-only, estimated, or provider-neutral capability is described as
  representative, observed, live, or production-ready;
- unrelated user work is discovered inside a packet.

## Next score-bearing vertical

After IR-0 through IR-4 have a controlled landing path, the next implementation
vertical is statement source recognition:

1. Add PDF-route and induced mid-import failure tests to prove zero partial
   persistence and no PDF-byte retention.
2. Add a statement-format registry that classifies institution, product, layout
   version, and confidence before opening the persistence transaction.
3. Keep the current HDFC credit-card adapter unchanged behind that registry.
4. Expand the HDFC deposit-account adapter only from reviewed, de-identified
   fixtures. The first exact profile now covers debit, credit, UPI, debit-card,
   ATM, transfer, opening/closing balance, and malformed/ambiguous cases;
   reversal/refund and broader layout cohorts remain evidence gaps.
5. Route normalized rows through the existing account ownership, fingerprint,
   review, and transaction services; never infer debit-card or UPI activity from
   a credit-card statement.

This vertical can raise implemented source coverage. It cannot raise the
evidence-backed intelligence score to 80-90 until representative cohorts,
provider truth, reconciliation intervals, matured forecasts, and outcome
evidence pass their non-compensating gates.
