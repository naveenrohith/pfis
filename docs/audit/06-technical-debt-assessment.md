# Report 6: Technical Debt Assessment

## Executive Summary

PFIS does not show the usual signs of a chaotic MVP. The technical debt is concentrated in predictable areas: growing pipeline orchestration, inline report rendering, local-first runtime assumptions, process-local background jobs, dual frontend direction, and future parser scalability. These are manageable if addressed before feature growth accelerates.

## Debt Register

| Item | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Monolithic pipeline orchestration | High | Parser evolution, bug risk | `backend/app/services/parser/pipeline.py` owns multiple stages | Extract stage functions and test them independently |
| Inline HTML report rendering | Medium | Maintainability, escaping risk | `backend/app/api/routes/reports.py` builds a full HTML page in Python strings | Move to templates or report renderer service |
| In-process background jobs | Medium | Reliability | `job_service.py` uses `asyncio.create_task` and `_active_tasks` | Use durable queue/worker for hosted or multi-user deployments |
| Local-first config | High for production | Security, operations | Default SQLite and dev secret are allowed for local use | Add production config validation |
| Static dashboard plus Svelte migration | Medium | UI duplication | `backend/app/static/` and `frontend/` coexist | Define migration outcome and retire duplicate UI paths |
| Broad generic parser fallback | Medium | Data quality | Registry maps many banks to fallback parser | Track fallback usage and require confidence review |
| Mixed schema paths | Medium | Schema drift | Alembic exists while startup create-all runs | Clarify migration policy |

## Strengths Reducing Debt Risk

- Tests already cover parsers, jobs, reports, insights, auth, budgets, config, and API regressions.
- Documentation exists before the codebase has grown too large.
- Quality tooling is configured in `pyproject.toml` and CI.
- Security and observability helpers are separated rather than scattered.
- The parser system has a clear contract.

## Dead Code and Redundancy Review

No obvious broad deletion should be performed as part of this audit. The repo already went through cleanup and the active dashboard assets are `dashboard-revamp.css` and `dashboard-revamp.js`. Future cleanup should use evidence:

- imports unused by Ruff
- files not referenced by routes, docs, tests, or static HTML
- stale frontend assets after the Svelte migration decision
- obsolete parser branches after fixture coverage confirms no use

## Recommended Solution

Address technical debt in this order:

1. Parser and pipeline boundaries.
2. Report rendering extraction.
3. Production configuration and migration discipline.
4. Durable job execution.
5. Frontend migration cleanup.
6. Type-check tightening.

This order reduces the highest product risk first without destabilizing the whole application.

## Migration Guidance

Technical debt work should be small and test-first. Do not combine parser changes, database changes, and UI changes in the same branch. Each cleanup should have a visible before/after signal: fewer responsibilities, better tests, clearer contracts, or removed unused code.

## Validation Strategy

- Run `make check` after code-impacting debt work.
- Use targeted parser, job, report, and auth tests for focused changes.
- Run `ruff check backend/app tests` before removing imports or files.
- Review `git diff` for accidental product behavior changes.

## Rollback Strategy

Keep debt-reduction commits small. If a refactor fails, revert only that commit and retain added regression tests when they describe correct behavior.

