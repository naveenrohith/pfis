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
- Production requires a unique `SECRET_KEY`, `AUTH_REQUIRED=true`, a non-SQLite `DATABASE_URL`, and non-local `CORS_ORIGINS`.

## OAuth

- Persist state in `OAuthState`.
- Enforce expiry.
- Delete used or expired state.
- Keep redirect URIs configured through settings.

## Frontend Safety

- Escape server-controlled values before HTML insertion.
- Do not inject raw email content into dashboard HTML.
- Avoid unsafe `innerHTML` unless the inserted fields are explicitly escaped.

## Financial Guidance and Workspace Privacy

- Guidance is deterministic and allowlisted; unsupported questions return supported examples.
- Do not persist or log raw coach queries, merchant-level telemetry, email bodies, tokens, or secrets.
- Recommendation state and dashboard preferences store only stable identifiers and validated settings.
- Account, balance, net-worth, transfer, preference, and guidance-state operations must resolve user ownership.
- Balance snapshots are append-only; corrections require a new dated snapshot rather than silent history edits.

## API Safety

- Preserve rate limiting for sensitive endpoints.
- Keep CORS scoped to configured origins and required methods/headers.
- Return generic errors for credential failures.

## Local Versus Production Mode

Local/demo mode keeps SQLite and optional auth available for fast development.
Production mode is explicit and fail-closed. Do not disable production validation
to work around deployment misconfiguration; fix the environment values instead.
