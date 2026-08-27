# Deposit statement-line review and import

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10

## Scope

The HDFC and issuer-neutral deposit importers already proved account identity,
currency, explicit debit/credit direction, and the complete running-balance
chain. Rows whose narration did not prove UPI, debit card, ATM, or transfer
were retained as `needs_review`, but no API existed to resolve them. This slice
adds an owned review queue and an explicit classify/import-or-ignore mutation.

## Contract and safety gates

`GET /api/review/deposit-statement-lines` returns only the authenticated user's
unresolved rows, with account label/masked number, source dates, direction,
balance, and decision count. `PATCH /api/deposit-statement-lines/{line_id}/review`
accepts `ignore` or `import`. Import requires a user-selected `upi`,
`debit_card`, `atm`, or `transfer` rail; `other` remains review evidence and
cannot grant ledger permission.

The mutation re-checks ownership, account scope, unresolved state, exact
reference/amount/date matches, and transaction currency. A unique existing
match is linked; otherwise one transaction is created through the existing
transaction service in the same unit of work. Duplicate or ambiguous evidence
fails closed. The line outcome, selected rail, optional transaction, and
bounded note are recorded in a dedicated append-only decision table. Repeating
the same decision is idempotent; a conflicting decision on an already-resolved
line is rejected.

Deposit-line temporal snapshots now preserve rail and review changes for
cutoff-safe reconstruction and forward-only backfill, without storing source
PDF bytes or statement text.

## Verification

- Integration coverage proves unknown-row listing, wrong-user `404`, missing
  rail rejection, explicit transfer import, exact idempotent retry, ignore, and
  empty queue after resolution.
- Migration discipline advances the Alembic head to
  `055_deposit_line_review` and verifies ORM/schema parity.
- Full backend, Ruff, mypy, and inventory results are recorded in the delivery
  response.

## Remaining scale gap

This is still user-confirmed classification, not an unrestricted NLP fallback.
Unsupported rails, ambiguous duplicate matches, malformed statements, and
unreviewed layouts remain review-only. Representative bank/issuer cohorts,
provider-backed transaction coverage, and a frontend queue are separate gates.

Verdict: `PASS_WITH_RISKS` for explicit, auditable unknown-rail deposit review.
