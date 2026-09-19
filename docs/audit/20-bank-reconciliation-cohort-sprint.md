# Sprint 3 - Bank reconciliation cohort review

Status: PASS_WITH_RISKS  
Verified: 2026-08-09  
Scope: immutable verified-observation intervals and cross-account attribution

## Repository evidence

- Each newly newest verified balance observation creates at most one immutable
  interval; late historical observations do not rewrite prior evidence.
- Eligible transaction movement is signed from the account balance kind,
  excludes pending/unreviewed/ignored activity, and records both eligible and
  excluded IDs with reason codes.
- Queries are user- and financial-account-scoped. A transaction belonging to a
  different account cannot explain another account's closing balance.
- The protected exporter computes keyed cohort residual ratios and institution
  counts without exporting balances, movements, descriptions, or raw IDs.

Focused evidence:

```text
python -m pytest -q tests/pytest/test_balance_reconciliation.py
3 passed
```

## Unresolved promotion gate

The repository proves interval behavior on deterministic fixtures, not the
release cohort threshold. Promotion still requires at least 10 attested users,
100 intervals, 6 institutions, median residual <=1%, and p95 residual <=5%.
Until a reviewed cohort manifest exists, reconciliation-dependent guidance must
remain bounded and the strict evidence gate remains deferred.

