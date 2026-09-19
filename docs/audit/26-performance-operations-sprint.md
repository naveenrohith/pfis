# Sprint 9 — Performance and operations

**Status:** PASS_WITH_RISKS  
**Scope:** make operational contracts executable in CI while keeping deployment-only proof
separate from local fixtures.

## Implemented

- Added a regression contract for `GET /api/health/metrics`. It verifies process scope,
  privacy wording, bounded latency/error fields, route-template aggregation, and that query
  strings do not become metric labels.
- Added the `ops-contract` Make target for health, observability, release-threshold, and
  restore-evidence validation tests.
- Added the backend CI operational contract step before the full coverage suite.
- Added a browser-job Alembic parity check and artifact after the disposable e2e database is
  migrated. Browser tests therefore cannot silently run against a schema different from the
  repository head.
- Added the metrics endpoint to the API reference and clarified in the deployment runbook what
  CI proves versus what remains deployment-owned.

## Verification

| Check | Result |
|---|---|
| Operational/observability/release contract tests | 30 passed |
| CI workflow YAML parse | passed |
| Migration parity contract | already passing for local `pfis_e2e`; browser job now records its own artifact |
| Process metrics privacy | query strings and source/user fields are excluded by contract test |

## Deployment gate

The repository already has a fail-closed release probe with a minimum 200-request sample,
error rate at most 0.5%, readiness p95 at most 750 ms, security headers, named owners,
deployment control identifiers, and restore evidence no older than 24 hours. Sprint 9 wires the
contract checks into CI; it does not claim that a hosted probe, alert route, backup, restore drill,
or incident rehearsal has run.

## Remaining risks

- Process metrics reset on restart and must be forwarded to a durable hosted metrics system.
- Hosted load/soak evidence, alert ownership, backup retention, restore drill, rollback rehearsal,
  and incident response remain external release gates.
- No provider outage or multi-instance telemetry rehearsal is represented by local tests.

