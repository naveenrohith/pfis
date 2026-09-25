# PFIS Enterprise Modernization Audit

> Historical baseline: reports 1–12 record the earlier modernization program
> and contain status statements that predate the current financial-position
> feature wave.
> [PFIS Intelligence and Productivity Recovery Roadmap](15-intelligence-productivity-recovery-roadmap.md)
> is the canonical execution roadmap verified on 2026-08-09. Report 14 remains
> the detailed 85% domain reassessment and balance-position contract; report 13
> remains the implementation history for the earlier 70% target.

This audit is a repository-grounded modernization blueprint for PFIS. It was based on the FastAPI backend, async SQLAlchemy persistence layer, Gmail ingestion services, parser pipeline, the now-retired static dashboard, the frontend migration folder, docs, tests, and CI configuration in this repository.

PFIS is currently best described as a structured MVP: the product has clear module boundaries and a useful test base, but production hardening, deeper domain boundaries, and operational maturity are still incomplete.

## Verification & Progress (verified 2026-08-02)

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
| Frontend cutover (retire static dashboard) | Done | React/Vite is canonical; `backend/app/static` removed after parity review |

The last consolidated verification baseline (before the deferred latest
issuer-history/recommendation/anomaly-evidence batch) was full `pytest` green
(**419 passed, 2 skipped**), frontend lint/build/**71 tests across 29 files**,
and the six-project responsive/light/dark workspace smoke suite. The current
85% continuation checkpoint has now passed focused backend provider/card,
financial-position, job, readiness, release-gate, export, and deletion suites
(**88 passed, 1 skipped** across the selected runs), plus frontend lint/build
and **71 tests across 29 files**, plus non-visual browser E2E (**26 passed,
10 intentionally skipped across six viewport/color projects**). Full
repository pytest and live provider-backed E2E remain release gates because
representative provider transport/evidence and a configured Postgres
environment are still not present.
The evidence-collection slice also adds manifest-backed parser cohorts and
protected forecast/recommendation/anomaly export commands; those artifacts still
remain deferred until real reviewed cohorts are supplied.

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
13. [Product and Intelligence Maturity Roadmap](13-product-intelligence-maturity-roadmap.md)
14. [85% Intelligence and Product-Stage Reassessment](14-85-intelligence-product-reassessment.md)
15. [Intelligence and Productivity Recovery Roadmap](15-intelligence-productivity-recovery-roadmap.md)

## Audit Evidence Base

- Backend app entrypoint: `backend/app/main.py`
- API routes: `backend/app/api/routes/`
- Services: `backend/app/services/`
- Parser pipeline: `backend/app/services/parser/`
- Gmail integration: `backend/app/services/gmail/`
- ORM models: `backend/app/models/`
- Schemas: `backend/app/schemas/`
- Retired static dashboard: removed from `backend/app/static/`
- Canonical React/Vite dashboard: `frontend/`
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
