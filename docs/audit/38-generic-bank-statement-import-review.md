# Generic bank statement import review

## Scope

PFIS previously detected generic bank/debit/UPI statement shapes and exposed a
redacted row preview, but only the reviewed HDFC deposit profile could write
ledger evidence. This slice adds the issuer-neutral
`generic-deposit-tabular-v1` profile and routes it through the existing deposit
statement persistence workflow.

## Write-enable contract

The detector marks a generic deposit statement `supported` only when the pure
extractor proves all of the following:

- masked account suffix;
- statement period and opening balance;
- unambiguous date, description, debit, credit, and balance columns;
- one debit or credit per row, with positive amounts;
- every row inside the period; and
- cent-exact running-balance reconciliation from opening to closing balance.

Pipe-delimited and fixed-width rows are accepted only when their column order is
deterministic. Single-amount tables, missing identity, ambiguous debit/credit
direction, period drift, and balance drift remain `recognized_not_supported` or
fail closed. The source text is never persisted; detection and analysis responses
redact the account suffix, while the imported transaction keeps only the matched
last four digits for existing ledger provenance.

## Persistence and safety

Supported rows reuse the existing idempotent `DepositAccountStatement` /
`DepositStatementLine` workflow. Explicit UPI, debit-card, ATM, and transfer
rails can create transactions; unknown rails remain durable `needs_review` lines.
The selected bank account must be owned, active, confirmed, suffix-matched, and
currency-compatible. The closing balance becomes a verified account snapshot.
Fingerprint retries return the existing statement, and the complete operation
rolls back on an unexpected database or ledger failure.

## Verification

- `tests/pytest/test_generic_deposit_statement_extractor.py`: extractor proof,
  tampered-balance rejection, API dispatch, ledger rows, and idempotent retry.
- Focused generic statement and adjacent deposit result: 19 passed, 63
  deselected.
- Full backend result after the shared persistence refactor: 540 passed, 2
  skipped.
- Ruff passes for backend, tests, and scripts; mypy passes for all 159 backend
  source files; the worktree inventory reports 353 assigned packets and no
  unassigned changes.

## Remaining scale gap

This is a deterministic tabular profile, not OCR or unrestricted PDF inference.
Scanned/encrypted PDFs, layouts with a single signed amount column, and issuer
formats without explicit running balances remain review-only. New layouts should
be promoted through sanitized fixtures and parser-corpus evidence rather than
loosening the write gate globally.
