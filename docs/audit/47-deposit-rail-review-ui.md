# Deposit statement rail-review UI

Status: `PASS_WITH_RISKS`

## Scope

The Statements workspace now consumes the user-owned deposit review queue and
shows unresolved bank rows with their account, masked suffix, statement period,
date, amount, direction, and balance context. A row cannot be imported until
the user explicitly selects UPI, debit card, ATM cash, or bank transfer. The
user can also hold the row outside the ledger without assigning an unsupported
rail.

The interaction is append-only through the existing backend review endpoint;
successful decisions invalidate the review queue, transactions, accounts, and
card/statement review dependents. The UI never infers a rail from description,
amount, or account type.

## Verification

- `DepositStatementReviewPanel.test.tsx`: rail selection is required before
  import and the mutation payload is explicit.
- `StatementImportSection.test.tsx`: statement intake remains compatible when
  the review queue is empty.
- Frontend lint, full tests, and production build are run with this slice.

## Residual risks

The review queue is intentionally bounded to the first 50 rows in one render;
the backend remains the source of truth for pagination/retention. Rail review
does not prove merchant identity or external settlement, and provider/cohort
evidence remains a separate release gate.
