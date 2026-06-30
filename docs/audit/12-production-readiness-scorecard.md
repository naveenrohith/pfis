# Report 12: Production Readiness Scorecard

## Executive Summary

PFIS is not production-ready yet, and the repository is honest about that. It is a strong structured MVP with good architecture, documentation, and tests. The path to production is achievable, but it requires deliberate work on production configuration, durable jobs, database operations, monitoring, backup/restore, frontend direction, and parser quality controls.

## Evidence Base

- `README.md` states the current target is local/single-user use and that production hardening is out of scope for now.
- `backend/app/config.py` allows local defaults such as SQLite and a development secret.
- `backend/app/security.py` provides auth and encryption primitives, but production use still depends on configuration.
- `backend/app/services/job_service.py` uses in-process task scheduling.
- `backend/app/observability.py` provides request-id logging but not metrics.
- `.github/workflows/ci.yml` provides a strong CI baseline.
- `docs/` provides source-of-truth documentation.

## Scorecard

| Category | Score | Assessment |
| --- | ---: | --- |
| Architecture | 8 | Clear layering and service separation, with pipeline growth risk |
| Maintainability | 8 | Good docs and module structure; some dense orchestration remains |
| Scalability | 6 | Good async foundation; SQLite default and in-process jobs limit scale |
| Performance | 6 | Adequate for local use; needs measurement and batch tuning |
| Reliability | 5 | Parse failures and job status exist; durable execution is missing |
| Security | 6 | Auth, encryption, and ownership helpers exist; production config must fail closed |
| Observability | 5 | Request ids and records exist; metrics and dashboards are missing |
| Testing | 7 | Useful pytest suite and CI; needs broader fixtures and stricter typing over time |
| Documentation | 8 | Strong source-of-truth docs and now audit docs |
| Developer experience | 8 | Clear commands, Makefile, CI, docs, tests |
| Technical debt | 7 | Debt is identifiable and manageable |
| Deployment readiness | 4 | Local/single-user profile is clear; production profile is not complete |
| Overall readiness | 6 | Structured MVP, not production candidate |

## Critical Production Gaps

| Gap | Severity | Recommendation |
| --- | --- | --- |
| Production configuration validation | High | Require non-default secrets, explicit CORS, production database, and auth mode |
| Durable background processing | High | Replace or supplement in-process jobs for hosted use |
| Database operations | High | Use Alembic migrations, production database, backups, and restore tests |
| Observability metrics | Medium | Add sync, parse, job, failure, fallback, and report metrics |
| Parser quality controls | Medium | Expand fixtures, fallback tracking, and review queues |
| Frontend migration decision | Medium | Choose static dashboard or Svelte as canonical |

## Production Readiness Criteria

PFIS should not be considered production-ready until:

- Production startup fails if secrets are default.
- Production uses a managed or server-grade database.
- Alembic migrations are the schema path.
- Background jobs survive process restarts.
- Backups and restore are documented and tested.
- Parser regressions are fixture-protected.
- Auth-required mode is tested and enabled for hosted use.
- Monitoring covers sync failures, parse failures, job failures, API errors, and latency.
- A deployment runbook exists.

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
| Hosted use with local defaults | Critical | Security and data reliability | Add production config validation |
| Process restart during job | High | Lost or stuck work | Add durable job execution |
| Missing restore drill | High | Data recovery risk | Document and test backup/restore |
| Limited metrics | Medium | Slow incident diagnosis | Add sync, parser, job, and API metrics |
| Parser quality drift | Medium | Incorrect transaction data | Expand parser fixtures and fallback tracking |

## Recommended Next Actions

1. Complete Phase 0 and Phase 1 of the modernization roadmap.
2. Add production configuration validation.
3. Decide the canonical frontend path.
4. Extract report rendering from route code.
5. Add operational metrics and production runbook.

## Validation Strategy

- Run full CI.
- Run production configuration smoke tests.
- Run parser regression suite.
- Run restore drill once backup procedure exists.
- Run restart test for background jobs after durable worker implementation.

## Migration Guidance

Move from structured MVP to production candidate by separating local/demo behavior from production behavior first. Production controls should be added behind explicit settings and deployment documentation, not by weakening the local developer experience.

## Rollback Strategy

Production hardening should be controlled by explicit environment profiles. If a production-only control blocks local development, fix profile separation rather than weakening the production requirement.
