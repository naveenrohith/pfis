# HDFC Deposit Statement Vertical Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-09  
Scope: automatic statement recognition, exact-profile HDFC deposit ingestion,
deposit source-line persistence, ledger/balance writes, and the React statement
intake workflow.

## Outcome

No blocking correctness, ownership, privacy, migration, accessibility, or API-
compatibility finding remains in this vertical. Automatic import is narrower
than recognition: only the reviewed HDFC card layout and one exact HDFC deposit
profile are write-enabled. Marker-compatible documents remain read-only.

The integrated reviewer runtime was unavailable after the permitted retry. The
main-task review therefore re-inspected the full slice and tightened three
boundaries before this verdict:

- marker-only credit-card documents no longer inherit the legacy fixture
  import permission through the automatic route;
- a concurrent document-fingerprint conflict resolves to the committed
  statement when possible;
- a nested transaction-service rollback cannot be swallowed as a harmless
  duplicate while the outer deposit import continues.

### Generic statement-family checkpoint — 2026-08-10

The read-only detector now also classifies strong non-HDFC credit-card and
bank/deposit shapes, including observed UPI, debit-card, ATM, and transfer
rails. These candidates carry a generic format ID and remain
`recognized_not_supported`; they cannot select an import parser or write ledger
rows. HDFC's reviewed card and deposit profiles remain the only automatic
write-enabled statement families. This improves preflight/account matching
without making a provider-wide support claim.

## Evidence

- Pure extraction proves masked suffix, period, opening balance, seven-column
  shape, valid dates, one direction per row, positive amounts, explicit rails,
  and cent-exact running balances before persistence.
- Service/API tests prove owned-account routing, text and PDF auto-dispatch,
  fingerprint idempotency, mismatch rejection, unknown-rail review, verified
  closing balance, induced mid-import rollback, and duplicate-race rollback.
- Migration 053 is current on both named local PostgreSQL databases; the fresh
  ORM/migration release gate passes.
- Frontend lint, 29 Vitest files / 73 tests, TypeScript production build, and
  desktop plus 360 px browser inspection pass. The browser console reported no
  warning or error.
- The current Vercel Web Interface Guidelines review found no actionable issue
  in the touched statement component: controls are labelled, async state is
  announced, actions use buttons, focus treatment comes from PFIS primitives,
  long filenames truncate, and mobile layout remains single-column.

## Residual risks

1. The deposit fixture is de-identified and grounded in HDFC's public column
   contract, but it is not a representative production statement cohort. The
   supported-layout claim must remain exact-profile only.
2. Concurrent fingerprint recovery is covered by deterministic rollback and
   conflict tests, not a two-connection PostgreSQL race test.
3. Reversal/refund, cheque, negative/overdraft balances, and alternate HDFC PDF
   text geometry are not write-enabled. They must fail closed or remain review
   evidence until new reviewed fixtures exist.
4. No connected-bank provider is configured. Statement closing balance is a
   verified source observation, not a live institution balance.

Verdict: `PASS_WITH_RISKS` for this bounded vertical. These risks block broad
production-layout claims, not the exact-profile implementation.
