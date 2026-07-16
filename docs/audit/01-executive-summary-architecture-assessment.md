# Report 1: Executive Summary and Architecture Assessment

## Executive Summary

PFIS is a Personal Finance Intelligence System that ingests financial emails, classifies and parses transaction content, normalizes merchants, deduplicates transactions, stores them through async SQLAlchemy models, and exposes insights, budgets, reports, and dashboard workflows through FastAPI.

The repository is beyond prototype stage. It has a real layered structure, a parser subsystem, Gmail integration, background jobs, authentication helpers, request-id logging, rate limiting, tests, and documentation. The correct classification is structured MVP, not production candidate.

The strongest architectural decision is the separation of HTTP routes, services, parser components, ORM models, schemas, and documentation. The largest risk is that parser, normalization, deduplication, reporting, and insight logic will become tightly coupled as the product grows.

## Product Maturity

Current maturity: 3 out of 5, structured MVP.

Evidence:

- `backend/app/main.py` registers isolated route modules for auth, Gmail, pipeline, jobs, transactions, categories, insights, budgets, and reports.
- `backend/app/services/parser/` contains parser contracts, registry, pipeline, patterns, normalizer, and bank parsers.
- `backend/app/services/gmail/` separates OAuth, sync, filtering, and demo data.
- `docs/README.md` declares `docs/` as the source of truth.
- `.github/workflows/ci.yml` runs Ruff, Black check, mypy, pytest, and coverage.
- `README.md` explicitly states local/single-user use and marks production hardening out of scope for now.

## Architecture Assessment

The current architecture is layered:

```text
Client or dashboard
  -> FastAPI routes
  -> service layer
  -> parser, Gmail, insights, reports, jobs
  -> async SQLAlchemy models
  -> SQLite by default
```

The intended product architecture should evolve toward:

```text
Connectors
  -> ingestion records
  -> background jobs or queue
  -> parser registry
  -> normalization and categorization
  -> transaction persistence
  -> insights, budgets, reports, exports
  -> dashboard and APIs
```

PFIS already has the first version of this flow in `backend/app/services/parser/pipeline.py`, but it still runs as an in-process flow and commits inside batch loops.

## Strengths

- Clear module boundaries: routes are under `backend/app/api/routes`, services under `backend/app/services`, models under `backend/app/models`, and schemas under `backend/app/schemas`.
- Parser isolation: `BaseParser`, `ParseResult`, `ParserRegistry`, `GenericParser`, and bank-specific parsers keep extraction away from HTTP handlers.
- Traceability: raw emails, parse failures, sync runs, parser version fields, confidence scores, and correction history are modeled.
- Security baseline: `backend/app/security.py` includes password hashing, JWT helpers, token encryption, optional auth, and ownership helpers.
- Observability baseline: `backend/app/observability.py` injects request ids into log records and `backend/app/main.py` returns `X-Request-ID`.
- Quality baseline: tests live under `tests/pytest`, and CI runs lint, format check, type check, tests, and coverage.

## Weaknesses and Risks

| Risk | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Parser and business rules can become coupled | High | Maintainability, scalability | `pipeline.py` performs classification, parsing, inference, normalization, dedup, storage, and failure handling | Split pipeline stages behind explicit interfaces before adding more connectors |
| Production posture is incomplete | High | Security, deployment readiness | `README.md` says local/single-user; SQLite default; default dev secret warning in `config.py` | Add production profile, secrets policy, deployment docs, and database migration controls |
| Background jobs are in-process | Medium | Reliability | `job_service.py` stores active tasks in process memory | Introduce a durable worker/queue before multi-user or hosted use |
| Reports route builds HTML by string concatenation | Medium | Maintainability, safety | `backend/app/api/routes/reports.py` creates large inline HTML | Move report rendering to templates or reusable view helpers |
| Static dashboard and Svelte migration coexist | Medium | Product direction | `backend/app/static/` is served while `frontend/` is in migration | Define frontend ownership and migration completion criteria |

## Readiness Scores

| Category | Score |
| --- | ---: |
| Architecture | 8 |
| Code organization | 8 |
| Separation of concerns | 8 |
| Parser foundation | 7 |
| Data model | 7 |
| Security baseline | 6 |
| Observability | 5 |
| Testing | 7 |
| Documentation | 8 |
| Production readiness | 4 |
| Overall | 7 |

## First Recommendations

1. Keep the current layered architecture, but introduce explicit connector and pipeline stage contracts before adding SMS, PDFs, bank APIs, or AI-assisted parsing.
2. Treat parser regression tests as product-critical tests. Every parser behavior change should include a sample input and expected `ParseResult`.
3. Convert the reports HTML endpoint to a template-based implementation before expanding report complexity.
4. Decide whether the static dashboard or Svelte app is the primary frontend target and document the migration end state.
5. Add production hardening as a roadmap phase, not as incidental fixes.

## Validation Strategy

- Use `pytest tests/pytest/test_parser_regression.py` for parser safety.
- Use `pytest tests/pytest/test_jobs_pipeline.py` for ingestion and pipeline behavior.
- Use `pytest tests/pytest/test_auth_security.py` for security changes.
- Use `make check` before merging modernization work.

## Rollback Strategy

Architecture changes should be phased behind existing API contracts. For each modernization phase, preserve the current route behavior, add tests first, and keep the previous service path available until the replacement path is validated.

