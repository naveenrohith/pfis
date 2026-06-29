# REVIEW Agent

Use REVIEW after CODE, TEST, and QUALITY.

## Review Order

1. Confirm the change matches the user's request.
2. Check `docs/` alignment.
3. Check ownership and security boundaries.
4. Check parser/data/API compatibility.
5. Check redundancy/dead-code findings from QUALITY.
6. Check tests and validation output.
7. Identify remaining risks.

## Security Checklist

- No secrets in logs, responses, docs, tests, or committed env files.
- User-scoped routes call `resolve_user_scope` or ownership helpers.
- OAuth state, access tokens, and refresh tokens are handled safely.
- CORS, auth, and rate limiting are not weakened.
- HTML responses do not inject unescaped user-controlled data.

## Architecture Checklist

- Existing service boundaries are respected.
- Async database and SDK usage is safe.
- Parser registry remains deterministic.
- Raw email retention, DLQ, confidence scoring, and dedup behavior are preserved.
- API contract changes are reflected in schemas/docs/tests.

## Output

Lead with findings. If no issues are found, say so and mention any residual test gaps.
