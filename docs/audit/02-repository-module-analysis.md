# Report 2: Repository and Module Analysis

## Executive Summary

PFIS has a clean repository structure for its current size. The backend is organized around FastAPI routes, services, models, schemas, static assets, and docs. Tests are centralized under `tests/pytest`. The main repository-level gap is not chaos; it is that the project has two frontend directions and no dedicated infrastructure/deployment layer yet.

## Repository Structure

Evidence:

- `backend/app/main.py` is the FastAPI entrypoint.
- `backend/app/api/routes/` contains route modules for auth, budgets, categories, Gmail, health, insights, jobs, pipeline, reports, transactions, and users.
- `backend/app/services/` contains transaction, seed, insights, job, Gmail, and parser services.
- `backend/app/models/` contains user, transaction, sync, email, and category models.
- `backend/app/static/` contains the served dashboard.
- `frontend/` contains the Svelte/Vite migration.
- `docs/` contains architecture, parser, data model, security, testing, workflow, and extension docs.
- `tests/pytest/` contains API, parser, job, insight, report, budget, auth, config, and dedup tests.

## Strengths

- The root `README.md` explains stack, quick start, commands, layout, and production-hardening caveats.
- `docs/README.md` acts as a documentation index and explicitly states what is out of scope.
- Test layout is separate from application code and is already recognized by `pytest.ini`.
- CI mirrors local quality gates with lint, format check, mypy, pytest, and coverage.
- Alembic exists under `backend/alembic`, which gives the project a migration path even though startup also calls `Base.metadata.create_all`.

## Weaknesses and Risks

| Issue | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Dual frontend direction | Medium | Product focus, duplicated UI work | `backend/app/static/` is active and `frontend/` is in migration | Define which UI is canonical and keep the other as migration-only |
| Infrastructure layer is not explicit | Medium | Deployment readiness | No deployment directory or production runtime profile is present | Add deployment docs and config profile before hosted use |
| Documentation is broad but not audit-oriented | Low | Planning | Existing docs describe system behavior, not modernization sequencing | Keep this audit under `docs/audit/` and link it from future planning docs if desired |
| Migrations and startup table creation coexist | Medium | Schema control | `database.py` has `init_db()` create-all and Alembic exists | Keep create-all for local demo only; use Alembic for controlled environments |

## Module Boundary Review

The route-to-service split is healthy. Route modules should remain thin and should not start owning parser rules, SQL-heavy aggregations, or report rendering details.

The service layer is becoming the main pressure point. `TransactionService`, `InsightsService`, `job_service`, Gmail services, and parser services already represent distinct concerns. As PFIS grows, the next boundary should be by domain workflow:

- ingestion and connectors
- parsing and extraction
- normalization and categorization
- transactions and corrections
- insights and reporting
- operations and background jobs

## Recommended Solution

Maintain the current layout for short-term work, but introduce new packages only when a real boundary is crossed. Avoid a broad directory reshuffle before tests are stronger. The best next repository-level additions are:

- `docs/audit/` for modernization analysis.
- A future `docs/adr/` for architecture decisions.
- A future production/deployment guide once the target runtime is known.

## Migration Guidance

1. Keep existing imports and public route paths stable.
2. Add new abstractions under existing service packages first.
3. Move modules only after tests prove behavior and the new boundary is established.
4. When frontend migration resumes, choose one primary UI and document the retirement path for the other.

## Validation Strategy

- `make check` for full local quality.
- `pytest tests/pytest/test_endpoints_smoke.py` for route availability.
- `pytest tests/pytest/test_api_regression.py` for API regressions.
- Static review of `docs/README.md`, `README.md`, and `.github/workflows/ci.yml` after docs changes.

## Rollback Strategy

Repository-level changes should be additive first. If a module move causes regressions, revert the move and keep extracted interfaces or tests that remain useful.

