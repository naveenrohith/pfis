# PFIS Intelligence and Productivity Recovery Roadmap

Status: canonical execution roadmap  
Verified: 2026-08-09  
Baseline source: `14-85-intelligence-product-reassessment.md`  
Target: evidence-backed intelligence >=85 and delivery productivity >=85

## Executive decision

PFIS is not stuck because too little code was written. It is stuck because the
program optimized for capability breadth while the score is now constrained by
representative data, longitudinal outcomes, provider truth, reconciliation,
query evaluation, and production proof.

The next program must therefore stop awarding intelligence credit for routes,
models, UI surfaces, or unit tests alone. A capability changes the intelligence
score only after its representative evidence artifact passes a release gate.
The product should remain at beta/product-candidate status until the
non-compensating financial-truth gates pass.

This roadmap replaces the forward execution sequence in report 14. Report 14
remains the detailed domain baseline and balance-position contract.

## Baseline: four measures, not one percentage

| Measure                              |                     Baseline | Confidence                 | What it measures                                                                                                             |
| ------------------------------------ | ---------------------------: | -------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| Implemented product breadth          |                       72/100 | Medium                     | Presence and coherence of intended workflows.                                                                                |
| Evidence-backed product intelligence |                    42.05/100 | Medium-high                | Weighted repository audit across ten intelligence dimensions.                                                                |
| Per-workspace evidence readiness     |                     Variable | High when API is available | User-specific data/history/reconciliation gates from `/api/analytics/intelligence-readiness`; this is not the product score. |
| Product-stage readiness              |                       58/100 | Medium                     | Security, operations, supportability, and dependable daily use.                                                              |
| Delivery productivity                | Stakeholder estimate: 65/100 | Low                        | No reproducible repository formula or historical telemetry exists yet. Sprint 0 establishes it.                              |

The reported 42-44 range is therefore understandable but ambiguous. The audit
score is 42.05; the user-scoped readiness API can return a different number for
each workspace. These values must never be presented as one metric.

## Why the score plateaued

### 1. Score-bearing work is not the same as feature work

The highest-weight weak dimensions are financial truth, not surface breadth:

| Dimension                              | Weight | Current | Target | Gap contribution |
| -------------------------------------- | -----: | ------: | -----: | ---------------: |
| Ledger correctness and lifecycle truth |    18% |      48 |     90 |      7.56 points |
| Account position and reconciliation    |    15% |      32 |     90 |      8.70 points |
| Representative source coverage         |    12% |      40 |     85 |      5.40 points |
| Forecasting and uncertainty            |    12% |      38 |     80 |      5.04 points |
| Learning and personalization           |     8% |      25 |     80 |      4.40 points |
| Query and conversational reasoning     |     5% |      20 |     80 |      3.00 points |

Those six gaps account for most of the distance to 85. Adding another screen,
schema, deterministic rule, or synthetic fixture contributes little or no
score while these gates remain unproved.

### 2. The program used a breadth-first Definition of Done

Historical checkpoints frequently awarded small score increases for an
implemented endpoint, model, evaluation command, or UI interpretation. The
stricter reassessment correctly removed that assumption. The current release
gate requires protected evidence for parser, forecast, reconciliation,
recommendation, and anomaly quality, but ordinary CI intentionally runs it in
non-strict mode. Deferred evidence is visible yet does not fail pull requests.

Consequently, work can be code-complete, test-complete, and CI-green while
remaining intelligence-incomplete.

### 3. Representative data and provider truth are missing

- Gmail is the only live connector.
- The ReBIT adapter provides a transport-neutral parsing boundary, not Account
  Aggregator consent, credentials, certification, or a production FIU path.
- Credit-card observations have a provider-neutral contract but no issuer
  transport for current outstanding, statement due, credit limit, and available
  credit.
- Forecast, anomaly, recommendation, and reconciliation gates require matured
  time periods, reviewed outcomes, multiple users, and representative cohorts.
- Synthetic and sanitized fixtures are useful for regression testing but cannot
  establish release quality.

The external provider/partner decision is a program dependency. It cannot be
completed through application code alone.

### 4. Evaluation coverage does not match the 85 scorecard

`scripts/intelligence_release_gate.py` evaluates five families: parser,
forecast, balance reconciliation, anomaly, and recommendation evidence. It does
not currently gate:

- live provider consent, refresh, revocation, freshness, and failure recovery;
- grounded-query accuracy and refusal quality;
- end-to-end financial task completion and user comprehension;
- migration parity across every active environment;
- production latency, error rate, alert routing, incident response, or restore
  proof as part of the intelligence promotion decision.

An 85 program needs one promotion manifest that joins intelligence, product,
privacy, and operational evidence.

### 5. Integration debt consumes delivery capacity

The 2026-08-09 working tree contains 140 modified and 152 untracked status
entries, including 35 untracked Alembic migrations. This is a point-in-time
working-state observation, not an accusation about ownership. It demonstrates
that implementation has outpaced integration into small, independently
reviewable release units.

Current concentration hotspots include:

| File                                                 | Approximate lines | Risk                                                                    |
| ---------------------------------------------------- | ----------------: | ----------------------------------------------------------------------- |
| `backend/app/services/financial_position_service.py` |             3,744 | Many financial policies and read models share one change surface.       |
| `backend/app/services/intelligence_service.py`       |             2,311 | Analytics evolution has a high regression radius.                       |
| `backend/app/services/guidance_service.py`           |             1,209 | Query routing and advice logic are tightly concentrated.                |
| `frontend/src/lib/types.ts`                          |             2,071 | Contract changes create broad frontend coupling.                        |
| `frontend/src/lib/api.ts`                            |             1,317 | API access and feature evolution share one client surface.              |
| `frontend/src/features/accounts/NetWorthSection.tsx` |             1,159 | A critical financial surface is difficult to change and verify locally. |

The previous browser verification also found local migration drift before
Alembic 051/052 was applied. After parity was restored, the browser suite passed
26 tests with 10 intentional skips, but important API calls were observed in
the 1-2.8 second range. The documented production target is p95 <=750 ms.

### 6. Productivity is not measured as conversion to release evidence

The current 65 productivity estimate cannot be regenerated. Test count and
feature count overstate progress when changes remain unintegrated or evidence
remains deferred. The replacement metric measures the flow from selected work
to releasable, proved behavior.

## Target contracts

### Intelligence 85

PFIS reaches intelligence 85 only when every row below passes. The result is
non-compensating: strong explainability cannot offset incorrect balances, and
strong parser accuracy cannot offset an unproved provider or forecast.

| Dimension                           | Target | Promotion evidence                                                                               |
| ----------------------------------- | -----: | ------------------------------------------------------------------------------------------------ |
| Representative source coverage      |     85 | Manifest-attested provider/parser cohort; freshness and recovery results.                        |
| Ledger correctness                  |     90 | Lifecycle/sign/cutoff contract tests plus representative interval reconciliation.                |
| Account position and reconciliation |     90 | >=10 users, >=100 intervals, >=6 institutions; median residual <=1%, p95 <=5%.                   |
| Temporal knowledge                  |     85 | >=95% immutable history coverage for evaluated rows and explicit forward-only limits.            |
| Forecasting and uncertainty         |     80 | >=5 representative users, >=3 matured periods, MAPE <=20%, interval coverage >=70%.              |
| Decision quality                    |     80 | Outcome-attested recommendations, conflict constraints, safe refusal, usefulness evidence.       |
| Learning and personalization        |     80 | Versioned user baselines, drift limits, minimum samples, rollback, offline evaluation.           |
| Query reasoning                     |     80 | Reviewed query set with grounded facts, citations, uncertainty, refusal, and task success.       |
| Explainability and safety           |     90 | Source, cutoff, ruleset/model version, assumptions, gaps, and recovery path on critical answers. |
| Evaluation and operations           |     85 | Strict promotion manifest, p95 <=750 ms, error <=0.5%, restore/incident/alert evidence.          |

### Delivery Productivity 85

Sprint 0 will generate the first auditable Delivery Flow Score (DFS):

| Component                | Weight | 85 gate                                                                                                  |
| ------------------------ | -----: | -------------------------------------------------------------------------------------------------------- |
| Integration hygiene      |    25% | Main/release branch at Alembic head; no orphaned migration; selected work lands in reviewable slices.    |
| First-pass verification  |    20% | >=85% of change sets pass their required checks without a fix-forward cycle.                             |
| Lead time and WIP age    |    20% | Median selected-to-integrated <=3 working days; no active item older than one sprint without escalation. |
| Evidence conversion      |    20% | >=85% of completed score-bearing items produce their required evidence artifact in the same sprint.      |
| Operational completeness |    15% | >=85% of releases have migration, rollback, observability, performance, privacy, and owner evidence.     |

Formula:

```text
DFS = 0.25*integration + 0.20*first_pass + 0.20*lead_time
    + 0.20*evidence_conversion + 0.15*operational_completeness
```

Until two sprints of telemetry exist, DFS is `unmeasured`; 65 remains a
stakeholder estimate, not a baseline claim.

## New delivery operating model

1. Run ten-working-day sprints with one score-bearing vertical slice.
2. Limit active implementation to two stories. Evidence collection counts as
   implementation, not post-sprint administration.
3. Do not start a new intelligence domain while the selected domain's evidence
   is deferred, unless the blocker is explicitly external and has an owner/date.
4. Require a migration plan, API contract, privacy classification, smoke-check
   example, focused tests, representative evidence plan, and rollback before a
   story is Ready.
5. Mark a story Done only when code, tests, migrations, API checks,
   observability, documentation, and its score/evidence artifact agree.
6. Use a clean integration boundary for each sprint. Existing uncommitted work
   must be inventoried and partitioned; unrelated user work must not be reset.
7. Review the machine-generated scorecard weekly. Never edit scores by opinion.

## Ten-sprint execution map

The detailed phases below remain the domain reference, but delivery is executed
as the following ten dependency-ordered sprints. A sprint may complete its
repository work while leaving an external or time-dependent release gate
explicitly pending; pending evidence never counts as a passed gate.

| Sprint | Score-bearing vertical slice | Observable acceptance gate | Owner boundary and evidence | Stop/rollback condition |
| ------ | ---------------------------- | --------------------------- | --------------------------- | ------------------------ |
| 1 | Integration baseline and release truth | Inventory has no unassigned change; all active databases report the same Alembic head; scorecard is reproducible | Release tooling, CI, migration runbook; inventory, parity, scorecard, and baseline-test receipts | Stop integration if ownership or migration parity is ambiguous; revert only the new tooling wiring |
| 2 | Provider/bank observation | Consent, refresh, revoke, cursor resume, expiry, partial-failure, and freshness contracts pass against the provider-neutral seam | Backend provider boundary and one sandbox adapter seam; contract-test and provider-readiness evidence | Stop live promotion without an eligible provider/FIU and approved credentials; keep estimated-only mode |
| 3 | Bank reconciliation cohort | Interval residuals satisfy the target cohort thresholds with attribution and idempotent position reads | Reconciliation service and cohort evidence; representative users/institutions/intervals required | Roll back reconciliation release if residual or duplicate-write thresholds regress |
| 4 | Credit-card issuer truth | Issuer-observed due, outstanding, limit, available credit, pending activity, and payment linkage are source-labelled and never synthesized | Card observation contract/adapter and issuer fixtures; card truth evidence | Stop card affordability promotion without issuer transport or representative statements |
| 5 | Forecast calibration | Immutable snapshots/outcomes, leakage-safe evaluation, calibrated intervals, drift thresholds, and rollback all pass | Forecast accountability service; matured-period evaluation artifact | Disable forecast recommendations on drift, missing outcomes, or interval under-coverage |
| 6 | Decisions and bounded learning | Constraint-aware ranking, outcome capture, minimum-sample adaptation, versioning, drift detection, and rollback pass | Recommendation policy and outcome ledger; offline and cohort evidence | Freeze adaptation and revert policy version when safety/usefulness constraints fail |
| 7 | Grounded financial query | Typed plans cite evidence, validate arithmetic/temporal scope, express uncertainty, and refuse unsupported answers | Guidance service and reviewed critical-intent set; query evaluation artifact | Refuse/degrade to evidence links when grounding or arithmetic checks fail |
| 8 | Product task success | Critical money/card/risk/recovery journeys pass desktop/mobile, accessibility, comprehension, and browser task gates | Frontend flows plus API contract fixtures; task-success and UX evidence | Disable or hide an unsafe action path if task completion or recovery is unreliable |
| 9 | Performance and operations | Critical-read latency/error budgets, restore/rollback, observability, privacy lifecycle, and incident recovery are evidenced | CI, deployment/runbooks, telemetry and drill artifacts; operations evidence | No product promotion without rollback/restore proof and alert ownership |
| 10 | Strict promotion and handoff | Signed manifest reruns every non-compensating gate; scorecard separates intelligence, readiness, and productivity | Release owner assembles manifest, changelog, support handoff, and unresolved-gate register | Remain beta/product-candidate and roll back release if any required gate is missing or fails |

The provider, representative-cohort, matured-outcome, hosted-operations, and
production-authorization dependencies are deliberately outside the repository
scope. They must be recorded with an owner and next action when encountered;
application code must not claim those gates are complete based on fixtures.

## Phase roadmap

### Phase 0 - Measurement and integration reset (Sprint 0, 10 working days)

Objective: make current progress reproducible before adding more features.

Deliverables:

- one score schema separating product intelligence, workspace readiness,
  product readiness, product breadth, and DFS;
- a command that emits the product score and gate status from evidence inputs;
- migration-head and untracked-migration checks in the local/CI workflow;
- a versioned API contract/smoke-check matrix for product boundary, money truth,
  provider readiness, reconciliation, forecasting, guidance, and readiness;
- a current-work inventory split into independently reviewable integration
  packets, with explicit ownership and no destructive cleanup;
- latency baseline for critical reads and database query traces for the slowest
  three paths;
- two-sprint DFS telemetry board.

Exit gate:

- the same command produces the same score from the same evidence manifest;
- every percentage shown in product/release documentation identifies its
  formula and evidence timestamp;
- local database, CI database, and browser-test database reach the same Alembic
  head;
- no new feature work is selected until the integration inventory has an owner
  and landing order.

Expected intelligence movement: none by default. This phase restores trust in
measurement and delivery.

### Phase 1 - One real provider vertical (Sprints 1-2)

Objective: prove observed bank-account truth end to end with one viable
institution/provider path.

Sprint 1 - provider decision and contract:

- decide eligible Account Aggregator/FIU partner path or an explicitly bounded
  alternative;
- document consent, token custody, data minimization, revocation, refresh
  cadence, incident ownership, sandbox/production boundary, and commercial
  dependency;
- implement provider contract tests for consent request, callback, discovery,
  mapping, first refresh, cursor resume, expiry, revoke, and partial failure;
- add provider contract checks against the sandbox using secret environment
  values that are never committed.

Sprint 2 - bank observation pilot:

- connect one provider transport to the existing observation envelope;
- preserve provider effective/retrieval timestamps, source record identity,
  coverage window, completeness, pending activity, and freshness;
- display/provider-return `observed`, `estimated`, `stale`, `incomplete`, and
  `needs_review` without relabeling estimates as live;
- run recovery drills for expired consent, duplicate batch, partial batch,
  timeout, stale cursor, and unmapped account.

Exit gate:

- at least one consented sandbox/pilot account completes connect -> discover ->
  map -> refresh -> observe -> revoke;
- retry is idempotent and no secret appears in logs, exports, fixtures, or
  provider contract artifacts;
- freshness and coverage failures fail closed in financial guidance.

Stop condition: if no eligible provider/partner path is approved by Sprint 1
day 5, stop transport implementation and escalate the external dependency. Do
not substitute a mock and claim provider progress.

### Phase 2 - Bank and credit-card financial truth (Sprints 3-4)

Objective: turn observed balances plus ledger movements into proved positions.

Sprint 3 - bank reconciliation cohort:

- collect manifest-attested observation-to-observation intervals;
- classify residual causes: missing transactions, cutoff mismatch, pending
  lifecycle, transfer/card-payment linkage, duplicate, fee/interest, provider
  correction, or unexplained;
- reduce query count and latency on position, net-worth, Cash Plan, and
  readiness paths without changing financial semantics;
- make unexplained residual and incomplete coverage block safe-to-spend.

Sprint 4 - issuer/card vertical:

- implement one issuer-specific adapter or approved card-data provider;
- ingest statement due, minimum due, current outstanding, credit limit,
  available credit, holds/pending when supplied, and provider timestamps;
- keep billed amount, paid since statement, unbilled activity, current
  outstanding, and available credit separate;
- reconcile card payments across the funding bank leg and card liability leg.

Exit gate:

- > =10 manifest-attested users, >=100 intervals, >=6 institutions;
- median absolute residual <=1% and p95 <=5%;
- unresolved/ambiguous transfer or card-payment matches never auto-link;
- issuer-observed available credit is never synthesized from the limit.

Expected score movement after gate: account position 32 -> 70+, ledger truth
48 -> 70+, source coverage 40 -> 60+. Full target credit waits for continued
cohort breadth.

### Phase 3 - Calibrated forecasts (Sprints 5-6)

Objective: prove that predictions are reliable enough to support decisions.

Sprint 5:

- schedule immutable daily forecast snapshots for eligible accounts;
- evaluate only against later verified observations;
- record data/ruleset version, cutoff, coverage, expected/low/high path,
  assumptions, and missing evidence;
- monitor sample maturity instead of filling gaps with imputed outcomes.

Sprint 6:

- segment errors by horizon, account type, source coverage, recurring-income
  stability, and obligation density;
- calibrate intervals and deterministic fallbacks;
- add drift thresholds and rollback to the prior ruleset/model;
- validate card-due and safe-to-spend decisions against the conservative band.

Exit gate: >=5 representative users with >=3 matured periods, MAPE <=20%,
interval coverage >=70%, transaction-history coverage >=95%, and no temporal
leakage.

Expected score movement after gate: forecasting 38 -> 80; temporal knowledge
55 -> 75+.

### Phase 4 - Decisions, outcomes, and bounded learning (Sprints 7-8)

Objective: optimize decisions, not recommendation volume.

Sprint 7:

- introduce a constraint planner for due obligations, reserves, liquidity,
  goal competition, uncertainty, reversibility, and user exclusions;
- produce ranked alternatives and an explicit safe refusal when evidence is
  incomplete;
- capture viewed, accepted, dismissed, snoozed, executed, not executed, reason,
  and observed outcome with privacy-safe retention.

Sprint 8:

- create per-user baselines only after minimum samples;
- version every adaptive threshold/policy and retain a deterministic fallback;
- run offline counterfactual evaluation before promotion;
- detect outcome drift and automatically disable a regressed policy.

Exit gate: >=10 adjudicated recommendation outcomes with >=5 representative
users per required cohort, usefulness/safety threshold agreed before evaluation,
and no policy promotion without rollback evidence.

Expected score movement after gate: decision quality 45 -> 80; learning 25 ->
65-80 depending on cohort sufficiency.

### Phase 5 - Grounded financial query and task success (Sprints 9-10)

Objective: replace keyword routing with typed, evidence-grounded reasoning.

Sprint 9:

- define a typed intent/plan layer over positions, statements, obligations,
  forecasts, decisions, and reconciliation;
- require source IDs, as-of/cutoff, assumptions, missing coverage, confidence,
  and ruleset/model version on every critical answer;
- build a reviewed query set covering present balance, card affordability,
  upcoming risk, what changed, why totals differ, and unsupported advice;
- score fact accuracy, citation correctness, arithmetic, temporal correctness,
  uncertainty, and refusal.

Sprint 10:

- test complete user tasks, not only response text;
- measure whether users can identify current money, upcoming shortfall, card
  amount due, confidence, and recovery action;
- add adversarial queries for stale data, conflicting sources, ambiguous dates,
  unsupported institutions, and pressure to overstate certainty.

Exit gate: >=80% reviewed query score, 100% critical arithmetic and source
grounding, >=90% safe refusal on unsupported/high-risk cases, and >=85% task
completion on the critical product tasks.

Expected score movement after gate: query reasoning 20 -> 80; explainability
70 -> 90.

### Phase 6 - Product-stage release (Sprints 11-12)

Objective: make intelligence dependable under real operating conditions.

Sprint 11:

- split/read-optimize the three highest-impact orchestration paths behind
  stable contracts; avoid a broad rewrite;
- enforce critical-read p95 <=750 ms and error rate <=0.5% under the documented
  load profile;
- connect hosted metrics, logs, traces, alerts, and named incident owners;
- verify privacy export/deletion, retention, consent revocation, and secret
  handling end to end.

Sprint 12:

- run the restore drill, rollback rehearsal, provider outage drill, stale-data
  drill, and incident exercise;
- execute strict intelligence, API smoke, migration, backend, frontend,
  browser, accessibility, performance, and security gates;
- assemble one signed promotion manifest linking all evidence hashes and dates.

Exit gate:

- every intelligence target row passes;
- DFS >=85 for two consecutive sprints;
- no P0/P1 correctness, privacy, security, migration, or operational blocker;
- product-stage wording and capability claims exactly match observed support.

## Sprint 0 backlog: start now

| ID    | Priority | Work packet                                  | Acceptance evidence                                                                                                                        |
| ----- | -------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| S0-01 | P0       | Canonical metric schema and score manifest   | One command emits all score names, formulas, timestamps, evidence status, and blockers.                                                    |
| S0-02 | P0       | Inventory/partition the current working tree | Every changed path belongs to an integration packet; migrations have an ordered landing owner; nothing unrelated is reset.                 |
| S0-03 | P0       | Migration parity gate                        | Fresh PostgreSQL, developer DB, and E2E DB reach the same head; orphaned/untracked migrations fail the integration gate.                   |
| S0-04 | P0       | Product score gate expansion design          | Query, provider, task-success, performance, migration, and operations checks have schemas and owners.                                      |
| S0-05 | P1       | Critical-read latency baseline               | At least 20 samples per route; p50/p95/error and query count for net worth, position, card runway, workspace, and readiness.               |
| S0-06 | P1       | Hotspot decomposition seams                  | Characterization tests and extraction order for financial position, intelligence, guidance, frontend API/types, and Net Worth. No rewrite. |
| S0-07 | P1       | DFS telemetry                                | Two-sprint board captures selected date, first CI, rework, evidence artifact, integration date, migration/ops completeness.                |
| S0-08 | P1       | Provider decision brief                      | Named decision owner, eligible partner path, sandbox access, compliance/consent boundary, date, and fallback scope.                        |
| S0-09 | P2       | Roadmap/archive reconciliation               | Report 15 is canonical; prior score claims are labeled historical and no dashboard mixes product and workspace scores.                     |

### Sprint 0 implementation checkpoint - 2026-08-09

S0-01 is now implemented as a versioned, fail-closed baseline. The manifest at
`docs/audit/intelligence-scorecard-manifest.json` separates product breadth,
evidence-backed product intelligence, runtime-only workspace readiness,
product-stage readiness, and Delivery Flow Score. Running
`python scripts/intelligence_scorecard.py` deterministically reproduces the
42.05 intelligence baseline and 85.15 weighted target while keeping DFS
`unmeasured` until telemetry exists. A score above its audited baseline requires
`evidence_status: passed` plus timestamped, hash-addressed evidence; intelligence
evidence must also be marked representative. Strict mode fails until every
non-compensating intelligence, product-stage, and productivity gate passes. It
also resolves every referenced evidence file and verifies that its content
matches the declared SHA-256 before approval.

The non-strict report is now a CI artifact. It makes the current `not_ready`
posture visible on every change without pretending that repository CI has
access to protected representative cohorts.

Sprint 0 sequencing:

```text
S0-02 -> S0-03
   |        |
   +------> S0-01 -> S0-04
                 |      |
                 +----> S0-07
S0-05 -> S0-06
S0-08 runs as an external-dependency track with a day-5 decision gate.
```

## Promotion manifest

One immutable promotion manifest should eventually reference:

```yaml
schema_version: pfis-promotion-manifest-1
commit: <sha>
alembic_head: <revision>
scorecard_version: <version>
evidence:
  parser: <artifact + sha256>
  provider_contract: <artifact + sha256>
  balance_reconciliation: <artifact + sha256>
  forecast: <artifact + sha256>
  anomaly: <artifact + sha256>
  recommendation: <artifact + sha256>
  grounded_query: <artifact + sha256>
  task_success: <artifact + sha256>
  performance: <artifact + sha256>
  restore: <artifact + sha256>
  privacy_security: <artifact + sha256>
decision:
  intelligence_score: <computed>
  delivery_flow_score: <computed>
  non_compensating_gates_passed: true|false
  status: deferred|blocked|approved
```

Missing, stale, invalid, or non-representative evidence must return `deferred`
or `blocked`; it must never be converted to partial confidence.

## Risks and stop/go rules

| Risk                                    | Trigger                                               | Response                                                                                  |
| --------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| No eligible provider path               | No owner/partner/sandbox by Sprint 1 day 5            | Stop provider coding; escalate external decision; retain estimated-only wording.          |
| Cohort cannot be recruited safely       | Required manifest sizes cannot be met                 | Do not lower thresholds silently; extend evidence phase or narrow product claim.          |
| Forecast evidence needs time            | Outcomes have not matured                             | Continue snapshot collection; do not manufacture/impute proof or start model expansion.   |
| Dirty integration state grows           | New score-bearing work starts before S0-02/S0-03      | Stop new work and land/partition existing packets first.                                  |
| Financial residual regresses            | Median >1% or p95 >5%                                 | Block position-dependent guidance; diagnose residual class before feature work.           |
| Critical API exceeds budget             | p95 >750 ms                                           | Profile the first wrong/slow state and optimize behind existing contracts before release. |
| Query is fluent but ungrounded          | Critical fact/citation/refusal gate fails             | Keep deterministic supported intents and safe refusal; do not promote broad conversation. |
| Productivity score rises by bookkeeping | Evidence conversion or integration remains below gate | Keep DFS component scores separate; no compensating average.                              |

## First decision after Sprint 0

Proceed to Phase 1 only if measurement is reproducible, migration state is
controlled, current changes have a landing order, and a real provider decision
has an accountable path. Otherwise continue Phase 0; adding more intelligence
features would repeat the same plateau.
