# Report 8: Stability and Reliability Assessment

## Executive Summary

PFIS has several reliability foundations: parse failure recording, sync run records, background job status, request-id logging, duplicate detection, and tests. The reliability gap is that jobs are in-process, transaction boundaries are informal, retry policies are limited, and production operations are not yet defined.

## Reliability Strengths

- `ParseFailure` records unresolved parser issues.
- `retry_parse_failures` provides a reprocessing path.
- `SyncRun` captures Gmail sync status and error summaries.
- `BackgroundJob` tracks queued, running, completed, and failed jobs.
- Request ids support log correlation.
- Duplicate transaction detection prevents repeated inserts.
- Gmail sync handles per-message failures and continues processing.

## Fragile Paths

| Path | Severity | Impact | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| In-process job tasks | High for production | Lost jobs on restart | `_active_tasks` is process memory | Use durable worker/queue for hosted deployments |
| Per-email pipeline commits | Medium | Partial batches | `pipeline.py` commits repeatedly inside loop | Define batch semantics and idempotency rules |
| Gmail credential refresh | Medium | Sync failures | token refresh happens during sync path | Add explicit credential-health checks |
| Parser fallback behavior | Medium | Silent quality drift | many sources use fallback parser | Add fallback metrics and review queue |
| SQLite local DB | Medium | Locking under concurrent access | default local SQLite | Use production database for multi-user or hosted use |

## Error Handling Assessment

The system handles many failures locally but lacks a shared reliability vocabulary. Recommended categories:

- retryable connector failure
- permanent connector authorization failure
- parser no-match failure
- parser low-confidence result
- duplicate transaction
- data integrity failure
- authorization failure
- report generation failure

Each category should map to logs, job status, user-facing message, and retry behavior.

## Deployment Risks

PFIS is not yet production-hardened. Risks include:

- default development secret if not changed
- local SQLite as default
- no deployment health checklist beyond app health route
- no backup/restore procedure
- no queue or worker supervision
- no structured metrics

These are acceptable for local/single-user mode because the README explicitly says that is the target. They are not acceptable for hosted production.

## Recommended Solution

1. Add reliability docs for local mode and production mode.
2. Add explicit retry policies for Gmail sync and parse retries.
3. Add metrics for jobs, syncs, parse failures, fallback parser use, and duplicate detection.
4. Move background execution to a durable worker before hosted deployment.
5. Add backup and restore procedures before production data is trusted.

## Validation Strategy

- `pytest tests/pytest/test_jobs_pipeline.py`
- `pytest tests/pytest/test_parser_edge_cases.py`
- Failure-injection tests for Gmail missing account, unsupported job type, parse errors, and duplicate transactions.
- Manual restart test once durable workers are introduced.

## Rollback Strategy

Reliability changes should keep current job records and route contracts compatible. If a queue migration fails, retain the existing job table and temporarily route scheduling back through the in-process runner for local mode.

