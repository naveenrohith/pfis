# Financial Position Roadmap Implementation

**Implementation baseline:** 29 July 2026  
**Currency scope:** INR  
**Supported statement scope:** one reviewed, unencrypted HDFC digital
credit-card PDF layout

This document maps every approved roadmap phase to its implementation, reason,
observable outcome, and release evidence. It complements the product intent in
`feature-ideas-roadmap.md`; the API, data-model, parser, workflow, and security
documents remain the normative technical contracts.

The settlement-aware current-position slice is now implemented: bank and card
positions expose observed anchors, eligible settled roll-forward, pending
impact, source-coverage checks, confidence, and review reasons; Cash Plan and Net Worth consume that
read model and fail closed when evidence is unsafe. Reconciliation now uses the
same settled/cutoff policy and can retain same-day observations from distinct
sources without overwriting append-only facts. Connector-backed live balances,
coverage-complete reconciliation, cross-account matching, and representative
cohort proof remain open work; deterministic cross-account candidate discovery
and explicit confirmation are now available, while representative matching
evidence remains open. Connector observations now have a first-class
source/cadence/coverage contract (`AccountBalanceSource`) and require a stable
source record identity so retries are idempotent; a real institution provider
is still required before PFIS can claim a live balance. Connector batches also
persist incomplete or failed refreshes as source-health errors, including when
the provider returned no balance fact, so a failed refresh cannot masquerade as
fresh coverage. `BalanceSyncService` now provides the provider-neutral runner:
it validates mapped owned accounts, resumes an opaque source cursor when all
accounts agree, ingests the batch, and records non-secret lifecycle audit events.

The ReBIT deposit v2.0.0 adapter now implements the next boundary slice: it
maps `linkedAccRef`, preserves `currentBalance` and `balanceDateTime`, carries
the transaction window into coverage, and rejects malformed or negative
evidence without clamping. It remains transport/consent neutral; no provider
credential or raw payload is persisted, and a credit-card issuer adapter is
still required for outstanding and available-credit semantics.

## Current 85% continuation checkpoint — 3 August 2026

`GET /api/balance-provider/status` now makes the remaining execution boundary
visible: it reports account mapping, connector-source freshness, and coverage
for owned accounts without exposing credentials. `refresh_supported` remains
false until a real transport, consent/revocation lifecycle, and provider
registry are configured, so the UI can offer an honest connection next step
without presenting transaction-derived amounts as live.

The provider execution slice now also persists non-secret consent lifecycle
state and exposes `/api/jobs/balance-refresh` as an idempotent read-only job
boundary. A registered connector factory and active, unexpired consent are
required; no route accepts credentials, and an unconfigured provider returns a
safe conflict instead of scheduling a pretend refresh.

Typed issuer-card observations now extend that boundary. A card-capable
connector can supply current outstanding plus independent billed-due, pending,
credit-limit, and available-credit facts. Current outstanding updates the
liability position; the other fields are preserved as append-only provider
evidence and surfaced separately from statement math.

The Net Worth surface now consumes the lifecycle response instead of showing a
static integration note. When a provider is registered it exposes the
provider-specific consent state (not connected, pending, expired, or active),
offers a consent request or reconnect action, and only enables **Refresh
balances** when consent is active and every owned account is mapped. Refresh
requests carry an idempotency key and invalidate bank, card, forecast, Cash
Plan, and Net Worth read models after the job is accepted. A pending consent or
missing transport remains an explicit next step; no button or copy labels a
transaction roll-forward as live.

Guidance queries now use the same provider evidence when it exists: bank cash
and card outstanding/available-credit answers distinguish provider-observed
facts from statement-backed estimates, and mixed or incomplete card coverage
remains explicitly qualified. The conversational surface therefore cannot
silently downgrade a provider fact to a statement estimate or upgrade an
estimate to a live claim.

The next Phase 3 slice is now implemented as `BalanceForecastService` plus
`GET /api/accounts/{account_id}/balance-forecast`. It gives each bank or card a
deterministic daily path from the canonical observed/estimated position.
Explicit dated income, confirmed commitments, mapped card-payment intentions,
and sourced liability schedules are shown as scheduled movement; a reviewed
settled-activity baseline is applied only after three or more eligible events.
Every point carries expected/low/high values, source IDs, and risk state.
Missing anchors return `needs_anchor`; stale, incomplete, or reconciliation-
blocked positions return `needs_review` rather than a reassuring number. The
Plan surface now exposes the path and its assumptions. This is still a
forecast, not live issuer/provider data; provider connection and representative
calibration evidence remain release gates.

Daily forecast accountability is now available through immutable
`balance-forecast/snapshots` and `balance-forecast/outcomes` routes. A snapshot
stores the complete point path at a financial-day cutoff; later exact-date
verified observations can be evaluated for absolute error and interval
coverage. Missing observations remain pending, so this instrumentation does
not manufacture calibration evidence. The intelligence-readiness forecast gate
now consumes these counts and metrics and stays in evidence-collection status
until at least three exact-date outcomes exist; representative cohort proof is
still a separate release gate.

Balance observation accountability now also persists one immutable
`AccountBalanceReconciliation` interval for each newest consecutive pair of
verified observations. It stores the settled movement used to explain the
closing balance, excluded transaction IDs, and signed residual drift. A zero
residual with no excluded activity is `reconciled`; pending, unreviewed, or
unexplained activity is `needs_review`. Late source knowledge never rewrites an
already captured interval. `scripts/export_balance_reconciliation_evidence.py`
now emits only keyed cohort membership and aggregate interval metrics, and
`scripts/intelligence_release_gate.py` can fail closed unless an independently
attested roster reaches the initial 10-user/100-interval/6-institution floor
with the published residual thresholds. This is evidence infrastructure, not
provider-backed live balance data; until a transport- and consent-backed
connector is enabled, current values remain explicitly estimated.

The next card-specific slice is also implemented as
`GET /api/cards/{account_id}/due-runway`. It compares an issuer-stated total due
with the conservative path of the explicitly selected funding account, keeping
minimum due, estimated outstanding, statement-date available credit, planned
payment intent, and forecast cash separate. It fails closed when the statement,
funding account, or funding anchor is missing; it never claims to have sent or
confirmed a payment. The card workspace now also shows the proof between the
statement anchor and estimated outstanding: paid since statement and signed net
unbilled activity, with unsettled/unreviewed rows still keeping the position in
review. The same read model now exposes deterministic minimum-due and full-due
payment scenarios, including any planned-intention credit, additional amount,
remaining billed due, and conservative post-payment balance. These scenarios are
planning comparisons only, not payment instructions or issuer-live available
credit.

## Shared foundation

The ledger now separates:

- `transaction_type`: debit, credit, or refund;
- `payment_rail`: UPI, debit card, ATM, transfer, wallet, or other;
- `card_event`: purchase, payment, refund, cashback, fee, tax, interest,
  reversal, or none;
- `financial_account_id`: the owned bank/card/loan/pay-later/cash/investment
  product that funded or received the event.
- `is_accounting_adjustment` and `ledger_subtype`: issuer conversion/anatomy
  rows that remain visible evidence but are excluded from spend/income.

The legacy `payment_method` remains in the API as a compatibility projection.
New financial calculations consume the explicit account, direction, rail, and
card-event fields.

Imported evidence carries source kind/identifier, parser or extractor version,
confidence/review state, and correction history. Statement outcomes are
`matched`, `newly_imported`, `ignored_by_rule`, or `needs_review`.

## Phase implementation map

| Phase | What and where | Why | User-visible outcome | Release evidence |
| --- | --- | --- | --- | --- |
| 0 — Trust foundation | Models/migrations `018`, `022`–`026`; parser contracts; `TransactionService`; `AccountService`; Data → Statements account linking; Activity → Review | Prevent direction, transport, product identity, and issuer accounting rows from being conflated | Explicit instrument links; user-confirmed account identity; approved rules repair uncorrected history; ambiguous evidence waits for review; corrections have history | Account-rule/invariant, parser, ownership, correction, accounting-effect, and reverse-dedup tests |
| 1 — HDFC statements | `hdfc_statement_extractor.py`; statement models/service/routes; Data → Statements; Plan → Cards; Activity → Review | Establish an official monthly liability and reconcile alert emails | Due/minimum/due date/limit snapshot, line anatomy, coverage, history, and review queue without duplicate purchases | De-identified extractor fixtures, fingerprint idempotency, exact field/line assertions, five real unique statements checked |
| 2 — Bank position | Verified balance snapshots; `account_position`; Plan → Verified position | Answer what is verified without pretending alert coverage is a live bank balance | Latest verified balance with source/as-of date, flow/rail evidence, snapshot-to-snapshot proof, and focused duplicate/unlinked/unexplained review items | Tests cover newer unverified observations, both transfer legs, and deterministic review items |
| 3 — Cash Plan | `CashPlan`, `Commitment`, read model; Plan → Safe to spend; Today Financial Horizon | Distinguish safely flexible money from money already constrained | Inline account identity/balance/income setup; verified balance − confirmed pre-income commitments − approved reserves; stale/missing inputs block the total in both Plan and Today | Tests cover product gating, no/stale balance, missing income, commitment lifecycle, reserves, and cross-user scope |
| 3b — Daily balance path | `BalanceForecastService`; `AccountBalanceForecastResponse`; Plan → Outlook | Move from month-end totals to account-level cash/liability runway without claiming live data | 30-day expected/uncertainty path from observed/estimated position, dated obligations/income/payment intents, reviewed history baseline, shortfall/limit-pressure states, and fail-closed anchor/review status | Focused bank/card/no-anchor tests pass; representative horizon calibration, interval coverage, and risk precision remain open |
| 4 — Liabilities/EMIs | `Liability`, `LiabilityScheduleItem`; schedule confirmation/progress API/UI; Plan → Liabilities | Show debt burden without guessed progress | Nullable sourced debt fields; complete schedules only after explicit rows; upcoming rows feed Cash Plan and paid/skipped rows remove only their linked commitment | Tests reject false completion, unordered/duplicate/repeated schedules, prove linked EMI projection, and exercise instalment lifecycle |
| 5 — Future reserves | `ReservePlan`; Cash Plan reserve allocation view | Keep known irregular expenses in the spendability decision | Draft, explicit approval/removal, pause/restore lifecycle; only approved active monthly allocations reduce flexible money | User-scoped lifecycle tests and Cash Plan calculation assertions |
| 6 — Card/cash extensions | Card preferences, payment-intent lifecycle, sourced fee/milestone calendar, disputes, deterministic activity centre; cash product and ATM transfer | Turn verified card data into safe actions and prevent cash double counting | Utilisation guardrail, explicit rewards, correctable/removable renewal/annual-fee/fee-reversal/milestone reminders with settled-spend evidence, cancellable payment intent, explicit idempotent manual transfer recording, disputes; ATM moves bank→cash and later cash purchase is spend | Card service/API tests, transfer invariants, mobile Card workspace |
| 7 — Daily management/reporting | Notes/tags, split allocations, bills/subscriptions, budget evidence, health checklist, unusual-spend signals, monthly cache/export | Complete daily workflows on the trusted ledger | Context-rich activity, bill status, explainable alerts, printable/CSV monthly reporting | User-scope, split-total, deterministic-signal, report, React interaction, lint/build tests |
| 8 — Household/payoff | `RoadmapService`; household tables/routes/UI; deterministic payoff comparison | Isolate the highest-privacy workflow from private financial evidence | Explicit owner/member/viewer access and role changes, read-only viewers, leave/removal, annotation-only expenses, record/cancel settlement lifecycle, guarded deletion; avalanche/snowball scenarios with assumptions | Viewer/owner/role/privacy/removal/deletion tests and incomplete-liability payoff states |

## HDFC statement validation record

Eight supplied PDF files were inspected. Their SHA-256 fingerprints resolved to
five unique documents; the three byte-identical copies did not create imports
or transactions. All five unique fingerprints are present for the canonical
user-owned HDFC credit-card account.

The five statement periods end from 22 March through 22 July 2026. Together
they contain 108 extracted domestic lines:

| Outcome | Count | Meaning |
| --- | ---: | --- |
| Matched | 19 | Reconciled to one existing ledger event |
| Newly imported | 53 | Created one statement-backed ledger event |
| Needs review | 36 | Conservatively withheld, including unidentified card-payment legs |
| Total | 108 | Every line has an explicit outcome |

There are 19 match records pointing to 19 unique transactions and 53
statement-created transactions. A controlled cross-source audit using card
identity, exact amount/direction, ±3 calendar days, and normalized merchant
found zero remaining Gmail/statement duplicate candidates.

The extractor retained structured values, fingerprints, version, and review
evidence only. It did not retain a source PDF, PDF password, full card number,
address, or contact data.

## Intelligence and experience hardening

The July hardening pass replaced raw-descriptor presentation with canonical
merchant evidence, added HDFC gateway/debit-card/UPI-credit counterparty shapes,
and grouped observed card EMI principal, interest, tax, fees, conversion, and
pre-closure rows by issuer plan reference. HDFC alert parser version 4 extracts
explicit reversal counterparties, separates ATM movement from debit-card
purchase semantics, and rejects maintenance/travel-document amount examples.
Resolver version 3 gives canonical merchant names deterministic precedence over
legacy shared aliases, rejects
sentence/newsletter boilerplate as merchant identity, and preserves explicit
user corrections. Historical repair projected 34 sourced EMI component rows,
marked three conversion rows as accounting adjustments, classified four
explicit card/pay-later repayments as non-spend, repaired 245 explicit legacy
rail/card-event/status classifications, and quarantined 28 proven newsletter,
maintenance, or travel-document false positives as recoverable
`ignored_by_rule` evidence. Two email-observed ATM withdrawals are visible
non-spend adjustments awaiting a user-selected cash pocket. The verified live
ledger contains 301 active transactions and an all-zero repeat repair preview;
all monthly spend, income, net, and transaction counts remained unchanged by
the semantic repair.

Refunds now net against spend; transfers, card payments, ignored rows, and
accounting adjustments remain visible but do not inflate spend/income. Insights
is now one continuous monthly investigation surface rather than a wall
of independent metric cards. Plan exposes five decision paths: Safe to spend,
Verified position, Debt & cards, Commitments, and Outlook & guardrails. Route
chunk recovery, a workspace error boundary, transient-query retry, reconnecting
sync events, online/visibility refresh, and a heartbeat address stale/blank
workspace behavior.

## Critical invariants

1. Explicit masked identifiers, connector identity, or a user-confirmed rule
   outrank keywords. An “amount debited” phrase supplies direction only.
2. Statement/Gmail arrival order is symmetric: either source can arrive first
   and converge on one ledger event.
3. Card payments are transfers only after the paying bank account is known.
4. Transfers remain visible at both accounts but never count as income/spend.
5. Bank positions use verified snapshots and show their observation date.
6. Stale or incomplete Cash Plan inputs yield the same action state in Plan and
   Today Financial Horizon, not a forecast.
7. Liability progress requires a complete issuer or user-confirmed schedule;
   paid/skipped status changes only the traceably linked commitment.
8. Active reserves reduce flexible money only after explicit approval.
9. Card payment plans and disputes never perform issuer or bank operations.
10. Household members never receive private transaction or source evidence by
    default.

## Product surfaces

- **Today:** trustworthy Financial Horizon derived from Cash Plan readiness.
- **Activity → Review:** ordinary low-confidence activity plus statement
  evidence, candidates, card-payment account selection, and decision history.
- **Plan → Verified position:** explicit product identity, balance
  observations, snapshot proof, rail evidence, and focused reconciliation
  items.
- **Plan → Cards:** official statement conclusion, statement anatomy, coverage,
  limits, ledger/history, activity signals, preferences, reminders, disputes,
  and payment intent. A planned intention can be cancelled, or explicitly recorded after the
  real payment as one paired bank-to-card transfer. Repeating that record action is idempotent,
  and PFIS never implies that it initiated issuer or bank activity.
- **Plan → Cash Plan:** funding account, next income, commitments, reserves, and
  flexible money.
- **Plan → Liabilities:** sourced debt fields and explicit complete-schedule
  confirmation.
- **Plan → Bills & safety / Household:** daily obligations, checklist, payoff,
  explicit member access, shared annotations, settlement resolution, and
  guarded household deletion.
- **Data & settings → Statements:** supported-layout upload with
  extract-then-delete disclosure and import result counts.

## Explicit exclusions

PFIS does not claim a live bank/card balance from alert email, scrape bank
portals, store bank credentials, parse arbitrary statement formats, retain
statement PDFs, initiate card payments, block/dispute transactions at an
issuer, expose standalone UPI/debit-card positions, aggregate multiple bank
accounts into the initial Cash Plan, or provide generic AI financial advice.
