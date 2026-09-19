# Card Payment Scenario Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: deterministic minimum-due/full-due comparisons on the card due runway

## Outcome

`GET /api/cards/{account_id}/due-runway` now returns a bounded
`payment_scenarios` envelope when an issuer total due and due date are known.
The envelope contains a `minimum_due` strategy when the issuer supplied a
minimum, plus a `total_due` strategy. Each strategy reports:

- issuer target amount and due date;
- existing planned-intention credit and any additional amount needed;
- effective hypothetical cash leaving the funding account;
- remaining billed total after that hypothetical plan; and
- expected, lower-band, and upper-band funding balances plus coverage/gap state
  when a supported funding path exists.

An existing planned intention is not treated as completed settlement. It is
credited toward the selected target to avoid double-counting a partial payment;
the effective amount is the larger of the target and the planned total. If the
funding account or balance anchor is missing, issuer amounts remain visible but
scenario affordability is `unavailable`.

## Evidence

- The covered runway regression verifies minimum/full scenarios, planned credit,
  additional payment, remaining billed due, and conservative post-payment cash.
- The missing-funding regression verifies both issuer scenarios are present but
  fail closed with `status=unavailable` and no numeric cash path.
- The response remains read-only: no payment intent, ledger transaction,
  statement, balance observation, or provider action is created.
- Focused card due-runway tests and Ruff/mypy checks pass.

## Residual risks

1. Scenario results are deterministic comparisons, not calibrated probabilities
   or advice about interest, fees, or issuer delinquency policy.
2. The payment date is the issuer-stated due date; the slice does not model an
   arbitrary earlier payment date or settlement latency.
3. Planned intentions are user-entered hypotheses. Provider confirmation,
   minimum-due policy changes, interest accrual, and live available credit still
   require a source-backed issuer integration.
4. A later UI slice can render the scenario rows beside the existing runway
   panel; the backend contract is additive and keeps current consumers valid.

Verdict: `PASS_WITH_RISKS` for the bounded card-payment decision envelope.
