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

## OAuth

- Persist state in `OAuthState`.
- Enforce expiry.
- Delete used or expired state.
- Keep redirect URIs configured through settings.

## Frontend Safety

- Escape server-controlled values before HTML insertion.
- Do not inject raw email content into dashboard HTML.
- Avoid unsafe `innerHTML` unless the inserted fields are explicitly escaped.

## API Safety

- Preserve rate limiting for sensitive endpoints.
- Keep CORS scoped to configured origins and required methods/headers.
- Return generic errors for credential failures.

