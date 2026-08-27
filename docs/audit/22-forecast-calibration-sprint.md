# Sprint 5 - Forecast calibration review

Status: PASS_WITH_RISKS  
Verified: 2026-08-09  
Scope: immutable account forecast snapshots and leakage-safe outcome evaluation

## Repository evidence

- Forecast snapshots freeze the ruleset, cutoff, evidence, assumptions, path,
  and starting-balance basis; duplicate snapshot requests are idempotent.
- Outcomes only use verified observations strictly after the snapshot cutoff,
  and each snapshot/date pair is immutable.
- Evaluation now reports median absolute percentage error, interval coverage,
  explicit thresholds, and a fail-closed calibration status:
  `insufficient_sample`, `within_threshold`, or `drift`.
- A drift result is evidence to disable forecast-dependent promotion; it is not
  silently averaged away by confidence or a different horizon.

Focused evidence:

```text
python -m pytest -q tests/pytest/test_balance_forecast_accountability.py tests/pytest/test_balance_forecast.py
5 passed
```

## Unresolved promotion gate

The calibration status is currently account-scoped and fixture/cohort evidence
is not matured. Strict promotion still requires at least 5 representative users,
3 matured periods, MAPE <=20%, interval coverage >=70%, transaction-history
coverage >=95%, and a verified protected cohort manifest. Until then, forecasts
remain explicitly uncertain and must not be used as provider-live balances.

