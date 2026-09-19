# Sprint 10 — Strict promotion and handoff

**Status:** PASS_WITH_RISKS  
**Scope:** make the final release decision reproducible and fail closed when evidence is absent.

## Implemented

- Added `scripts/build_promotion_manifest.py`, which records the repository commit, Alembic head,
  scorecard artifact/version/digest, named evidence artifact digests, intelligence and delivery
  scores, and every missing or blocking gate.
- Added explicit evidence keys for parser, provider contract, balance reconciliation, forecast,
  anomaly, recommendation, grounded query, task success, performance, restore, and privacy/security.
  Evidence can be discovered from a protected release directory or supplied as `KEY=PATH` overrides.
- The manifest emits `deferred` unless the scorecard is strict and approved and every named
  artifact is present; it never upgrades missing evidence to partial confidence.
- Added `make promotion-manifest`, focused unit tests, mypy coverage, and a CI artifact step.
- Added an explicit optional strict-scorecard receipt in this sprint to prove the current posture
  fails closed rather than approving a partial baseline.

## Verification

| Check | Result |
|---|---|
| Promotion-manifest unit tests | 2 passed |
| Promotion-manifest mypy | passed |
| Promotion-manifest CLI against current scorecard | emitted `deferred` with missing-gate register |
| Strict scorecard invocation | failed closed with exit code 1 (optional evidence receipt) |
| Current Alembic head recorded | `053_deposit_statement_ledger` |

## Current handoff posture

The generated local manifest reports `deferred`, not approved. The current scorecard remains an
audited baseline (intelligence 42.05; product-stage readiness 58) with representative provider,
cohort, hosted-operations, restore, task-success, and productivity evidence still missing. This is
the expected safe result for the repository state.

## Release-owner sequence

1. Collect protected, de-identified cohort and hosted-operation artifacts without committing secrets
   or raw user/source content.
2. Run the strict intelligence gate and strict scorecard against those artifacts.
3. Build the promotion manifest, verify every digest and Alembic head, and attach the release,
   rollback, support, privacy, and incident handoff records.
4. Approve only when the manifest status is `approved`; otherwise remain beta/product-candidate and
   keep the recovery path visible.

## Remaining risks

- The manifest hashes files but does not replace semantic validation by each strict gate.
- No signing key, hosted release registry, provider authorization, or incident owner was invented.
- A future release must re-run the manifest after every artifact or migration change.

