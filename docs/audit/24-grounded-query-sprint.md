# Sprint 7 - Grounded financial query review

Status: PASS_WITH_RISKS  
Verified: 2026-08-09  
Scope: supported query planning, evidence citations, arithmetic/temporal limits, and refusal

## Repository evidence

- Queries are classified into a finite typed intent plan before any read model
  is queried. Unsupported questions return a safe refusal without touching
  financial data.
- Supported answers now return the plan steps, selected temporal scope,
  source-type citations, cutoff, confidence, and explicit uncertainty.
- Position answers preserve observed/estimated/provider-live wording and refuse
  spendability conclusions when coverage, freshness, or reconciliation is
  incomplete.
- Arithmetic remains server-owned; query text cannot supply a balance, due
  amount, or confidence value.

Focused evidence:

```text
python -m pytest -q tests/pytest/test_premium_workspace.py
5 passed
```

## Unresolved promotion gate

This is a deterministic query contract, not a claim of broad conversational
reasoning. A reviewed critical-intent set, grounded-answer accuracy, citation
completeness, refusal quality, and end-to-end task success are still required
before the query dimension can contribute its target score.

