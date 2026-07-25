# Report 12: Production Readiness Scorecard

## Executive Summary

PFIS has moved beyond its structured-MVP baseline and now has a production-candidate
application foundation. Application-level controls cover production configuration,
durable jobs, database migrations, authentication, connector ownership, regression
testing, and operational health. A real deployment is not ready for go-live until
its managed database, backup/restore drill, TLS/network controls, monitoring, and
alert routing are provisioned and verified.

## Evidence Base

- `backend/app/config.py` preserves local defaults but rejects them in production.
- `backend/app/security.py` provides revocable authentication, CSRF protection,
  password hashing, and token encryption primitives.
- `backend/app/services/job_service.py` persists leased jobs with bounded retries,
  idempotency, and restart recovery.
- `backend/app/observability.py` and health routes expose request ids, timing,
  readiness, and operational counters.
- `.github/workflows/ci.yml` gates formatting, lint, typing, dependency audit,
  PostgreSQL integration, browser regression, and branch-aware coverage.
- `docs/` provides source-of-truth documentation.

## Scorecard

| Category | Score | Assessment |
| --- | ---: | --- |
| Architecture | 8 | Clear layering and service separation, with pipeline growth risk |
| Maintainability | 8 | Good docs and module structure; some dense orchestration remains |
| Scalability | 7 | Async services, PostgreSQL support, and atomic job claims support scale-out; load limits still need deployment-specific measurement |
| Performance | 6 | Adequate for local use; needs measurement and batch tuning |
| Reliability | 8 | Durable leased jobs, bounded retries, restart recovery, and atomic parser/source persistence are implemented |
| Security | 8 | Fail-closed production config, revocable sessions, CSRF, encrypted OAuth credentials, and service-level connector ownership are implemented |
| Observability | 7 | Request ids, server timing, readiness, operational counters, and sanitized failure categories are implemented; hosted dashboards remain deployment-owned |
| Testing | 9 | PostgreSQL, browser, responsive, accessibility, typing, dependency audit, and branch-aware coverage gates run in CI/local regression |
| Documentation | 8 | Strong source-of-truth docs and now audit docs |
| Developer experience | 8 | Clear commands, Makefile, CI, docs, tests |
| Technical debt | 7 | Debt is identifiable and manageable |
| Deployment readiness | 7 | Production profile and runbook are complete; provider backups, alert routing, and infrastructure remain deployment-owned |
| Overall readiness | 8 | Production-candidate application baseline; environment operations are still required before go-live |

## Critical Production Gaps

> Status verified 2026-07-21. Resolved gaps are marked; remaining gaps keep their
> original recommendation.

| Gap | Severity | Status | Recommendation |
| --- | --- | --- | --- |
| Production configuration validation | High | Resolved | Fails closed on default secret, SQLite, non-local CORS, and auth mode |
| Durable background processing | High | Resolved | Database leases, retries, idempotency, recovery, and multi-replica atomic claims are implemented |
| Database operations | High | Partial | Alembic + parity test + prod skips `create_all`; backups/restore still needed |
| Observability metrics | Medium | Partial | Request ids, `/health/ops`, and fallback metric exist; full metrics dashboard pending |
| Parser quality controls | Medium | Partial | Fallback tracking added; expand fixtures and review queue |
| Frontend migration decision | Medium | Resolved | React/Vite is canonical and production fails closed without its build |


## Production Readiness Criteria

The application baseline is complete. A deployment should not be considered
production-ready until all environment-owned criteria are verified:

- Production uses a managed or server-grade database and applies Alembic migrations.
- Backup retention is configured and a restore drill has succeeded.
- Auth-required mode is enabled with deployment-owned secrets and OAuth credentials.
- Monitoring and alerting cover sync, parse, job, API, capacity, and latency failures.
- TLS termination, network policy, scaling limits, and incident ownership are assigned.
- The deployment runbook and rollback procedure are exercised in the target environment.

## Strengths to Preserve

- Keep docs as source of truth.
- Keep parser contracts explicit.
- Keep raw email reprocessing capability.
- Keep user correction feedback.
- Keep route/service separation.
- Keep CI quality gates.

## Weaknesses and Risks

| Risk | Severity | Impact | Recommendation |
| --- | --- | --- | --- |
| Misconfigured production environment | Critical | Security and data reliability | Keep fail-closed startup checks in deployment smoke tests |
| Unverified restore procedure | High | Data recovery risk | Run and record recurring restore drills |
| Limited metrics | Medium | Slow incident diagnosis | Add sync, parser, job, and API metrics |
| Parser quality drift | Medium | Incorrect transaction data | Expand parser fixtures and fallback tracking |

## Recommended Next Actions

All repository-owned modernization phases through Phase 17 are complete. The
remaining actions require the target hosted environment and operational owners:

1. Select the managed PostgreSQL provider and provision encrypted backups.
2. Run and record a point-in-time restore drill.
3. Connect operational health and structured logs to hosted dashboards and alerts.
4. Execute load, soak, failure-recovery, and rollback tests in staging.
5. Complete the release checklist with named incident and data-recovery owners.

## Validation Strategy

- Run full CI.
- Run production configuration smoke tests.
- Run parser regression suite.
- Run a restore drill against the selected production database provider.
- Repeat restart, lease-expiry, multi-worker, load, and soak tests in staging.

## Migration Guidance

Deploy the production-candidate application through an explicit production profile.
Keep provider-specific infrastructure and secrets outside the repository while
retaining the repository's fail-closed validation and documented local profile.

## Rollback Strategy

Production hardening should be controlled by explicit environment profiles. If a production-only control blocks local development, fix profile separation rather than weakening the production requirement.
