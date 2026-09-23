# PFIS Security

## Ownership

User-scoped endpoints must use:

- `get_current_user_optional`
- `resolve_user_scope`
- `ensure_user_owns_resource`

When `AUTH_REQUIRED=false`, local/demo mode may accept `user_id`, but authenticated requests must never access another user's data.

## Secrets

- Never commit real `.env` secrets.
- Never log Google OAuth codes, access tokens, refresh tokens, passwords, encryption keys, or full raw emails.
- Store OAuth tokens encrypted through `encrypt_secret`.
- Rotate any credentials that were committed or shared.
- Set `ENVIRONMENT=production` for deployed environments so startup validates production-safe settings.
- Production requires a unique `SECRET_KEY`, `AUTH_REQUIRED=true`, a PostgreSQL
  `DATABASE_URL`, non-local `CORS_ORIGINS`, secure cookies, and demo login disabled.
- Keep `GOOGLE_ALLOWED_EMAILS` empty for normal multi-user production access.
  Use a non-empty value only as an emergency deployment-level sign-in restriction;
  never commit personal addresses in repository configuration.

## Browser Sessions and Passwords

- Browser authentication uses a high-entropy opaque session token in an `HttpOnly`, `SameSite=Lax` cookie. Only its SHA-256 hash is stored in `AuthSession`.
- A separate readable CSRF cookie is bound to the server session. Cookie-authenticated mutations must echo it in `X-CSRF-Token` and pass the same-origin request check.
- Logout revokes the server-side session before clearing both browser cookies. Sessions have absolute and idle expiry limits.
- API responses use `Cache-Control: no-store`; browser tokens must never be copied to `localStorage` or `sessionStorage`.
- Passwords use Argon2id. A successful login transparently upgrades legacy PBKDF2 hashes.
- Production session cookies must use the `__Host-` prefix, `Secure`, path `/`, and no `Domain` attribute.
- Signed bearer JWTs remain an API compatibility mechanism; they are not returned by browser login or registration.

## OAuth

- Google sign-in requests identity scopes only (`openid`, email, profile). It does not request Gmail access.
- Gmail connection is a later, explicit workflow that separately requests read-only Gmail scope and offline access.
- Gmail disconnect attempts provider revocation, always removes the local
  connector grant, stops future sync, and records only non-secret outcome
  metadata. Imported evidence is retained explicitly rather than silently
  deleted with the connection.
- Persist state in `OAuthState`, bind it to a short-lived `HttpOnly` browser cookie, enforce expiry and flow type, and delete it before exchanging the authorization code.
- Gmail OAuth states carry the owner's persisted connection generation. Disconnect and account deletion increment that generation and delete pending Gmail states; the callback locks the owner row and rejects stale or inactive intents before storing credentials, revoking any unclaimed provider grant.
- Use PKCE for both Google flows and verify the OpenID Connect nonce, issuer/audience, stable `sub`, and `email_verified` claim.
- Link Google identities by provider `sub`, never by email alone. An existing password account requires an explicit account-linking flow.
- Keep both redirect URIs configured through settings and registered exactly with Google.
- Gmail callbacks require the granted `gmail.readonly` scope before persisting
  credentials. They permit same-mailbox reconnects, reject mailbox replacement,
  and reject a Google subject already owned by another PFIS user without
  overwriting tokens or sync cursors.
- The Gmail connection status is derived from the owner-scoped account record;
  a revoked/invalid authorization is surfaced as reauthorization-required.
- `gmail.readonly` is a restricted Google scope. Public Gmail rollout requires
  Google's OAuth verification and any required security assessment before
  inviting general users.

## Frontend Safety

Sync WebSockets accept configured origins or the exact HTTP host serving PFIS;
production same-host origins must use HTTPS. Session ownership remains mandatory,
query tokens remain rejected in production, per-user connection limits apply,
and client heartbeats remain size limited.

The durable change-replay endpoint resolves the authenticated user scope and
returns only that user's ordered event metadata. WebSocket change hints contain
no transaction, balance, statement, or account values; every API process filters
delivery by the event's `user_id`. The browser stores only a versioned,
user-keyed replay cursor in `sessionStorage` (never an auth token), and a
`BroadcastChannel` hint is accepted only for the same user before making an
authenticated replay request. Journal retention is 90 days; pruning removes
only invalidation metadata, not source financial records.

- Escape server-controlled values before HTML insertion.
- Do not inject raw email content into dashboard HTML.
- Avoid unsafe `innerHTML` unless the inserted fields are explicitly escaped.
- Serve dashboard files only after resolving and confirming that their paths remain inside `frontend/dist`.
- Production startup must fail when the canonical React build is absent; never serve the retired static dashboard as an authentication fallback.

## Financial Guidance and Workspace Privacy

- Guidance is deterministic and allowlisted; unsupported questions return supported examples.
- Do not persist or log raw coach queries, merchant-level telemetry, email bodies, tokens, or secrets.
- Recommendation state and dashboard preferences store only stable identifiers and validated settings.
- Account, balance, net-worth, transfer, preference, and guidance-state operations must resolve user ownership.
- Balance snapshots are append-only; corrections require a new dated snapshot rather than silent history edits.
- Balance-provider connections persist only provider type, consent status/expiry,
  refresh timestamps, stable error codes, and a one-way consent-reference hash;
  raw consent artifacts and credentials never enter PFIS. Typed card issuer
  facts are append-only, source-scoped, and current outstanding is the only
  field allowed to update the liability position.
- Provider account mappings are separate from Gmail and other generic connector
  identities. They contain only the opaque provider account key needed to
  verify observation lineage, are unique within a user's provider connection,
  and are available only to that user. Discovery adapters return masked/display
  candidates; full account or card numbers are not accepted as mapping inputs.
- Forecast capture is an explicit user-scoped write. Snapshots preserve the
  original aggregate prediction/evidence without raw source content; outcomes
  are separate one-to-one records and cannot overwrite predictions. Both are
  included in portable export and owned account deletion.
- Recommendation decisions are accepted only for a currently recomputed,
  user-owned recommendation ID. Preserved evidence is aggregate-only; free-form
  decision/outcome notes are bounded to 500 characters. Outcomes require the
  same owner and cannot be overwritten with a different result.
- Statement PDFs follow extract-then-delete retention. PFIS prefers embedded
  text and, when enabled, renders a bounded page set for local OCR entirely in
  memory. It stores structured values, SHA-256 fingerprint, extractor version,
  and review evidence only; it does not retain PDF bytes, rendered images,
  passwords, full card numbers, addresses, or contact data. OCR output still
  has to pass the strict issuer/generic extractor before any ledger write.
- Statement imports, line review, card plans/disputes, account positions,
  commitments, reserves, liabilities, bills, and household resources all
  resolve the authenticated user scope before reads or writes.
- Statement-review decisions and confirmed liability schedules are append-only
  evidence. Existing decisions/schedules are not destructively replaced.
- Household data is a separate annotation/settlement domain. Another member
  cannot see private accounts, transactions, source emails, statement lines, or
  transaction evidence through household APIs. Viewer members cannot mutate.
- Household deletion and member removal are owner-only and are blocked until
  affected planned settlements are resolved.
- Portable exports require authenticated user-scope resolution and CSRF
  protection, are rate-limited, and return `Cache-Control: no-store`. Their
  versioned manifest exposes the complete exported field inventory and
  checksums. Password hashes, auth sessions, OAuth state/verifiers/nonces,
  Gmail credentials, and transient worker leases are excluded by explicit
  allowlists rather than post-generation redaction.
- Shared-household export is limited to the annotation/settlement domain.
  Other members' identifiers are replaced with stable archive-local aliases;
  their accounts, transactions, emails, statements, and evidence are never
  traversed.
- Processed raw-email content follows an owned, versioned retention policy.
  New users default to 365 days and may choose 30/90/180/365 days or explicit
  keep-until-deleted. Shortening the policy requires a destructive confirmation.
- Retention clears sender, subject, and body irreversibly but preserves source
  IDs, timestamps, parser evidence, and transaction lineage. Unresolved parse
  failures are never redacted; each completed redaction writes a non-secret,
  idempotent audit event without copying source content into logs or payloads.
- Account deletion is CSRF-protected, limited to 3 attempts/hour, bound to the
  authenticated user, and requires a non-demo browser session created within
  15 minutes plus the exact `DELETE <email>` phrase. Bearer-only authorization
  is insufficient for this irreversible operation.
- Deletion first commits a user-scoped write fence. Authentication and new jobs
  reject that user, registered in-flight jobs/manual ingestion are cancelled,
  and automatic sync is disabled before provider revocation or erasure begins.
  Deletion never logs decrypted credentials, removes every
  identity/session/private record, and clears browser cookies. Provider
  unavailability is reported without blocking local erasure.
- Shared household evidence retains only a non-login participant tombstone.
  Its personal profile and all private ledger/source data are erased; remaining
  members keep auditable expenses and settlements. No account recovery is
  available after the deletion transaction commits.

## API Safety

- Preserve rate limiting for sensitive endpoints.
- Keep CORS scoped to configured origins and required methods/headers.
- Return generic errors for credential failures.
- Validate connector-account ownership again inside ingestion services; route
  authorization alone is not a sufficient trust boundary for workers.
- Persist and broadcast stable connector/job error categories only. Provider
  exception text may contain credentials, source details, or request metadata
  and belongs neither in API responses nor durable operational records.
- Pipeline record and request failures follow the same rule: API responses,
  per-record statistics, logs, and parse-failure rows expose only stable public
  categories and exception types, never raw exception messages.
- WebSocket upgrades must use an allowed origin and a revocable browser session
  in production. Query-string bearer tokens, oversized frames, and excess
  per-user connections are rejected; slow clients are isolated from broadcasts.

## Local Versus Production Mode

Local/demo mode uses local Supabase PostgreSQL and may keep authentication
optional for fast development. Production mode is explicit and fail-closed. Do
not disable production validation to work around deployment misconfiguration;
fix the environment values instead.
