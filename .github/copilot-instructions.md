# Copilot Instructions - PFIS

You are working in PFIS, the Personal Finance Intelligence System.

Before making non-trivial changes:

1. Read `agents/AGENTS.md`.
2. Read `agents/CONTEXT.md`.
3. Read the relevant files in `docs/`.
4. Inspect existing code before proposing APIs, models, or behavior.

Follow the agent sequence:

PLANNER -> CODE -> TEST -> QUALITY -> REVIEW -> FIX

Skip FIX only when REVIEW finds no issues.

## Project Context

- Backend: FastAPI/Python under `backend/app`.
- Database: async SQLAlchemy models and `AsyncSession`.
- API routes: `backend/app/api/routes`, mounted under `/api`.
- Services: Gmail sync, parser pipeline, transaction service, insights, jobs, reports.
- Frontend: canonical React/Vite app under `frontend/`; `backend/app/static` is a no-build fallback.
- Tests: pytest under `tests/pytest`.
- Core pipeline: raw email -> classify -> parse -> normalize -> categorize -> deduplicate -> store -> insights/dashboard/reports.

## Source Of Truth

Use `docs/` as the source of truth:

- `docs/architecture.md`
- `docs/data_model.md`
- `docs/data-models.md`
- `docs/workflows.md`
- `docs/security.md`
- `docs/api-reference.md`
- `docs/integrations.md`
- `docs/parser.md`
- `docs/testing.md`

If a detail is not in docs or existing code, do not invent it. State the missing context.

## Rules

- Preserve user data ownership checks.
- Never log or expose credentials, tokens, passwords, OAuth codes, or full raw email bodies.
- Keep parser changes deterministic and covered by regression tests.
- Keep route behavior aligned with schemas and docs.
- Use existing services before adding abstractions.
- Do not add new dependencies without a clear reason.
- Do not copy Java/Spring/vendor-invoice rules into PFIS.
- Run QUALITY checks for redundant code, dead files, stale imports, and copied project references before REVIEW.
- For UI/UX work, read `agents/UI_UX.md` and `docs/ui-ux-masterplan.md`.
- Use the official shadcn MCP registry for component discovery, then apply PFIS accessibility,
  dependency, performance, and privacy gates before adopting registry output.

## Required Response Shape For Non-Trivial Work

Use a concise version of:

### PLANNER
- Scope, affected files, risks, tests

### CODE
- Implementation summary

### TEST
- Commands run and result

### QUALITY
- Redundant code/files removed or deferred

### REVIEW
- Issues found or no issues found

### FIX
- Corrections applied, or skipped because review passed
