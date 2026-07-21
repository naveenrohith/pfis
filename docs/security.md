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
- Production requires a unique `SECRET_KEY`, `AUTH_REQUIRED=true`, a non-SQLite `DATABASE_URL`, non-local `CORS_ORIGINS`, secure cookies, and demo login disabled.

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
- Persist state in `OAuthState`, bind it to a short-lived `HttpOnly` browser cookie, enforce expiry and flow type, and delete it before exchanging the authorization code.
- Use PKCE for both Google flows and verify the OpenID Connect nonce, issuer/audience, stable `sub`, and `email_verified` claim.
- Link Google identities by provider `sub`, never by email alone. An existing password account requires an explicit account-linking flow.
- Keep both redirect URIs configured through settings and registered exactly with Google.

## Frontend Safety

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

## API Safety

- Preserve rate limiting for sensitive endpoints.
- Keep CORS scoped to configured origins and required methods/headers.
- Return generic errors for credential failures.
- Validate connector-account ownership again inside ingestion services; route
  authorization alone is not a sufficient trust boundary for workers.
- Persist and broadcast stable connector/job error categories only. Provider
  exception text may contain credentials, source details, or request metadata
  and belongs neither in API responses nor durable operational records.

## Local Versus Production Mode

Local/demo mode keeps SQLite and optional auth available for fast development.
Production mode is explicit and fail-closed. Do not disable production validation
to work around deployment misconfiguration; fix the environment values instead.
