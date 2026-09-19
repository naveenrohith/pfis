# Card Credit-Limit Runway Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: hard credit-limit pressure derived from the bounded daily projection

## Outcome

The next-statement card projection now keeps the user's utilization target
separate from the issuer-stated credit limit. It returns:

- `credit_limit_status`: `under_limit`, `at_risk`, or `over_limit`;
- central headroom or excess at projected close;
- the first central daily breach date and day offset; and
- the same hard-limit status on every `daily_path` point.

`at_risk` means the central path remains below the limit while the uncertainty
upper bound crosses it. `over_limit` means the central projected close is at or
above the limit. If either hard-limit state is present, the next state becomes
`reduce_spend_or_pay`; the user-target status remains independently visible.

## Evidence

- Existing target/headroom regressions now verify separate under-limit fields and
  the additive ruleset v9 contract.
- A high-balance pure projection regression verifies the central breach date,
  excess amount, daily status, and actionable next state.
- Focused projection tests, Ruff, mypy, and the repository-wide backend suite
  pass after the schema extension.

## Residual risks

1. The limit path is a deterministic estimate, not a calibrated probability
   interval or live available-credit signal.
2. Issuer holds, pending authorizations, settlement latency, fees, and provider
   coverage gaps can move real available credit independently of the ledger path.
3. The central breach date is a PFIS estimate and does not predict issuer decline
   behavior or credit-reporting consequences.
4. A later UI slice can render hard-limit status beside the daily utilization
   path; the backend keeps it additive for current consumers.

Verdict: `PASS_WITH_RISKS` for the bounded hard-limit runway extension.
