# PFIS Product and Intelligence Maturity Audit

> Historical 70% roadmap. The target was raised after a full reassessment on
> 2026-08-02. Use
> [PFIS 85% Intelligence and Product-Stage Reassessment](14-85-intelligence-product-reassessment.md)
> as the canonical forward plan. This report remains the implementation and
> evidence history behind that reassessment.

Status: repository-grounded assessment  
Verified: 2026-08-02
Goal: move PFIS from a broad MVP/production-candidate foundation to a dependable
personal-finance product, and raise measurable financial intelligence from
approximately 30% to at least 70%.

## Executive conclusion

PFIS is no longer a small MVP in feature count. It has a serious foundation:
user-scoped data, revocable sessions, CSRF protection, encrypted OAuth tokens,
durable jobs, PostgreSQL migrations, source retention, deterministic parsing,
statement reconciliation, verified balances, cash planning, liabilities,
budgets, explainable forecasts, a polished React workspace, and substantial
automated tests.

The product is still MVP-like in **depth and proof**. Many capabilities are one
deterministic rule or one supported provider/layout deep. Intelligence is mostly
fixed monthly aggregation and threshold logic. The application can display many
financial concepts, but it cannot yet prove broad source coverage, calibrated
accuracy, robust prediction, useful personalization, or production operations
under real usage.

The right next move is therefore not another wave of screens. PFIS should first
make its financial truth measurable, then deepen its knowledge and decision
models, and only then add a grounded conversational or generative layer.

## Current assessment

### Intelligence maturity: 47/100

This score measures whether PFIS can turn incomplete financial evidence into
reliable, personalized, evaluated decisions. It does not measure the number of
features or UI surfaces.

| Dimension | Weight | Current | Evidence and limitation |
| --- | ---: | ---: | --- |
| Data-source and format coverage | 15% | 40 | Gmail is the only live connector and HDFC is the only statement extractor. The sanitized benchmark now has 50 extraction and 50 classification/negative cases. HDFC, SBI, and ICICI account alerts meet the dedicated-parser `supported` gate; Axis, Kotak, and major digital-payment senders now have institution-aware routing but remain unverified until representative cohorts clear the gates. No source is verified and broader production-representative coverage remains incomplete. |
| Financial truth and reconciliation | 20% | 55 | Transaction, transfer, statement, account, and evidence invariants now include an enforced single-ledger currency, a user-owned financial timezone, mismatch containment, operational repair counts, and an explicit reconciliation-quality endpoint for review coverage, statement outcomes, duplicate candidates, and unexplained balance movements. Broad cross-source reconciliation and representative production proof are still incomplete. |
| Knowledge depth | 15% | 50 | A versioned temporal read model now unifies planned income, bills, commitments, card-payment intentions, issuer schedules, card milestones, reserves, recurring debit/credit patterns, account identity/lifecycle states, and pending/refund/reversal transaction lifecycles as typed expected-versus-observed events with exact causal references. Owned confirmations, cancellations, manual observations, conflicts, exact ledger links, and append-only snapshots for core planning sources, account identity, and ledger mutations persist across recomputation. Broader historical reconstruction and richer account/connector lineage remain incomplete. |
| Forecasting and uncertainty | 15% | 35 | Cash-flow ruleset v6 consumes dated expected inflows/outflows as non-duplicating floors, uses same-cutoff residuals when available for interval width, and carries temporal conflicts into range/confidence. It now exposes evidence-gated category-mix and recurring-income pay-cycle signals without applying weak cohorts. Rolling retained-ledger backtests and immutable prospective snapshots/outcomes measure error and interval coverage without rewriting predictions; historical-safe backtests consume transaction-derived patterns and versioned core planning snapshots, including complete liability schedules. Statement-line and dispute status history now append to the same source contract, but representative calibration cohorts, broader mutable histories, and thresholds remain incomplete. |
| Recommendation quality | 15% | 50 | Recommendations remain deterministic threshold templates, but accepted/not-relevant decisions now snapshot server-derived evidence, bounded consequence ranges, conflict/goal context, a resolution status/next step, and supported baselines. Immutable outcomes preserve the user's answer and recompute the same metric as a separate directional impact. Representative effectiveness proof remains incomplete. |
| Learning and personalization | 10% | 25 | Merchant corrections, preferences, recommendation acceptance/relevance, and later outcomes persist. Ranking now adapts only after three completed same-type outcomes with a six-point cap and an evidence line; broader per-user thresholds and representative safety proof remain incomplete. |
| Explainability and safety | 5% | 75 | This is a strength: observed/calculated/forecast labels, evidence, ruleset versions, deterministic scenarios, and explicit limitations are present. Temporal pattern events now cite the exact transactions that caused them and distinguish user/issuer status from a ledger match. Some older surfaces still attach generic evidence. |
| Evaluation and monitoring | 5% | 70 | CI emits parser-quality/drift contracts, rolling forecast error/coverage, immutable forecast outcomes, recommendation baseline-to-observed records, anomaly adjudication metrics, and a versioned cohort-safe effectiveness report. Production-representative adjudication, eligible real-world recommendation cohorts, complete mutable-status history, and passing release evidence remain incomplete. |

Weighted current score: **47.00**, rounded to **47/100**.

## Implementation checkpoint — 2026-07-30

The first stabilization and measurement slice is complete:

- Black, Ruff, and mypy are clean across the backend application and release,
  restore, and parser-evaluation scripts.
- The full backend regression suite passes: **327 passed, 2 skipped**.
- The sanitized truth corpus now contains **12 transaction extraction cases**
  and **12 source-classification/negative cases**, up from 4 transaction cases
  with no scored classification corpus.
- `scripts/evaluate_parser_corpus.py` now produces deterministic JSON covering
  exact extraction accuracy, per-field accuracy, classification confusion,
  fallback rate, confidence calibration error, and per-institution support
  tiers.
- CI blocks transaction or classification exact accuracy below 95% and retains
  the parser-quality JSON as a build artifact; it now also uploads the
  non-strict intelligence release posture so deferred evidence is visible.
- Source classification now uses one stable `UNKNOWN` institution value instead
  of alternating between an empty string and `UNKNOWN`.

At that checkpoint, the sanitized benchmark was **100% exact on 12 extraction
and 12 classification cases**, with a 33.33% generic-fallback rate and 0.05 mean
absolute confidence-calibration error. This is a regression baseline, not proof
of broad real-world accuracy: every institution remains **best effort** because
none yet meets the documented sample-size requirement for supported or verified
status.

This checkpoint closes the immediate formatting/type-check regression and starts
the measurable-truth program. Together with the subsequently verified
money/time contract, it raised the evidence-based score to 36/100. The next
proof milestone was a larger adjudicated corpus and a richer quality contract;
the later checkpoint below records the completed measurement slice and the
remaining representative-coverage and drift work.

### Evaluation-contract checkpoint — 2026-07-31

- The sanitized corpus has grown to 50 extraction and 50
  classification/negative cases, reaching the lower 100-case target with
  CI-enforced non-shrinking case counts.
- Parser quality report version 2 is content-addressed and records the support
  policy used to assign each tier.
- Classification now publishes precision, recall, F1, macro recall, weighted
  F1, institution recognition, and confusion evidence rather than accuracy
  alone.
- Extraction is cohortable by explicit format ID, parser name/version,
  institution, dedicated/fallback path, critical field, and an explicit
  `synthetic_fixture`/`sanitized_production`/`production_safe` evidence label.
- Representative status is now manifest-backed: the independent manifest pins
  the corpus fingerprint, lists opaque case IDs, and attests de-identification
  and review; fixture labels alone cannot satisfy the release gate.
- Every declared institution appears in the report; absent evidence is labeled
  `unsupported` instead of disappearing from the result.
- The quality CLI can compare a prior report and fail on overall or field-level
  regression, while retaining minimum accuracy, recall, and case-count gates.
- `/api/health/ops` now reports aggregate observed counts and measured
  duplicate, parse-failure, fallback, and pending-review rates. Empty cohorts
  return zero rates with zero sample counts rather than `null`.
- Pipeline events retain only the non-secret institution identifier needed for
  source cohorts. Seven-day failure/fallback rates are compared with the prior
  seven days, and alerts require at least 20 observations in both windows.

This improves evaluation maturity but does not make the 100-case synthetic and
sanitized corpus equivalent to production evidence. HDFC, SBI, and ICICI
account alerts meet the documented `supported` gate with passing dedicated
parser cases across distinct format cohorts. No source is `verified`; generic
fallback sources and card-specific cohorts remain best effort until their
sample-size, format-diversity, accuracy, and dedicated-parser gates are met.

### User-visible confidence checkpoint — 2026-07-31

- Financial Health now exposes a versioned four-part Data Confidence contract:
  observed history coverage, evidence freshness at the user's financial-day
  boundary, parsing/merchant quality, and review/conflict cleanliness.
- The overall score is computed server-side from those published dimensions;
  the React application does not recreate or reinterpret the rules.
- Every `watch` or `limited` dimension includes a concrete recovery action to
  Inbox or Review. Strong dimensions do not create unnecessary tasks.
- Empty accounts correctly return four limited dimensions rather than treating
  an empty review queue as high confidence.
- Coverage explicitly describes observed PFIS records and does not claim that
  an inbox, provider, or account history is complete.

This completes Phase 1 item 5 and acceptance milestone 6. No maturity-score
credit is added at that checkpoint: the then-current 39/100 remained evidence-based until broader
source cohorts prove real completeness and the remediation journeys receive
task-level browser validation.

### Temporal event-contract checkpoint — 2026-07-31

- `GET /api/knowledge/events` introduces one versioned contract for expected,
  observed, overdue, missed, cancelled, and conflicting financial events.
- Planned income, bills/subscriptions, commitments, issuer instalments, card
  dates, approved reserves, recurring expenses, and recurring income are
  projected into the same bounded, user-scoped timeline.
- User/provider dates remain exact. Pattern dates use visible cadence windows
  and amount ranges, with confidence and sufficiency carried forward.
- Recurring patterns now retain stable stream identity, account/currency scope,
  and the exact transaction IDs used as evidence.
- Explicit paid status without a ledger link is labelled `user_status` or
  `issuer_status`; it never fabricates a transaction match.
- Empty, reversed, and oversized ranges have deterministic tested behavior.

This completes Phase 2 item 1 and begins item 3. Knowledge and explainability
receive limited credit, raising evidence-backed maturity from 39 to 40/100.
Forecasting receives no credit until this event model is consumed and backtested.

### Persisted temporal-decision checkpoint — 2026-07-31

- Owned `confirmed`, `cancelled`, `observed`, `linked`, and `conflict` decisions
  now survive read-model recomputation without mutating source or ledger rows.
- Exact transaction links enforce user ownership, direction, currency,
  ignored-activity, and date-window constraints. Material amount variance is
  surfaced as a conflict with both evidence records retained.
- Removing a decision restores the source-derived state. Portable export schema
  v2 includes owned decisions, and account deletion removes them.
- Integration coverage proves persistence, update/delete behavior, cross-user
  isolation, link validation, conflict explanation, export ownership, and
  deletion completeness.

This completes the persistence/API portion of Phase 2 item 4. The end-user
review journey and conflict-resolution outcome measurement remain open. The
evidence-backed maturity score rises from 40 to 41/100; forecasting still
receives no credit until it consumes this contract and passes rolling backtests.

### Recompute-audit and event-timed forecast checkpoint — 2026-07-31

- `GET /api/knowledge/events/audit` performs a read-only rebuild and reports
  applicable/orphaned overlays, ruleset drift, missing transaction links, and
  event coverage by kind/state. Repeated runs are deterministic and do not
  repair or delete evidence.
- Cash-flow ruleset v6 consumes active dated inflows/outflows for current and
  future months. Event totals set projection floors with `max` semantics so an
  already-higher pace forecast is not increased a second time.
- Conflicting outflows are excluded from the central estimate, widen the upper
  range, and lower confidence. Observed/cancelled events are not forecast again.
- Future `data_through` is capped at the user's financial day rather than
  claiming knowledge through a future month end.

This begins Phase 2 item 5 and Phase 3 item 1. The score remains 41/100 because
one deterministic integration test is not a rolling backtest and provides no
production-representative forecast-error or interval-coverage evidence.

### Rolling forecast-evaluation checkpoint — 2026-07-31

- `GET /api/analytics/cash-flow/backtest` evaluates 3–12 completed months at
  day-7, day-14, and day-21 information cutoffs.
- It publishes mean absolute error, median absolute percentage error, weighted
  absolute percentage error, interval coverage, interval width, eligible sample
  count, and explicit exclusion reasons.
- Training uses up to 6 earlier retained-ledger months. Periods with fewer than
  3 observed prior months or zero observed spend are excluded rather than
  assigned misleading percentage error.
- Mutable bills/commitments and later status changes are not reconstructed from
  today's state. The report explicitly marks temporal evidence unevaluated,
  preventing future-information leakage while knowledge-time history is absent.

This adds limited forecasting/evaluation credit and raises maturity from 41 to
42/100. It does not prove the <20% target: production-safe representative runs,
temporal as-of reconstruction, and release thresholds remain required.

### Prospective forecast-accountability checkpoint — 2026-07-31

- Explicit snapshot capture freezes the original prediction, range, evidence,
  assumptions, confidence, and forecast/temporal rulesets. Projection reads
  remain side-effect free.
- The uniqueness contract is user + target month + financial-day cutoff +
  forecast ruleset. Later ledger changes and repeated requests cannot rewrite
  or duplicate the prediction.
- Once the target month closes, outcome evaluation writes a separate one-to-one
  record with actual income/spend/net, absolute/percentage spend error, and
  interval coverage. Repeated evaluation is idempotent.
- User-scope tests, portable export schema v3, and account-deletion tests prove
  the prediction/outcome lifecycle boundary.

This raises evidence-backed maturity from 42 to 43/100. It establishes the
prospective measurement loop but does not claim accuracy: enough real snapshots
must mature, thresholds must be enforced, and temporal knowledge-time history
must support leakage-safe retrospective evaluation.

### Recommendation decision/outcome checkpoint — 2026-07-31

- Accept, not-relevant, dismiss, and snooze mutations validate the ID against a
  freshly recomputed owned recommendation for the selected financial period.
- The decision preserves title, target, expected impact, evidence, reason
  codes, guidance ruleset, period, and optional bounded user note.
- Accepted/not-relevant advice leaves the active brief. The UI exposes “Use
  this action,” snooze, and “Not relevant” without engagement scoring.
- Only accepted advice can receive a helped/no-change/worse/not-completed
  outcome. The first outcome is idempotent and immutable; typed impact is
  optional and owner scoped.
- Export schema v4 and deletion tests close the owned lifecycle.

This raised evidence-backed maturity from 43 to 45/100. The next slice adds
automatic baselines and the end-user outcome-review journey:

- Accepting supported review, budget, recurring-cost, and savings guidance
  stores a typed baseline beside the immutable evidence snapshot.
- Recording the one-time outcome recomputes the same period metric and stores
  baseline, observed value, and directional automatic impact separately from
  the user's helped/no-change/worse/not-completed answer.
- The Action follow-up surface shows the baseline, collects one plain-language
  response, and then shows the measured change without engagement scoring.

This raises evidence-backed maturity from 45 to 46/100. It still does not prove
recommendation effectiveness across representative cohorts: competing-goal
conflicts, adaptive ranking safeguards, and release thresholds remain open.

The aggregate-effectiveness contract is now implemented without claiming that
representative evidence already exists:

- a versioned 180-day evaluator separates cohorts by recommendation type,
  guidance ruleset, outcome ruleset, metric, and unit;
- recommendation cohorts and measured subsets independently require at least
  10 immutable outcomes from 5 distinct active users;
- smaller cohorts reveal no type-specific counts or rates;
- reported completion/help, automatic improvement/impact, and directional
  agreement remain separate, and the UI explicitly avoids causal language.

The score remains 47/100 until real eligible cohorts, release thresholds, and
conflict-aware recommendation consequences provide stronger evidence.

Conflict-aware decision context and capped personalization are now implemented:

- recommendations carry bounded numeric consequence ranges, smallest feasible
  actions, confidence/freshness, urgency, reversibility, goal links, and
  explicit Cash Plan/data-gap/overlap conflicts;
- accepted decisions persist that context beside the evidence snapshot;
- ranking uses consequence materiality and conflict penalties, while explicit
  per-user feedback can move a type by at most six priority points after three
  completed outcomes;
- the Today and Action follow-up surfaces show the boundary conditions before
  the user accepts an action.

Representative outcome cohorts and release-threshold enforcement are still
required before the maturity score moves. Conflict resolution now has an
explicit deterministic status/next-step contract: blocked evidence, review
warnings, overlapping actions, and competing goals are distinguished without
silently choosing a financial action.

The release-threshold enforcement artifact is now implemented without claiming
that the current repository has production evidence:

- `scripts/intelligence_release_gate.py` joins parser-quality JSON, per-user
  rolling forecast backtests, and the privacy-safe recommendation effectiveness
  report into one machine-readable release decision;
- parser accuracy/recall/critical-field thresholds, the combined 100-case
  corpus minimum plus explicit representative case/format/institution coverage,
  distinct production-safe forecast-user metadata, the eligible-user forecast
  MAPE limit, and the minimum recommendation cohort safeguards are checked
  explicitly;
- audit mode records missing evidence as `deferred`, while `--strict` fails
  closed so an absent cohort cannot be mistaken for a green release.

The artifact makes the remaining evidence gap executable; it does not raise the
score until representative forecast and recommendation cohorts are actually
collected and pass.

The recommendation-resolution slice is now implemented as a bounded decision
contract:

- every recommendation declares `ready`, `needs_review`, `blocked`, or `choose`;
- blocking evidence maps to one explicit next step (review records or complete
  the Cash Plan), while overlaps and constrained competing goals expose related
  actions/goal IDs without silently allocating money;
- the resolution and rationale are persisted with accepted/snoozed/dismissed
  decision evidence and included in portable export schema v8;
- Today and Action follow-up show the resolution label and next step in the
  same calm evidence block as the consequence and conflicts.

Representative outcome cohorts and release thresholds remain the proof gate.

The anomaly-intelligence slice is now implemented as a bounded, user-relative
signal:

- category and merchant spend departures compare the current month with up to
  twenty-four retained months using a robust median/MAD baseline and prefer repeated
  same-calendar-month history when at least two observations exist;
- a signal requires at least three observed history months plus absolute and
  relative materiality floors, and carries confidence, evidence, assumptions,
  and a versioned ruleset;
- Insights renders the signal as a review prompt, and Today can rank the same
  baseline departure as an action without presenting it as fraud or certainty.

This improves decision depth but receives no score credit until the baseline is
backtested against adjudicated user corrections and false-positive rates.

The adjudication path is now executable: `scripts/evaluate_anomaly_quality.py`
produces a privacy-safe precision/recall/false-positive report, and the strict
intelligence release gate requires that report before anomaly actions can be
promoted. The protected export carries only aggregate contributing-user and
category/merchant coverage; the gate now requires at least five users and both
anomaly kinds in addition to both alert/non-alert sampled cases and both
material/expected labels. An all-alert or single-user artifact cannot establish
recall or false-positive rate. Insights now exposes bounded non-alert samples,
stores the `predicted_alert` boundary, and excludes `insufficient_evidence` from
binary labels. The current repository has no representative adjudication cohort,
so the gate remains deferred rather than claiming anomaly accuracy.

The demo first-success baseline is also now time-safe: runtime demo sync shifts
sample evidence relative to the user's financial day while leaving fixed parser
fixtures unchanged. This removes the stale-month trap; onboarding and a guided
first correction still remain product-workflow work.

### Historical temporal evaluation checkpoint - 2026-08-02

Forecast backtests now evaluate a leakage-safe temporal slice at each
historical cutoff:

- `/api/knowledge/events` and its audit endpoint accept an optional `as_of`
  financial day and reject future dates;
- historical-safe evaluation includes transaction-derived recurring income/
  expense patterns plus append-only snapshots for Cash Plans, bills,
  commitments, complete liability schedules, approved reserves, and card
  calendar events, and mutable ledger transaction states;
- other mutable status histories remain excluded until they receive the same
  versioned-source contract;
- backtest reports now expose whether temporal and transaction evidence was
  evaluated, measured snapshot coverage, how many periods contained temporal
  signals, and how many event floors were consumed;
- cash-flow v5 uses same-cutoff residual calibration when at least three
  comparable months exist, and the release gate requires MAPE, coverage, and
  evidence-completeness thresholds together.

This closes the former all-or-nothing temporal exclusion without claiming that
every mutable planning source can be reconstructed historically. Forecast MAPE,
interval coverage, and representative cohorts are still required before the
release gate can credit the capability.

### Product-stage operations checkpoint — 2026-08-02

The next product slice is now wired through the same evidence boundary:

- recommendation actions expose a persisted `ready`, `needs_review`, `blocked`,
  or `choose` resolution with one explicit next step, and acceptance refuses a
  blocking action;
- `/api/health/capabilities` and Data & settings publish beta source scope,
  freshness expectations, incident-feed posture, and recovery paths without
  pretending that unsupported institutions are production verified;
- direct account-link repair, merchant bulk correction, financial-position
  repair, and cross-source duplicate removal append transaction snapshots;
- Data Confidence freshness uses observed activity plus connector state, last
  completed sync age, and unprocessed inbox records;
- budget and card-reminder deletion use the shared accessible confirmation
  dialog, and transaction filters preserve shareable URL state;
- consolidated evidence is green for backend static checks (136 files), the
  current backend regression subset (**67 passed, 1 skipped**), frontend tests
  (**71 passed across 29 files**), and the production build; 26 non-visual
  browser scenarios passed across mobile, tablet, desktop, and dark-mode
  projects after the rolling-demo assertion was aligned with the current
  contract.

This improves product trust and operational clarity but does not raise the
47/100 intelligence score: representative parser cohorts, forecast calibration,
recommendation outcomes, and hosted operational evidence remain unproven.

### Account identity and lifecycle checkpoint — 2026-08-02

The next knowledge-depth slice is now durable rather than UI-only:

- `FinancialAccount` stores `identity_status`, bounded `identity_confidence`,
  compact non-secret evidence references, and an `updated_at` lifecycle clock;
- imported masked suffixes remain `inferred` until a user confirms the
  institution/product/masked identity, while explicit account creation and
  resolution become `confirmed` without claiming balance truth;
- account creation, identity edits, masked-suffix approval, and activation or
  deactivation append immutable `financial_account` temporal snapshots;
- `GET /api/accounts/{account_id}/identity-history` exposes the captured
  evidence, and the Plan identity dialog shows current confidence plus recent
  changes;
- the temporal timeline includes neutral account identity events and explicitly
  prevents temporal-decision overlays from being used to resolve them.
- focused verification remains green: **38 passed, 1 skipped** across account,
  temporal, and migration suites; frontend tests remain **71 passed**, and the
  six responsive/light-dark Plan workspace browser scenarios pass.

The same evidence boundary now covers transaction lifecycle depth:

- pending/initiated/processing/authorized activity is represented as an
  `expected` lifecycle event; failed/declined/cancelled/expired/reversed
  activity is `cancelled`; explicit refunds and reversals are typed observed
  inflows when the source says they settled;
- every lifecycle event carries the exact transaction ID and amount, preserves
  the original ledger row, and refuses temporal-decision overlays;
- transaction source snapshots feed historical-safe timelines, so a later
  correction does not erase the status that was known at an earlier cutoff;
- focused lifecycle coverage now proves pending, failed, refund, reversal,
  decision rejection, historical-safe reconstruction, and no duplicate ledger
  movement.

This closes the former account-identity and transaction-lifecycle gaps in the
knowledge model but does not
raise the **47/100** score: representative connector/account cohorts, forecast
calibration, recommendation outcomes, and hosted operational evidence remain
the proof gates for the 70% target.

### Source-completeness and settled-ledger checkpoint — 2026-08-02

The source boundary is now explicit in both the API and the Financial Health
evidence ledger:

- `GET /api/analytics/source-coverage` reports observed Gmail history, owned
  ledger history, account-identity coverage, and ingestion processing coverage
  with freshness, counts, date ranges, `known`/`partial`/`unknown` completeness,
  limitations, and a recovery target;
- a connected-but-empty source remains in the weighted denominator, so a
  connected provider cannot make a sparse ledger look complete;
- Financial Health carries the same versioned source register, while the UI
  labels it as observed coverage and never implies that Gmail or external
  account history is complete;
- settled-ledger predicates exclude pending, initiated, processing,
  authorized, failed, declined, cancelled, expired, reversed, and other
  non-settled statuses from spend, income, recurrence, and aggregate read
  models while keeping those rows visible in Activity and temporal evidence;
- cash-flow backtest reports expose settled versus unsettled retained rows and
  state the exclusion in their limitations, making forecast calibration honest
  about what actually moved money.

This closes the former “coverage is only a score” and “pending activity can
look like spend” product-trust gaps. It does not raise the **47/100** score:
source coverage is still observed-record evidence, not provider completeness,
and representative parser, forecast, and recommendation cohorts remain the
proof gates for 70% intelligence.

Consolidated verification for this slice is green: backend formatting/lint/type
checks pass for the changed service, schema, and route modules; the focused
analytics, workspace, account, temporal, and migration suite is **49 passed,
1 skipped**; frontend lint, build, and **71 tests across 29 files** pass; and
the six responsive/light-dark financial-roadmap browser scenarios pass. The
full collected backend suite is now also green: **419 passed, 2 skipped** in
467.78 seconds.

The next implementation batch completed without changing the score:

- `POST /api/knowledge/history/backfill` previews or captures a forward-only
  baseline for legacy transaction and financial-account rows that predate
  immutable temporal snapshots, with per-source candidate/missing/skipped/
  captured counts and explicit non-reconstruction limitations;
- cash-flow projections now expose category-mix calibration status/sample depth
  and recurring-income pay-cycle evidence, applying a category baseline only
  when repeated settled history supports it and otherwise staying neutral;
- the Data & settings surface gives users a preview/capture recovery action and
  labels the operation as evidence-only.

These changes improve future historical coverage and model transparency, but a
forward-only baseline cannot retroactively create representative forecast proof.

### Intelligence-readiness and cutoff replay checkpoint - 2026-08-02

The batch now exposes a user-scoped recovery contract rather than another opaque
confidence number:

- `GET /api/analytics/intelligence-readiness` reports explicit
  `ready`/`collecting`/`blocked`/`deferred` gates for observed source coverage,
  immutable temporal history, rolling forecast calibration, recommendation
  outcomes, anomaly adjudication, and representative release evidence.
- Data & settings renders the gate summaries, evidence, next step, and safe
  workspace navigation. A bounded evidence-readiness score is labelled as
  readiness; it is not the repository's 47/100 intelligence score and does not
  claim the 70% target.
- Historical forecast backtests now replay the evidence-gated category-mix
  baseline from cutoff-visible transaction snapshot state. The report counts
  supported and applied cutoff periods and leaves weak category cohorts neutral,
  preventing current category corrections from leaking into historical forecasts.

This closes the missing readiness/recovery surface and makes the new forecast
signal measurable, but it does not raise the maturity score. Representative
parser cohorts, forecast accuracy/coverage, recommendation outcomes, anomaly
adjudication, and hosted operational evidence remain the proof gates for 70%.

Consolidated verification after this batch is green: backend Ruff and mypy
pass across 137 files; full backend regression is **419 passed, 2 skipped**;
frontend lint, production build, and **71 tests across 29 files** pass; and
the responsive/light-dark browser workspace suite is **6 passed** across
mobile, tablet, and desktop. The mobile tab roots now constrain to the viewport
and scroll their tab list internally, removing the 360px dark-mode overflow edge.

### Parser-depth and reconciliation-quality checkpoint - 2026-08-02

The next implementation batch closes two concrete product gaps without
inflating the maturity score:

- Axis and Kotak account/card alerts now use dedicated institution-aware
  patterns, and Paytm, PhonePe, Google Pay, Amazon Pay, Razorpay, and LazyPay
  receipts use a shared digital-payment parser. Parser telemetry records the
  selected parser/version and fallback bit; dedicated routing is not promoted
  to `supported` until representative format cohorts clear the corpus gates.
- Parser evaluation now publishes explicit case cohorts and representative
  case/format/institution coverage. Existing unlabelled fixtures remain
  `synthetic_fixture`, so the strict release gate continues to defer promotion
  until sanitized production-safe cohorts are adjudicated.
- The strict release gate also requires distinct production-safe forecast-user
  metadata (protected hashes only), so repeated reports from one user cannot
  masquerade as a multi-user calibration cohort.
- `GET /api/analytics/reconciliation-quality` exposes observed transaction
  review coverage, statement-line outcomes, verified-account reconciliation,
  duplicate candidates, unexplained movements, and bounded evidence score.
  Intelligence readiness now includes a cross-source reconciliation gate and
  surfaces that evidence in Data & settings.

This improves the truth and source-depth implementation, but it does not raise
the **47/100** score: representative parser cohorts, adjudicated anomaly
feedback, forecast calibration, recommendation outcomes, and hosted operational
evidence remain required for the 70% target. Consolidated tests are intentionally
deferred until the next evidence gates are implemented, per the implementation
plan.

### Mutable issuer-evidence checkpoint - 2026-08-02

The following mutable source records now participate in the append-only temporal
history contract:

- statement lines capture review outcome, created-ledger linkage, issuer plan
  reference, and merchant-resolution state after import, review, and repair;
- card-dispute create/update operations capture issuer status, reference, and
  linked statement-line identity without overwriting prior decisions;
- card-payment-intent create, cancel, and manual-record operations capture the
  user planning status and transfer-group lineage without treating a user
  record as issuer settlement proof;
- the temporal-history readiness view reports transaction, account, issuer-line,
  and card-payment-intent snapshot coverage separately, while the forward-only
  backfill can baseline legacy statement lines and card-payment intentions on request.

Recommendation relevance feedback is also structured (`not_feasible`,
`already_done`, `too_risky`, or `wrong_timing`) and bounded before it can affect
ranking; anomaly adjudications remain append-only and protected from release
metrics until aggregate cohorts exist. Parser, forecast, anomaly, and
recommendation release artifacts now have protected export commands; the
forecast exporter uses keyed user hashes (the release gate rejects raw user IDs)
and a reviewed roster, while the other
exports omit user/source identifiers and small cohorts. These changes close
implementation and evidence-collection gaps, but the score remains **47/100**
because representative parser/forecast/recommendation cohorts, complete
mutable-source coverage, and hosted operations evidence are still required.
Consolidated verification remains deferred until the next evidence gates are
implemented.

The connector contract now records provider query coverage on every Gmail sync:
whether pagination was exhausted, whether the configured cap truncated results,
the page count, and the provider result estimate. Health, readiness, and source
coverage surfaces expose that distinction as known, partial, or unknown instead
of treating fetched rows as proof of inbox completeness. The anomaly ruleset is
now `pfis-anomaly-2`: it uses a 24-month robust baseline and prefers repeated
same-calendar-month observations when enough seasonal evidence exists. CI also
publishes a non-strict intelligence release posture artifact so these deferred
proof gates remain visible during development.

Focused verification for this slice is clean: Ruff and mypy pass across the
changed parser, temporal-history, readiness, recommendation, release-gate,
financial-position, and temporal-event modules; Python compilation, the
frontend TypeScript production build, and ESLint on changed UI/API files pass;
the parser corpus scorer is 100/100 exact on existing fixtures; and the strict
gate reports the missing representative cohort as `deferred`; protected
forecast and recommendation exporters produce gate-shaped artifacts without
raw user identifiers, while raw forecast user IDs are rejected by the gate. The full
backend/frontend/browser matrix remains intentionally deferred for the planned
consolidated pass.

### Money/time correctness checkpoint — 2026-07-31

The ledger currency and financial-day foundation is implemented:

- `User.currency` is now an enforced single-ledger contract rather than an
  unused display field.
- Account, balance, transaction, transfer, ATM-cash, parser-ingestion,
  statement, household-expense, and household-settlement paths cannot post
  money in another currency.
- HDFC statement import is explicitly restricted to INR ledgers instead of
  assigning an account's currency to INR statement values.
- Cross-currency household membership is rejected before shared balances can be
  created.
- Every spend/income read-model predicate excludes legacy rows whose currency
  differs from the owning user's ledger; those rows remain visible for repair.
- Monthly aggregate caches carry the `single-ledger-v1` contract and currency,
  invalidating older potentially mixed-currency payloads.
- `/api/health/ops` reports aggregate account, balance, and transaction currency
  mismatches as `healthy` or `needs_repair`.
- Parser mismatches enter the recoverable DLQ as
  `ledger_currency_mismatch`, rather than a generic processing failure.
- Users now have a validated IANA timezone with a migration-safe
  `Asia/Kolkata` default and an owned update API.
- Server-local calendar dates have been removed from financial services.
  Default periods, balance freshness, schedule status, recurring analysis,
  forecasts, insights, and empty-workspace cutoffs use the user's financial day.
- Data & settings exposes a labelled, keyboard-accessible Financial day control
  with inline validation and a current-boundary preview.
- Browser financial defaults now use that same boundary for balance snapshots,
  quick activity, card records, bills, commitments, household records, cash-plan
  freshness, workspace periods, daily briefs, and time-sensitive greetings.
- Source transaction and statement dates remain unchanged evidence.

This closes the foundational money/time contract and contributes to the verified
36/100 score above. No further credit is taken until a representative truth
corpus and production-safe telemetry prove the contract across real-world data.

### Data-lifecycle checkpoint — 2026-07-31

The first owned connector exit is implemented:

- Data & settings exposes a confirmed Gmail disconnect whose safe initial action
  is **Keep connected**.
- The confirmation states that imported emails, transactions, and evidence
  remain after the connection is removed.
- PFIS attempts Google provider-token revocation without logging the credential,
  then removes the local connector grant and stops future sync in every outcome.
- The response and toast distinguish confirmed provider revocation from an
  unconfirmed remote result.
- A non-secret connector audit event records revocation status, retained raw
  email count, and derived-record retention.
- Tests prove both provider success and provider-unavailable paths, including
  local grant removal and secret-safe logging.

The second owned lifecycle control is now implemented:

- Data & settings previews schema version 1, included record groups, sensitive
  source evidence, permanent credential exclusions, and secure-storage risk.
- The authenticated, CSRF-protected, rate-limited endpoint returns a no-store
  ZIP with deterministic JSONL payloads and a manifest containing ledger
  currency/timezone, exported fields, entity/row counts, ownership scope, and
  SHA-256 checksums.
- The model-inventory test forces an explicit include/exclude decision for every
  persisted table. Ownership tests prove private cross-user ledgers do not
  enter the archive, while shared household actors are archive-local aliases.
- Password hashes, sessions, OAuth state, Gmail credentials, transient leases,
  and global product reference data are explicitly excluded.

The third owned lifecycle control is also implemented:

- New users default to a 365-day processed-source policy and can select 30, 90,
  180, or 365 days, or explicit keep-until-deleted.
- Shortening the policy requires an irreversible-action confirmation that names
  the cleared content and retained lineage.
- User changes and a system scheduler feed the same durable retention job. The
  sweep clears sender, subject, and body only after successful processing,
  defers unresolved parser failures, and preserves provider IDs, timestamps,
  parser evidence, and transaction linkage.
- Atomic conditional updates plus one non-secret pipeline event per redacted row
  make repeated and concurrent sweeps idempotent.

The fourth owned lifecycle control is implemented:

- Account deletion requires a non-demo browser session created within 15
  minutes, CSRF protection, an exact account-specific typed phrase, and a
  3/hour rate limit. Bearer-only and cross-user requests are rejected.
- PFIS first commits a user-scoped deletion fence, rejects new authentication,
  jobs, and ingestion, disables automatic Gmail sync, and cancels registered
  work already in flight. It then attempts provider revocation; local erasure
  continues with an explicit unconfirmed result if Google is unavailable.
- One table-complete service removes private rows, identities, connector grants,
  and every session. The browser and client query cache are cleared afterward.
- Sole-member households are deleted. Shared households transfer ownership,
  close the departing membership, cancel affected planned settlements, and
  retain only a non-login participant tombstone for shared auditability.
- Tests prove success and provider-failure paths, exact confirmation, recent
  authentication, cross-user isolation, in-flight ingestion cancellation,
  post-fence job rejection, zero private/session access, household
  transfer/removal behavior, and secret-safe terminal audit evidence.

Together, disconnect/revoke, portable export, owned retention, and account
deletion close the planned P0 personal-data lifecycle sequence. Production
privacy/legal review and restore-policy sign-off remain release activities, not
missing lifecycle mechanics.

#### Remaining lifecycle delivery order

1. **Versioned portable export — completed 2026-07-31:** schema version,
   manifest, checksums, explicit model inventory, secret exclusions, ownership
   isolation, and the annotations-only shared-household boundary are covered by
   integration tests.
2. **Evidence-safe raw-email retention — completed 2026-07-31:** owned policy,
   durable scheduled redaction, unresolved-failure deferral, preserved source
   and transaction lineage, irreversible content clearing, and one non-secret
   idempotent audit event per row are covered by integration tests.
3. **Owned account deletion — completed 2026-07-31:** recent authentication,
   typed confirmation, concurrent-work fencing, connector-first revocation,
   complete private/session erasure, deterministic shared-household
   transfer/tombstone semantics, and terminal audit evidence are covered by
   integration tests.
4. **Lifecycle proof — completed for repository scope 2026-07-31:** model
   inventories, retention idempotency/lineage, cross-user isolation, provider
   failure, shared-household behavior, and zero remaining login/session access
   are covered. Staging provider and restore-policy drills remain release gates.

### Product readiness: 61/100

PFIS has a stronger engineering foundation than its product-operating model.

| Area | Current assessment |
| --- | ---: |
| Core workflow breadth | 65 |
| Financial correctness and trust | 65 |
| UX, responsive design, accessibility foundation | 70 |
| Security and privacy controls | 75 |
| Reliability and production operations | 45 |
| User lifecycle, support, consent, export, and deletion | 70 |
| Release quality and performance evidence | 55 |
| Maintainability under continued feature growth | 45 |

The UI already has a calm, credible financial-product direction. The main UX
risk is information breadth and incomplete workflows, not visual styling.

## What is genuinely strong

1. **Trust boundaries:** authenticated scope resolution, ownership checks,
   CSRF, server-side session revocation, secure production configuration, and
   encrypted connector credentials are implemented and tested.
2. **Evidence-preserving ledger:** raw sources, parser versions, confidence,
   correction history, statement matches, transfers, and review states provide
   the right base for explainable finance.
3. **Deterministic financial safety:** PFIS avoids claiming live balances,
   guaranteed forecasts, inferred EMI facts, or bank actions without evidence.
4. **Modern delivery foundation:** React/Vite code splitting, accessibility
   tests, responsive browser projects, bundle budgets, Alembic, PostgreSQL,
   durable jobs, and release scripts are materially beyond a prototype.
5. **Useful domain direction:** the product is organized around position,
   activity, obligations, decisions, and provenance rather than generic KPI
   cards.

These should be preserved while the intelligence layer becomes deeper.

## Highest-priority gaps

### P0 — stabilize the current product baseline

The working tree still contains a large uncommitted cross-cutting feature wave.
The targeted blocking gates and the full backend run are now clean:

- frontend lint, **71 unit tests across 29 files**, and the production build
  pass;
- Black, Ruff, and mypy pass across the affected backend and release-script
  files;
- the single Alembic head is `042_sync_coverage_metrics`;
- `/api/health/ops` derives `healthy`, `degraded`, or `needs_repair` from
  unresolved parser/job/integrity conditions and keeps provider completeness
  warnings visible without falsely declaring the service unavailable;
- `/api/health/capabilities` and Data & settings publish the beta source
  boundary, freshness expectations, and user recovery paths without implying a
  hosted incident feed;
- Data & settings now also surfaces the aggregate operational posture, keeping
  repair-required service checks separate from partial or capped provider
  coverage warnings and routing each issue to its recovery workspace;
- `/api/health/metrics` now exposes bounded process request/error/latency
  metrics with route-template labels and an explicit process scope, giving a
  deployment probe a machine-readable baseline without retaining user data;
- account-link repair, merchant bulk correction, financial-position repair, and
  cross-source duplicate removal now append transaction snapshots, so historical
  backtests do not silently lose direct mutation paths;
- account identity/lifecycle changes append financial-account snapshots and the
  API exposes their current confidence plus capture history;
- pending, failed, refund, and reversal transaction states now appear as typed
  lifecycle evidence in the temporal timeline, with exact transaction links
  and no duplicate ledger effect;
- Data Confidence freshness now combines observed activity with connector state,
  last completed sync age, and unprocessed inbox records, and exposes those
  recovery signals in the evidence ledger;
- budget and card-reminder deletion now use the shared accessible confirmation
  dialog; the reminder form also marks deletion as a non-submit action;
- the parser/classifier benchmark passes its CI thresholds;
- the consolidated current-slice backend suite passes: **67 passed, 1 skipped**;
- 26 non-visual browser scenarios pass across responsive/light/dark projects;
- the full collected backend suite passes: **419 passed, 2 skipped** in 467.78
  seconds.

The new financial-position implementation is concentrated in very large files:
`financial_position_service.py` is about 2,900 lines and
`FinancialPositionSection.tsx` is about 1,600 lines. Transaction, cards, roadmap,
API-client, and type modules have similar growth. This is a regression-risk and
team-velocity issue even where tests pass.

Required outcome:

- one clean integration branch;
- keep formatting, typing, migrations, full backend tests, frontend tests/build,
  and browser tests green as the feature wave is decomposed;
- split orchestration and UI hotspots by domain capability;
- document which roadmap items are production-ready, beta, or experimental
  instead of marking implementation presence as completion.

### P0 — establish measurable financial truth

PFIS cannot claim 70% intelligence until it can measure the accuracy of the data
feeding that intelligence.

Current gaps:

- the 50 extraction and 50 classification cases reach the lower numerical
  target, but additional adjudicated production-safe format diversity is still
  required before calling the corpus representative;
- Axis, Kotak, and major digital-payment senders now route through institution-aware parsers, while remaining institutions still use the generic fallback;
- the corpus scorer now publishes explicit synthetic-versus-sanitized-production
  cohorts and the strict release gate refuses to treat unlabelled fixtures as
  representative evidence;
- precision/recall, field accuracy, confusion, fallback, calibration, support
  tiers, parser versions, and formats are scored, but sample counts are still
  too small for broad source-quality claims;
- live failure/fallback drift alerts exist for email parser source cohorts, and
  digital-statement imports now emit privacy-safe layout rejection reason and
  extractor-version telemetry; a representative statement-layout cohort and
  release threshold are still required;
- source completeness is now explicit for observed records and Gmail syncs now
  retain provider-pagination coverage/truncation metadata, but PFIS still has
  no provider-level proof that an inbox or external account universe is whole;
- operational aggregate quality rates and service posture alerts now cover
  parser drift, unresolved failures, failed jobs, ledger repair, and statement
  rejection rates, with a 20-attempt/25%-layout-rejection operational alert;
  a representative deployment cohort and release threshold are still required
  for promotion decisions;
- reconciliation quality is now measurable per workspace, but it still depends
  on observed rows, explicit review outcomes, and two verified balance snapshots;
- parse confidence is partly a field-presence score, not an empirically
  calibrated probability of correctness.

Required outcome:

- a sanitized golden corpus of at least 100–150 representative cases across
  supported institutions and negative/non-transaction examples;
- field-level expected outputs and adjudicated ambiguous cases;
- precision, recall, field accuracy, fallback rate, duplicate rate, review rate,
  and calibration error produced in CI;
- production-safe aggregate drift and coverage metrics;
- support tiers: **verified**, **supported**, **best effort**, and **unsupported**.

### P0 — complete personal-data lifecycle semantics

These are correctness and trust requirements, not optional enhancements.

- The single-ledger currency and owned financial-timezone contracts are now
  implemented across writes, aggregate read models, caches, operational health,
  and browser financial defaults.
- Gmail connect/reauthorize, owned disconnect/provider revocation, a versioned
  portable full-data copy, owned raw-email retention, and recent-auth account
  deletion are implemented.
- Processed raw financial-email content now has a 365-day default and owned
  30/90/180/365-day or keep-until-deleted policy. Redaction preserves lineage,
  defers unresolved failures, and emits idempotent non-secret audit evidence.
- Statement PDFs follow extract-then-delete; the wider personal-data lifecycle
  now has explicit disconnect, export, retention, and deletion boundaries.

Required outcome achieved for repository scope. Staging provider revocation,
backup/restore policy, privacy/legal review, and operational evidence remain
release gates.

### P1 — replace monthly heuristics with temporal financial knowledge

The existing recurrence service is a useful seed, but 70% intelligence requires
an event-aware model.

Build a versioned knowledge layer for:

- income streams and pay-cycle windows;
- bills, subscriptions, EMIs, card due dates, and irregular reserves;
- account and instrument identity confidence;
- merchant identity and alias history;
- transaction lifecycle: authorization, posted, reversed, refunded, disputed
  (pending/failed/refund/reversal typed events are covered; transaction status,
  statement-line review/settlement lineage, and card-dispute status now append
  immutable source history). Broader issuer settlement and provider lineage
  remain. Settled-status semantics keep non-settled rows visible without letting
  them change spend/income read models;
- expected versus observed events;
- freshness, coverage, conflicts, and user confirmation;
- explicit causal links from every derived signal to source records.

Do not create a generic graph platform. Use typed PFIS domain records and
versioned read models that can be recomputed from retained evidence.

### P1 — make forecasting a backtested product capability

The current projection uses settled observed daily pace, historical median/MAD, and
recurring totals. It is transparent but shallow.

The next forecasting engine should:

- model dated expected income and obligations;
- separate fixed, semi-variable, and discretionary spending;
- account for day-of-week, pay-cycle, month position, and category seasonality
  only when sample size supports them;
- include approved irregular reserves and verified balances;
- produce ranges from measured historical error rather than a fixed percentage
  fallback alone;
- backtest every ruleset against rolling historical cutoffs;
- expose forecast error, coverage, and confidence by horizon;
- fall back visibly when evidence is insufficient.

Target: median absolute percentage error below 20% for users with at least
3 complete months, while reporting coverage and excluding periods that cannot be
evaluated honestly.

### P1 — turn recommendations into decisions and measured outcomes

Current recommendations mostly say “review,” “slow down,” or “open” a section.
Move to an explicit decision contract:

```text
signal -> evidence -> consequence -> feasible action -> expected range
       -> user decision -> later observed outcome
```

Each recommendation needs:

- the financial consequence if ignored;
- the smallest feasible action;
- conflicts with goals, cash needs, or other recommendations;
- expected impact as a range, not generic copy;
- freshness and confidence;
- dismiss/snooze/accept/not-relevant feedback;
- an outcome check that does not use manipulative engagement metrics.

Ranking should optimize consequence, confidence, urgency, reversibility, and
user intent. It should avoid repeating advice the user rejected or cannot act on.

### P1 — complete product workflows, not just data forms

Important UX/product gaps found in the current implementation:

- demo sync now shifts sample evidence relative to the user's financial day so
  it does not age into an empty current-month workspace; the Overview surface
  provides a guided first-success path for connect, add, and confirm;
- several destructive actions execute immediately or rely on browser
  `window.confirm` rather than a consistent accessible confirmation/undo flow;
- transaction type/search/category/sort state is now reflected in shareable URL
  query parameters while preserving the existing section hash; review filters
  and pagination remain local to the current session;
- plan surfaces have become very broad and contain large multi-domain
  components, increasing cognitive load and regression risk;
- browser coverage is concentrated in one premium-workspace specification;
- the staging Lighthouse and visual-baseline approval gate is still pending;
- there is no complete in-product support, data-correction escalation, connector
  troubleshooting, or incident-status journey.

Required outcome:

- rolling or relative demo dates (**completed 2026-08-02**) and a guided
  first-success path;
- consistent confirmation/undo for destructive actions;
- URL-backed filters and shareable product state where privacy permits;
- task-level browser coverage for connect, sync, review, statement import,
  reconciliation, cash plan, card payment, export, disconnect, and deletion;
- a clear beta label for narrow institution/layout support;
- user-facing recovery paths for stale data, parse drift, connector expiry, and
  conflicting evidence.

### P1 — operate the product in a real environment

Repository controls are production-candidate quality, but production evidence is
not present:

- no completed release record;
- no named operational owners in repository evidence;
- no verified hosted backup/restore drill;
- no hosted metrics, tracing, alert routing, or incident process;
- no staging load, soak, failure-recovery, or rollback result;
- no approved release-host Lighthouse baseline;
- no infrastructure definition or deployed environment contract in this
  repository.

Required outcome:

- staging and production environments with secret management, managed
  PostgreSQL, backups, restore evidence, TLS/network policy, structured logs,
  metrics, alerts, and on-call ownership;
- service-level objectives for API availability, sync freshness, parse latency,
  job exhaustion, and data correctness;
- load and failure tests based on expected transaction and user volumes;
- tested rollback and incident runbooks.

### P2 — add grounded conversational intelligence only after the truth layer

The current `/api/ai/explain` route is deterministic templating over frontend
supplied title/description/metrics. The guidance query supports a small
allowlisted grammar. These are safe scaffolds, not a financial assistant.

After P0 and P1 gates pass, a hosted or local model may be added for:

- natural-language intent parsing;
- composing explanations from server-fetched, user-scoped evidence;
- comparing scenarios;
- navigating the product;
- drafting questions the user should verify.

It must use typed tools, never receive OAuth secrets or unrestricted raw email,
cite PFIS evidence, preserve deterministic calculations, separate facts from
language generation, and refuse regulated or unsupported advice. Every answer
needs an evaluation set for factuality, scope, privacy, and unsupported claims.

An LLM must not calculate balances, silently categorize transactions, or
substitute fluent wording for missing data.

## Roadmap from 47% to 70% intelligence

### Gate 0 — trustworthy baseline (1–2 weeks)

1. Integrate or isolate the current working-tree feature wave.
2. Clear formatting and all 42 type errors.
3. Run the full CI matrix, migrations, browser suite, and release gates.
4. Split the largest service/component modules around existing domain
   boundaries.
5. Mark every user-facing capability as stable, beta, experimental, or deferred.

Exit: one reproducible green build and no ambiguous release scope.

### Phase 1 — truth and evaluation foundation (3–5 weeks)

1. Build the golden parser/classifier/reconciliation corpus and scoring CLI.
2. Add field accuracy, calibration, fallback, duplicate, review, and drift
   metrics.
3. Enforce ledger currency semantics and user timezone. **Completed 2026-07-31.**
4. Add connector/data lifecycle controls. **Completed 2026-07-31: disconnect,
   revoke, portable export, evidence-safe retention, and account deletion.**
5. Surface a user-visible Data Confidence breakdown with exact remediation.
   **Completed 2026-07-31.**

Expected intelligence score: **45–50**.

### Phase 2 — temporal knowledge engine (4–6 weeks)

1. Introduce typed expected/observed financial events. **Completed 2026-07-31.**
2. Upgrade recurring, income, obligation, reversal/refund, and account identity
   models.
3. Consolidate duplicated heuristics into versioned recomputable read models.
4. Add conflict resolution and confirmation workflows. **Persistence and API
   contract completed 2026-07-31; end-user review workflow remains.**
5. Backfill from retained evidence with dry-run and audit reports. **Read-only
   recomputation audit completed 2026-07-31; forward-only legacy snapshot
   baseline backfill is now implemented, while historical reconstruction of
   pre-capture states remains impossible without retained evidence.**

Expected intelligence score: **55–60**.

### Phase 3 — decision intelligence (5–7 weeks)

1. Build and backtest event-timed cash forecasting. **Event consumption, a
   leakage-safe retained-ledger rolling backtest, evidence-gated category-mix
   calibration, and recurring-income pay-cycle signals are implemented;
   temporal as-of evaluation, representative thresholds, and calibration
   cohorts remain.**
2. Add category/merchant anomaly baselines with materiality and seasonality.
   **The versioned detector now uses a 24-month robust baseline with explicit
   same-calendar-month evidence; adjudicated representative calibration remains.**
3. Implement the recommendation decision/outcome contract. **Explicit
   decisions, relevance feedback, immutable user-reported outcomes, supported
   automatic metric comparisons, the outcome-review journey, conflict-aware
   consequence context, capped personalization, and a minimum-sample
   aggregate-effectiveness report completed 2026-07-31;
   representative eligible cohorts and adaptive ranking remain.**
4. Expand scenarios to goals, obligations, reserves, and debt trade-offs.
5. Add offline evaluation and release thresholds for every intelligence
   ruleset.

Expected intelligence score: **68–72**.

### Phase 4 — product operations and completeness (4–6 weeks, partly parallel)

1. Complete onboarding, demo, correction, support, export, disconnect, and
   deletion journeys.
2. Expand task-level browser/accessibility coverage and approve release
   baselines.
3. Deploy staging observability, alerts, backup/restore, load/soak, and rollback.
4. Establish beta cohorts and a structured accuracy-feedback process.
5. Publish supported-source and data-freshness expectations.

Product-readiness target: **75+** with intelligence held above **70**.

### Phase 5 — grounded assistant (optional, separately gated)

Add typed, evidence-citing natural-language interaction only after the preceding
accuracy, privacy, consent, and cost gates pass.

## Definition of 70% intelligence

PFIS reaches the target only when all of the following are true:

- at least 95% of transactions for declared supported formats are correctly
  classified as financial/non-financial;
- critical fields (amount, direction, date, account/instrument) achieve at least
  98% accuracy on the golden corpus;
- merchant/category accuracy reaches at least 90% after user-specific rules,
  with unknowns preserved rather than guessed;
- fallback, duplicate, review, and reconciliation rates are measured by source;
- forecast backtests publish coverage and error, with MAPE below 20% for eligible
  users;
- recommendation acceptance/relevance and later financial outcome are measured
  without behavioral manipulation;
- every calculated/forecast/recommended value exposes evidence, freshness,
  ruleset, sufficiency, and assumptions;
- correction feedback changes future behavior safely and can be inspected or
  forgotten;
- drift, stale data, failed jobs, and exhausted retries generate operational
  alerts;
- no cross-currency or cross-timezone totals are silently wrong;
- privacy lifecycle, export, disconnect, and deletion are complete.

## First implementation backlog

| Order | Workstream | Deliverable | Primary metric |
| ---: | --- | --- | --- |
| 1 | Release stabilization | Clean format/type/test/browser/release gates | 100% blocking gates green |
| 2 | Intelligence benchmark | Golden corpus and evaluation report | Accuracy and calibration by source/field |
| 3 | Money/time correctness | Ledger currency and timezone contract | 0 silent mixed-currency or boundary errors |
| 4 | Data lifecycle | Disconnect, revoke, export, retention, deletion | 100% lifecycle integration tests |
| 5 | Parser depth | Dedicated high-volume institution formats | ≥95% supported-format classification |
| 6 | Coverage model | User-visible observed-source completeness/freshness/conflict score | Remediation available for every low score |
| 7 | Temporal knowledge | Expected/observed income and obligation events | Event precision/recall and confirmation rate |
| 8 | Forecast v2 | Rolling backtest and calibrated intervals | Eligible-user MAPE <20% |
| 9 | Recommendation v3 | Decision/outcome contract and feedback | Relevance, feasibility, and measured impact |
| 10 | Product operations | Staging SLOs, alerts, restore, load, rollback | Release record fully evidenced |

## Explicit non-goals for this stage

- adding more dashboard sections without closing a measured workflow gap;
- claiming broad bank support through generic fallback alone;
- using an LLM to compensate for weak parsing or missing evidence;
- initiating bank payments, cancellations, or disputes;
- inferring investment prices, live balances, loan terms, or regulatory advice
  without an approved source and separate review;
- collecting product analytics before consent, minimization, retention, and
  deletion are designed.
