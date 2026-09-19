# Sprint 6 - Decisions and bounded learning review

Status: PASS_WITH_RISKS  
Verified: 2026-08-09  
Scope: constraint-aware recommendation ranking and outcome feedback

## Repository evidence

- Recommendations are ranked from deterministic financial evidence, conflicts,
  cash-plan readiness, goals, source coverage, and reversibility before any
  feedback is applied.
- User feedback is versioned through the decision/outcome records and has a
  minimum three-completed-outcome sample before it can affect ranking.
- Positive adaptation is capped at six priority points. Repeated negative
  outcomes put the feedback state in `drift`, add a visible
  `personalization_drift` reason, and force a bounded suppression/rollback
  adjustment rather than allowing another category to compensate.
- Cohort effectiveness remains privacy-safe and suppressed until at least 10
  outcomes from 5 users are available.

Focused evidence:

```text
python -m pytest -q tests/pytest/test_recommendation_policy.py tests/pytest/test_recommendation_decisions.py
5 passed
```

## Unresolved promotion gate

No production outcome cohort has been attested here. The adaptation code is a
bounded policy seam, not proof that recommendations are useful for a live
population. Strict promotion still requires protected, versioned outcomes,
conflict/safety review, and drift evidence; otherwise policy remains frozen or
deterministic-only.

