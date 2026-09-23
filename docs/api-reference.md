# PFIS API Reference

All application routes are mounted under `/api`. Authentication is optional in
local/demo mode (`AUTH_REQUIRED=false`). The browser uses an opaque `HttpOnly`
session cookie plus `X-CSRF-Token` for mutations; bearer JWTs remain supported
for API compatibility.
User-scoped routes accept a `user_id` and resolve the effective user via
`resolve_user_scope(user_id, current_user)`.

Common error codes: `400` bad state, `401` unauthenticated, `403` forbidden,
`404` not found, `409` conflict/duplicate, `500` server error. Browser OAuth
callbacks use stable dashboard query codes for recoverable provider errors.

## Financial position

`POST /api/financial-intelligence/repair` performs user-scoped deterministic
historical repair. `{ "dry_run": true }` previews merchant, provenance,
explicit transaction-semantic, EMI-component, duplicate-merge, fuel-surcharge
reconciliation, liability-sync, and conflict counts. `dry_run=false` applies
only improvements that do not overwrite the corresponding field-specific user
corrections.
A duplicate merge requires unique cross-source statement/email evidence and
records an immutable statement review decision. The response also reports
`false_positive_transactions_removed`; for compatibility this counter means
removed from the active ledger, not physically deleted. Eligible rows are
quarantined as recoverable `ignored_by_rule` evidence with correction history.

Statement-line import, review, and repair, deposit-line review/import, plus
card-dispute create/update, append immutable `TemporalSourceSnapshot` rows.
These snapshots preserve issuer/bank review and settlement lineage for cutoff
evaluation; they do not turn current status into evidence that an external
provider feed was complete.

`GET /api/cards/{account_id}` includes `emi_plans`. Each plan reports only
observed issuer components (`observed_principal`, `observed_interest`,
`observed_tax`, and `observed_fees`) plus source lines. Its
`schedule_completeness` remains `partial` until a complete issuer or
user-confirmed schedule exists.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET`, `POST` | `/api/account-link-rules` | List or approve a user-owned masked-suffix mapping and repair uncorrected historical evidence. |
| `DELETE` | `/api/account-link-rules/{rule_id}` | Deactivate a future account-link rule without rewriting linked history. |
| `PATCH` | `/api/accounts/{account_id}` | Explicitly resolve or update a user-owned product identity; validated products derive the correct asset/liability direction. |
| `GET` | `/api/accounts/{account_id}/identity-history` | Read append-only account identity and activation/deactivation evidence for the owned account. |
| `GET` | `/api/accounts/{account_id}/position` | Verified position, flow/rail evidence, snapshot proof, and focused deterministic reconciliation items. |
| `GET` | `/api/accounts/{account_id}/balance-reconciliations` | Immutable consecutive verified-observation intervals with eligible movement, excluded activity, residual drift, and review reason codes. |
| `GET` | `/api/accounts/{account_id}/balance-forecast` | Account-level daily expected/low/high path from the canonical observed or estimated position; fail-closed anchor/review states. |
| `POST`, `GET` | `/api/accounts/{account_id}/balance-forecast/snapshots` | Freeze or list immutable forecast cutoffs for prospective calibration. |
| `POST`, `GET` | `/api/accounts/{account_id}/balance-forecast/outcomes`, `/outcomes/evaluate` | Match later verified observations to frozen points and report absolute error and interval coverage. |
| `GET`, `POST`, `PATCH` | `/api/commitments`, `/api/commitments/{id}` | Manage source-labelled confirmed commitments. |
| `GET`, `PUT` | `/api/cash-plan` | Read or configure the primary account and next confirmed income date. |
| `GET`, `POST`, `PATCH` | `/api/reserves`, `/api/reserves/{id}` | Manage draft/approved and active/paused future-expense reserves. |
| `GET`, `POST` | `/api/liabilities` | Manage sourced loan, pay-later, card, and EMI obligations. |
| `GET` | `/api/liabilities/overview` | Read the obligation ledger with confirmed monthly debt separated from statement-observed EMI anatomy and unknown schedule fields. |
| `GET` | `/api/liabilities/{liability_id}/schedule` | Read the user-owned instalment evidence for one liability. |
| `POST` | `/api/liabilities/{liability_id}/schedule/confirm` | Permanently confirm a complete ordered schedule and project its upcoming rows as linked Cash Plan commitments. |
| `PATCH` | `/api/liabilities/{liability_id}/schedule/{item_id}` | Mark one confirmed instalment upcoming, paid, or skipped and update only its traceable Cash Plan commitment. |
| `POST` | `/api/statements/detect` | Read-only preflight for statement text; returns institution, product type, format candidate, import-support status, evidence codes, observed activity rails, and a bounded analysis preview without persisting the source. Generic card or bank/deposit shapes remain candidates unless their strict reviewed profile passes. |
| `POST` | `/api/statements/detect/upload` | Read-only in-memory preflight for an unencrypted PDF; embedded text is preferred and a bounded local OCR fallback is used when configured. Source bytes/text are discarded, and only a reviewed issuer profile or strict reconciled generic table can pass the import gate. |
| `POST` | `/api/statements/hdfc/detect` | Read-only HDFC PDF document classifier; embedded text is preferred and bounded local OCR is optional. Returns redacted card/deposit kind, reviewed format, importability, stable reason, and matched signal codes without extracting values or persisting anything. |
| `POST` | `/api/statements/review/text` | Persist a user-owned, redacted analysis artifact for a statement that needs account/layout review; no account mapping, transaction, statement row, source text, or uploaded bytes are persisted. Repeated fingerprints are idempotent. |
| `POST` | `/api/statements/review/upload` | Extract an unencrypted PDF in memory (with bounded local OCR when available) and persist only the same bounded redacted analysis artifact; no source bytes/text or ledger activity are retained. |
| `GET` | `/api/statements/review`, `/api/statements/review/{review_id}` | List or read owned durable analysis artifacts, optionally filtered by `ready_to_import` or `pending_review`, with detection metadata, analysis totals, redacted preview lines, and explicit next review state. |
| `GET` | `/api/review/deposit-statement-lines` | List owned bank-statement rows whose rail evidence was not explicit enough for automatic import. |
| `PATCH` | `/api/deposit-statement-lines/{line_id}/review` | Explicitly classify one unresolved bank row as UPI, debit card, ATM, or transfer and import it, or ignore it. Decisions are user-scoped, idempotent, append-only, and never accept the unsupported `other` rail as a write permission. |
| `POST` | `/api/statements/import/text` | Detect and atomically import a write-enabled HDFC credit-card, reviewed HDFC deposit, issuer-neutral reconciled tabular bank statement, or reviewed issuer-neutral credit-card table into the selected owned account. |
| `POST` | `/api/statements/import/upload` | Detect and atomically import a write-enabled unencrypted PDF; bounded local OCR can supply text when configured, while strict extractors still gate writes. Returns a product-typed statement envelope and never retains source bytes/text. |
| `POST` | `/api/statements/hdfc/upload` | Import one supported, unencrypted HDFC PDF; bounded local OCR can supply text when configured, without retaining source bytes. |
| `POST` | `/api/statements/hdfc/text` | Safe extractor/test surface for HDFC statement text. |
| `GET` | `/api/statements/{statement_id}` | Read statement fields and matched/new/review lines. |
| `GET` | `/api/review/statement-lines` | List unresolved statement evidence and controlled ledger candidates. |
| `GET` | `/api/statement-lines/{line_id}/payment-candidates` | Read-only, user-scoped bank-debit candidates for a card-payment line, ranked by explicit card wording, statement reference, amount, and posting date. Never creates a transfer or match. |
| `PATCH` | `/api/statement-lines/{line_id}/review` | Ignore, import, match, or pair a card-payment line with an owned bank account. |
| `GET` | `/api/cards/{account_id}` | Read statement-backed due, current utilisation, coverage, payment intents, card calendar, refund lifecycle evidence, deterministic activity signals, and the explainable next-statement projection. |
| `GET` | `/api/cards/{account_id}/utilization-history` | Read issuer-statement utilization history plus a bounded day-by-day settled-ledger roll-forward from the latest statement, with user-target and hard-limit statuses. |
| `GET` | `/api/cards/portfolio/upcoming-state` | Compose a conservative next-state view across all active cards, preserving per-card events and review states while aggregating only known issuer dues; never synthesizes live total available credit. |
| `GET` | `/api/cards/portfolio/payment-plan` | Compare minimum-due and total-due plans across active cards. Existing planned intentions remain in the shared funding forecast; only additional hypothetical payments are replayed, and no payment is submitted. |
| `POST` | `/api/cards/portfolio/spend-routing` | Preview which active card can carry one hypothetical purchase under an explicit utilization/reward priority. Uses provider or ledger evidence, ignores invalid reward rules, and never creates a transaction or payment. |
| `GET` | `/api/cards/{account_id}/due-runway` | Compare issuer-stated total/minimum due with the selected funding account's conservative forecast; no bank or issuer action. |
| `GET` | `/api/cards/{account_id}/upcoming-state` | Compose the next dated card state from issuer due, planned payments, calendar events, refunds, utilization/limit pressure, and bounded projection events; read-only. |
| `PUT` | `/api/cards/{account_id}/preferences` | Save user-selected payment account, utilisation guardrail, and explicit reward assumptions. |
| `POST` | `/api/cards/{account_id}/payment-intents` | Record a non-executing card-payment plan. |
| `PATCH` | `/api/cards/{account_id}/payment-intents/{intent_id}` | Cancel an intention or, after the user confirms the real payment, record an idempotent manual bank-to-card transfer. This never contacts a bank or issuer. |
| `POST`, `PATCH`, `DELETE` | `/api/cards/{account_id}/calendar`, `/api/cards/{account_id}/calendar/{event_id}` | Add, correct, or remove a manual card renewal, fee, reversal, or milestone reminder. |
| `GET`, `POST` | `/api/cards/{account_id}/disputes` | Track a user-owned dispute record; no issuer action is performed. |
| `PATCH` | `/api/card-disputes/{dispute_id}` | Update a dispute status or note. |

The PDF upload body is the raw PDF bytes and must be no larger than 10 MB.
The query supplies `user_id` and `financial_account_id`. Only reviewed,
write-enabled HDFC digital layouts, the strict issuer-neutral tabular bank
profile, or the strict issuer-neutral credit-card table profile are accepted.
PFIS computes the document
SHA-256 fingerprint, extracts embedded text or bounded local OCR in memory,
persists structured values and provenance, and discards the bytes. OCR is
subject to `STATEMENT_OCR_ENABLED`, an eight-page default limit, a 160-DPI
render, and an eight-second per-page timeout; unavailable or low-quality OCR
fails closed. A repeated fingerprint returns the existing statement without
creating ledger rows.

Detection responses include an additive `analysis` object. Reviewed HDFC card,
HDFC deposit, strict generic bank, and strict generic card profiles return
reconciled, source-labelled totals; recognized generic tables return only rows
whose date, amount columns, and direction are explicit. The response is bounded to a small redacted preview and never
contains the source document or account/card suffixes. Generic and ambiguous
documents remain read-only even when analysis is available; analysis is not an
import permission. When a user explicitly calls the statement-review route,
PFIS persists only that bounded analysis, detection metadata, and a per-user
fingerprint in `statement_analysis_reviews`. The review artifact has no account
foreign key by design: account mapping and any later import remain explicit,
separate actions. `ready_to_import` means a reviewed write-enabled detector
profile is available; it does not auto-import or create ledger activity.

The auto-import response identifies `product_type` and includes either
`credit_card_statement` or `deposit_account_statement`. Deposit writes require
a confirmed, active asset-bank account, an exact masked-suffix match, and either
the reviewed pipe-delimited HDFC profile or the strict issuer-neutral tabular
profile. Credit-card writes require an active owned card, an exact masked-suffix
match, and either the reviewed HDFC extractor or `generic-credit-card-tabular-v1`.
HDFC deposit imports remain INR/HDFC-specific; generic imports use the selected
account's currency and reject an explicit source-currency mismatch. Every
running balance must reconcile. Lines with explicit UPI, debit-card, ATM, or
NEFT/IMPS/RTGS evidence become ledger transactions; unknown rails stay as durable
`needs_review` source lines. A reconciled closing balance creates one verified,
idempotent statement balance observation.

`POST /api/statements/hdfc/detect` is a narrower document contract for digital
HDFC PDFs. It recognizes only complete reviewed HDFC credit-card or
account-statement signal sets, reports `recognized`, `ambiguous`, or `unknown`,
and exposes only stable signal names. A reviewed HDFC card points to the legacy
HDFC PDF importer; a reviewed HDFC deposit points to the account-aware
auto-import route. Marker-compatible or mixed documents remain non-importable,
and this preflight never creates rejection telemetry, statement rows, ledger
transactions, balance snapshots, or durable review artifacts.

Financial-position routes are user scoped. Duplicate document fingerprints are rejected;
ambiguous card-payment matches remain in review until a paying bank account is selected.
Card activity signals are read-only explanations: exact duplicate candidates, statement
lines worth at least 10% of the printed credit limit, and explicitly classified
non-completed reversals. They do not initiate disputes, reversals, or card blocks.
The nested `next_statement_projection` is also read-only. It is available only
inside a current 21-45 day statement cycle with a current balance anchor, issuer
credit limit, and at least three settled non-payment card events. It returns a
projected closing balance, uncertainty range, projected utilisation, confidence,
calibration method, explicit planned-payment adjustment, evidence, ruleset, and
next state. When a utilization target is configured, it also returns a typed
target status (`under_target`, `at_risk`, or `over_target`) with projected
headroom or excess at close. `at_risk` means the uncertainty range crosses the
target even though the central estimate remains below it. When two prior settled cycles are available, the current pace is
blended with their historical pace; explicit user-planned payments before the
close are subtracted and labelled as intentions, not issuer settlement proof.
The response also includes a bounded `daily_path` from tomorrow through the
projected close. Each point carries central/range balance, projected
utilisation, target state, and labelled planned/scheduled/recurring events;
the path is an estimate and never an issuer schedule.
When at least two prior statement cycles contain positive settled liability
movement on the same future cycle days, the projection also applies a bounded
calendar day-of-cycle blend. `seasonal_sample_count` and
`seasonal_days_covered` report the evidence used; quiet or under-sampled days
fall back to the current pace, and observed day-level variation widens the
uncertainty range. This remains a PFIS estimate, not issuer seasonality.
When a utilization target is configured, the response also reports the first
date the central path would cross that target, if it does before close. That
breach date includes planned payments, scheduled charges, and recurring charge
candidates; it is a PFIS estimate and not an issuer warning.
The response separately reports `credit_limit_status` (`under_limit`,
`at_risk`, or `over_limit`), central headroom/excess, and the first central
credit-limit breach date. `at_risk` means the uncertainty upper bound crosses
the issuer limit while the central path remains below it; this is distinct from
the user's utilization target and never stands in for live available credit.
Active card-EMI schedule items due before the close are added as known future
charges and remain separate from observed spend.
Early or mature merchant cadences observed on the same card are also returned
as `recurring_charge_candidates` when their expected date falls before the
projected close. Their expected amount, date, cadence, occurrence count, and
confidence are visible. When at least three settled observations support
interval movement, `expected_date_low` and `expected_date_high` expose a
bounded historical timing envelope around the central median cadence date.
For monthly, quarterly, and annual cadences, the central date advances by
calendar month and clips safely at month end rather than accumulating a fixed
day-count drift. It remains a PFIS estimate, not an issuer due date.
For the amount envelope, at least three settled observations support
amount drift, `expected_amount_low` and `expected_amount_high` expose a
bounded historical envelope (capped at 50–150% of the central average); the
central estimate still uses the average and the envelope widens only the
uncertainty range. Their bounded total is included in the central estimate
with explicit uncertainty widening. These are historical cadence estimates,
not issuer-confirmed charges or payment instructions; scheduled EMI rows with
the same date and amount are not counted twice.
Pending refund rows also expose `potential_pending_refund_total`: this amount
can lower only the projection's `range_low`, while the central estimate remains
unchanged until the refund settles. The response adds explicit evidence and a
reason code for this potential credit; it is not issuer-confirmed available
credit or a promise that the refund will post.
The same card response includes a bounded `refund_tracker`: explicit pending
refund rows remain visible until their transaction lifecycle settles, while
posted-refund totals are limited to the latest 90 days. Unknown refund
lifecycles enter `needs_review`; PFIS never infers a missing refund or issuer
credit restoration.
`GET /api/cards/{account_id}/upcoming-state` composes those separate read-model
signals into one bounded timeline. It returns the next state (`payment_due`,
`target_pressure`, `limit_pressure`, `monitor_cycle`, or a fail-closed review
state), a next event, and up to 30 dated events. Issuer due dates remain
observed facts; planned payments and calendar events remain user intentions;
projection charges, breach dates, and pending refunds remain estimates. The
endpoint performs no mutation and does not claim issuer scheduling, settlement,
or live available credit.
`GET /api/cards/portfolio/upcoming-state` composes the same timeline separately
for every active card. It reports the portfolio's highest-priority state, the
earliest card-labelled event, known issuer total due with its coverage count,
and per-card projection/position states. A total estimated outstanding is
returned only when every active card has an eligible non-review position;
issuer available credit is never totaled as a live portfolio amount.
`GET /api/cards/portfolio/payment-plan` compares the issuer minimum and total
targets for every active card. It returns per-card scenarios, target and
additional-payment totals, and one funding path per selected bank account. When
cards share a bank account, PFIS replays the additional hypothetical payments
in due-date order over one forecast so the same cash is not counted once per
card. Missing statements, funding mappings, anchors, or forecast coverage stay
typed as review/unavailable states; the endpoint never models rewards, issuer
settlement timing, or live available credit.
`POST /api/cards/portfolio/spend-routing` is the complementary purchase
decision surface. Its request carries one amount, an optional user category,
and an explicit `utilization_safety`, `rewards`, or `balanced` priority. Each
option shows the current evidence source, hypothetical immediate/next-close
utilisation, hard-limit and user-target headroom, and the matching explicit
reward rule. Category-specific rules outrank wildcard rules; invalid or
issuer-unknown rules are ignored. Missing or review-state evidence produces a
typed `needs_review` option, and the endpoint never records a spend, schedules
a payment, or treats a reward estimate as an issuer promise.
For statements, a generic bank candidate becomes write-enabled only when the
source proves a masked account suffix, statement period, opening balance,
explicit debit/credit/balance columns, and a cent-exact running-balance chain.
The selected bank account must be owned, active, confirmed, and currency
compatible. A generic credit-card candidate additionally needs the billing
facts, opening liability, a final balance equal to total due, and explicit
payment/refund/cashback wording for every credit. Unsupported or ambiguous
layouts remain review artifacts.
Old cycles and insufficient evidence return a
typed recovery status with no projected amount; the estimate is never described
as an issuer-observed statement balance.
HDFC statement imports currently require an INR user ledger and a compatible
confirmed credit-card or HDFC deposit account; the issuer-neutral tabular bank
profile uses the selected confirmed bank account's currency and the generic
credit-card profile uses the selected active card's currency. Both reject an
explicit source-currency mismatch. PFIS does not relabel extracted statement
amounts as another currency.

PFIS uses a single ledger currency per user. Account, balance, transaction,
transfer, parser-ingestion, statement, household-expense, and household-settlement
writes that do not match `User.currency` are rejected. Household membership also
requires one shared ledger currency. PFIS has no implicit exchange-rate conversion.
Legacy mismatched transaction rows remain visible for repair but are excluded from
spend/income aggregates.

An account-link rule accepts a four-digit masked suffix only when it matches the
selected active account and currency. Approval repairs transactions that still
point to an unknown account (or none), records a `financial_account_id`
correction for each repair, and skips any transaction with an earlier explicit
account correction. Deactivation affects future resolution only. Every account
response also exposes `identity_status` (`unresolved`, `inferred`, or
`confirmed`), a bounded `identity_confidence`, and compact `identity_evidence`;
the history endpoint returns the immutable snapshots behind that current read.
Account identity confidence is about the instrument label/type only and never
stands in for a verified balance.

An imported statement line has exactly one reconciliation outcome:
`matched`, `newly_imported`, `ignored_by_rule`, or `needs_review`. Review
mutations append a `StatementLineReviewDecision`; they never overwrite prior
decision evidence. `GET /api/statement-lines/{line_id}/payment-candidates`
returns at most ten same-currency bank debits only when their description has
explicit card-payment wording or a matching statement reference plus payment
wording. It is evidence for the review UI, not an authorization. The
`record_card_payment` mutation still requires the user to choose an owned bank
account and atomically creates the bank debit and card credit under one
transfer group.

Liabilities cannot be created with `complete_schedule=true`. Schedule
confirmation requires at least one ordered, uniquely dated instalment and is
append-only. Upcoming schedule rows become confirmed commitments linked by
`liability_id`; rows after the next confirmed income date do not yet reduce
flexible money.

### Current position and Cash Plan

`GET /api/accounts/{account_id}/position` is the canonical account-position
read model. `observed_balance` is the latest balance observation (verified or
provisional); `estimated_balance` is that anchor plus eligible settled
movement after its effective cutoff. `pending_increase` and
`pending_decrease` are reported separately. `position_status` and
`position_reason_codes` expose whether the estimate is observed, estimated,
stale, incomplete, or needs review. A date-only anchor does not silently
include same-day activity without a reliable effective timestamp.
When two verified observations exist, `reconciliation_delta` is the closing
balance residual after eligible settled movement and `last_reconciled_at` marks
the closing observation used for that check; a non-zero residual remains a
review signal rather than an inferred transaction, and it blocks spendability
until the gap is resolved.
When a provider observation has been ingested, the response also exposes the
source coverage window, latest successful retrieval, completeness flag, and
`coverage_status` (`fresh`, `due`, `overdue`, or `unknown`). A provider source
that is overdue or history-truncated moves the position to `needs_review`; PFIS
does not silently label a transaction-derived estimate as live.
`GET /api/cards/{account_id}` carries the same provider source and
coverage fields, so billed due, estimated outstanding, pending impact, and
provider freshness stay separate in the card workspace. It also exposes the
current-outstanding proof fields: `billed_total_due` and its as-of date,
`paid_since_statement`, and signed `unbilled_activity` (with increase/decrease
breakdowns). These are derived from eligible settled card ledger rows and never
replace issuer-reported available credit.

The provider-neutral `BalanceSyncService` scopes every refresh to the mapped
owned accounts requested by the caller. If a connector omits one requested
account or returns an unrequested account, PFIS rejects or marks the refresh
incomplete and fails dependent spendability checks closed; partial provider
responses cannot masquerade as a fresh live position.

`GET /api/cash-plan` and `PUT /api/cash-plan` return the same position evidence
alongside `verified_balance`. `planning_balance` is populated only when the
position is eligible for the flexible-money calculation; it may be an
estimated current position, never an issuer-reported live balance.
`needs_position_review` is returned when pending, unreviewed, or cutoff-
ambiguous activity could make a spendable total unsafe. Flexible money fails
closed in that state, while the estimated position and reason codes remain
available for the user to resolve.

`GET /api/net-worth` uses the same position policy for the current point when
every active account has a fresh eligible position. `current_position_status`,
`current_position_confidence`, and `current_position_reason_codes` make partial,
stale, or review-blocked totals explicit; historical snapshot points remain
available and are never rewritten as if they were current.

`GET /api/accounts/{account_id}/balance-forecast` is the account-level daily
path introduced for the Phase 3 predictive slice. It starts from the canonical
observed/estimated position, applies explicitly dated income, confirmed
commitments, mapped card-payment intentions, and sourced liability schedules,
then adds a clearly labelled settled-history baseline only when there is enough
reviewed activity. `low_balance`/`high_balance` are uncertainty bounds, not
issuer available-balance or credit-limit claims. The response fails closed with
`status=needs_anchor` when no verified/provider observation exists and uses
`needs_review` when the starting position is stale, incomplete, or reconciled
with unresolved reasons.

`GET /api/cards/{account_id}/due-runway` joins the issuer statement's `total_due`,
`minimum_due`, due date, and statement-date available-credit evidence to an
explicitly selected bank funding account. It returns `covered` only when the
lower forecast band remains above the full billed total; otherwise it returns
`at_risk` or a fail-closed state such as `needs_statement`,
`needs_payment_account`, `needs_funding_anchor`, or `needs_review`. A planned
payment intention is shown as intent and is not treated as settlement. No field
in this response is a live bank balance, live issuer balance, or payment-success
claim. The response also includes bounded `payment_scenarios` for the issuer's
minimum and total due when those facts are available. Each scenario shows the
issuer target, the portion already covered by planned intentions, any additional
amount needed, the hypothetical effective payment, remaining billed due, and the
expected/lower/upper funding balances after that plan. Scenario `covered` means
the lower forecast band covers the effective hypothetical payment; `at_risk`
means it does not, and `unavailable` means the funding path is missing or
unsupported. These are deterministic planning comparisons only: PFIS never
creates, sends, or confirms a payment from them.

Forecast snapshots may receive an explicit historical `cutoff_date` (never a
future date) so backtests do not use evidence created after the prediction
cutoff. Evaluation only creates an outcome when a verified balance observation
exists for the exact forecast point date; missing observations remain pending
instead of being imputed.

## Temporal financial knowledge

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/knowledge/events` | `user_id`, optional `range_start`, `range_end` (maximum 366 days), `as_of` | `200` | Versioned `TemporalEventSummary` with expected, observed, overdue, missed, cancelled, and conflict counts plus source-linked events |
| `GET` | `/api/knowledge/events/audit` | `user_id`, optional `range_start`, `range_end`, `as_of` | `200` | Non-mutating recomputation report with event/decision coverage, ruleset drift, orphaned overlays, and missing exact links |
| `POST` | `/api/knowledge/history/backfill` | `user_id`, `TemporalHistoryBackfillRequest{dry_run,source_types,max_rows_per_source}` | `200` | Preview or capture a forward-only baseline for legacy transaction, account, statement-line, or card-payment-intent rows missing immutable temporal snapshots |
| `PUT` | `/api/knowledge/events/{event_id}/decision` | `user_id`, optional `range_start`, `range_end` | `200` | Recomputed event after persisting a `confirmed`, `cancelled`, `observed`, `linked`, or `conflict` decision |
| `DELETE` | `/api/knowledge/events/{event_id}/decision` | `user_id` | `204` | Removes the owned decision so the event returns to its source-derived state |

The temporal timeline is recomputed from retained user-owned evidence. It
unifies planned income, bills, subscriptions, commitments, card-payment
intentions, liability schedule items, card milestones, approved reserves,
recurring expenses, and recurring income. Each event carries an exact expected date/window, amount or amount
range, confidence, sufficiency, ruleset, and typed source references. Pattern
events cite every transaction that supported the pattern.

Transaction lifecycle evidence is emitted as `transaction_lifecycle` events
when a transaction is pending, initiated, processing, authorized, failed,
declined, cancelled, expired, reversed, or explicitly marked as a refund or
reversal. The event carries the exact transaction source, amount, status-derived
state, and a clear assumption that it is read-model evidence over the existing
ledger row. Lifecycle events cannot receive temporal-decision overlays; resolve
the underlying transaction or source record instead. Supplying `as_of` reads the
append-only transaction snapshot history so these states are not silently
replaced by a later correction.

`observed` does not imply a ledger match. `observation.confirmation` separates
`ledger_match`, `user_status`, and `issuer_status`; `transaction_id` remains
null unless an exact transaction match exists. Similar merchant text or amount
alone never creates a match. User/issuer dates use exact one-day windows;
pattern windows are explicitly estimated from cadence.

Decisions are user-owned overlays on the recomputable event model, not ledger
mutations. Manual observations require an observed date, explicit conflicts
require a note, and only `linked` decisions accept a transaction ID. A link is
accepted only when the transaction belongs to the same user, has the expected
debit/credit direction and currency, is not ignored activity, and falls within
the event window plus a 14-day review tolerance. Linked amount variance above
10% (or one ledger currency unit) remains visible as a conflict rather than
silently changing the expectation.

Supplying `as_of` evaluates the transaction-derived patterns and any
append-only planning snapshots known at that financial day. Cash plans, bills,
commitments, complete liability schedules, approved reserves, and card calendar
events have snapshot history; mutable source types without history are
deliberately excluded. This is the safe mode used by forecast backtests and it
does not pretend that unsupported status changes were known in the past.

Account reconciliation compares the two latest verified snapshots using
settled, non-ignored, non-accounting-adjustment ledger movement with
asset/liability-aware signs. The read model exposes
opening/closing balances, known movement, unexplained difference, and focused
items for review-required activity, exact duplicate candidates, unpaired card
payments, and unexplained movement.

`GET /api/accounts/{account_id}/position` also returns the verified observation,
settled movement after the observation, a transaction-derived estimated balance,
pending increase/decrease, position status/confidence, and reason codes. Date-only
observations conservatively exclude same-day transactions; callers should show
that cutoff as unresolved until a source effective timestamp or new observation
resolves it. Credit-card statement imports create a verified statement-date
liability anchor from the issuer's total due when no anchor already exists.


Fuel alerts and statement postings use a narrow reconciliation rule only when
the account, direction, merchant evidence, date window, and explicit fuel
language agree. The statement gross may be up to 3% (and no more than INR 50)
above the alert amount. PFIS retains one purchase at the official statement
amount and keeps any separately posted surcharge-waiver credit; ambiguous,
split, transferred, or amount-corrected candidates are sent to review.

Statement-labelled card EMI components materialize a partial liability evidence
record. Its latest principal, interest, tax, and one-time fee components are
reported separately. Outstanding balance, rate, tenure, remaining instalments,
and progress remain null until a complete schedule is explicitly confirmed.

## Roadmap extensions

| Method | Path | Purpose |
| --- | --- | --- |
| `GET`, `POST`, `PATCH` | `/api/bills`, `/api/bills/{bill_id}` | Bill/subscription reminders with due, paid, and skipped lifecycle. |
| `GET`, `PUT` | `/api/health-checklist`, `/api/health-checklist/{item_type}` | User-maintained deterministic financial safety checklist. |
| `GET`, `POST` | `/api/households` | List or create privacy-scoped household workspaces. |
| `POST`, `GET`, `PATCH`, `DELETE` | `/api/households/{id}/members`, `/api/households/{id}/members/{member_user_id}` | Explicit owner/member/viewer access, role changes, leave, and removal. |
| `GET`, `POST` | `/api/households/{id}/expenses` | Shared annotations and participant allocations, never private transaction evidence. |
| `GET`, `POST`, `PATCH` | `/api/households/{id}/settlements`, `/api/households/{id}/settlements/{settlement_id}` | Planned/completed settlement records. |
| `DELETE` | `/api/households/{id}` | Owner-only deletion after planned settlements are resolved. |
| `GET` | `/api/liabilities/payoff-comparison` | Deterministic avalanche/snowball comparison from explicit balances, rates, and minimums. |

Household viewers are read-only. Removing a member or deleting a household is
blocked while a planned settlement involving that member remains. Household
expenses are purpose-built annotations and have no foreign key to a private
ledger transaction.

## Health

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/api/health` | `{status, app, version}` |

## Auth

| Method | Path | Body | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/auth/register` | `RegisterRequest` | — | `201` | `409,422` | `AuthSessionResponse` + session/CSRF cookies (rate 5/min) |
| `POST` | `/api/auth/login` | `LoginRequest` | — | `200` | `401,403` | `AuthSessionResponse` + session/CSRF cookies (rate 10/min) |
| `POST` | `/api/auth/demo` | — | — | `200` | `404` | Isolated demo `AuthSessionResponse` (disabled in production; rate 10/min) |
| `POST` | `/api/auth/logout` | — | — | `200` | `403` | Revokes browser session; requires CSRF header |
| `GET` | `/api/auth/session` | — | — | `200` | `401` | Browser-safe session metadata; never returns a token |
| `GET` | `/api/auth/me` | — | — | `200` | `401` | `AuthMeResponse` (auth required) |
| `GET` | `/api/auth/google/login` | — | — | `307` | — | Redirect to identity-only Google consent |
| `GET` | `/api/auth/google/callback` | — | `code, state` | `303` | `400` | Verifies OIDC transaction, sets session, redirects to dashboard |

## Users

| Method | Path | Body | Path param | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/users/` | `UserCreate` | — | `201` | `409` | `UserResponse` |
| `GET` | `/api/users/` | — | — | `200` | — | `list[UserResponse]` (current user if authed, else all) |
| `GET` | `/api/users/{user_id}` | — | `user_id` | `200` | `404` | `UserResponse` |
| `PATCH` | `/api/users/{user_id}` | `UserUpdate{name?, timezone?, raw_email_retention_days?}` | `user_id` | `200` | `403,404,422` | Updated `UserResponse`; changed timezone emits a durable view-change event; changed retention enqueues an owned durable sweep |
| `DELETE` | `/api/users/{user_id}` | `AccountDeletionRequest{confirmation}` | `user_id` | `200` | `403,422` | `AccountDeletionResponse`; recent browser authentication and exact `DELETE <email>` phrase required; rate 3/hour |

`UserResponse.timezone` is a validated IANA timezone. It defines the user's
financial calendar day for default periods, balance freshness, recurring
expectations, and forecasts. Explicit source transaction dates are not shifted.

`UserResponse.raw_email_retention_days` is `30`, `90`, `180`, `365`, or
`null`. New users default to 365 days; `null` means keep source content until
the user deletes it. The policy applies only to processed source emails.
Expired sender, subject, and body fields are irreversibly cleared while provider
message ID, timestamps, parser evidence, transaction linkage, and a non-secret
audit event remain. Unresolved parser failures are deferred until resolution.

Account deletion accepts only a cookie session created within the previous 15
minutes; bearer-only access and demo sessions cannot authorize it. PFIS first
commits a deletion-in-progress fence that blocks authentication, new jobs, and
new ingestion, disables automatic sync, and cancels registered in-flight jobs
and ingestion. It then attempts provider revocation and removes private rows,
identities, credentials, and every session in one deletion service. The current
browser cookies are cleared. Deletion continues with an explicit `unconfirmed`
provider result when Google cannot be reached.

Shared annotations are not another member's private data. A sole-member
household is removed. A multi-member household transfers ownership to the
earliest active member, closes the departing membership, cancels affected
planned settlements, and retains historical annotations under a non-login
`Deleted participant` tombstone. The tombstone contains no email, name,
password, identity, session, connector credential, private ledger, or source
evidence. PFIS cannot restore cleared account data after success.

## Gmail

Auth router (`/api/auth/gmail`):

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/auth/gmail/connect` | `user_id` | `307` | `500` | Redirect to Google consent; state is bound to the browser and target user |
| `GET` | `/api/auth/gmail/callback` | `state`, `code?`, `error?` | `303` | `400` | Stores encrypted connector tokens on success and redirects to dashboard; provider denial, missing code, scope failure, stale connection, and ownership conflicts use `gmail_error` |

Operations router (`/api/gmail`):

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/gmail/sync` | `user_id`, `max_results` (1–5000, def 500) | `200` | `404,409,500` | `{status, stats}` |
| `GET` | `/api/gmail/status` | `user_id` | `200` | — | `{latest_status, runs[]}` (latest 5 runs; each run includes provider-coverage completeness and truncation metadata) |
| `GET` | `/api/gmail/emails` | `user_id`, `processed?` (bool), `limit` (1–100, def 20), `offset` (≥0) | `200` | — | `{total, all_total, processed_total, unprocessed_total, applied_filter, emails[]}` |
| `DELETE` | `/api/gmail/connection` | `user_id` | `200` | `404` | Removes the connector and returns provider-revocation status plus retained-evidence counts |
| `POST` | `/api/gmail/demo-sync` | `user_id` | `200` | — | `{status, mode, stats}` (injects sample emails, no OAuth) |

Auto-sync additions:

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/gmail/auto-sync` | `user_id` | `200` | `404` | Auto-sync settings, `connection_status` (`connected` or `reauthorization_required`), status, last sync, and cursor; `404` means disconnected |
| `PATCH` | `/api/gmail/auto-sync` | `user_id` | `200` | `404,409,422` | Update auto-sync enabled state or interval |

Permanent Gmail authorization failures set auto-sync to `paused`. The user must
complete `/api/auth/gmail/connect` once; a successful callback clears the safe
credential error and returns an enabled connection to `idle`, after which the
scheduler performs due incremental syncs automatically.

Disconnect attempts provider revocation with the stored refresh token, removes
the local connector grant in every case, stops future sync, and records a
non-secret connector audit event. Already imported raw emails and derived
financial records are retained; the response states that explicitly. A
revocation value other than `revoked` means PFIS could not confirm Google's
remote result and the user should review Google Account permissions.

## WebSocket

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/ws/sync` | `user_id`, `token?` | WebSocket | Sync events scoped by browser session cookie; query bearer tokens are local/compatibility-only and rejected in production |

Sync events include `sync_started`, `gmail_checked`, `emails_stored`,
`pipeline_started`, `transactions_updated`, `financial_state_updated`,
`sync_completed`, and `sync_failed`.
In local compatibility mode, an optional query token must identify the same user
as `user_id`. Production requires an allowed origin and the revocable browser
session cookie; bearer tokens are not accepted in WebSocket URLs.

## Cross-domain change replay

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/sync/changes` | `user_id`, `after_sequence` (default `0`), `limit` (default `250`, max `500`) | `200` | `401,403,422` | Ordered user-scoped invalidation page and current sequence |

The authenticated identity must match `user_id`; the response never includes
source financial values. `events` contain `event_id`, `sequence`,
`event_type=financial_state_updated`, changed `domains`, and `created_at`.
`current_sequence` is the user's durable high-water mark, `has_more` indicates
another page, and `oldest_available_sequence` reports the retained boundary.
When the requested cursor is older than the 90-day journal window or is ahead
of the current sequence (for example, after a database restore), the endpoint
returns `reset_required=true` and the current high-water mark; the client must
invalidate that user's cached views before resuming from it.

The WebSocket `financial_state_updated` event carries only the event ID,
sequence, and domain tags and is a low-latency hint. Clients must use this replay
endpoint as the source of truth after reconnects or missed socket events.

## Pipeline

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/pipeline/process` | `user_id`, `limit` (1–200, def 50) | `200` | `500` | `{status, stats}` (parse → normalize → categorize → dedup → store) |

Unexpected pipeline request failures use the standard generic `internal_error`
envelope. Per-record failures expose `pipeline_processing_failed` in statistics;
durable diagnostics retain only the exception type, not its message.

### GET `/api/pipeline/metrics`

Returns parser-pipeline health for a user/month:

- parse attempts
- transaction created count
- parse success rate
- average confidence
- fallback rate
- unknown merchant rate
- duplicate rate
- retry count
- DLQ size
- average parse time

Query parameters: `user_id`, optional `month`, optional `year`.

### GET `/api/pipeline/failures`

Lists parser DLQ items without raw email bodies. Query parameters:

- `user_id`
- `resolved` defaults to `false`
- `limit`
- `offset`

Each item includes failure stage/code, parser versions, retry metadata, subject/sender previews, and non-secret diagnostics.

### POST `/api/pipeline/failures/{failure_id}/retry`

Retries one unresolved parse failure for the scoped user.

Query parameters: `user_id`.

### POST `/api/pipeline/reprocess`

Replays retained raw emails. The default `dry_run: true` compares parser output without mutating transactions.

Query parameters: `user_id`.

JSON body:

```json
{
  "email_ids": ["optional-email-id"],
  "from_date": "2026-05-01",
  "to_date": "2026-05-31",
  "dry_run": true,
  "limit": 100
}
```

## Transactions

| Method | Path | Body | Query / Path | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/transactions/` | `TransactionCreate` | — | `201` | `409` | `TransactionResponse` (auto-dedup) |
| `GET` | `/api/transactions/` | — | `user_id`; optional `month`, `year`, `category_id`, `text`/`q`, `type`/`transaction_type`, `payment_method`, `review_state`/`reviewed`, `date_from`, `date_to`, `amount_min`, `amount_max`, `sort_field`/`sort`, `sort_direction`/`direction`; `limit`, `offset` | `200` | — | `list[TransactionResponse]`; header `X-Total-Count` |
| `GET` | `/api/transactions/summary` | — | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | — | `TransactionSummary` |
| `GET` | `/api/transactions/transfer-match-candidates` | — | `user_id`; optional `account_id`, `limit` | `200` | `404` | Conservative, non-mutating `list[TransferMatchCandidate]` pairs for imported bank/card or internal-transfer legs |
| `POST` | `/api/transactions/{txn_id}/transfer-link` | `TransferMatchLinkRequest` | `txn_id`, `user_id` | `200` | `404,422` | Explicitly confirmed paired `TransferResponse`; no external payment is initiated |
| `PATCH` | `/api/transactions/bulk-update` | `BulkTransactionUpdate` | `user_id` | `200` | — | `BulkTransactionUpdateResponse` |
| `GET` | `/api/transactions/{txn_id}` | — | `txn_id` | `200` | `404` | `TransactionResponse` |
| `PATCH` | `/api/transactions/{txn_id}` | `TransactionUpdate` | `txn_id` | `200` | `404,409` | `TransactionResponse` (correction learning) |
| `DELETE` | `/api/transactions/{txn_id}` | — | `txn_id` | `204` | `404` | — |
| `GET` | `/api/transactions/{txn_id}/splits` | — | `txn_id`, `user_id` | `200` | `403,404` | User-owned allocation rows |
| `PUT` | `/api/transactions/{txn_id}/splits` | `TransactionSplitReplace` | `txn_id`, `user_id` | `200` | `403,404,422` | Atomically replaces allocations; amounts must equal the ledger amount |

`TransactionCreate` also accepts an optional owned `financial_account_id`. Transfer
legs include `transfer_group_id` and `is_transfer=true`; they remain visible in the
ledger but are excluded from income, spending, budget, guidance, forecast, and
report aggregates.
`transfer-match-candidates` only proposes pairs with exact amount/currency,
settled lifecycle evidence, distinct owned accounts, and a bounded date window.
The link route recomputes those invariants and requires an explicit confirmation;
ambiguous candidates are never auto-linked. Card-payment links require a bank
debit and credit-card credit and mark only the card leg as `card_event=payment`.
`TransactionUpdate` accepts a note and up to 20 normalized tags. These edits use
the same immutable correction history as other transaction corrections. Split
rows explain one transaction; they never create additional ledger events or alter
income/spending totals.

`TransactionResponse` includes additive merchant provenance fields:
`merchant_resolution_source`, `merchant_resolution_confidence`,
`merchant_rule_id`, and `merchant_resolver_version`. Direct transaction-create
requests are recorded as `manual`; client-supplied provenance values are ignored.

## Guidance and Dashboard Preferences

| Method | Path | Query / Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/guidance/brief` | `user_id`, `period=daily|weekly|monthly`, optional `month`, `year` | `GuidanceBrief` with ruleset version, freshness, ranked recommendations, bounded consequences, conflicts, goal links, confidence, and a deterministic resolution/next-step contract |
| `POST` | `/api/guidance/query` | `user_id`, `GuidanceQueryRequest` | `GuidanceQueryResult`; current bank/card balance, safe-to-spend, net-worth, and dated card-next-state questions are grounded in typed read models and return a plan, source citations with cutoff, uncertainty, confidence, and temporal scope. Unsupported intents return a refusal plan and supported examples instead of a generated answer |
| `PATCH` | `/api/guidance/{recommendation_id}/state` | `user_id`, state `active|dismissed|snoozed|accepted|not_relevant`, optional `snoozed_until`, `as_of`, `note`, `reason` (`not_relevant|not_feasible|already_done|too_risky|wrong_timing`) | Persisted state plus a server-derived snapshot of the recommendation/evidence/ruleset for non-active decisions; structured relevance feedback is bounded and user-owned |
| `GET` | `/api/guidance/decisions` | `user_id` | Owned recommendation decisions with preserved title, target, impact, evidence, consequence range, smallest action, conflicts, goal links, resolution/next step, confidence/freshness, period, note, ruleset, and available automatic baseline |
| `POST` | `/api/guidance/decisions/{decision_id}/outcome` | `user_id`, `RecommendationOutcomeCreate` | Idempotent immutable outcome for accepted advice; supports helped/no-change/worse/not-completed, optional typed impact, and a server-derived baseline-to-observed comparison when the recommendation has a supported metric |
| `GET` | `/api/guidance/outcomes` | `user_id` | Owned recommendation outcome checks |
| `GET` | `/api/guidance/effectiveness` | `user_id` authorizes the viewer; no user records are returned | Versioned 180-day aggregate effectiveness cohorts; recommendation and measured subsets are suppressed until they contain at least 10 immutable outcomes from at least 5 distinct active users |
| `GET` | `/api/preferences/dashboard` | `user_id` | Versioned `DashboardPreferences`; deterministic defaults when missing |
| `PATCH` | `/api/preferences/dashboard` | `user_id`, partial preferences | Validated, user-owned preferences, including `briefing_cadence: daily|weekly|monthly` |
| `DELETE` | `/api/preferences/dashboard` | `user_id` | Reset defaults |

Guidance is deterministic and allowlisted. Supported intents cover period totals,
merchant/category spend, comparisons, recurring charges, budget status, card-due
affordability, dated card-next-state and cross-card portfolio questions, and
current bank/card/net-worth or safe-to-spend questions grounded in the position
read models. Card-due
affordability uses the conservative lower forecast band and fails closed when a
statement, funding account, or position anchor is missing. Card-next-state
questions compose the same upcoming timeline exposed by Cards, preserve the
current-cycle temporal scope, and never submit a payment or claim live available
credit. Raw queries are neither persisted nor logged by the guidance service.

Recommendation IDs alone are not trusted as decision evidence. Accept,
not-relevant, dismiss, and snooze mutations recompute the selected period and
reject IDs not present in the server-derived recommendation set. Accepted and
not-relevant advice leaves the active brief. Outcomes require an accepted,
owned decision and become immutable after the first successful record.
For review, budget, recurring-cost, and savings recommendations, PFIS captures a
typed baseline when the decision is made and recomputes the same metric when the
outcome is recorded. A positive `automatic_impact_value` means movement in the
recommended direction; it remains separate from the user's reported outcome.
Aggregate effectiveness never returns decisions, notes, user identifiers, or a
small cohort's type-specific counts. Cohorts are separated by recommendation,
guidance ruleset, outcome ruleset, metric, and unit. User-reported help,
completion, automatically measured improvement, mean impact, and agreement are
reported as distinct fields; the automatic subset must independently meet the
same 10-outcome/5-user safeguard.
Recommendation context also includes a smallest feasible action, bounded
consequence range, freshness, urgency, reversibility, explicit Cash Plan/data
gaps, overlapping-impact warnings, goal links, and a resolution status with one
next step. PFIS only applies a
per-user ranking adjustment after at least three completed explicit outcomes of
the same recommendation type; the adjustment is capped at six priority points
and is preserved as an evidence line. Sparse or contradictory feedback leaves
the deterministic ranking unchanged.

## Accounts, Balances, Net Worth, and Transfers

| Method | Path | Query / Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/accounts` | `user_id` | `list[FinancialAccount]`; each account retains its latest verified snapshot and exposes the settlement-aware `current_balance`, `current_balance_as_of`, `current_balance_status`, confidence, and reason codes when an anchor exists |
| `POST` | `/api/accounts` | `user_id`, `FinancialAccountCreate` | Created account |
| `PATCH` | `/api/accounts/{account_id}` | `user_id`, `FinancialAccountUpdate` | Updated owned account |
| `GET` | `/api/accounts/{account_id}/identity-history` | `user_id` | `list[AccountIdentitySnapshot]` in capture order |
| `POST` | `/api/accounts/{account_id}/balances` | `user_id`, `BalanceSnapshotCreate` | Append-only balance snapshot; unidentified manual duplicates for one account/date return `409`; connector observations require `source_record_id`; optional `effective_at` preserves the source's balance-effective timestamp; repeated `source_record_id` is idempotent |
| `POST` | `/api/accounts/{account_id}/balance-observations` | `user_id`, `BalanceObservationCreate` | Connector-neutral provider observation with stable source record identity, effective/retrieval timestamps, expected cadence, and explicit history coverage; complete coverage requires both window timestamps; returns the snapshot plus `BalanceCoverage` |
| `POST` | `/api/accounts/{account_id}/card-observations` | `user_id`, `CardPositionObservationCreate` | Typed issuer facts for current outstanding, billed due, pending amount, credit limit, and available credit; current outstanding also updates the account position; source identity is retry-safe |
| `GET` | `/api/accounts/{account_id}/card-observations` | `user_id`, optional `limit` | Recent append-only typed issuer facts with effective/retrieval timestamps and coverage evidence |
| `GET` | `/api/balance-provider/status` | `user_id` | Read-only mapping, consent, coverage, and freshness readiness for owned bank/card accounts; reports whether refresh is supported and never returns credentials or claims live amounts |
| `GET` | `/api/balance-provider/connections` | `user_id` | Non-secret provider consent lifecycle rows; no credentials or consent artifacts are returned |
| `POST` | `/api/balance-provider/connections` | `user_id`, `BalanceProviderConnectionRequest` | `202` pending consent state when a registered provider exists; `409` when the provider transport is not configured |
| `DELETE` | `/api/balance-provider/connections/{provider_type}` | `user_id` | Revokes the local consent state and clears the stored consent reference hash |
| `GET` | `/api/balance-provider/mappings` | `user_id`, optional `provider_type` | Provider-scoped opaque account mappings; identities are returned only to the owning user |
| `GET` | `/api/balance-provider/discovered-accounts` | `user_id`, `provider_type` | Sanitized provider account candidates for user mapping; requires active consent and an adapter discovery capability |
| `POST` | `/api/accounts/{account_id}/balance-provider-mapping` | `user_id`, `BalanceProviderAccountMappingRequest` | Maps one owned account to a provider-discovered identity; requires active consent and rejects duplicate provider identities |
| `DELETE` | `/api/accounts/{account_id}/balance-provider-mapping/{provider_type}` | `user_id` | Removes one provider-scoped account mapping |
| `GET` | `/api/accounts/{account_id}/balance-coverage` | `user_id`, optional `source` | Source freshness/cadence and coverage evidence; `fresh`, `due`, `overdue`, and `unknown` are explicit and do not imply issuer-live availability |
| `GET` | `/api/accounts/{account_id}/balance-reconciliations` | `user_id` | Immutable verified-observation intervals with expected/observed closing balance, known movement, residual drift, source transaction IDs, and review status |
| `GET` | `/api/accounts/{account_id}/balance-forecast` | `user_id`, optional `horizon_days` (1–180, default 30) | Evidence-labelled daily path with starting basis, expected/low/high balance, scheduled and history-derived movement, risk dates, source IDs, assumptions, and position/coverage status |
| `GET` | `/api/net-worth` | `user_id`, optional `as_of` | `NetWorthSeries`, using eligible current positions when every active account is fresh and reconciled; otherwise historical verified totals plus explicit current-position status |
| `POST` | `/api/transfers` | `user_id`, `TransferCreate` | Atomic debit/credit pair sharing a transfer identifier; returns the applied `payment_rail` |
| `POST` | `/api/transactions/{transaction_id}/atm-cash-link` | `user_id`, `cash_account_id` | Convert one observed ATM debit into one idempotent bank-to-cash pair after the source is identified as a bank account |

All account and preference routes resolve the authenticated user scope. Cross-user
resource access returns no data, and cross-currency transfers are rejected.
`TransferCreate.payment_rail` defaults to `transfer` for compatibility. The `atm`
rail is restricted to an active bank account as the source and an active cash
account as the destination. ATM legs remain transfers, so withdrawing cash does
not become income or spending. An email-observed ATM debit remains a visible
`unlinked_atm_withdrawal` adjustment in Review until the user selects the cash
pocket; it never inflates spend while waiting.

## Categories

| Method | Path | Success | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/categories/` | `200` | `list[CategoryResponse]` |

## Budgets

| Method | Path | Body | Query / Path | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- | --- |
| `POST` | `/api/budgets/` | `BudgetCreate` | `user_id` | `201` | `409` | `{id, status}` |
| `GET` | `/api/budgets/` | — | `user_id` | `200` | — | `list[BudgetResponse]` |
| `PATCH` | `/api/budgets/{budget_id}` | `BudgetUpdate` | `budget_id` | `200` | `404` | `{id, monthly_limit, status}` |
| `DELETE` | `/api/budgets/{budget_id}` | — | `budget_id` | `204` | `404` | `{status}` |
| `GET` | `/api/budgets/track` | — | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | — | `list[BudgetTracker]` sorted by status |

## Insights

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/insights/` | `user_id`, `month?` (1–12, def current), `year?` (2020–2030, def current) | `200` | `{meta, insights, daily_trend, recurring_payments, anomalies}`; anomalies use a 24-month robust median/MAD baseline and prefer repeated same-calendar-month history when available, with confidence, evidence, and assumptions |

| `POST` | `/api/insights/anomalies/{anomaly_id}/adjudication` | `user_id`, `month`, `year`, `AnomalyAdjudicationRequest{decision,note?}` | `201` | Server-derived append-only anomaly decision; browser-supplied amounts and labels are ignored |
| `GET` | `/api/insights/anomaly-samples` | `user_id`, `month`, `year`, optional `limit` | `200` | Bounded ordinary category/merchant samples that did not trigger an alert, for balanced recall/false-positive adjudication |
| `POST` | `/api/insights/anomaly-samples/{sample_id}/adjudication` | `user_id`, `month`, `year`, `AnomalyAdjudicationRequest{decision,note?}` | `201` | Server-derived append-only label for a non-alert calibration sample |
| `GET` | `/api/insights/anomaly-adjudications` | `user_id`, optional `limit` | `200` | Owned anomaly decisions without raw source rows |

## Dashboard

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/dashboard/workspace` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | `WorkspaceResponse` |

`WorkspaceResponse` is an aggregate DTO for the Financial Decision Workspace,
composed from existing deterministic services (transactions, insights, budgets,
gmail status). It never contains raw email bodies, tokens, or secrets.

```jsonc
{
  "month": 7, "year": 2026,
  "snapshot": {
    "income": 0, "spend": 0, "savings": 0, "net_cash_flow": 0,
    "transaction_count": 0, "review_count": 0, "budget_risk_count": 0,
    "sync_status": "idle"
  },
  "timeline": [
    { "type": "income|subscription|bill|shopping|refund|spending",
      "label": "Merchant", "merchant": "Merchant", "category": "Food",
      "amount": 0, "direction": "in|out", "date": "2026-07-01", "confidence": 0.9 }
  ],
  "insights": [ { "type": "…", "icon": "🏷️", "title": "…", "description": "…", "severity": "info" } ],
  "recommendations": [
    { "type": "savings|recurring|budget|anomaly|review", "severity": "warning",
      "title": "…", "description": "…", "action_label": "Open review queue", "target": "review" }
  ],
  "review_summary": { "pending_count": 0, "low_confidence_count": 0, "avg_confidence": null },
  "sync_summary": { "latest_status": null, "last_synced_at": null, "processed_total": 0, "unprocessed_total": 0 },
  "projection": { "projected_net": 0, "confidence": 0.35, "data_sufficiency": "low", "evidence": [] },
  "month_comparison": { "spend_change_pct": null, "category_deltas": [] },
  "financial_health": { "monthly_stability": 0, "data_confidence": 0, "data_sufficiency": "low" },
  "recurring_commitments": []
}
```

The workspace endpoint is the authoritative Today briefing contract. Projection ranges use
historical variation when enough months exist, treat only mature recurring streams as confirmed
commitments, and label forecast confidence and assumptions. `financial_health.score` is retained
as a compatibility alias for `monthly_stability`; data quality is reported separately as
`data_confidence`. Missing budgets return `budget_adherence: null` and do not inflate stability.

## Merchant, Category, Analytics, Goals, and AI-ready Explanations

These endpoints extend the Financial Decision Workspace with Phase 2-4 read
models. They are deterministic and aggregate-only; they do not expose raw email
bodies, tokens, passwords, or connector secrets.

| Method | Path | Query / Body | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/merchants/` | `user_id`, `month`, `year` | `200` | `list[MerchantSummary]` with spend, trend, category, recurrence lifecycle/cadence/confidence, expected date, and data sufficiency |
| `GET` | `/api/merchants/learned-rules` | `user_id` | `200` | User-owned exact merchant mappings learned from explicit corrections |
| `DELETE` | `/api/merchants/learned-rules/{rule_id}` | `user_id` | `204` | Forget one user-owned learned mapping; another user's id returns `404` |
| `GET` | `/api/merchants/{merchant_key}` | `user_id`, `month`, `year` | `200` | `MerchantDetail` with aliases, default category, latest transactions |
| `PATCH` | `/api/merchants/{merchant_key}` | `user_id`, `month`, `year`, `MerchantUpdate` | `200` | Updated `MerchantDetail`; can apply normalized name/category to existing transactions |
| `GET` | `/api/categories/intelligence` | `user_id`, `month`, `year` | `200` | `CategoryIntelligenceResponse` with hierarchy, budget usage, MoM change, top merchants |
| `GET` | `/api/analytics/cash-flow` | `user_id`, `month`, `year` | `200` | Evidence-labelled projection with dated event inflows/outflows, conflict-adjusted range, expected income, flexible spend, historical range, confidence, sufficiency, assumptions, and both forecast/temporal rulesets |
| `GET` | `/api/analytics/source-coverage` | `user_id` | `200` | Observed source coverage, freshness, processing backlog, account identity coverage, and explicit completeness limitations |
| `GET` | `/api/analytics/reconciliation-quality` | `user_id` | `200` | Cross-source transaction review, statement-line resolution, verified-account reconciliation, duplicate candidates, unexplained movements, and bounded evidence score |
| `GET` | `/api/analytics/intelligence-readiness` | `user_id` | `200` | User-scoped readiness gates for observed coverage, temporal snapshots, forecast calibration, recommendation outcomes, anomaly adjudication, and representative release evidence |
| `GET` | `/api/analytics/cash-flow/backtest` | `user_id`, optional `months` (3–12, default 6) | `200` | Rolling completed-month report at day 7/14/21 cutoffs with MAE, median APE, WAPE, interval coverage/width, settled versus unsettled retained-row counts, exclusions, ruleset, and leakage limitations |
| `POST` | `/api/analytics/cash-flow/snapshots` | `user_id`, `CashFlowForecastSnapshotCreate{month,year}` | `200` | Creates or returns the immutable forecast for this user/target/financial-day/ruleset; current month through 12 months ahead only |
| `GET` | `/api/analytics/cash-flow/snapshots` | `user_id`, optional `month`, `year` | `200` | Owned immutable forecast snapshots with original evidence, assumptions, confidence, temporal totals, and ruleset versions |
| `POST` | `/api/analytics/cash-flow/outcomes/evaluate` | `user_id` | `200` | Idempotently evaluates snapshots whose target month has closed and returns newly created observed outcomes |
| `GET` | `/api/analytics/cash-flow/outcomes` | `user_id` | `200` | Owned snapshot/outcome pairs with actual income/spend/net, absolute/percentage spend error, and interval coverage |
| `POST` | `/api/analytics/scenario` | `user_id`, `ScenarioRequest` | `200` | Non-mutating `ScenarioResponse` with baseline, adjusted outcome, effective capped adjustments, assumptions, freshness, and ruleset |
| `GET` | `/api/analytics/month-comparison` | `user_id`, `month`, `year` | `200` | `MonthComparison` with category deltas |
| `GET` | `/api/analytics/financial-health` | `user_id`, `month`, `year` | `200` | Monthly Stability and versioned Data Confidence with coverage, freshness, parsing, and conflict dimensions; retains `score` as a stability compatibility alias |
| `GET` | `/api/goals/` | `user_id`, `month`, `year` | `200` | `list[GoalResponse]` |
| `POST` | `/api/goals/` | `user_id`, `GoalCreate` | `201` | Created `GoalResponse` |
| `PATCH` | `/api/goals/{goal_id}` | `user_id`, `month`, `year`, `GoalUpdate` | `200` | Updated `GoalResponse` |
| `POST` | `/api/ai/explain` | `ExplainRequest` | `200` | `ExplainResponse` with summary, drivers, next actions, safety note |

`financial_health.data_confidence_breakdown` is an ordered evidence ledger. Each
dimension contains `key`, `label`, a 0–100 `score`, `status`, plain-language
`summary`, and aggregate-only `evidence`. Every `watch` or `limited` dimension
includes a `remediation_label` and application `remediation_target`; `strong`
dimensions omit both. Coverage reports observed active periods rather than
claiming connector or inbox completeness. Freshness is measured against the
user's financial-day boundary and is conservatively capped when a connected
inbox is paused, has no completed sync, or still has unprocessed records; the
evidence ledger exposes connector status, last completed sync, sync age, and
waiting inbox count. The weighted overall score uses the separately
reported `data_confidence_ruleset_version` (`pfis-data-confidence-2`).

`GET /api/analytics/source-coverage` adds the missing completeness boundary:
it reports retained Gmail range, owned-ledger month depth, account identity
resolution, and pipeline backlog separately. Each source declares whether its
coverage is known, partial, or unknown. A current Gmail sync is therefore not
presented as proof that the entire provider inbox or account universe was
covered.

`GET /api/analytics/intelligence-readiness` is a recovery and release-boundary
view, not a replacement for the maturity audit. It reports a user-scoped
evidence-readiness score and gate statuses while keeping representative parser,
anomaly, recommendation, and hosted-operations proof explicitly deferred until
aggregate release artifacts pass their privacy and quality thresholds. The
temporal-history gate counts immutable transaction, account, issuer statement-line,
and card-payment-intent snapshots and links to the forward-only backfill action; it
never treats a current baseline as historical knowledge. Forecast readiness now also
reports frozen daily account-path snapshot count, exact-date verified outcomes,
interval coverage, and mean absolute error. A forecast gate remains collecting until
at least three such outcomes exist, and missing points are never imputed. Card-dispute
status changes are also captured as append-only source evidence for later
issuer-settlement evaluation.

`GET /api/accounts/{account_id}/position` is the account truth contract. It
returns the verified observation, settled movement after the observation,
transaction-derived estimated balance, pending increase/decrease, position
status/confidence, and reason codes. Date-only observations conservatively
exclude same-day transactions; callers should show those as an unresolved
cutoff reason until a source effective timestamp or new observation resolves it.
Assets and liabilities use opposite signed movement semantics, while transfers
and card payments remain balance movements even though they are excluded from
spend/income aggregates.

`GET /api/analytics/reconciliation-quality` is the corresponding truth
checkpoint. It counts only observed user-owned rows and reports transaction
review coverage, statement-line outcomes, accounts with two verified snapshots,
duplicate candidates, and unexplained balance movements. A `ready` response is
not provider-completeness proof: newly imported statement lines remain
unresolved until a user or matching rule adjudicates them, and duplicate or
unexplained items remain review signals rather than fraud claims.

Cash-flow ruleset `pfis-cash-flow-6` consumes the temporal event contract for
the selected current or future month. Active dated outflows set a floor on
projected spend and active dated inflows set a floor on expected income; the
engine uses `max` floors instead of adding the same expectation to an already
higher pace projection. When repeated settled category history exists, the
projection also reports a category-mix baseline; recurring settled income
patterns expose pay-cycle calibration evidence. Neither signal is applied when
its sample is insufficient. Conflicting outflows are excluded from the central
estimate, widen the upper range, and reduce confidence. Future months use the
median comparable month when available; `data_through` never advances beyond
the user's current financial day.

Backtest ruleset `pfis-cash-flow-backtest-2` evaluates only information that can
be reconstructed safely from the retained spend ledger at each historical
cutoff. A month requires at least 3 earlier observed-spend months and non-zero
actual spend. Bills, commitments, and complete liability schedules use
append-only source knowledge-time snapshots; other mutable status changes are
excluded until they have the same history contract. The report must not use
today's temporal state as if it were known in the past. Current
ledger corrections and review outcomes do apply, and the report discloses that
their historical decision time is not yet reconstructed. Each horizon also
reports interval-coverage gap against an 80% target and historical transaction
snapshot coverage; release evidence requires at least 95% transaction-state
coverage and
at least 70% coverage so a low-error but systematically under-covered forecast
cannot be promoted.

Category-mix calibration is replayed from the cutoff-visible transaction state
when at least two categories repeat across supported history. The report exposes
how many cutoff periods supported or applied that signal; unsupported periods
remain neutral rather than receiving a guessed category baseline.

Snapshot capture is an explicit `POST`, never a side effect of the projection
`GET`. One record is retained per user, target month, financial-day cutoff, and
forecast ruleset, so repeated capture is idempotent and later ledger activity
cannot rewrite what PFIS predicted. Outcome ruleset `pfis-cash-flow-outcome-1`
creates a separate immutable measurement only after target month-end. Zero
actual spend keeps percentage error null; absolute error and interval coverage
remain defined.

Merchant edits are user scoped. `PATCH /api/merchants/{merchant_key}` creates
exact `UserMerchantRule` mappings for the selected user and, when
`apply_existing=true`, updates matching historical transactions atomically with
correction history, duplicate protection, and monthly-summary invalidation. It
does not mutate the shared `Merchant` catalog.

Two similar purchases are not sufficient evidence of recurrence. PFIS requires a recognizable
weekly, fortnightly, monthly, quarterly, or annual interval; 2 supported occurrences are `early`,
3 or more high-confidence occurrences can become `mature`, and late streams become `missed` or
`inactive`. Amount consistency contributes confidence but is not used as a cadence substitute.

`ScenarioRequest` accepts `month`, `year`, `flexible_spend_reduction`,
`recurring_reduction`, and `additional_income`. All adjustment amounts are
non-negative. The service reuses the cash-flow projection rules, caps reductions
to supported projected amounts, and never writes a transaction, goal, or
preference.

## Reports

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `POST` | `/api/reports/export/portable` | `user_id` | `200` | Versioned ZIP containing `manifest.json` plus one JSONL file per included entity; `Cache-Control: no-store`; limited to 2/minute |
| `GET` | `/api/reports/export/csv` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | CSV stream; `Content-Disposition` attachment |
| `GET` | `/api/reports/monthly` | `user_id`, `month` (1–12), `year` (2020–2030) | `200` | Printable HTML report |

Portable export schema version 14 records the export instant, ledger currency,
financial timezone, file/field inventory, row counts, ownership scope, and a
SHA-256 checksum for every JSONL payload. Password hashes, sessions, OAuth
state, connector credentials, and temporary job leases are never included.
Shared household rows contain only the user's visible annotation domain and
replace other member identifiers with stable archive-local aliases. Version 2
added owned temporal-event decisions; version 3 added immutable forecast
snapshots/outcomes; version 4 added recommendation decisions and outcome
checks; version 5 added append-only temporal source snapshots; version 6 adds
persisted recommendation resolution context; version 7 adds append-only anomaly
adjudications without raw source email bodies; version 8 adds structured
recommendation relevance reasons; version 11 adds immutable balance-reconciliation
intervals with their source snapshot IDs and residual evidence; version 13 adds
typed issuer-card observations; version 14 adds provider-scoped account identity
mappings.

## Jobs

Job enqueue endpoints accept an optional `Idempotency-Key` header. Repeating the
same key for the same user and job type returns the original durable job instead
of starting the financial workflow twice. Job responses include `attempt_count`
and `max_attempts`; `queued` may mean either newly accepted or waiting for a
bounded retry.

Async job submissions return `202 Accepted` with a `JobResponse`; poll the job
by id for status. Submissions are rate-limited to 5/min. Failed jobs keep
`error_message` populated and include `result.error_type` for stable operational
classification.

| Method | Path | Query | Success | Errors | Returns |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/api/jobs/demo-sync-pipeline` | `user_id`, `limit` (1–200, def 50) | `202` | — | `JobResponse` |
| `POST` | `/api/jobs/gmail-sync-pipeline` | `user_id`, `max_results` (1–5000, def 500), `limit` (1–5000, def 500), `sync_all` (bool) | `202` | — | `JobResponse` |
| `POST` | `/api/jobs/retry-parse-failures` | `user_id`, `limit` (1–200, def 20) | `202` | — | `JobResponse` |
| `POST` | `/api/jobs/balance-refresh` | `user_id`, `BalanceProviderRefreshRequest`, optional `Idempotency-Key` | `202` | `404,409` | Durable read-only balance refresh job; requires a registered connector, active consent, mapped owned accounts, and never accepts credentials in the request |
| `GET` | `/api/jobs/{job_id}` | — | `200` | `404` | `JobResponse` |

---

Keep this file updated whenever paths, query parameters, response headers, or
response shapes change. Route source lives in `backend/app/api/routes`.

## Error contract

Successful response bodies retain their endpoint-specific schema. API failures
use this stable envelope and also expose the same correlation value through
`X-Request-ID`:

```json
{
  "error": {
    "code": "not_found",
    "message": "Transaction not found",
    "details": null,
    "request_id": "trace-abc-123"
  }
}
```

Validation errors use `code: "validation_error"` and include Pydantic error
items in `details`; server errors return a generic message and do not expose
internal exception text.

## Health

`GET /api/health/metrics` returns bounded process request counts, status
errors, latency percentiles, slow-request counts, and low-cardinality route
buckets. It retains no user identifiers, query strings, request bodies, or
source content. Counters reset when the process restarts.

| Method | Path | Query | Success | Returns |
| --- | --- | --- | --- | --- |
| `GET` | `/api/health/capabilities` | — | `200` | Public beta boundary: supported-source tiers, deferred connected bank/card balance status, freshness expectations, recovery paths, and incident-feed posture |
| `GET` | `/api/health` | — | `200` | Basic liveness: status, app, version |
| `GET` | `/api/health/metrics` | — | `200` | Bounded process request totals, 4xx/5xx counts, p50/p95 latency, slow-request count, and low-cardinality route buckets without user or source content |
| `GET` | `/api/health/ops` | — | `200` | Non-secret operational posture (`healthy`, `degraded`, or `needs_repair`), status reasons, data warnings, job counters, ledger-currency integrity, and aggregate ingestion/parser/statement/review quality rates |

`sync.coverage` reports completed runs whose provider query was not exhausted,
whether the latest completed run was complete/truncated, and Gmail's bounded
result-size estimate. This is coverage evidence, not a claim that the entire
external account universe is represented.

`data_quality` contains 30-day sample counts beside duplicate, parse-failure,
generic-fallback, and pending-review rates plus aggregate parser-version usage.
The bounded SQL aggregation does not load source records or unbounded event
history. Rates are `0.0` when no eligible observations exist; callers must use
the sample counts and must not interpret an empty cohort as proven quality.
`data_quality.statement_quality` reports imported and rejected digital-statement
attempts, extractor versions, issuers, and stable rejection reason codes without
retaining uploaded statement text. `status_reasons` describe service conditions
that need attention; provider truncation and historical sync failures remain
`data_warnings` because they affect evidence completeness rather than process
liveness. After 20 attempts, a layout-rejection rate of 25% or more marks the
statement quality status as `alert` and contributes `statement_layout_drift` to
the operational status.
`source_drift` compares each institution's latest seven-day parser failure and
fallback rates with the preceding seven days. A source can alert only when both
windows contain at least 20 observations and a rate crosses its documented
delta threshold; otherwise it reports `stable` or `insufficient_history`.
