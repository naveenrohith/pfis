# Report 7: Performance Assessment

## Executive Summary

PFIS performance is adequate for local/single-user MVP use. The current bottlenecks are unlikely to be FastAPI itself. The likely future bottlenecks are Gmail sync volume, parser throughput, per-email database commits, repeated aggregation queries, SQLite concurrency, and dashboard/report rendering as data grows.

## Backend Performance Findings

| Area | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Per-email commits in parser pipeline | Medium | Batch throughput | `_process_email_batch` commits after many per-email outcomes | Define batch transaction strategy and reduce commits where safe |
| Gmail API calls run through thread offload | Low now, Medium later | Sync latency | `sync_service.py` uses `asyncio.to_thread` for Google client calls | Keep for MVP; add job progress and pagination controls for scale |
| Aggregation queries are service-local | Low now | Query cost | `InsightsService` runs multiple aggregate queries | Add indexes and query profiling as data grows |
| SQLite default | Medium | Concurrency | `config.py` default database is SQLite | Move production/shared use to PostgreSQL or equivalent |
| Inline report HTML generation | Low now | Memory/latency for large months | `monthly_report` builds full HTML string | Use templates and pagination/summary rules for large datasets |

## Strengths

- Async SQLAlchemy is already in place.
- Gmail blocking API work is offloaded with `asyncio.to_thread`.
- Merchant normalization uses TTL caching to avoid scanning merchant rows on every parse.
- Transaction indexes target common user/date/category/review queries.
- Insights monthly aggregates combine spend, income, and average confidence in one query.

## Parser Performance

Parser performance is likely acceptable at current scale because regex processing over email bodies is cheap for single-user batches. The risk grows with:

- broader Gmail queries
- larger inbox histories
- more generic parser attempts
- additional connector types
- AI-assisted processing

Recommended guardrails:

- keep Gmail sync limits explicit
- measure parse duration per email
- track parser fallback rate
- track parse failures by sender and parser version
- keep parser regexes specific and tested

## Frontend Performance

The active static dashboard is simple and likely fast. The Svelte migration under `frontend/` should avoid duplicating expensive dashboard queries client-side. Backend contracts should expose the aggregated data the UI needs rather than forcing the UI to fetch and aggregate raw transactions repeatedly.

## Recommended Solution

1. Add lightweight timing around Gmail sync, parser pipeline, and report generation.
2. Reduce per-email commits only after failure semantics are defined.
3. Keep aggregate queries server-side.
4. Use PostgreSQL for production-like performance testing.
5. Add dataset-size benchmarks before changing algorithms.

## Validation Strategy

- Create deterministic benchmark fixtures from demo emails.
- Measure parse time, sync batch time, and monthly insight/report time.
- Run `pytest tests/pytest/test_jobs_pipeline.py` after pipeline performance changes.
- Compare query counts before and after service changes.

## Rollback Strategy

Performance optimizations must preserve correctness. If an optimization changes transaction counts, duplicate detection, confidence scores, or parse failure recording, revert it and keep the benchmark as diagnostic evidence.

