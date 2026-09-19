# Card Daily Projection Path Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: bounded daily next-statement card trajectory and dated event labels.

## Outcome

The card projection now exposes `daily_path` from tomorrow through the
projected statement close (at most one regular 21–45 day cycle). Each point
contains a central balance, cumulative low/high range, projected utilization,
utilization-target state, and known dated event labels. Planned payments are
negative events; scheduled EMI and recurring candidates are positive events.

The path reuses the same seasonal/current daily pace and event map used by the
aggregate estimate and target-breach date. It does not create ledger events,
claim issuer scheduling, or synthesize available credit.

The projection now also evaluates the path against the issuer credit limit as
a separate hard-limit runway. `under_limit`, `at_risk`, and `over_limit` are
derived from the central close and uncertainty upper bound; the first central
breach date and per-day status are exposed without treating them as live
available credit.

## Evidence

- Pure projection coverage verifies path length, close-date termination,
  cumulative balances, range fields, and planned/scheduled/recurring labels.
- The card API regression verifies JSON serialization of the path and a
  recurring event label.
- Full backend tests, Ruff, mypy, inventory, and diff validation remain green.

## Residual risks

1. The path and hard-limit runway are deterministic estimates, not calibrated probability
   distribution; representative cohorts and matured outcomes remain required.
2. Event labels are bounded evidence from PFIS plans/cadences, not issuer
   confirmations. Provider pending/holds and unobserved future EMI components
   remain separate gaps.
3. The frontend currently consumes the aggregate projection; a later UI slice
   can render the daily path as a chart or timeline without changing the API
   contract.

Verdict: `PASS_WITH_RISKS` for the bounded daily trajectory extension.
