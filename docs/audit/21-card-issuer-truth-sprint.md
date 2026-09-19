# Sprint 4 - Credit-card issuer truth review

Status: PASS_WITH_RISKS  
Verified: 2026-08-09  
Scope: typed issuer observations, card position reads, and payment linkage

## Repository evidence

- Card observations preserve independent issuer facts: current outstanding,
  billed due, pending amount, credit limit, and available credit. Missing fields
  remain `null`; PFIS does not derive them from statement totals or estimates.
- Only provider current outstanding updates the generic liability position.
  Statement due and available credit remain typed card facts.
- Provider source identity and account mapping are required before a card
  observation can be ingested, preventing a user-facing route from fabricating
  a connector observation without a mapped issuer account.
- Card payment intentions remain explicit, user-owned plans and are linked to a
  funding account; they are never reported as completed issuer payments.

Focused evidence:

```text
python -m pytest -q tests/pytest/test_balance_sync.py
10 passed
python -m pytest -q tests/pytest/test_card_due_runway.py tests/pytest/test_card_statement_projection.py
<focused card suites pass in the Sprint 4 release run>
```

## Unresolved promotion gate

The repository contains a provider-neutral issuer contract and deterministic
fixtures, but no issuer transport, production statements, or representative
card cohort. The strict card-truth gate therefore remains deferred. The UI and
guidance must distinguish provider-observed, statement-observed, estimated, and
unavailable amounts and must not promise live credit-card balances until an
eligible provider path is approved.

