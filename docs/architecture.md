# PFIS Architecture

PFIS is a FastAPI personal-finance backend with a React dashboard served by FastAPI. It turns financial emails into structured transactions and insights.

## Layers

1. API routes in `backend/app/api/routes`
2. Service layer in `backend/app/services`
3. Knowledge Engine in `backend/app/services/knowledge`
4. Parser pipeline in `backend/app/services/parser`
5. ORM models in `backend/app/models`
6. Pydantic schemas in `backend/app/schemas`
7. React dashboard source in `frontend/`
8. Built dashboard assets served by FastAPI from `frontend/dist`
9. Tests in `tests/pytest`

## Core Pipeline

```
Gmail/demo raw email
  -> email classification
  -> parser registry
  -> ParseResult
  -> user-scoped merchant resolution
  -> category assignment
  -> transaction deduplication
  -> transaction storage
  -> knowledge rules (evidence, cadence, confidence, provenance)
  -> temporal expected/observed events -> financial intelligence (stability, forecast, recommendations)
  -> immutable forecast snapshot -> closed-period outcome evaluation
  -> premium workspace, reports
```

Connector-driven ingestion now sits before raw email storage:

```
Connector
  -> SourceRecord
  -> classification engine
  -> RawEmail persistence
  -> domain events
  -> parser pipeline
```

## Module Boundaries

- Route modules validate HTTP inputs and call services.
- `TransactionService` owns transaction create/update/delete, dedup, correction learning, and summaries.
- `FinancialPositionService` owns statement ingestion/reconciliation, verified
  account positions, Cash Plan inputs, reserves, liabilities, schedules, and the
  statement-backed card read model.
- `RoadmapService` owns bills, safety checks, card disputes, privacy-separated
  household annotations/settlements, and deterministic payoff comparison.
- `TemporalEventService` recomputes one versioned expected-versus-observed
  timeline from owned bills, commitments, schedules, reserves, card dates,
  planned income, and recurring ledger evidence. It preserves typed source
  references and never infers a ledger match from merchant/amount similarity.
- `AccountService` owns explicit product identity, append-only balance
  observations, and atomic two-leg transfers. Email ingestion and statement
  review use the same account/transfer invariants.
- `services/ledger_currency.py` owns the single-ledger-currency write policy,
  shared-household compatibility checks, and aggregate integrity telemetry.
  Every spend/income predicate correlates a transaction to its user's ledger
  currency, while mismatches remain visible in Activity for explicit repair.
- `services/financial_clock.py` and `utils/financial_time.py` own the user's
  validated IANA timezone and financial calendar boundary. Financial services
  must not use the server-local day for user decisions.
- `PortableExportService` owns the versioned personal-data archive contract. It
  uses an explicit include/exclude decision for every persisted table, applies
  ownership filters before serialization, aliases shared-household actors, and
  emits deterministic JSONL payloads with manifest checksums. Routes only
  authorize, rate-limit, and stream the resulting no-store archive.
- `retention_service.py` owns versioned, lineage-preserving source redaction.
  User policy changes and the system retention scheduler feed the same durable
  `raw_email_retention` job handler. Eligibility is resolved before an atomic
  conditional update, and audit events are created only for rows actually
  redacted, making retries and concurrent workers idempotent.
- `account_deletion_service.py` owns the irreversible lifecycle boundary. It
  commits a user write fence, cancels tracked jobs and ingestion, stops/revokes
  connectors, applies a table-complete private-data inventory in reverse
  dependency order, closes or transfers household participation, strips the
  user to a non-login shared-evidence tombstone, and writes one non-secret
  terminal audit event. The route owns recent-auth, typed-confirmation,
  rate-limit, CSRF, and cookie-clearing concerns.
- The global `Merchant` catalog is curated shared reference data. Explicit user corrections are
  stored as `UserMerchantRule` rows and take precedence during resolution without mutating other
  users' merchant behavior.
- Merchant resolution records its source, confidence, matching rule, and resolver version on the
  transaction so later intelligence remains explainable.
- `services/knowledge` owns reusable evidence contracts, versioned rulesets, and recurring-stream
  lifecycle analysis. Insights, merchants, forecasts, guidance, and workspace recommendations must
  consume this service instead of implementing competing recurrence heuristics.
- Recurring knowledge groups only user-owned debit ledger entries with the same account, normalized
  merchant, and currency. It separates cadence confidence from amount confidence and exposes
  `candidate`, `early`, `mature`, `missed`, and `inactive` lifecycle states.
- `IntelligenceService` separates Monthly Stability (financial behavior) from Data Confidence
  (coverage and classification quality). Review cleanliness never raises Monthly Stability.
- `WorkspaceService` is the authoritative premium briefing read model. It includes projection,
  month comparison, stability/data confidence, recurring commitments, evidence, and ranked actions
  so the Today workspace does not issue overlapping analytics requests. Empty periods take a
  two-query fast path and return the same stable response contract without invoking the complete
  analytics graph.
- Parser modules extract transaction data only; they do not write database rows directly.
- Parser persistence is atomic per source email: the ledger row, processed flag,
  summary invalidation, failure state, and pipeline events commit together.
- A parsed source whose currency differs from the user ledger is retained as a
  `ledger_currency_mismatch` failure at the persist stage; it never creates a
  transaction and is not misreported as an unknown parser exception.
- Background work is claimed from the database with an atomic lease. Every API
  replica may run a worker poller without executing the same queued job twice;
  queued jobs survive process restarts and unexpected failures retry within a
  bounded attempt budget.
- Gmail sync stores raw email and sync metadata; processing happens through parser pipeline.
- Gmail and statement arrival order is deliberately symmetric. A statement line
  can match an earlier email transaction; a later email can also attach its
  source evidence to a statement-created transaction. Both paths converge on
  one ledger event and one statement match.
- Fuel reconciliation is a controlled exception to exact amount matching:
  explicit fuel merchant evidence may reconcile a lower real-time alert with a
  bounded higher posted statement charge. The official posted amount replaces
  the alert amount while a separate surcharge-waiver credit remains visible.
  User merchant/category corrections are not overwritten.
- Issuer-labelled EMI rows feed an evidence-only liability materializer. It
  exposes the latest instalment anatomy and cumulative evidence but does not
  infer rate, tenure, remaining instalments, outstanding balance, or progress.
- Connector implementations fetch source records only; the ingestion coordinator owns sync orchestration, audit records, retry handling, and domain events.
- Security helpers own JWT decoding, optional auth, user-scope resolution, and resource ownership checks.

## Cross-domain financial change propagation

Authoritative ORM writes to transaction, account, statement, card, planning,
guidance, and ingestion source tables append one user-scoped invalidation event
inside the same PostgreSQL transaction. The explicit table-to-domain allowlist
is in `financial_change_capture.py`; Core/bulk mutations use its async helper.
Because `User` is keyed by `id` rather than `user_id`, a changed financial
timezone is explicitly journaled by the profile route for activity, Today,
planning, and guidance consumers. Learned merchant-rule changes invalidate both
activity and data views.
Derived read models such as monthly summaries and forecasts do not recursively
emit events. Payloads contain only an opaque event ID, per-user sequence, event
type, domain tags, and timestamp—never balances, transactions, or statement text.

`FinancialChangeCursor` allocates each user's monotonic sequence, while
`FinancialChangeEvent` retains replay metadata for 90 days. A transaction-scoped
PostgreSQL advisory lock preserves the global identity order used by worker
tailers. Every API process polls committed rows and relays them to its own local
WebSocket connections; `GET /api/sync/changes` is the durable recovery path for
reconnects, process restarts, and missed socket hints. No external message broker
is required.

The React shell stores only the per-user replay cursor in versioned
`sessionStorage`, replays on socket connection, network recovery, tab visibility,
and at a 15-second fallback interval, then invalidates matching current-user
React Query roots. `BroadcastChannel` messages are hints between tabs; each tab
still fetches its own ordered journal. An expired or future cursor requires a
user-scoped full query invalidation before resuming. This reports change-channel
connectivity, not freshness from Gmail, HDFC, a bank, or a credit bureau.

### Migration rollout and recovery

Migration `057_financial_change_journal` is additive: it creates only the
per-user cursor and metadata-event tables. Apply it before starting the updated
API; the previous application version can continue to run while those unused
tables exist. If application rollback is needed, roll back the API and frontend
first and leave the additive schema in place. Run the migration downgrade only
after the old application is active and only when intentionally discarding
replay metadata; it does not alter ledger, statement, balance, or planning
source rows.

For database recovery, restore a consistent database snapshot rather than
reconstructing journal rows by hand. Clients whose saved sequence is ahead of a
restored user cursor receive `reset_required` and invalidate that user's views.
Verify the Alembic head and authenticated replay before returning the updated
API to service. This change has not been deployed to production.

## Extension Points

- New bank format: add or update a parser and registry mapping.
- New API capability: add schema, service behavior, route, docs, tests.
- New dashboard feature: add backend contract first, then frontend rendering.
- New data source: produce raw records compatible with the parser pipeline.

## Financial position read path

```text
Email alert ─┐
             ├─> instrument resolver ─> canonical ledger event ─┐
HDFC PDF ────┘                                                  ├─> account/card position
verified balance snapshot ──────────────────────────────────────┤
confirmed commitments + complete liability schedules ──────────┤
approved reserve allocations ───────────────────────────────────┘
                                                                └─> Cash Plan / Today horizon
```

## Temporal knowledge read path

```text
planned income ───────────────┐
bills + commitments ─────────┤
issuer liability schedules ──┤
card milestones + reserves ──┼─> TemporalEventService
recurring debit/credit rows ──┘       │
                                      ├─> exact events (user/issuer evidence)
                                      └─> estimated windows (pattern evidence)
```

The temporal model is a recomputable read model, not a second ledger and not a
generic graph. Exact observations and pattern-derived expectations share one
typed contract, but their confirmation modes, source IDs, confidence, and
assumptions remain distinct. A paid source status without a matched transaction
is represented as an explicit observation with a null transaction ID.

Official statement values remain immutable statement-date observations. Any
post-statement card value is labelled estimated and is produced only when all
contributing activity is visible. Bank positions use the most recent verified
snapshot, never a partial alert-derived “live” balance.

## Frontend Direction

The React shell reconnects the user-scoped sync WebSocket with bounded
exponential backoff and a heartbeat. Durable change replay invalidates dependent
views after commits, on reconnect, when connectivity returns, and when a tab
becomes visible; a short journal poll is the fallback. Update-channel status is
presented separately from upstream source freshness. Code-split route
and nested feature failures caused by a newly deployed hashed bundle trigger
one guarded shell reload per chunk; a workspace error boundary prevents an
unexplained blank page or reload loop.

The React/Vite app under `frontend/` is the canonical UI. FastAPI serves its production build at `/dashboard` and never falls back to the retired static dashboard. Production startup fails when the React build artifact is missing. Financial read models use event-driven cache invalidation with bounded staleness; only operational status views retain low-frequency foreground polling. See `docs/frontend.md`.
