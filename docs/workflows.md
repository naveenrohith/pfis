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
6. `POST /api/gmail/sync` fetches raw emails.

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

