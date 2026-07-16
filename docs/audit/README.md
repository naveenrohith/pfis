# PFIS Enterprise Modernization Audit

This audit is a repository-grounded modernization blueprint for PFIS. It is based on the current FastAPI backend, async SQLAlchemy persistence layer, Gmail ingestion services, parser pipeline, static dashboard, Svelte migration folder, docs, tests, and CI configuration in this repository.

PFIS is currently best described as a structured MVP: the product has clear module boundaries and a useful test base, but production hardening, deeper domain boundaries, and operational maturity are still incomplete.

## Verification & Progress (verified 2026-06-30)

This audit has been re-verified against the current code. Most of the roadmap is
already implemented; the table below is the live status. Items not listed remain
as described in the individual reports.

| Audit item | Status | Evidence |
| --- | --- | --- |
| Pipeline decomposed into stages | Done | `services/parser/pipeline.py` stage functions |
| Report HTML extracted from route (XSS-safe) | Done | `services/report_service.py`, `report_renderer.py` (`html.escape`) |
| Production config fails closed | Done | `config.py` `is_production` + `model_validator` |
| Background job error classification | Done | `job_service.classify_job_error` |
| Operational health counters | Done | `/api/health/ops` |
| Connector source-record contract | Done (scaffold) | `services/connectors/source_record.py` |
| Migration/model parity test | Done | `tests/pytest/test_migration_discipline.py` |
| Duplicate vs generic `ValueError` masking | Done | `DuplicateTransactionError` typed + caught in pipeline |
| Alembic-only schema in production | Done | `database.init_db()` skips `create_all` when production |
| Track fallback parser usage | Done | `ParseResult.used_fallback` + pipeline `fallback_parsed` stat |
| Per-email commit in pipeline loop | Intentional (won't change) | per-email durability is the correct resilience choice for ingestion |
| Normalizer global cache correctness | Deferred | benign for single-user local; revisit before multi-user |
| Durable job queue / worker | Out of scope | local/single-user profile |
| Frontend cutover (retire static dashboard) | Out of scope (now) | needs Node + Svelte parity work |

Current test status: full `pytest` suite green.

## Reports

1. [Executive Summary and Architecture Assessment](01-executive-summary-architecture-assessment.md)
2. [Repository and Module Analysis](02-repository-module-analysis.md)
3. [Backend Architecture Review](03-backend-architecture-review.md)
4. [Parser and Processing Pipeline Review](04-parser-processing-pipeline-review.md)
5. [Database and Domain Model Review](05-database-domain-model-review.md)
6. [Technical Debt Assessment](06-technical-debt-assessment.md)
7. [Performance Assessment](07-performance-assessment.md)
8. [Stability and Reliability Assessment](08-stability-reliability-assessment.md)
9. [Maintainability Review](09-maintainability-review.md)
10. [Enterprise Modernization Roadmap](10-enterprise-modernization-roadmap.md)
11. [Engineering Standards](11-engineering-standards.md)
12. [Production Readiness Scorecard](12-production-readiness-scorecard.md)

## Audit Evidence Base

- Backend app entrypoint: `backend/app/main.py`
- API routes: `backend/app/api/routes/`
- Services: `backend/app/services/`
- Parser pipeline: `backend/app/services/parser/`
- Gmail integration: `backend/app/services/gmail/`
- ORM models: `backend/app/models/`
- Schemas: `backend/app/schemas/`
- Static dashboard: `backend/app/static/`
- Svelte migration: `frontend/`
- Tests: `tests/pytest/`
- CI gate: `.github/workflows/ci.yml`
- Source-of-truth docs: `docs/`

## Scoring Scale

- 9-10: strong foundation with limited hardening needed
- 7-8: good structure with known modernization gaps
- 5-6: workable but needs deliberate refactoring or controls
- 3-4: fragile and likely to block scale
- 1-2: unsuitable for the intended role

## Severity Scale

- Critical: likely data loss, security failure, or major outage
- High: likely production incident, major regression risk, or blocking architecture issue
- Medium: meaningful maintainability, scalability, or quality risk
- Low: cleanup, consistency, or local improvement

