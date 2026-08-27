# Card Calendar Seasonality Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: bounded day-of-cycle spending seasonality in the next-statement card
projection.

## Outcome

The next-statement projection no longer assumes that every future day has the
same spend pattern when prior statement cycles provide stronger timing evidence.
At least two valid prior cycles are aligned by statement-cycle day. Positive
liability movement observed on the same future day is blended 35% with the
historical signal and 65% with the current pace. Quiet or under-sampled days
fall back to the flat pace.

The response exposes `seasonal_sample_count`, `seasonal_days_covered`, explicit
reason codes, evidence, and an uncertainty contribution. The central result
remains a PFIS estimate; no issuer balance, due date, or payment is inferred.

## Evidence

- Pure projection tests prove the central path changes only for a qualifying
  future cycle day, while the current pace remains the dominant component.
- The card API test imports three statement cycles and verifies that prior
  cycles flow through the service into seasonal sample/coverage fields.
- The existing projection, card API, full backend suite, Ruff, mypy, inventory,
  and diff checks remain green.

## Residual risks

1. The profile is deterministic and shrinkage-bounded, not a statistically
   calibrated seasonal model; representative card cohorts and backtests remain
   required before promotion.
2. Only positive settled liability movement is used. Merchant/category,
   weekday, holiday, and calendar-month effects remain future refinements.
3. Provider issuer truth and unobserved future EMI components remain external or
   separately scoped evidence gaps.

Verdict: `PASS_WITH_RISKS` for the explainable seasonal extension. The existing
fail-closed projection and import boundaries remain intact.
