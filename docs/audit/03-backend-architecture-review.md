# Report 3: Backend Architecture Review

## Executive Summary

The PFIS backend is well structured for a FastAPI MVP. It uses isolated routers, async SQLAlchemy sessions, service modules, settings validation, request-id logging, rate limiting, optional authentication, and typed schemas. The main modernization need is to keep business workflows out of routes and prevent the service layer from turning into a mixed orchestration layer.

## Current Backend Shape

Evidence:

- `backend/app/main.py` creates the FastAPI app, installs middleware, mounts static assets, and includes routers.
- `backend/app/config.py` centralizes settings through Pydantic settings.
- `backend/app/database.py` owns async engine, session factory, declarative base, and database lifecycle helpers.
- `backend/app/security.py` owns JWT, password hashing, encryption, auth dependency, user scope resolution, and ownership checks.
- `backend/app/rate_limit.py` owns the shared SlowAPI limiter.
- `backend/app/observability.py` owns request-id logging.

## Strengths

- Route registration is explicit and readable.
- CORS configuration is settings-driven.
- Request ids are surfaced through response headers and logs.
- Auth can run in optional local/demo mode or required mode.
- Secrets stored for Gmail can be encrypted through `encrypt_secret`.
- The service layer keeps most business logic out of routes.
- CI includes mypy even if non-blocking, which gives a path toward stronger typing.

## Weaknesses and Risks

| Issue | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| App startup creates tables | Medium | Migration discipline | `init_db()` calls `Base.metadata.create_all` | Keep for local demo, but require Alembic for shared environments |
| Optional auth can hide ownership mistakes | Medium | Security | `resolve_user_scope` allows `user_id` when `AUTH_REQUIRED` is false | Keep tests around both auth-required and local modes |
| Report rendering is route-heavy | Medium | Maintainability | `reports.py` builds CSV and a full HTML document inline | Move report assembly to service/template modules |
| Job orchestration is process-local | Medium | Reliability | `_active_tasks` is an in-memory set in `job_service.py` | Add durable worker before production use |
| Settings are local-first | High for production | Security, operations | Default SQLite and dev secret are intentionally allowed | Add production configuration checklist before exposure |

## Dependency Injection Review

FastAPI dependencies are used for database sessions and user resolution. This is appropriate. The next improvement is not a framework change; it is to make services easier to test by passing collaborators explicitly where workflows become complex.

Recommended direction:

- Keep `get_db` as the route-level session dependency.
- Construct service classes inside routes or small dependency providers.
- Avoid global state except stable configuration or registries with explicit reset hooks for tests.

## Error Handling Review

The backend uses FastAPI exceptions in security helpers and route validation through Pydantic/FastAPI. Pipeline code records parse failures. Job code marks failed jobs. This is a good base.

The gap is consistency: some service failures return structured job status, some route failures raise HTTP exceptions, and parser failures become `ParseFailure` rows. A future error taxonomy should standardize domain errors, validation errors, retryable connector errors, and unrecoverable parse errors.

## Logging Review

Request-id logging is a strong baseline. The logs should continue to avoid full email bodies, credentials, tokens, and sensitive merchant detail at INFO level. `ParserRegistry` already avoids merchant names at INFO and logs detail at DEBUG.

## Recommended Solution

1. Keep backend layering intact.
2. Move route-heavy report rendering into a service/template layer.
3. Define domain error classes for parser, connector, transaction, and authorization workflows.
4. Keep local/demo startup behavior, but document that production must use migrations.
5. Introduce a durable job runner only when PFIS moves beyond local/single-user operation.

## Validation Strategy

- `pytest tests/pytest/test_auth_security.py`
- `pytest tests/pytest/test_endpoints_smoke.py`
- `pytest tests/pytest/test_api_regression.py`
- `pytest tests/pytest/test_jobs_pipeline.py`
- `make check`

## Rollback Strategy

Backend refactors should keep route paths and response contracts unchanged. If a service extraction regresses behavior, restore the previous route/service implementation and keep only tests that captured the expected contract.

