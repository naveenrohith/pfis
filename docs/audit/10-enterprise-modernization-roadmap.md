# Report 10: Enterprise Modernization Roadmap

## Executive Summary

PFIS should modernize through phased stabilization, not a rewrite. The current architecture is strong enough to evolve. The roadmap should protect parser correctness, clarify frontend direction, improve production posture, and add operational reliability in sequence.

> Progress (verified 2026-06-30): Phase 0 (baseline) and Phase 1 (pipeline
> stabilization) are complete. Phase 2 report extraction and most of Phase 3
> (migration discipline) and Phase 5 (production config) are complete. Remaining
> focus: Phase 2 frontend canonicalization, Phase 4 durable jobs/metrics, and
> Phase 6 connector integration.

## Evidence Base

- `backend/app/main.py` shows the current API, middleware, static dashboard, and route registration boundaries.
- `backend/app/services/parser/pipeline.py` shows the raw-email-to-transaction workflow that needs staged hardening.
- `backend/app/services/job_service.py` shows in-process background task orchestration.
- `backend/app/config.py` shows local-first SQLite and development-secret defaults.
- `.github/workflows/ci.yml` shows the existing lint, format, mypy, pytest, and coverage gate.
- `docs/README.md` confirms `docs/` is the source of truth.

## Strengths to Preserve

- Route/service/model/schema separation is already useful.
- Parser contracts and regression tests give modernization work a safety net.
- Raw-email retention and parse-failure records support reprocessing.
- CI already exists and should remain the baseline gate.

## Key Risks

| Risk | Severity | Impact | Recommendation |
| --- | --- | --- | --- |
| Roadmap work becomes a rewrite | High | Regression risk | Keep changes phased and behavior-preserving |
| Parser changes ship without fixtures | High | Data quality | Require parser regression tests before parser changes |
| Production hardening mixes with local UX | Medium | Developer friction | Keep local/demo and production profiles explicit |
| Frontend migration stays unresolved | Medium | Duplicate work | Decide the canonical UI during Phase 2 |

## Phase 0: Baseline Protection

Objective: make current behavior measurable and hard to regress.

Affected subsystems:

- tests
- docs
- parser fixtures
- CI

Work:

- Keep `make check` as the local quality gate.
- Add parser fixtures for each known sender/bank variant.
- Document expected local mode behavior.
- Keep audit reports as modernization planning input.

Validation:

- CI passes.
- Parser regression tests cover known formats.
- Docs reflect current architecture.

Rollback:

- Revert only failing test/doc additions that are proven incorrect.

Success criteria:

- No modernization phase starts without a passing baseline.

## Phase 1: Pipeline Stabilization

Objective: reduce parser pipeline risk.

Affected subsystems:

- `backend/app/services/parser/pipeline.py`
- `backend/app/services/parser/registry.py`
- `backend/app/services/parser/normalizer.py`
- `tests/pytest/test_parser_*`
- `tests/pytest/test_jobs_pipeline.py`

Work:

- Extract classify, parse, enrich, normalize, persist, and failure-handling stages.
- Preserve `ParseResult` as the parser output contract.
- Add tests around each stage.
- Track fallback parser usage.

Validation:

- Parser regression and edge-case tests pass.
- Jobs pipeline tests pass.
- Existing transaction outputs remain compatible.

Rollback:

- Keep previous end-to-end pipeline behavior available until stage tests pass.

Success criteria:

- New parser support can be added without editing unrelated pipeline stages.

## Phase 2: Report and Dashboard Boundary Cleanup

Objective: make reporting and UI easier to evolve.

Affected subsystems:

- `backend/app/api/routes/reports.py`
- `backend/app/static/`
- `frontend/`
- report tests

Work:

- Move report HTML generation to template or renderer helpers.
- Keep CSV export behavior unchanged.
- Decide and document whether static dashboard or Svelte is canonical.
- Avoid duplicate data aggregation in frontend code.

Validation:

- `pytest tests/pytest/test_reports.py`
- endpoint smoke tests
- manual dashboard check in local mode

Rollback:

- Restore route-owned rendering if template extraction changes output unexpectedly.

Success criteria:

- Report presentation can change without touching database query logic.

## Phase 3: Data Integrity and Migration Discipline

Objective: prepare the data layer for reliable growth.

Affected subsystems:

- SQLAlchemy models
- Alembic migrations
- `backend/app/database.py`
- data model docs

Work:

- Clarify create-all as local/demo behavior.
- Require Alembic for shared environments.
- Add constraints and indexes where justified by tests and query patterns.
- Review duplicate override workflow.

Validation:

- migration applies cleanly
- model tests pass
- dedup tests pass

Rollback:

- Use reversible migrations or documented restore scripts.

Success criteria:

- Schema changes are explicit, reviewed, and test-backed.

## Phase 4: Reliability and Operations

Objective: make jobs and syncs safe beyond local use.

Affected subsystems:

- `backend/app/services/job_service.py`
- Gmail sync services
- observability
- health checks

Work:

- Add structured job metrics.
- Define retry categories.
- Add credential health checks.
- Move to durable worker/queue when hosted deployment is planned.

Validation:

- job tests pass
- failure injection tests pass
- restart behavior is verified for durable jobs

Rollback:

- Keep local in-process job runner for development mode.

Success criteria:

- Jobs survive process restarts in the production profile.

## Phase 5: Production Hardening

Objective: make PFIS deployable safely.

Affected subsystems:

- configuration
- security
- database
- deployment docs
- CI

Work:

- Require non-default secrets for production.
- Define production database settings.
- Add backup and restore documentation.
- Add deployment checklist and monitoring checklist.
- Tighten mypy module by module.

Validation:

- production config validation fails closed
- security tests pass
- CI remains green

Rollback:

- Keep local/demo config path separate from production config.

Success criteria:

- PFIS can be deployed with known secrets, database, health, backup, and monitoring controls.

## Phase 6: Connector Platform Expansion

Objective: evolve from Gmail-first to connector-driven ingestion.

Affected subsystems:

- Gmail services
- parser pipeline
- models
- docs

Work:

- Define source record contract.
- Support new connectors by producing parser-compatible records.
- Avoid source-specific transaction creation paths.
- Add source-specific parser fixtures.

Validation:

- each connector has end-to-end fixture tests
- parser and dedup tests remain stable

Rollback:

- Disable connector registration without removing parser core.

Success criteria:

- New sources can be added without duplicating the finance pipeline.

## Migration Guidance

Run phases in order unless a production deployment date forces Phase 5 earlier. Do not combine parser restructuring, database migrations, frontend migration, and job-runner changes in one branch. Each phase should produce tests, docs, and a rollback path before the next phase starts.

## Overall Validation Strategy

- `make check` before merging each phase.
- Targeted parser tests for parser and connector work.
- Targeted report tests for report rendering changes.
- Targeted job tests for background-processing changes.
- Migration review for schema changes.

## Overall Rollback Strategy

Use small commits and preserve public API behavior. If a phase fails, revert that phase only, keep any useful tests, and re-enter the roadmap at the last passing phase.
