# Card utilization history review

Status: `PASS_WITH_RISKS`

## Scope

This slice closes the gap between the existing current-card projection and a
historical, explainable utilization view. `GET
/api/cards/{account_id}/utilization-history` returns:

- issuer-statement points based only on each statement's observed `total_due`
  and `credit_limit`;
- a bounded daily roll-forward from the latest statement using settled ledger
  movements, with payments reducing liability balance;
- separate user-target and hard-limit statuses, peaks, breach counts, trend
  basis, confidence, and reason codes.

The daily series is an estimate, not a live issuer balance or available-credit
claim. Pending, failed, and ignored transactions are excluded. Unreviewed
activity remains represented through a confidence reduction and explicit
reason code.

## Evidence and safety

The endpoint is read-only and account ownership is checked before any
statement or transaction data is read. It fails closed for missing accounts,
non-card accounts, and missing statement evidence. Statement history is kept
separate from ledger-estimated days so downstream consumers cannot mistake an
estimate for issuer truth.

## Verification

- `tests/pytest/test_card_utilization_history.py`: focused trend, roll-forward,
  ownership, account-type, and no-evidence coverage.
- Full backend, static, migration-parity, inventory, and diff checks are run
  before this slice is considered delivered.

## Residual risks

The estimate is not calibrated against provider current-balance observations,
and issuer feeds/OCR are still bounded by their reviewed extractor coverage.
Historical accuracy improves when more statements and settled ledger coverage
are available. Frontend rendering and cohort-level predictive calibration are
separate follow-up work.
