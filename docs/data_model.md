# PFIS Data Model

> **Scope:** persistence layer (SQLAlchemy ORM entities and storage rules).
> For API/Pydantic request and response shapes, see
> [data-models.md](data-models.md).

PFIS uses async SQLAlchemy models under `backend/app/models`.

## Main Entities

- `User`: registered user profile, currency, auth status.
- `AuthIdentity`: external provider identity keyed by stable provider subject and linked to a user.
- `AuthSession`: revocable server-side browser session containing only hashed session and CSRF tokens.
- `GmailAccount`: connected Gmail account, encrypted token references, and the
  access-token expiry used for proactive refresh.
- `FinancialAccount`: user-owned account identity with explicit/inferred status,
  bounded confidence, compact evidence references, and activation lifecycle.
- `TemporalSourceSnapshot`: append-only state observations used to reconstruct
  account identity changes, issuer statement-line review/settlement lineage,
  card-dispute status, and other mutable planning sources at a financial-day
  cutoff.
- `AccountLinkRule`: user-approved masked-identifier evidence mapped to one
  active owned account; deactivation never reverses historical corrections.
- `AccountBalanceSnapshot`: append-only balance observation for an asset or liability
  account. `verified` distinguishes trusted anchors from provisional observations;
  optional `effective_at` records the provider/source timestamp used to avoid
  double-counting same-day transactions. Optional `source_record_id` makes
  connector retries idempotent without mutating the observation. Multiple
  observations may share a financial day when their source identities/effective
  times differ; un-identified manual duplicates remain rejected by the service.
- `AccountBalanceSource`: operational freshness/cadence state for one account
  source. It records the opaque provider account key, expected refresh cadence,
  coverage window, completeness flag, last successful observation, and stable
  source record ID. It never stores connector credentials and is not itself a
  financial balance fact.
- `TransactionSplit`: user-owned category/label allocation of one transaction.
- `StatementImport`, `CreditCardStatement`, `StatementLine`, and `StatementLineMatch`:
  credit-card statement evidence and reconciliation records.
- `StatementAnalysisReview`: user-owned, fingerprint-idempotent review evidence
  for an unfamiliar or ambiguous statement. It stores only detector metadata and
  a bounded redacted analysis JSON payload; it intentionally has no account
  foreign key and never stores source text, PDF bytes, full account numbers, or
  ledger activity.
- `DepositAccountStatement` and `DepositStatementLine`: arithmetically reconciled
  HDFC or issuer-neutral bank-statement boundaries and their immutable source
  rows. A line records value date, direction, explicit payment rail, balance
  after, review outcome, and an optional created/matched ledger transaction. A
  verified closing-balance observation is append-only and keyed to the statement.
  Source PDF bytes, passwords, full account numbers, and statement text are
  never stored.
- `Commitment`, `CashPlan`, `ReservePlan`, `Liability`, and `LiabilityScheduleItem`:
  source-labelled planning and debt records that supply confirmed financial obligations.
- `RoadmapBill`, `HealthChecklistItem`, and `CardDispute`: user-owned daily
  management records with explicit status and source fields.
- `Household`, `HouseholdMember`, `HouseholdExpense`, and `HouseholdSettlement`:
  the separate shared-expense domain. Shared expenses contain annotations and
  allocations, not links to private ledger evidence.
- `StatementLineReviewDecision`: append-only statement review and correction
  evidence, including the previous/new outcome and optional matched transaction
  or paying account.
- `DepositStatementLineReviewDecision`: append-only user decisions for unknown
  bank-statement rails, including the selected supported rail (when imported),
  previous/new outcome, optional created/matched transaction, and bounded note.
- `DashboardPreference`: versioned, user-owned widget layout, theme, density, favorites, onboarding goal, and in-app briefing cadence.
- `RecommendationState`: user-owned dismissal or snooze state keyed by stable recommendation id.
- `MonthlySummary`: persisted dashboard/report aggregate cache for one user and month.
- `RawEmail`: stored email subject/body/sender/received timestamp for traceability;
  `content_redacted_at` records irreversible policy-driven clearing while the
  source row and transaction linkage remain.
- `Transaction`: parsed financial transaction with confidence, parser version, fingerprint, and optional source email.
- `Category`: category hierarchy for spending groups.
- `Merchant`: curated shared merchant name, aliases, and default category. User workflows do not
  mutate this global catalog.
- `UserMerchantRule`: exact, user-owned mapping from an imported merchant descriptor to the user's
  preferred normalized name and category.
- `Budget`: user/category monthly budget limit.
- `SyncRun`: Gmail sync observability record.
- `ParseFailure`: dead-letter queue for failed parser attempts.
- `UserCorrection`: feedback loop for corrected merchant/category/amount fields.
- `BackgroundJob`: async job tracking.
- `OAuthState`: single-use OAuth transaction with expiry, flow type, browser binding, encrypted PKCE verifier, and encrypted OIDC nonce.

`User.currency` is the currency of the user's complete private ledger, not a
display preference. New financial accounts, balances, transactions, transfers,
and imported ledger events must match it. Shared households require all members
and all annotations to use the same ledger currency. PFIS does not sum or
convert mismatched currencies; legacy mismatched transactions are visible for
repair but excluded from financial-effect read models. Monthly summary caches
carry the `single-ledger-v1` aggregation contract and ledger currency so an old
mixed-currency cache cannot be reused.

`User.timezone` is a validated IANA timezone and defaults existing Indian-ledger
profiles to `Asia/Kolkata`. Financial services derive "today," current periods,
freshness windows, due/upcoming decisions, and forecast elapsed days from this
field. Source-authored transaction dates remain evidence and are never shifted
to another day.

`User.raw_email_retention_days` is nullable and constrained to 30, 90, 180, or
365 when present. The default is 365; null is the explicit keep-until-deleted
policy. It controls processed source content only, not derived ledger records.

`User.deleted_at` distinguishes an active profile from the minimal tombstone
retained only when shared household rows still reference that participant.
Deletion replaces email/name, clears password and identities, deactivates login,
and removes every private row. `HouseholdMember.left_at` closes access without
destroying another member's shared expense/settlement evidence.

Transactions may reference a `FinancialAccount` through the nullable
`financial_account_id` field. Migration `009_financial_accounts` backfills
accounts from existing four-digit account metadata; new ingestion reuses the
user-scoped account record and never stores full account numbers.

Account identity is intentionally separate from balance truth. An imported
masked suffix creates an `inferred` account hint with bounded confidence; a
user-created or explicitly resolved institution/product/masked identity becomes
`confirmed`. `identity_evidence_json` stores only typed, non-secret source
references and short notes. Updates to identity fields and activation status
append a `financial_account` row in `TemporalSourceSnapshot`; prior snapshots
remain immutable, and deactivation retains historical evidence.

Migration `011_premium_workspace` adds asset/liability classification, balance
snapshots, dashboard preferences, recommendation state, and linked transfer
metadata. Balance snapshots are immutable after creation. Manual observations
without a source identity remain unique per account and date; provider and
statement observations may share a date when their source identities/effective
times differ. Net worth carries forward each account's most recent **verified**
snapshot and calculates assets minus liabilities. It does not infer balances from
cash flow.

Migration `012_financial_rhythm` adds the non-null `briefing_cadence` preference
with a backward-compatible `daily` default. Allowed API values are `daily`,
`weekly`, and `monthly`; the value only controls the deterministic in-app brief
period and does not schedule external notifications.

Migration `014_auth_sessions` adds external identities and revocable browser
sessions, and hardens OAuth transactions with browser binding, PKCE, and nonce
references. Google identity and Gmail connector authorization remain separate
records and separate consent flows.

Migration `015_financial_integrity` moves ledger amounts, balances, budgets, and
goal targets to `NUMERIC(18,2)`, rejects invalid monetary values, enforces one
budget per user/category and one Gmail connection per user/account, and keys
financial-account identity by user, institution, account type, and masked number.
The migration refuses to guess when legacy duplicates or invalid amounts exist;
operators must reconcile those rows before retrying.

Migration `016_durable_jobs` turns `BackgroundJob` into a durable queue record
with atomic leases, attempt limits, retry availability, and scoped idempotency
keys. Queued work survives restarts; interrupted running leases are requeued
until their attempt budget is exhausted.

Migration `018_financial_position_foundation` separates payment rail, card event,
source, and review outcome from the legacy `payment_method` compatibility field. It
also adds statement, commitment, reserve, cash-plan, and liability persistence. A
flexible-money value requires a fresh verified balance, a confirmed next income
date, and an eligible current account position. Settled post-anchor movement may
roll the position forward; pending, unreviewed, or cutoff-ambiguous activity
blocks the spendable total while remaining visible as position evidence.

Migration `019_card_cash_extensions` adds user-owned card preferences, payment
intents, and card calendar events. These are planning records only: they cannot send
payments, block cards, or claim issuer data beyond the imported statement snapshot.

Migration `020_transaction_management` adds transaction notes, serialized tag
metadata, and normalized split-allocation rows. Split rows must total the original
transaction amount and are not transactions themselves, so monthly aggregates
continue to count the source ledger event exactly once.

Migration `021_roadmap_extensions` adds bill lifecycle, safety checklist, card
disputes, household membership/annotation/settlement tables, and their
user/household access indexes. The household model deliberately has no
transaction foreign key, preventing shared members from traversing into a
private account or source email.

Migration `022_statement_review_history` adds immutable statement-line review
decisions. The current `StatementLine.review_outcome` is the fast read state;
the decision table is the historical evidence explaining how it changed.

Migration `023_account_link_rules` adds durable user-approved masked-suffix
resolution. Rules are unique per user/evidence/currency and can repair only
uncorrected unknown or unlinked history. Every repair appends a
`UserCorrection`; a prior explicit account correction always wins.

Migration `024_merchant_emi_intelligence` adds derived statement merchant and
EMI component evidence without changing immutable issuer descriptions.
Migration `025_liability_evidence` extends liabilities with observed EMI
anatomy and explicit schedule state.

Migration `026_spend_truth` adds `Transaction.is_accounting_adjustment` and
`ledger_subtype`. Issuer conversion debit/credit pairs and similar anatomy stay
in the audit ledger but are excluded from spend/income read models. Refunds
produce a negative spend effect; transfers, ignored evidence, card payments,
and accounting adjustments produce no spend/income effect.

Migration `027_user_timezone` adds the required 64-character IANA timezone to
users with a backward-compatible `Asia/Kolkata` default.

Migration `028_raw_email_retention` adds the owned retention policy,
`RawEmail.content_redacted_at`, a constrained policy domain, and the composite
retention eligibility index.

Migration `029_account_deletion` adds the indexed user tombstone timestamp and
indexed inactive-household-membership timestamp used by the deletion boundary.
Migration `030_parser_source_telemetry` adds a non-secret source institution to
pipeline events and an institution/time index for bounded operational quality
and drift aggregation. It never stores sender, subject, body, merchant, amount,
or account identifiers in that field.

Migration `031_temporal_event_decisions` adds one user-owned decision per stable
derived temporal event. The row records the source identity, occurrence date,
ruleset version, confirmation/cancellation/observation/conflict choice, and an
optional exact transaction foreign key. Transaction deletion clears only that
link; account deletion removes the owned decision. These rows are overlays on
recomputed knowledge and never create or mutate ledger activity.

Migration `032_forecast_accountability` adds `CashFlowForecastSnapshot` and
`CashFlowForecastOutcome`. A snapshot is immutable prediction evidence unique
to user, target month, financial-day cutoff, and forecast ruleset. It retains
the original projection/range, confidence, evidence, assumptions, and temporal
ruleset/totals. A separate one-to-one outcome stores the closed-month actuals,
spend error, and interval coverage under its own ruleset. Deleting a snapshot
cascades to its outcome; owned export and account deletion include both tables.

Migration `033_recommendation_decisions` extends `RecommendationState` from a
hide preference into an optional server-snapshotted decision record. Accepted,
not-relevant, dismissed, and snoozed states can retain type, title, target,
expected impact, evidence, reason codes, guidance ruleset, selected date, and
user note. Supported recommendations also retain a typed metric key, value, and
unit as the decision-time baseline. `RecommendationOutcome` is a user-owned
one-to-one immutable outcome for accepted advice with helped/no-change/worse/
not-completed state, optional typed user impact, and the server-recomputed
observed metric plus directional automatic change. Deleting the decision
cascades to its outcome.

Migration `034_account_deletion_compat` conditionally restores the
`users.deletion_started_at` column and index for legacy databases that were
already stamped at revision 029 before its final schema shape. Fresh databases
are unchanged, and the repair is forward-only so existing deletion state is
never dropped during compatibility recovery.

Migration `035_rec_conflict_contract` extends recommendation decisions with a
bounded consequence range, smallest feasible action, conflict and goal-link
snapshots, confidence, freshness, urgency, and reversibility. These fields are
immutable evidence context for a decision; they do not turn a recommendation
into a prediction when the Cash Plan or source evidence is incomplete.

Migration `036_temporal_source_history` adds append-only snapshots for mutable
planning sources used by temporal evaluation. Cash Plans, bills, commitments,
complete liability schedule rows, transactions, approved reserves, and card
calendar events record a user-scoped JSON state after each service-layer
create/update/delete.
Historical-safe timelines select the latest state known at the requested
financial day; they never rewrite an earlier snapshot. Unsupported mutable
sources remain excluded until they have the same history contract.
Transaction snapshots now also support typed lifecycle read events for pending,
failed, refund, and reversal states; these are read-model evidence over the
existing ledger row, never additional money movement.
`POST /api/knowledge/history/backfill` can capture a current baseline for
legacy transaction, financial-account, issuer statement-line, and card-payment-
intent rows that predate the snapshot hooks. The response reports candidate,
missing, skipped, and captured counts. This is forward-only evidence: the
captured timestamp is the first safe knowledge time, not a reconstruction of the
row's earlier state.
Settled spend/income aggregates accept only completed/posted/settled/captured
statuses; pending, failed, declined, cancelled, and reversed rows remain
visible for audit and temporal review without changing settled totals.

Migration `037_recommendation_resolution` adds a JSON resolution snapshot to
recommendation decisions. The snapshot records whether an action is ready,
needs review, blocked, or requires a user choice, together with one next step,
the rationale, related overlapping recommendations, and competing goal IDs.
It is advisory and never moves money or silently changes goal priority.

Migration `038_account_identity_evidence` adds the current account identity
status, bounded confidence, compact evidence references, and `updated_at`
timestamp. Account creation, explicit identity resolution, masked-suffix
approval, and activation/deactivation append `financial_account` snapshots to
the temporal source history so current API fields and historical-safe timelines
share one evidence contract.

Migration `039_anomaly_adjudications` stores append-only user or reviewer
adjudication of anomaly materiality and expectedness. These rows are feedback
evidence, not release-quality proof until protected aggregate cohorts exist.
Migration `040_recommend_feedback_reason` adds bounded structured reasons
for relevance feedback (`not_relevant`, `not_feasible`, `already_done`,
`too_risky`, and `wrong_timing`) so personalization can respond without
silently rewriting the recommendation ledger.

Migration `041_anomaly_prediction_label` records whether an anomaly decision was
made on a surfaced alert or a server-sampled non-alert case. This distinction is
required for honest recall and false-positive measurement; `insufficient_evidence`
decisions remain feedback but are excluded from binary release labels.

Migration `042_sync_coverage_metrics` records whether a provider query was
fully exhausted or truncated on each sync run, including pagination and result
estimate evidence for source-completeness decisions.

Migration `043_balance_position_truth` adds the optional `effective_at` timestamp
to account balance observations. The account-position read model uses it when
available and otherwise excludes same-day transactions conservatively.

Migration `044_balance_snapshot_source_identity` adds the optional provider/source
record identity and a scoped uniqueness contract so the same connector
observation can be retried safely.

Migration `045_balance_observation_multi` removes the legacy one-snapshot-per-day
constraint and adds an account/effective-time index. This allows a provider
observation to arrive on the same day as a statement or manual check without
overwriting either fact; connector observations must carry `source_record_id`.

Migration `046_balance_source_coverage` adds the connector-neutral source state
used to distinguish a fresh provider observation from a due, overdue, or
history-truncated source. The state is updated idempotently from provider
observations and is exposed alongside the account-position proof line.

Migration `047_balance_source_cursor` adds an opaque connector pagination cursor
to that operational state. `BalanceSyncService` resumes a mapped provider
refresh from a single consistent cursor when possible, records provider-safe
audit events, and marks every affected account incomplete on connector failure
or a partial response that omits one of the requested accounts; an observation
for an unrequested account is rejected. The cursor is never returned in the
user-facing coverage response.

`BalanceForecastService` still rebuilds the live daily read model from the
canonical account position, reviewed settled transactions, and user/provider-
sourced dated records (`CashPlan`, confirmed `Commitment`, `CardPaymentIntent`,
and `LiabilityScheduleItem`). Migration `048_account_balance_forecast` adds
immutable `AccountBalanceForecastSnapshot` and
`AccountBalanceForecastOutcome` rows for prospective accountability. Snapshots
retain the full point path at an explicit cutoff; outcomes are created only
when an exact-date verified observation exists, preserving error and interval
coverage evidence without treating a forecast as a balance fact. Migration
`049_balance_reconciliation` adds append-only `AccountBalanceReconciliation`
intervals between consecutive verified observations. Each interval stores
eligible settled movement, excluded transaction IDs, expected versus observed
closing balance, signed and absolute residual drift, reason codes, and a
ruleset/status. A later transaction or source correction never mutates the
interval that was known at capture time.

Migration `050_balance_provider_connections` adds the non-secret provider
connection lifecycle. It records provider type, consent status and expiry,
refresh timestamps, and stable error codes; credentials and raw consent
artifacts are intentionally excluded. The balance refresh job can only run
when a registered connector and active consent are both present.

Migration `051_card_position_observations` adds append-only issuer facts for
credit cards. Current outstanding, billed due, pending amount, credit limit,
and available credit are stored independently with source identity, effective
time, and coverage evidence; missing issuer fields remain unknown rather than
being derived from an estimate.

Migration `052_balance_provider_account_mappings` adds provider-scoped account
identity mappings. A mapping belongs to one user, provider type, and owned
financial account; provider account identities are unique within that provider
and cannot be silently shared by two local accounts. This prevents Gmail or
another connector's legacy account identity from being mistaken for a bank or
issuer account when live refresh is enabled.

Rejected HDFC statement attempts use the existing `connector_audit_events`
table with `connector_type=statement` and stable reason codes only; uploaded
PDF/text content and source descriptions are never persisted as telemetry.

Liability schedules are confirmed as a whole. The API refuses
`complete_schedule=true` on ordinary liability creation, refuses duplicate or
unordered due dates, and does not replace an existing schedule. On confirmation,
each upcoming instalment creates one confirmed `Commitment` linked by
`liability_id` and a stable `liability_schedule:{item_id}` source identifier.
Marking the schedule row paid or skipped deactivates only that linked
commitment; restoring it to upcoming reactivates the commitment and recomputes
remaining instalments and next due.

An atomic transfer creates debit and credit transactions with one
`transfer_group_id`. Both rows have `is_transfer=true`, remain auditable in the
transaction ledger, and are excluded from income/spend aggregates.
Imported transfer candidates are not stored as facts: the matching service
derives deterministic pairs from settled, exact-amount rows within a bounded
posting window. Only the explicit `transfer-link` confirmation writes the shared
group ID and correction history, so uncertain counterparty matches cannot alter
balances silently.
An ATM withdrawal is the same atomic pair with `payment_rail=atm`: the bank leg
is a debit and the cash-account leg is a credit. A later manual purchase linked
to the cash account is the spending event, preventing the withdrawal and
purchase from being counted twice.

`MonthlySummary` is invalidated within the same transaction-service commit as
transaction creation, correction, or deletion. The next dashboard or report
read recomputes and persists the snapshot, keeping request-time aggregations
bounded without introducing a worker or broker.

## Operational access paths

### Merchant and EMI statement intelligence

`StatementLine` keeps the issuer descriptor immutable and stores separate derived
fields for `merchant_normalized`, `merchant_confidence`, `component_kind`,
`issuer_plan_reference`, and `installment_number`. EMI component kinds distinguish
conversion purchase/credit, principal, interest, tax, processing fee/reversal,
and pre-closure principal/interest. These fields do not imply a complete schedule,
annual rate, tenure, or remaining-instalment count.

Statement/email duplicates are reconciled only when account, direction, exact
amount, canonical merchant, controlled posting window, and candidate uniqueness
all agree. The statement line links to the retained ledger event and an
append-only review decision records the merge. Repeated same-merchant amounts
alone are never sufficient.

Migration `025_liability_evidence` extends `Liability` with an issuer plan key,
stable source identifier, latest observed statement date, evidence count, and
separate observed original/monthly/principal/interest/tax/fee amounts.
`schedule_status` distinguishes `not_provided`, `observed_partial`, and
`confirmed`; observed evidence never sets outstanding balance, rate, tenure, or
remaining instalments. `LiabilityScheduleItem` now stores optional tax and fee
anatomy plus immutable source identity and confidence.

EMI issuer keys are extracted from the loan token inside the component
description; a trailing statement `(Ref# ...)` identifies the posting and is
never used as the loan key. GST rows are linked to the correct EMI only when
their posting reference matches a previously observed EMI-interest reference.
This keeps simultaneous issuer loans separate and makes tax attribution
deterministic.

In addition to the transaction reporting indexes, the persistence layer keeps
composite user/time indexes on `RawEmail(user_id, received_at)` and
`SyncRun(user_id, start_time)`. These support incremental ingestion history,
sync-run timelines, and user-scoped operational queries without scanning all
users' records. The indexes are managed by Alembic migration
`008_operational_indexes` for shared and production databases.

## Rules

- All user-owned entities must be queried with user scope or checked with ownership helpers.
- Raw session and CSRF tokens must never be stored; persist hashes only. OAuth tokens and transient OAuth secrets must be encrypted before storage.
- Raw emails are retained to support reprocessing.
- Transaction `fingerprint` protects deduplication.
- Statement-import document fingerprints are unique per user and make repeated
  PDF imports idempotent.
- Direction (`transaction_type`), transport (`payment_rail`), funding/product
  account, and `card_event` are independent facts. `payment_method` is a
  one-release compatibility projection and is not the calculation source.
- Imported financial records carry source kind/identifier, parser or extractor
  version, confidence/review state, and append-only correction evidence where
  a user decision changes classification.
- Monetary API inputs accept at most two decimal places and monetary persistence
  uses fixed-scale decimal columns rather than binary floating point.
- Transfer legs must be created together and excluded from financial aggregates.
- Dashboard preferences, recommendation state, accounts, and balances are always user scoped.
- Parser changes must preserve `parser_version` traceability.
- Merchant corrections must remain user scoped. They create or update `UserMerchantRule` rows;
  they must not promote aliases or category preferences into the global `Merchant` catalog.
- Transactions preserve merchant-resolution source, confidence, rule id, and resolver version.
- Model changes require tests and migration review.
- Local/demo startup may create tables automatically for convenience, but shared or production environments must use Alembic migrations as the schema control path.

## Migration Discipline

PFIS keeps `Base.metadata.create_all` as a local/demo startup convenience only. It is not the production schema authority.

For shared or production-like databases:

- Apply schema changes through Alembic migrations under `backend/alembic/versions`.
- Keep Alembic migrations aligned with SQLAlchemy models in `backend/app/models`.
- Add or update tests before changing deduplication, ownership, or nullable field behavior.
- Run `tests/pytest/test_migration_discipline.py` when a model or migration changes.
