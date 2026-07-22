# PFIS Modernization Implementation Plan

This document tracks implementation of the modernization audit. It is the phase-level execution companion for the audit reports under `docs/audit/`.

PFIS modernization must follow the project agent framework:

```text
PLANNER -> CODE -> TEST -> QUALITY -> REVIEW -> FIX
```

## Current Phase

Phase 16: Pipeline failure privacy.

Status: complete. All repository-owned modernization phases are implemented and
validated. Phase 16 removes raw pipeline exception text from responses, logs,
per-record results, and durable parse-failure messages while retaining stable
error categories and exception types.

Goal: keep modernization work phased, tested, and reversible while preserving the local/demo developer path.

## Phase 0 Acceptance Criteria

- Current parser behavior is protected by regression fixtures.
- Existing test baseline is confirmed, or environment blockers are documented.
- Local validation commands are documented.
- No runtime behavior changes are introduced.
- Future parser/pipeline refactors must start from this baseline.

## Phase Order

| Phase | Focus | Status |
| --- | --- | --- |
| 0 | Baseline protection | Complete |
| 1 | Parser pipeline stabilization | Conservative helper extraction complete |
| 2 | Report and dashboard boundary cleanup | Report renderer extraction and frontend ownership docs complete |
| 3 | Data integrity and migration discipline | Alembic baseline parity test added |
| 4 | Reliability and operations | Job error classification and operational health counters complete |
| 5 | Production hardening | Production config validation and deployment runbook complete |
| 6 | Connector platform expansion | SourceRecord contract complete |
| 9 | Parser pipeline observability and replay | Complete |
| 10 | Financial accounts and cached monthly summaries | Complete |
| 11 | Coverage enforcement and ingestion privacy | Complete |
| 12 | Realtime channel security and backpressure | Complete |
| 13 | Gmail token lifecycle and provider contracts | Complete |
| 14 | Financial account, currency, budget, and transfer invariants | Complete |
| 15 | Paired-transfer mutation and deletion integrity | Complete |
| 16 | Pipeline failure privacy and stable errors | Complete |

## Phase 0 Scope

Allowed work:

- Add or strengthen tests for existing parser and classifier behavior.
- Document local validation commands and known environment requirements.
- Run quality scans from `agents/QUALITY.md`.

Out of scope:

- Refactoring `backend/app/services/parser/pipeline.py`.
- Changing parser extraction rules.
- Changing route behavior.
- Adding external dependencies.
- Introducing durable queue or production infrastructure.

## Validation Commands

Preferred PowerShell commands from the repo root:

```powershell
New-Item -ItemType Directory -Force .test-run | Out-Null; $env:TEMP=(Resolve-Path .test-run).Path; $env:TMP=(Resolve-Path .test-run).Path; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .test-run\pytest tests\pytest\test_parser_regression.py tests\pytest\test_parser_edge_cases.py
New-Item -ItemType Directory -Force .test-run | Out-Null; $env:TEMP=(Resolve-Path .test-run).Path; $env:TMP=(Resolve-Path .test-run).Path; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .test-run\pytest
```

Use the repo-local `.test-run` override when the default Windows user temp directory is not writable in the managed environment. The cache provider is disabled in that command to avoid ACL-blocked `.pytest_cache` writes.

## Quality Commands

```powershell
git status --short --branch
git ls-files | rg "(__pycache__|\.pyc$|\.db$|\.db-journal$|dashboard\.css$|dashboard\.js$)"
rg -n "TODO|FIXME|copy-paste|Vendor\s+Invoice|Spring\s+Boot|Java\s+21|com[.]siemens|U\s*B\s*M|repeat[_-]until[_-]found" agents docs .github backend tests
```

## Phase 1 Entry Criteria

Phase 1 can start only after Phase 0 parser regression and edge-case tests pass, or after any environment-only blocker is documented with the exact failing command.

Completed Phase 1 stabilization work:

- Extract named internal parser pipeline stages without changing route behavior.
- Preserve transaction persistence through `TransactionService`.
- Add parser metadata to per-email pipeline results for parser version and generic fallback visibility.
- Cover stored, duplicate, invalid-parse, parser fallback, and parser version result paths with regression tests.

Remaining Phase 1 follow-up:

- Consider deeper pipeline stage objects only if future parser or connector work needs them.
- Keep additional extraction behavior behind regression fixtures.

## Phase 3 Acceptance Criteria

- Local/demo startup may continue to use SQLAlchemy `create_all` for convenience.
- Shared and production environments must use Alembic as the schema control path.
- ORM model changes must update Alembic migrations in the same change set.
- Deduplication and ownership behavior must remain covered before schema edits.
- Migration parity is guarded by `tests/pytest/test_migration_discipline.py`.

## Phase 4 Acceptance Criteria

- Job failure categories are persisted in job results.
- Operational health exposes non-secret runtime posture and job status counters.
- Real Gmail calls remain excluded from tests.
- Database-backed job leases, retries, idempotency, and restart recovery protect
  hosted background work without requiring a separate broker.

## Phase 5 Acceptance Criteria

- Production mode fails closed for unsafe secret, auth, database, or CORS settings.
- Local/demo mode remains simple and keeps SQLite available.
- Deployment, backup, restore, and monitoring expectations are documented.

## Phase 6 Acceptance Criteria

- Future connectors use `SourceRecord` rather than duplicating transaction creation.
- Gmail remains the first connector and current behavior remains unchanged.
- Connector fixture tests protect the source-record contract.

## Deployment-Owned Decisions

- Production database provider, backup schedule, and restore-drill ownership.
- Hosted log/metrics platform and alert routing.
- TLS termination, network policy, and infrastructure scaling policy.

These are release gates rather than unfinished source phases. They require the
selected production provider and named operational owners; source code cannot
truthfully provision or certify them.

## Phase 10 Acceptance Criteria

- Financial account records contain only masked account metadata and remain user-scoped.
- Existing transactions backfill to a nullable `financial_account_id` without reconstructing full account numbers.
- New transactions reuse the inferred financial account from their existing last-four metadata.
- Monthly dashboard/report summaries persist after their first calculation and are invalidated by transaction mutations.
- Dashboard feature sections load as users approach them, keeping the overview bundle small.
- Cached aggregates and durable database-backed jobs remain compatible with the
  local developer profile and a multi-replica PostgreSQL deployment.

## Phase 11 Acceptance Criteria

- Backend CI measures statement and branch coverage and rejects regressions below 70%.
- Ingestion validates user and source ownership inside the service boundary.
- A source record and its stored event are handled atomically per record.
- Connector and job failures persist, audit, and broadcast stable public errors;
  provider exception text is restricted to non-secret classifications.
- Ownership, rollback, duplicate, and exception-privacy failure paths have
  regression tests.

## Phase 12 Acceptance Criteria

- Production WebSocket upgrades require an explicitly allowed HTTPS origin and
  a revocable session cookie; credentials in query strings are rejected.
- Per-user connection and inbound-frame limits are configuration-bounded.
- Broadcasts send concurrently with a timeout so one slow client cannot block
  other users or sockets.
- Disconnect, cross-user, origin, session, capacity, frame-size, slow-client,
  and connection-establishment behavior has regression coverage.

## Phase 13 Acceptance Criteria

- Gmail access-token expiry is persisted through a reversible migration and
  used for proactive refresh; legacy rows refresh once when expiry is unknown.
- Repeated Gmail page tokens terminate safely instead of looping indefinitely.
- Malformed individual messages produce non-secret record failures without
  swallowing retryable or credential-wide provider failures.
- Demo sync rolls back partial email storage and persists only a stable failure
  category when a batch fails.
- OAuth, migration, pagination, token refresh, message isolation, and rollback
  behavior is protected by offline regression tests.

## Phase 9 Acceptance Criteria

- Parser behavior remains protected by regression fixtures before extraction rules change.
- Parser stages are explicit: prepare, classify, parse, validate, normalize, identity, persist, events, metrics.
- `ParseResult` keeps existing public fields and adds optional per-field confidence, validation, parser, pattern, confidence, and normalization metadata.
- Parse failures act as a DLQ with non-secret diagnostic metadata; raw email bodies remain only in `raw_emails`.
- Pipeline events are persisted for source preparation, classification, parsing, validation failure, normalization, duplicate detection, transaction creation, retry, and replay.
- Replay supports dry-run comparison without mutating transactions.
- No external queue, broker, or AI parser is introduced in this phase.

## Phase 9 Validation Commands

```powershell
New-Item -ItemType Directory -Force .test-run | Out-Null; $env:TEMP=(Resolve-Path .test-run).Path; $env:TMP=(Resolve-Path .test-run).Path; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .test-run\pytest tests\pytest\test_parser_regression.py tests\pytest\test_parser_edge_cases.py tests\pytest\test_jobs_pipeline.py tests\pytest\test_pipeline_phase9.py
New-Item -ItemType Directory -Force .test-run | Out-Null; $env:TEMP=(Resolve-Path .test-run).Path; $env:TMP=(Resolve-Path .test-run).Path; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider --basetemp .test-run\pytest
```
