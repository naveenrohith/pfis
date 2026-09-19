# PFIS Workflows

## Sign In

1. Email/password registration hashes the password with Argon2id, or Google sign-in requests identity scopes only.
2. Google state is bound to the initiating browser and protected with PKCE and an OIDC nonce.
3. Google identities resolve by the stable provider subject, not by email alone.
4. PFIS creates a revocable server-side session and returns the raw token only in an `HttpOnly` cookie.
5. The React app restores the session through `GET /api/auth/session`; it does not persist credentials in browser storage.
6. Cookie-authenticated mutations echo the session-bound CSRF cookie in `X-CSRF-Token`.
7. Logout revokes the session and clears browser cookies.

## Demo Sync

1. `POST /api/gmail/demo-sync?user_id=...`
2. Runtime shifts the embedded sample dates relative to the user's financial
   day so a new demo sync always creates current and prior-period activity.
   The immutable `SAMPLE_EMAILS` fixtures remain fixed for parser evaluation.
3. Store sample financial raw emails.
4. Track sync stats.
5. Process later via `/api/pipeline/process`.

## Gmail OAuth Sync

1. After sign-in, the user explicitly chooses `GET /api/auth/gmail/connect?user_id=...`.
2. Request identity plus read-only Gmail scope and offline access; this consent is separate from sign-in.
3. Persist browser-bound OAuth state, encrypted PKCE verifier, nonce, flow type, expiry, and the owner's Gmail connection generation.
4. Google redirects to callback; PFIS validates and consumes the transaction.
5. Exchange code for tokens and verify the Google identity. The callback locks the owner row and rejects a state invalidated by disconnect or account deletion; any unclaimed grant is revoked.
6. Encrypt and store token references. A healthy connection may preserve its existing refresh token, but recovery from a paused credential state requires Google to issue a replacement grant.
7. A successful reconnect clears the credential error and returns enabled auto-sync to `idle`.
8. Record a connector audit event.
9. `POST /api/gmail/sync` or auto-sync invokes the ingestion coordinator.
10. `GmailConnector` fetches records, `SourceRecord` values are classified and stored, then the parser pipeline processes them.

Migration 056 normalizes legacy unscoped Gmail message IDs to the owner-prefixed
identity used by multi-user ingestion. During the compatibility window, a
resync checks both identities for the same owner before creating a raw-email
row.

## Automatic Sync

1. Scheduler finds due connected Gmail accounts.
2. Incremental sync uses the saved Gmail history cursor when possible.
3. Expired cursor falls back to a bounded recent query.
4. Transient connector failures retry with bounded backoff.
5. Permanent credential failures pause auto-sync and surface an error state.
6. OAuth refresh failures are terminal credential errors for the current job and are not retried as unexpected failures.
7. Reconnecting Gmail resumes enabled auto-sync; the scheduler runs due accounts without requiring the user to click Sync.

### Gmail disconnect

1. The user confirms **Disconnect Gmail** in Data & settings.
2. PFIS resolves the authenticated owner and asks Google to revoke the stored
   refresh grant without logging the credential.
3. PFIS removes the local connector account and stops all future Gmail sync,
   even if provider revocation cannot be confirmed.
4. Imported raw emails, transactions, and evidence remain available; the UI
   explains this before confirmation and the API reports the retained count.
5. A non-secret connector audit event records the revocation outcome and
   retained-data semantics.
8. WebSocket events update the dashboard live; polling remains a fallback.

## Processing

1. Fetch unprocessed `RawEmail` rows for a user.
2. Clean HTML/text.
3. Classify email type.
4. Skip OTP, promotion, statement, and ignored emails.
5. Parse transaction fields.
6. Infer merchant when exact extraction is missing.
7. Normalize merchant and category.
8. Create transaction through `TransactionService`.
9. Mark email processed and resolve or record parse failure.

## User Correction

Transaction updates can create correction records and improve merchant aliases/category learning. Ownership must be checked before updates.

## Reports

Reports use stored transactions and insights. CSV export returns monthly
transaction rows with separate amount and currency columns. Monthly HTML report
is printable and must escape or control server-rendered content.

### Portable data copy

1. Data & settings → Preferences & export explains the sensitive content,
   included record groups, permanent secret exclusions, and schema version.
2. The authenticated user requests one rate-limited export. PFIS resolves the
   requested user scope before reading any entity.
3. `PortableExportService` walks an explicit model inventory. New tables fail
   the inventory test until they receive an include or exclude decision.
4. The ZIP contains `manifest.json` and deterministic JSONL files. The manifest
   lists each file, exported fields, ownership scope, row count, and SHA-256
   checksum.
5. Shared household annotations are included without crossing into another
   member's private ledger; other member identifiers become archive-local
   aliases.
6. Password/session/OAuth secrets, Gmail credentials, transient leases, and
   global product reference data are excluded. The response is an attachment
   with `Cache-Control: no-store` and is not retained by the service.

### Raw-email retention

1. Data & settings → Preferences & export shows the owned source-retention
   policy. New users default to 1 year; supported choices are 30, 90, 180, or
   365 days, plus keep-until-deleted.
2. Moving to a shorter policy requires an irreversible-action confirmation that
   explains which content is cleared and which evidence remains.
3. Saving a changed policy enqueues an owned durable
   `raw_email_retention` job. A system scheduler also enqueues one idempotent
   sweep per UTC day so expiry continues without a signed-in browser.
4. The sweep considers processed source emails only. It defers rows with an
   unresolved parse failure because their content may still be needed for
   deterministic repair.
5. For eligible expired rows, PFIS atomically clears sender, subject, and body
   and records `content_redacted_at`. It preserves the row ID, provider message
   ID, received/created timestamps, processed state, parser metadata, parse
   failure history, and transaction/source linkage.
6. Every successful row redaction appends one non-secret
   `raw_email_content_redacted` pipeline event containing policy version,
   retention duration, and field names only. Repeated or concurrent sweeps do
   not create another event for an already-redacted row.

### Account deletion

1. Data & settings → Preferences & data explains the private records removed,
   shared evidence retained, connector action, and irreversible recovery limit.
2. The user opens a confirmation dialog whose safe action receives initial
   focus, then types `DELETE <sign-in email>` exactly. The destructive action
   remains disabled until it matches.
3. The API requires the same authenticated user, CSRF protection, and a browser
   session created within the previous 15 minutes. Bearer-only, demo, stale,
   mismatched-user, and mismatched-confirmation requests are rejected.
4. PFIS commits a deletion-in-progress fence, disables automatic Gmail sync,
   rejects new jobs/ingestion, and cancels registered work already in flight.
   It then attempts provider-token revocation without logging the token.
   Provider failure is recorded as unconfirmed but cannot strand the user's
   private data in PFIS.
5. For a sole-member household, PFIS deletes the household. For a shared
   household, PFIS transfers ownership deterministically, closes the departing
   membership, cancels planned settlements involving that participant, and
   preserves shared annotations under a non-login tombstone.
6. One service removes every private table row, auth identity, session,
   connector grant, source record, ledger record, plan, and preference. It then
   strips the user row to the minimal shared-participant key and appends one
   non-secret deletion audit event.
7. The response clears session, CSRF, and OAuth cookies; the client clears its
   private query cache and returns to sign-in. The deleted data cannot be
   recovered from PFIS.

# Cash-pocket workflow

1. The user creates an asset account with product type `cash` in Plan → Position.
2. Quick add → ATM cash records a bank-to-cash transfer. The API rejects any
   source/destination pair that is not an active bank account followed by an
   active cash account.
3. Both ledger legs carry the same `transfer_group_id`, `is_transfer=true`, and
   `payment_rail=atm`. They are visible for audit but excluded from income and
   spending totals.
4. The user records each later cash purchase as an ordinary debit linked to the
   cash account. That purchase, rather than the ATM withdrawal, affects spending.
5. If an ATM alert arrives first, PFIS labels it as an unresolved cash movement,
   excludes it from spend, and places it in Activity → Review. The user must
   identify the source instrument as a bank account and select a cash pocket;
   the link action reuses the observed debit, creates one cash credit, and is
   idempotent.

## Card activity centre

1. Cards keeps issuer-stated due, the current card position, and the next
   statement estimate as three visibly separate facts.
2. The next-statement estimate runs only while the latest 21-45 day statement
   cycle is current and PFIS has a balance anchor, credit limit, and at least
   three settled non-payment events in that cycle.
3. PFIS extrapolates the observed net daily liability movement through the
   estimated cycle close. When two prior settled cycles exist, their historical
   pace calibrates the current-cycle pace. Card payments are excluded from the
   spend pace because the current balance already reflects them; settled
   refunds reduce the pace. When at least two prior statement cycles expose
   settled movement on the same cycle days, PFIS applies a conservative
   day-of-cycle seasonal blend, shrunk toward the current pace. Sparse or quiet
   days fall back to the flat pace; the response reports seasonal sample count,
   covered future days, and an uncertainty contribution.
4. Explicit user-planned payments scheduled before the close reduce the forecast
   and remain labelled as intentions, not issuer settlement proof.
5. Active card-EMI schedule items due before the close are added as known future
   charges, not silently folded into the ordinary daily-spend pace.
6. Early or mature merchant cadences on this card can add bounded recurring
   charge candidates when their expected date is before close. Each candidate
   shows its merchant, expected date/amount, cadence, occurrence count, and
  confidence. With at least three settled observations, the UI also shows a
  bounded historical amount band capped at 50–150% of the central average;
  that band widens the range but never changes the central estimate. It is an
 estimate rather than an issuer-confirmed charge. When observed intervals
 move, the UI also shows a bounded expected-date window while keeping the
  central median cadence date unchanged. Month-based cadence uses a calendar
  advance with safe month-end clipping. Overlapping scheduled EMI rows are not
  double-counted.
7. When a utilization target exists, PFIS also reports the first central-path
   breach date before close when one exists. Planned payments, scheduled charges,
   and recurring candidates participate in that path; the date is not an issuer
   alert, and an uncertainty-only crossing remains `at_risk` without a central
   breach date.
8. Explicit pending refund rows can widen only the lower side of the range via
   a `potential_pending_refund_total`; the central estimate and target breach
   path remain unchanged until settlement is observed. This is potential
   credit, not issuer-confirmed available credit.
9. The result shows a gross-activity, historical-deviation, and (when proven)
   calendar-seasonality uncertainty band, plus a bounded daily path from
   tomorrow through the projected close. Each point exposes central/range
   balances, utilization, target state, and only known dated event labels;
   issuer schedules are never invented.
   projected utilisation, confidence capped below certainty, evidence rows, and
   one recommended next state. The band is explicitly not a statistical guarantee.
10. An old statement, irregular cycle, missing balance/limit, or thin activity
   fails closed to a recovery instruction without a projected amount.

1. The latest imported statement supplies duplicate and high-value evidence.
2. Duplicate candidates require identical statement date, amount, normalized
   description, and direction. PFIS labels them as candidates rather than deleting
   or ignoring either line.
3. High-value activity is deterministic: a debit line must equal at least 10% of
   the credit limit printed on the same statement.
4. Pending-reversal signals require an explicit reversal classification and a
   non-completed status. PFIS directs the user to check the issuer and never claims
   to block, reverse, or dispute activity.

## Transaction context and splits

1. Activity → Review lets the user add a note and up to 20 comma-separated tags.
   PFIS normalizes blank/duplicate tags and records both changes in correction history.
2. A non-transfer transaction may be allocated across 2–20 labels/categories.
3. The API atomically replaces the allocation set only when its rounded total
   exactly equals the original transaction amount.
4. Allocations never become new transactions. Spending, income, reports, and cash
   flow continue to count the original ledger event once.

## Statement import and reconciliation

Before account selection, `POST /api/statements/detect` or
`POST /api/statements/detect/upload` analyzes source text in memory and reports
whether it is a supported HDFC credit-card statement, a recognized-but-not-yet-
importable HDFC deposit-account statement, a write-enabled reviewed HDFC deposit
profile, a strict issuer-neutral bank/deposit profile, a strict reviewed
issuer-neutral credit-card table, a generic credit-card or bank/deposit
candidate from another issuer, an ambiguous document, or an unsupported layout.
Generic candidates are classification evidence only unless the relevant strict
profile proves its identity, billing facts, explicit directions, and complete
running-balance chain. The detector may report UPI, debit-card, ATM,
transfer, and cheque activity types only when transaction-like evidence is
present; a column heading alone is not activity. The response also carries a
bounded read-only analysis: reviewed profiles expose reconciled totals, while
generic tables expose only explicit rows and retain `partial` status when
direction, opening balance, or running-balance proof is missing. A redacted
preview never includes account/card suffixes, and analysis does not change the
import gate. Detection creates no statement, transaction, balance observation,
or audit row.

For HDFC PDFs, `POST /api/statements/hdfc/detect` provides a smaller
document-level preflight before account selection. It requires an unencrypted
PDF and prefers embedded text, with bounded local OCR when the runtime is
configured for it. It returns only the issuer, card/deposit document kind,
reviewed format, importability, stable reason, and matched signal codes. A
complete card and deposit signature in one document is `ambiguous`; incomplete
or unfamiliar HDFC layouts are `unknown` and remain review-only. The endpoint
does not extract values, retain source bytes/text, record rejection telemetry,
or create statement/ledger/balance rows.

When the user wants to keep an unfamiliar result for later mapping, the explicit
`POST /api/statements/review/text` or `/api/statements/review/upload` path stores
only the same bounded redacted analysis, detector metadata, and a per-user
fingerprint. `GET /api/statements/review` lists those artifacts for review. The
artifact has no account identity and never becomes a ledger event; `ready_to_import`
only means a reviewed write-enabled profile is available for a separate import
action. Repeated fingerprints are idempotent and all review reads are user-owned.

`POST /api/statements/import/text` and `/api/statements/import/upload` run the
same detector and dispatch only `supported` profiles. Deposit import requires a
confirmed active bank account whose masked suffix matches the source; the HDFC
profile remains INR/HDFC-specific, while the generic bank profile requires a
matching source currency when one is printed. The generic card profile requires
an active owned credit-card account, a matching masked suffix/currency, explicit
card event wording, and a liability balance that reconciles to total amount due.
Unknown card credits, unknown deposit rails, and unfamiliar table/PDF layouts
remain review-only. `GET /api/review/deposit-statement-lines` lists owned bank
rows whose narration did not prove a rail. A user can explicitly choose UPI,
debit card, ATM, or transfer through
`PATCH /api/deposit-statement-lines/{line_id}/review`, or ignore the row. The
mutation reuses exact reference/amount/date matching, creates at most one
ledger event atomically, records an append-only decision, and never treats an
unsupported `other` rail as import permission.
The extractor reconciles the complete opening-to-closing balance chain before
the unit of work begins. It then stores the statement and every source line,
creates ledger rows only for explicit supported rails, stores unknown rails as
`needs_review`, and captures the reconciled closing balance as a verified
observation. Fingerprint retries return the existing statement; any unexpected
row, ledger, or database failure rolls back the statement, lines, transactions,
and balance observation together.

The issuer description remains evidence; canonical merchant/category and EMI
anatomy are derived separately with provenance. Reference IDs match first.
Otherwise PFIS requires one unique account, amount, direction, canonical merchant
candidate within a ±3-calendar-day posting window. Zero or multiple candidates
stay in review. Historical repair skips fields with explicit user corrections
or user-owned rules and records automatic cross-source merges in statement
decision history. Rows whose retained source deterministically proves
newsletter/non-financial content are quarantined as `ignored_by_rule` with
correction history; they are hidden from active calculations but remain
recoverable.

1. Data & settings → Statements lets the user approve a four-digit masked
   suffix for one owned product. The rule repairs only uncorrected unknown
   history; future imports use it before keyword or ambiguous suffix matching.
2. Data & settings → Statements accepts an unencrypted PDF of at most 10 MB and an existing
   compatible credit-card or confirmed bank account.
3. PFIS prefers embedded text and may render at most eight pages for local OCR
   when enabled. It then validates the supported issuer/generic layout, masked
   suffix, dates, running balance, and SHA-256 fingerprint before persistence,
   then deletes the bytes. OCR alone never grants import permission.
4. Each line receives one outcome: matched, newly imported, ignored by rule, or
   needs review. Reimporting the same document returns the existing statement.
5. Activity → Review presents provenance and controlled ledger candidates. Bank
   statement rows with unknown rails are available through the owned
   deposit-review API queue; classify or ignore them explicitly before they
   affect ledger totals.
   For a card-payment line, the read-only payment-candidates endpoint ranks
   same-currency bank debits only when explicit card-payment/reference evidence
   exists; amount and date alone never become a suggestion. Matching or
   ignoring appends decision history.
6. A card-payment line requires the owned paying bank account. PFIS then creates
   one atomic bank-to-card transfer; it never labels the payment as income.
7. If Gmail arrives after the statement, ingestion reconciles it back to the
   statement-created event. The order of the two sources cannot create a second
   purchase.

## Anomaly adjudication

1. Insights only raises an anomaly after the server-side history, materiality,
   and robust-score gates pass. The card remains a review signal, never a fraud
   or causality claim.
2. The user can label a departure **expected**, **material**, or **insufficient
   evidence**, with an optional note. The API first recomputes the anomaly for
   the requested period, so the browser cannot submit arbitrary amounts or
   merchant/category labels.
3. Each decision is append-only and stores the server-derived anomaly snapshot,
   period, confidence, transaction count, and ruleset. The latest decision is
   shown on the current anomaly card; the history remains available through
   `GET /api/insights/anomaly-adjudications`.
4. Insights also offers a bounded calibration sample of ordinary category and
   merchant activity that did not trigger an alert. The user can label it with
   the same expected/material/insufficient-evidence contract; the server stores
   that it was sampled as `predicted_alert=false` rather than treating it as a
   surfaced anomaly.
5. Protected export can later transform both alert and non-alert decisions into
   aggregate evaluator cases. `insufficient_evidence` rows are excluded from
   precision/recall labels, and small personal cohorts remain collecting evidence
   rather than promoting anomaly rules.

## Financial day and timezone

1. Data & settings → Financial day shows the boundary PFIS currently uses.
2. The user chooses a valid city-based IANA timezone and saves it to the owned
   profile.
3. Today, default monthly periods, balance freshness, recurring expectations,
   due/upcoming decisions, and forecast elapsed days use that timezone.
4. Source transaction and statement dates remain unchanged evidence.

## Verified bank position and Cash Plan

1. Plan → Accounts records append-only balance observations. Only a verified
   observation may headline the account position. Imported masked suffixes
   create bounded `inferred` identity evidence; the user must explicitly
   identify the institution and product before the account can supply typed
   position, liability, or Cash Plan calculations. The account response shows
   the current identity confidence and compact evidence trail, while the
   identity-history endpoint exposes immutable identity/lifecycle snapshots.
2. Reconciliation compares verified opening/closing observations with eligible
   settled account activity, including both sides of transfers and excluding
   pending, ignored, failed, and issuer-accounting rows from known movement. It
    returns focused duplicate, unlinked-payment, activity-review, and
    unexplained-movement items. A non-zero residual produces `needs_review` and
    blocks spendability, not an invented live balance.
   Imported rows that appear to be two sides of the same bank/card movement are
   exposed through `transfer-match-candidates` as reviewable pairs. Exact
   amount/currency, settled status, distinct owned accounts, and a seven-day
   posting window are required; ambiguous pairs remain candidates. A user
   confirmation through `transfer-link` assigns one transfer group atomically,
   records correction history, and never initiates an external payment.
3. A Cash Plan selects one primary bank account and a user-confirmed next income
   date. A missing balance, a balance older than seven days, or a missing income
   date prevents a flexible-money total.
4. Flexible money equals verified balance minus confirmed commitments due
   before that income date minus approved monthly reserve allocations.
5. A complete liability schedule creates traceable confirmed EMI commitments.
   An EMI-labelled statement row without a complete schedule remains ledger
   activity only.
6. Today Financial Horizon consumes this same Cash Plan read model. Missing or
   stale evidence produces a direct setup action; it never falls back to a
   monthly-spend forecast as a spendable-money total.
7. Plan also requests the account-level balance forecast for the selected
   funding account. The path starts from the same observed/estimated position,
   applies dated income, confirmed obligations, mapped card-payment intentions,
   and sourced liability schedules, and only then uses a reviewed settled-history
   baseline. Each point exposes its evidence IDs and uncertainty band. A missing
   anchor returns `needs_anchor`; a stale/incomplete/reconciled-with-gaps
   position returns `needs_review`, so the path cannot silently become a live
   balance or safe-to-spend claim.
8. Commitments and reserves may be saved as drafts. Confirmation/approval,
   pause/restore, and paid/skipped instalment changes are explicit user actions
   with user-scoped mutations.
9. Cards requests the due-runway read model when a statement is available. It
   compares issuer total due with the lower band of the explicitly selected
   funding account's daily path, keeps minimum due and available credit
   statement-scoped, and returns a setup/review state instead of extrapolating
   when the statement, funding account, or anchor is missing.
10. Cards can request the read-only upcoming-state timeline, which composes the
    issuer due date, planned payments, calendar events, pending refunds, and
    bounded projection events into one next-event surface. Missing projection
    evidence does not hide explicit due or user-plan events.
11. A portfolio view can compose that same timeline across all active cards.
    It keeps each issuer's due, projection, and review state separate, sums only
    known statement dues with an explicit coverage count, and surfaces the
    earliest card-labelled event. It never totals live available credit or
    merges uncertain positions into a fake card.
12. Cards can compare a minimum-due plan with a total-due plan across the active
    portfolio. Existing planned payment intentions stay in the shared funding
    forecast; only the additional hypothetical amount is replayed at each due
    date, and missing statement/funding/anchor evidence produces a review state.
    PFIS does not model rewards or submit payments from this comparison.
13. Cards can request a read-only spend-routing preview for one hypothetical
    purchase. The caller chooses utilization safety, explicit reward rules, or
    a balanced priority. The preview ranks only hard-limit-safe cards, shows
    provider-versus-ledger evidence and next-statement pressure, and ignores
    malformed or category-mismatched reward rules. It never records a spend,
    schedules a payment, or treats user-entered reward rates as issuer facts.
14. Grounded Guidance accepts dated card-next-state questions such as what
    happens next, the next statement close, or utilization/limit pressure. It
    reads the same upcoming-state surface with a `current_card_cycle` temporal
    scope and returns a review action rather than submitting a payment or
    claiming live available credit.
15. Cards also compares the next-statement central projection and uncertainty
    range with the user's utilization target. It reports projected headroom,
    projected excess, or an `at_risk` state when only the uncertainty band
    crosses the target; no issuer balance is mutated or inferred from this
    comparison.
16. The same projection keeps the user's target separate from hard credit-limit
    pressure. It reports central headroom/excess and the first estimated limit
    breach date; a limit `at_risk` state means only the uncertainty upper bound
    crosses the limit and never means live available credit.
17. Cards exposes a refund lifecycle tracker from explicit card refund rows.
    Pending refunds remain separate from settled posted refunds, a bounded
    90-day posted total prevents lifetime history from looking current, and
    unknown lifecycle states route to review instead of changing outstanding.
18. Forecast accountability can freeze a path at a current or historical
    financial-day cutoff. Later exact-date verified observations are evaluated
    for error and interval coverage; missing observations stay pending and are
    never imputed as calibration success.
19. Cards can request a bounded utilization-history read model. Issuer
    statement points are kept as the authoritative historical series; when a
    newer issuer statement is unavailable, settled ledger movements are
    replayed from the latest statement anchor as a clearly labelled estimate.
    Pending, failed, and ignored activity is excluded, while unreviewed
    activity lowers confidence and remains visible in reason codes. User
    utilization targets and hard credit limits are evaluated separately, and
    the trend never claims a live issuer balance or available credit.

## Temporal event recomputation

1. `GET /api/knowledge/events` resolves the authenticated user and their
   financial-day boundary before choosing the default 31-day lookback and
   90-day horizon. Explicit ranges are bounded to 366 days.
2. PFIS reads user-owned planned income, bills, commitments, confirmed issuer
   schedules, card milestones, approved reserves, and recurring debit/credit
   patterns. It does not write a second ledger.
3. Exact user/provider dates produce exact event windows. Pattern events expose
   cadence-based estimated windows and amount ranges.
4. Every pattern expectation cites the transaction IDs that produced it.
   Explicit source events cite their source record ID.
   Account identity/lifecycle events cite the owned financial-account snapshot;
   transaction lifecycle events cite the retained transaction snapshot. Both
   are explainable source observations and never create a second ledger row.
5. Paid/skipped source states become observed/cancelled states. A paid source
   without an exact ledger match remains `user_status` or `issuer_status` with
   no transaction ID.
6. Past exact expectations become overdue; late pattern expectations become
   missed. Similar labels or amounts never create an automatic observation.
7. The response includes ruleset version, confidence, sufficiency, data-through
   date, assumptions, and per-state counts so future forecasts can consume the
   same evidence contract.
8. `PUT /api/knowledge/events/{event_id}/decision` persists an owned overlay.
   Confirmations raise confidence; cancellations and manual observations change
   the event state; explicit conflicts retain the user's reason.
9. Exact transaction links are owner-, direction-, currency-, ignored-state-,
   and date-window validated. A material amount mismatch becomes a visible
   conflict while retaining both expectation and observation evidence.
10. `DELETE` removes only the overlay and recomputes the source-derived event.
    Decisions are included in portable export schema v8 and removed by owned
    account deletion.
11. `GET /api/knowledge/events/audit` rebuilds the selected range without
    writes, then reports applicable/orphaned decisions, ruleset drift, missing
    exact links, and event counts by kind/state. Repeated audits are identical
    while source evidence is unchanged.
12. Cash-flow ruleset v6 consumes active current/future inflow and outflow
   events as projection floors. Conflicts widen the upper spend range and lower
   confidence; observed/cancelled events are not forecast again.
13. The Plan surface exposes overdue, missed, and conflicting events with their
    source evidence, confidence, and assumptions. Users can confirm an event
    occurred or mark it cancelled; both actions persist an owned decision and
    invalidate the cash-plan/workspace read models.
14. `GET /api/analytics/cash-flow/backtest` evaluates completed months at day
    7/14/21 cutoffs using only ledger evidence available by each cutoff and up
    to 6 earlier training months. It reports MAE, median APE, WAPE, interval
    coverage/width, settled versus unsettled retained rows, and excluded
    periods. Pending, failed, declined, cancelled, expired, and reversed rows
    remain visible but do not contribute to settled spend or income.
15. The backtest does not reconstruct mutable temporal sources from their
    current state. Its response marks temporal evidence unevaluated until
    knowledge-time history prevents future-status leakage, and discloses that
    current ledger correction/review state is applied without historical
    decision timestamps.
16. `POST /api/knowledge/history/backfill` previews or captures a current
    baseline for legacy transaction, account, statement-line, or card-payment-
    intent rows without immutable snapshots. It is explicitly forward-only; it
    improves future cutoff coverage but never turns a present-day row into
    evidence that was known in the past. Statement-line snapshots preserve
    issuer review and settlement lineage; card-payment-intent snapshots preserve
    user planning status, not issuer settlement proof.
17. `POST /api/analytics/cash-flow/snapshots` explicitly freezes the current
    projection, evidence, assumptions, confidence, and rulesets. Repeating the
    same user/target/cutoff/ruleset request returns the original row even when
    later ledger activity changes the live projection.
18. Outcome evaluation considers only snapshots whose target month has closed.
    It writes one separate outcome per snapshot with actual income/spend/net,
    absolute and percentage spend error, and interval coverage. Repeated runs
    do not rewrite or duplicate outcomes.
19. Snapshot/outcome rows are user scoped, portable in export schema v8, and
    erased with the owned account lifecycle.
20. `GET /api/analytics/reconciliation-quality` exposes observed transaction,
    statement-line, verified-balance, duplicate-candidate, and unexplained-
    movement evidence. It reports review coverage without implying that a
    provider feed or account universe is complete.
21. `GET /api/analytics/intelligence-readiness` combines the workspace's source
    coverage, transaction/account/issuer-line/card-intent temporal snapshot coverage, rolling forecast evidence,
    reconciliation quality, and privacy-safe recommendation status into
    explicit ready/collecting/blocked/deferred gates. It is a recovery view,
    not an 85% intelligence claim; anomaly adjudication and representative
    release evidence remain deferred until aggregate artifacts pass their
    quality thresholds.

Anomaly release evidence must contain both prompted and sampled non-prompted
cases, as well as both material and expected reviewer labels. A runtime list of
only surfaced anomalies is useful for user feedback but cannot establish recall
or false-positive rate and therefore remains deferred by the evaluator.

## Recommendation decision and outcome loop

1. PFIS derives and ranks recommendations from the selected owned workspace.
   The browser cannot invent a recommendation ID and persist it as accepted.
2. Accept, not-relevant, dismiss, and snooze requests recompute that period and
   snapshot the matching title, target, expected impact, evidence, reason codes,
   ruleset, financial date, optional user note, and a typed baseline for a
   supported review, budget, recurring-cost, or savings metric. Not-relevant
   actions may also carry a structured reason (`not_feasible`, `already_done`,
   `too_risky`, or `wrong_timing`) so repeated infeasible prompts can be
   down-ranked without hiding unrelated recommendation types.
3. Accepted and not-relevant recommendations leave the active brief; snoozed
   recommendations return after their owned resume time.
4. Only an accepted decision can receive a later outcome. Helped, no-change,
   worse, or not-completed outcomes may include one typed actual impact value.
5. Outcome creation is idempotent and immutable. A different second payload is
   rejected rather than silently rewriting whether advice helped.
6. PFIS recomputes the same supported metric for the decision period and stores
   baseline, observed value, and directional automatic change separately from
   the user's helped/no-change/worse answer.
7. The Action follow-up UI exposes the baseline, collects one calm outcome, and
   then shows the measured change without engagement scores or celebratory UI.
8. Decisions/outcomes are user scoped, included in portable export schema v8,
   and erased by account deletion.
9. The effectiveness evaluator groups only recent immutable outcomes by
   recommendation type, guidance ruleset, outcome ruleset, metric, and unit.
   A cohort remains completely hidden until it has at least 10 outcomes from 5
   distinct active users.
10. Automatic-impact rates and averages have an independent 10-outcome/5-user
    threshold. Not-completed actions are excluded from measured effectiveness,
    and reported help is never presented as causal proof.
11. Analytics shows either the safeguard explanation or the eligible aggregate
    cohorts. It never exposes individual answers, notes, or user identifiers.

## Conflict-aware recommendation ranking

1. Every active recommendation carries a bounded consequence range, a
   smallest feasible step, freshness date, confidence, urgency, and
   reversibility. Missing Cash Plan evidence is represented as a data gap rather
   than converted into flexible-money or future-income estimates.
2. Savings, recurring, and budget actions surface overlap when they may target
   the same money. Savings actions become blocking when the confirmed shortfall
   is larger than flexible money or when the Cash Plan is not ready.
3. Active savings, category-reduction, and recurring-reduction goals are linked
   to supporting recommendations. A goal that exceeds confirmed flexible money
   is shown as a trade-off, never silently funded from obligations or reserves.
4. Ranking combines consequence materiality, confidence, urgency,
   reversibility, goal support, and conflict penalties. Explicit personal
   feedback can adjust a type only after three completed outcomes and never by
   more than six priority points; the adjustment is visible in evidence.

## Bills, card planning, and household sharing

1. Bills and subscriptions have explicit due, paid, or skipped status; no
   recurrence guess silently changes the Cash Plan.
2. Card utilisation settings, reward assumptions, payment intents, calendars,
   and disputes are user-owned records. Calendar reminders can be corrected or
   removed. PFIS does not initiate, block, or imply an issuer/bank action.
3. A planned card payment may be cancelled without a ledger effect. After the
   user confirms that the external payment occurred, PFIS can record one paired
   manual bank-to-card transfer. Repeating the same record action does not create
   another transfer, and the card leg is classified as payment rather than spend.
4. The Cards payment-runway panel labels a planned payment as intention only. A
   `covered` result means the conservative forecast covers the full issuer total
   due; it is never a live issuer balance, available-credit assertion, or bank
   payment-success signal.
5. The same read model returns `payment_scenarios` for minimum-due and full-due
   planning. Existing planned intentions are credited toward each strategy, while
   any additional amount, remaining billed due, and conservative post-payment
   balance remain hypothetical. Missing funding or anchor evidence leaves the
   scenarios `unavailable` instead of treating the minimum due as affordable.
6. Household owners explicitly add members and can change a non-owner between
   member and viewer access. Viewers are read-only; members can add shared
   annotations and settlement intentions. A member can leave, while an owner
   can remove another member only after that member's planned settlements are
   resolved. Shared expenses are purpose-built annotations and allocations,
   not private transaction links.
7. Settlements move from planned to completed/cancelled through an explicit
   update. Planned settlements must be resolved before involved members or the
   household are deleted.
8. Payoff comparison uses only liabilities with explicit balance, annual rate,
   and minimum payment, and always exposes excluded incomplete records and
   assumptions.
