# CODE Agent

Use CODE after PLANNER has identified the target behavior and affected files.

## Python/FastAPI Standards

- Prefer existing modules and services over new layers.
- Keep route handlers thin when service logic already exists.
- Use Pydantic schemas for request and response contracts.
- Use dependency injection for `AsyncSession` and current-user resolution.
- Keep async paths non-blocking; wrap unavoidable blocking SDK calls with a thread boundary.
- Use structured, parameterized logging where possible.
- Never log secrets, OAuth codes, raw tokens, passwords, or full email bodies.

## Data Access

- Use `AsyncSession` with SQLAlchemy `select`, `await db.execute(...)`, and explicit commits.
- Keep user filters in queries for user-owned resources.
- Use service methods for transaction creation, deduplication, correction learning, and deletion.
- For model changes, update docs and migrations when the project has migration coverage.

## Parser And Pipeline Rules

- Parser output is `ParseResult`.
- Minimal valid parse requires amount and transaction type.
- Confidence scoring must remain explainable and deterministic.
- Bank-specific parser changes belong in `backend/app/services/parser/bank_parsers.py` or related parser modules.
- Normalize merchant names through `normalizer.py`; invalidate cache after merchant mutations.
- Store parse failures in the DLQ model instead of silently dropping errors.

## Frontend Rules

- Keep dashboard behavior tied to documented API contracts.
- Escape server-controlled strings before inserting HTML.
- Preserve loading, error, empty, and auth states.
- Avoid unrelated design rewrites during backend or parser tasks.

## Documentation

Update docs when changing:

- API routes or response shape
- Data models or migrations
- Parser behavior or confidence rules
- Gmail/OAuth flow
- Security posture
- Dashboard workflows

