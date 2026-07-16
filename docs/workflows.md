# PFIS Workflows

## Demo Sync

1. `POST /api/gmail/demo-sync?user_id=...`
2. Store sample financial raw emails.
3. Track sync stats.
4. Process later via `/api/pipeline/process`.

## Gmail OAuth Sync

1. `GET /api/auth/gmail/connect?user_id=...`
2. Persist OAuth state.
3. Google redirects to callback.
4. Exchange code for tokens.
5. Encrypt and store token references.
6. Record a connector audit event.
7. `POST /api/gmail/sync` or auto-sync invokes the ingestion coordinator.
8. `GmailConnector` fetches records, `SourceRecord` values are classified and stored, then the parser pipeline processes them.

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
