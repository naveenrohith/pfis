# Report 11: Engineering Standards

## Executive Summary

This report defines the engineering standards PFIS should use while moving from structured MVP to production candidate. The goal is not process overhead. The goal is to protect parser correctness, financial data integrity, security, and maintainability.

## Evidence Base

- `backend/app/api/routes/` shows the current route organization that should remain thin.
- `backend/app/services/` shows where business workflows belong.
- `backend/app/services/parser/base_parser.py` defines the parser contract.
- `backend/app/security.py` defines current auth, ownership, password, JWT, and encryption helpers.
- `backend/app/observability.py` defines request-id logging.
- `tests/pytest/` shows the expected test location.
- `.github/workflows/ci.yml` shows the current quality gate.

## Strengths to Preserve

- PFIS already has explicit docs, tests, CI, and clear module names.
- Security helpers are centralized instead of scattered through routes.
- Parser behavior has a structured output type.
- Request correlation exists and should remain part of every backend change.

## Risks These Standards Address

| Risk | Severity | Impact | Standard Response |
| --- | --- | --- | --- |
| Parser regression | High | Wrong financial data | Fixture-backed parser tests |
| Cross-user data leak | High | Security failure | Mandatory scope and ownership checks |
| Production config misuse | High | Deployment risk | Fail-closed production settings |
| Route/service drift | Medium | Maintainability | Thin routes and service-owned workflows |
| Sensitive logging | Medium | Privacy risk | No secrets, tokens, or full email bodies in logs |

## API Standards

- Keep routes thin.
- Put business behavior in services.
- Use Pydantic schemas for request and response shapes.
- Preserve route paths and response contracts unless a migration is documented.
- Enforce user scope through `resolve_user_scope` or ownership helpers.
- Add tests for success, validation failure, authorization failure, and ownership failure.

## Parser Standards

- Parser modules extract data only; they do not write database rows.
- Every parser change must include regression fixtures.
- Prefer bank-specific rules over broad generic regex.
- Keep `ParseResult` fields stable unless all downstream users are updated.
- Record failed parses instead of dropping them silently.
- Track parser version and confidence.
- Treat fallback parser results as lower trust unless confidence and review policy allow acceptance.

## Service and Domain Standards

- Services should own workflow behavior, not HTTP details.
- Avoid large functions that mix classification, parsing, normalization, persistence, and error handling.
- Introduce abstractions only when they reduce real complexity or make tests clearer.
- Keep connector-specific behavior out of transaction-domain services.
- Keep financial calculations deterministic and test-backed.

## Data Standards

- All user-owned data must be scoped by user id or ownership checks.
- Raw source records should be retained for reprocessing.
- Transaction deduplication must be deterministic and tested.
- Schema changes require migration review.
- Production-like environments should use Alembic migrations, not implicit table creation.
- Sensitive tokens must be encrypted at rest.

## Logging and Error Handling Standards

- Logs must include request id where request context exists.
- Never log tokens, OAuth codes, full email bodies, passwords, or raw credentials.
- Merchant and transaction details should stay out of INFO logs unless deliberately reviewed.
- Use structured error categories for connector, parser, validation, authorization, and data integrity failures.
- Job errors should be persisted in job records and visible to callers.

## Security Standards

- Default development secrets are acceptable only for local/demo use.
- Production must require unique `SECRET_KEY` and token encryption configuration.
- Authentication-required mode must fail closed.
- All cross-user access must be denied.
- OAuth state must expire and be validated.
- CORS origins must be explicit for deployed environments.

## Testing Standards

- Run `make check` before merge.
- Parser changes require parser regression tests.
- API changes require endpoint tests.
- Security changes require negative tests.
- Job and sync changes must not call real Gmail in tests.
- Report changes require CSV/HTML contract tests.
- Database changes require migration review and model behavior tests.

## Performance Standards

- Measure before optimizing.
- Keep expensive aggregations server-side and indexed.
- Avoid repeated full-table scans in request paths.
- Keep Gmail sync limits explicit.
- Add timing metrics around sync, parse, and report generation before scaling.

## Documentation Standards

- `docs/` remains the source of truth.
- Update docs when changing architecture, APIs, parser behavior, data models, security, testing, or workflows.
- Add architecture decision records for major irreversible decisions.
- Keep audit reports as planning documents; implementation docs should live beside the relevant domain docs.

## Code Review Checklist

- Does the change preserve user scope and ownership?
- Are parser and transaction changes covered by tests?
- Does the change avoid logging sensitive data?
- Are database changes migrated and documented?
- Does the service boundary remain clear?
- Are docs updated when behavior changes?
- Does CI pass?
- Is rollback straightforward?

## Validation Strategy

Use this standards document during planning, code review, and modernization phase acceptance. It should be updated when PFIS changes its deployment target or architecture materially.

## Migration Guidance

Apply these standards incrementally. New code should follow them immediately. Existing code should be brought into compliance when it is touched for functional work or when a modernization phase targets that subsystem.

## Rollback Strategy

If a standard proves too strict for current development, document the exception and define when it will become mandatory instead of silently ignoring it.
