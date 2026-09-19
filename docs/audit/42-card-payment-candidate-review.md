# Card-payment funding candidate review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10

## Scope

Statement card-payment lines previously remained `needs_review` until the user
manually chose a bank account. PFIS could create the transfer safely, but the
review surface did not use the user's existing bank-debit evidence to narrow
that choice. This slice adds the read-only
`GET /api/statement-lines/{line_id}/payment-candidates` surface.

## Candidate contract

The endpoint is user-scoped and returns at most ten same-currency, active-bank
debit transactions within five calendar days of the statement payment line and
with the exact amount. A candidate must have explicit card-payment wording
(`CREDIT CARD`, `CARD PAYMENT`, `CARD BILL`, `CC PAYMENT`, or settlement wording)
or a matching statement reference plus payment wording. Amount and date alone
are deliberately insufficient.

Each result exposes the paying account, masked number, transaction description,
reference, deterministic match method (`reference`, `same_day_amount`, or
`near_day_amount`), confidence, and bounded evidence codes. Results are sorted
by score and stable transaction identity. The endpoint never creates a
transaction, transfer, statement match, or review decision. The existing
`record_card_payment` mutation still requires the user to choose the bank
account and remains the only write path.

## Verification

- Generic-card import regression now creates a same-day, same-reference bank
  debit and unrelated same-amount noise; only the explicit card payment is
  returned.
- The candidate is confidence-capped, user-owned, and read-only; another user
  receives `404` for the statement line.
- Focused generic-card suite: 7 passed.
- Full backend suite after this slice: 560 passed, 2 skipped.
- Ruff and targeted mypy checks are clean.

## Remaining scale gap

The endpoint does not auto-pair ambiguous transfers, infer a bank account from
amount/date alone, or contact a provider. Issuer/provider transaction feeds,
representative posting-date cohorts, and user confirmation remain required
before any automatic transfer-linking policy is considered.

Verdict: `PASS_WITH_RISKS` for evidence-ranked, read-only card-payment review.
