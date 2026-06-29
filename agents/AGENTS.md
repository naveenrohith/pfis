# PFIS Agents - Master Orchestration Guide

PFIS uses an agent-based workflow so Copilot and coding agents make changes in a consistent order. The workflow is project-specific to the Personal Finance Intelligence System and must not inherit rules from other repositories.

## Execution Order

Before starting any non-trivial task, read [CONTEXT.md](CONTEXT.md) and the relevant files in `docs/`.

| # | Agent | File | Responsibility |
|---|-------|------|----------------|
| 1 | PLANNER | [PLANNER.md](PLANNER.md) | Analyze the request, affected modules, risks, and tests |
| 2 | CODE | [CODE.md](CODE.md) | Implement focused changes using PFIS conventions |
| 3 | TEST | [TEST.md](TEST.md) | Add or update deterministic pytest coverage |
| 4 | QUALITY | [QUALITY.md](QUALITY.md) | Detect redundant code, dead files, duplication, and maintainability drift |
| 5 | REVIEW | [REVIEW.md](REVIEW.md) | Validate architecture, security, data ownership, and regressions |
| 6 | FIX | [FIX.md](FIX.md) | Repair review/test failures and re-run validation |

If REVIEW finds no issues, FIX may be skipped. TEST and QUALITY must still run for code changes unless the environment blocks them.

## Source Of Truth

- `docs/` is the source of truth for architecture, data models, workflows, API behavior, integrations, and security.
- Existing code is the source of truth for exact class, function, schema, and route names.
- If documentation and code disagree, inspect code and either align the change to code or update the relevant doc in the same task.
- Do not invent routes, models, config keys, or parser behavior.

## PFIS Technical Identity

- Backend: Python FastAPI application under `backend/app`.
- Database: async SQLAlchemy models with `AsyncSession`; SQLite in local development, PostgreSQL-compatible design for production.
- API: routers under `backend/app/api/routes`, mounted with `/api`.
- Services: Gmail sync, parser pipeline, transaction service, insights, jobs, seed data.
- Frontend: static dashboard served by FastAPI from `backend/app/static`.
- Tests: pytest suite under `tests/pytest` with `pytest.ini` pointing there.
- Core pipeline: Gmail/raw email -> classify -> parse -> normalize -> categorize -> deduplicate -> store transaction -> insights/reports/dashboard.

## Core Rules

1. Follow PLANNER -> CODE -> TEST -> REVIEW -> FIX for non-trivial tasks.
2. Run QUALITY before REVIEW when code, tests, docs, or file structure changes.
3. Keep changes minimal and scoped to the requested workflow.
4. Preserve user data ownership using `resolve_user_scope`, `get_current_user_optional`, and `ensure_user_owns_resource`.
5. Use async SQLAlchemy APIs correctly; do not add blocking calls inside async request paths unless wrapped appropriately.
6. Never log access tokens, refresh tokens, passwords, OAuth codes, full email bodies, or other secrets.
7. Parser changes must include regression tests with representative email samples.
8. API changes must update `docs/api-reference.md`, schemas when applicable, and tests.
9. Data model changes must update SQLAlchemy models, migrations when present, `docs/data_model.md`, and tests.
10. Frontend changes must preserve dashboard workflows and avoid unsafe `innerHTML` with unescaped server data.
11. Do not introduce new frameworks or external dependencies without explicit need and documentation.

## Prohibited Actions

- Do not copy Java/Spring/vendor-invoice assumptions into PFIS.
- Do not bypass the service layer for business rules that already live in services.
- Do not skip ownership checks on user-scoped resources.
- Do not store secrets in committed files.
- Do not make parser logic less deterministic without tests.
- Do not remove existing public routes, schema fields, or config keys unless explicitly requested.
- Do not mutate unrelated dirty worktree files.

## Completion Criteria

A task is complete only when:

- The implementation matches the relevant `docs/` contract.
- Tests were added or updated when behavior changed.
- QUALITY found no unresolved redundant/dead-code issue in touched areas.
- Validation was run, or an environment blocker is reported clearly.
- REVIEW found no unresolved issues.
- Documentation was updated when API, workflow, data model, or security behavior changed.
