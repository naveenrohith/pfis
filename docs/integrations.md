# PFIS Integrations

## Gmail

PFIS integrates with Gmail through Google OAuth and Gmail API clients. Real Gmail calls must not run in tests.

Gmail is the first source connector. Future connectors should produce a
connector-neutral `SourceRecord` from `backend/app/services/connectors/` and
feed the same classify -> parse -> normalize -> dedup -> store pipeline instead
of creating a parallel transaction path.

Gmail sync now runs through the connector-driven ingestion path:

1. `GmailConnector` fetches backfill or incremental records from Gmail.
2. The connector returns `SourceRecord` values plus cursor, pagination, and
   coverage metrics. Backfills mark `coverage_complete=false` when Gmail
   reports more results than the configured cap; observed rows are never
   presented as proof that the provider query was exhaustive.
3. `IngestionCoordinator` verifies connector ownership and persists each eligible
   source record in an isolated savepoint before publishing its stored event.
4. Domain events and WebSocket sync events expose progress to the dashboard.
5. The parser pipeline remains the only owner of transaction extraction and storage.

Gmail access-token expiry is persisted with the encrypted token references.
Legacy accounts without an expiry refresh once on their next sync. Provider
pagination rejects repeated page tokens, and malformed individual messages are
reported with stable non-secret connector errors while transient and credential
failures still fail the sync for retry or reauthorization.

Google identity sign-in and Gmail consent remain separate. A rejected refresh
grant pauses automatic sync and the dashboard sends the user through the
read-only Gmail consent flow. A successful reconnect replaces the grant, clears
the connector error, and returns enabled automatic sync to the scheduler. OAuth
refresh failures are treated as terminal credential errors for the active job,
so the queue does not repeat an authorization request that requires user consent.

The owned disconnect workflow calls Google's token-revocation endpoint, removes
the local connector grant, and records a non-secret lifecycle audit event.
Provider failure never leaves future PFIS sync enabled: local access is removed
and the response marks remote revocation as unconfirmed so the user can review
Google Account permissions. Imported source and derived financial records are
retained until separate retention/deletion controls are used.

The legacy Gmail sync functions remain compatibility wrappers over this
coordinator so existing API routes and jobs keep the same public behavior.

## Multi-user Google and Gmail rollout

Google identity sign-in accepts any Google account with a verified email when
`GOOGLE_ALLOWED_EMAILS` is empty. That setting remains available as an
emergency deployment control, but individual user addresses must not be
committed to configuration examples or source code.

Sign-in and Gmail access are intentionally separate decisions:

1. Google sign-in requests only OpenID Connect identity scopes.
2. The signed-in user chooses `Connect Gmail` inside their own workspace.
3. Gmail requests the read-only Gmail scope and offline access for sync.
4. The callback verifies the granted read-only scope and links the mailbox to
   the authenticated OAuth transaction's PFIS user.

Each PFIS user can connect one Gmail mailbox. A same-mailbox reconnect refreshes
credentials without resetting its history cursor. A different mailbox cannot
silently replace the existing link, and a Google mailbox already owned by
another PFIS user is rejected without changing either account.
## Balance connectors

Balance providers implement the read-only `BalanceConnector` contract and return
`BalanceObservationBatch` values. `BalanceSyncService` validates that every
requested account is owned, active, and mapped to a provider account, resumes a
shared opaque pagination cursor when the source states agree, and delegates
append-only observation/cadence persistence to `BalanceObservationService`.
Each requested account must appear with its mapped provider account ID; omitted
accounts, mismatched identities, provider exceptions, and incomplete batches
mark coverage incomplete and write only non-secret audit metadata. No balance
connector is enabled by default; an institution/Account Aggregator adapter and
consent path must be selected before PFIS can expose provider observations in
production.

`GET /api/balance-provider/status` exposes this execution boundary to the
product: account mapping, last successful observation, cadence/freshness, and
coverage are visible without returning credentials. `refresh_supported` stays
`false` until a transport, consent lifecycle, and provider registry are wired;
the endpoint therefore cannot be used to mistake a transaction roll-forward
or an injected test connector for a live issuer amount.

Provider account identity is stored in `BalanceProviderAccountMapping`, not in
the legacy generic connector field. The mapping is unique per user/provider
identity and per owned financial account/provider pair. A provider adapter must
discover and verify the opaque account identity before calling the mapping
service; PFIS rejects duplicate identities and never accepts a full account or
card number as a mapping shortcut. Existing legacy IDs remain a read-only
fallback during migration and do not get overwritten by a provider-scoped map.

Discovery is an explicit optional registry capability. An adapter may register
an account-discovery factory; `GET /api/balance-provider/discovered-accounts`
then returns sanitized display/masked identity candidates with existing mapping
state. A provider without that capability fails closed with a conflict rather
than accepting a user-entered account key.

The connection lifecycle is now durable but non-secret. A provider adapter must
register a `BalanceConnectorRegistry` factory, complete consent through its
verified callback, and leave only the provider type, consent status/expiry,
refresh timestamps, and a one-way consent-reference hash in PFIS. The
`/api/jobs/balance-refresh` route creates an idempotent background job only for
an active consent and mapped owned accounts; a missing registry or consent is a
user-visible `409`, never a fake refresh.

Card-capable adapters may attach `CardPositionObservation` facts to the same
`BalanceObservationBatch`. The typed contract requires current outstanding and
permits independently absent billed due, pending, limit, or available-credit
fields. PFIS mirrors only current outstanding into the liability position and
retains the remaining issuer facts at
`/api/accounts/{account_id}/card-observations`; statement totals remain
historical evidence.

### ReBIT deposit adapter

`RebitDepositConnector` and `parse_rebit_deposit_payload` implement the
provider-neutral parsing boundary for ReBIT deposit FI type schema v2.0.0. The
adapter maps each owned PFIS account to the payload's opaque `linkedAccRef`,
reads `Summary.currentBalance`, `Summary.currency`, and
`Summary.balanceDateTime`, and carries the `Transactions.startDate`/`endDate`
window into source coverage. It produces a retry-stable, hashed source record
identity, preserves the provider-effective timestamp separately from retrieval
time, and marks the requested account incomplete when its evidence is missing
or malformed. A response containing ReBIT `PendingTxns` is retained as an
observation but remains coverage-incomplete because pending amounts are not
silently folded into the settled balance. Negative balances are rejected
rather than clamped because the current PFIS observation contract is
non-negative; overdraft and available-credit semantics need a typed extension.
The schema fields are
defined by the [official ReBIT deposit v2.0.0 specification](https://specifications.rebit.org.in/api_schema/account_aggregator/documentation/deposit_v2.0.0.html).

The adapter receives an injected payload fetcher so no provider credentials,
consent artifact, or raw XML is stored in this repository. A production
integration still needs an eligible Account Aggregator/FIP transport, consent
and revocation lifecycle, account discovery/mapping UX, encrypted payload
handling, rate-limit/retry policy, and independently attested bank cohorts.
Credit cards are intentionally not treated as deposits: their connector must
map issuer current outstanding, billed/remaining due, statement date, limit,
and available credit into the card-specific position contract before PFIS can
label those figures provider-observed.

`register_rebit_deposit_provider` is the explicit deployment hook for the
ReBIT adapter. It accepts a provider-owned payload fetcher (and optional
discovery factory), builds the account map from active PFIS provider mappings,
and registers the connector only for that deployment. No default registration
is made in local or demo mode.

## Classification

Source classification is connector-neutral. The Gmail `email_filter` module is a
compatibility facade over `services/classification`, which returns classification
type, confidence, matched signals, and a reason. Categories include transaction,
statement, OTP, promotion, investment, salary, refund, failed payment,
subscription, loan, and ignore.

## Connector Audit Events

Connector lifecycle and sync operations write non-secret audit events. These
events record connect, token refresh, sync started, sync completed, and sync
failed states without storing tokens, provider exception text, or full source
bodies. Source ownership mismatches never associate an audit record with another
user's connector.

## Database

Local development, CI, and hosted deployments use PostgreSQL 17. The local
database is provided by Supabase CLI; hosted environments use Supabase
PostgreSQL. Alembic remains the single application-schema authority.

## Dashboard

The canonical React/Vite dashboard is built into `frontend/dist` and served by
FastAPI. It consumes `/api` routes and must not bypass backend ownership rules.

## External Dependencies

Primary dependencies are listed in `backend/requirements.txt`. New dependencies require a clear need, tests, and documentation.
