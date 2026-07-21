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
2. Store sample financial raw emails.
3. Track sync stats.
4. Process later via `/api/pipeline/process`.

## Gmail OAuth Sync

1. After sign-in, the user explicitly chooses `GET /api/auth/gmail/connect?user_id=...`.
2. Request identity plus read-only Gmail scope and offline access; this consent is separate from sign-in.
3. Persist browser-bound OAuth state, encrypted PKCE verifier, nonce, flow type, and expiry.
4. Google redirects to callback; PFIS validates and consumes the transaction.
5. Exchange code for tokens and verify the Google identity.
6. Encrypt and store token references, preserving an existing refresh token if Google does not issue a new one.
7. Record a connector audit event.
8. `POST /api/gmail/sync` or auto-sync invokes the ingestion coordinator.
9. `GmailConnector` fetches records, `SourceRecord` values are classified and stored, then the parser pipeline processes them.

## Automatic Sync

1. Scheduler finds due connected Gmail accounts.
2. Incremental sync uses the saved Gmail history cursor when possible.
3. Expired cursor falls back to a bounded recent query.
4. Transient connector failures retry with bounded backoff.
5. Permanent credential failures pause auto-sync and surface an error state.
6. WebSocket events update the dashboard live; polling remains a fallback.

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

Reports use stored transactions and insights. CSV export returns monthly transaction rows. Monthly HTML report is printable and must escape or control server-rendered content.
