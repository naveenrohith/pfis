# PFIS Modernization Implementation Plan

This document tracks implementation of the modernization audit. It is the phase-level execution companion for the audit reports under `docs/audit/`.

PFIS modernization must follow the project agent framework:

```text
PLANNER -> CODE -> TEST -> QUALITY -> REVIEW -> FIX
```

## Current Phase

Phase 3: Data Integrity and Migration Discipline.

Status: in progress. Phase 0, Phase 1, and Phase 2 implementation gates are complete.

Goal: keep local SQLite convenient while making Alembic the protected schema path for shared and production environments.

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
| 2 | Report and dashboard boundary cleanup | Report renderer extraction complete |
| 3 | Data integrity and migration discipline | Alembic baseline parity test added |
| 4 | Reliability and operations | Job error classification complete |
| 5 | Production hardening | Production config validation complete |
| 6 | Connector platform expansion | SourceRecord contract complete |

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
