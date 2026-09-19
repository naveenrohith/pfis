# Card spend-routing preview review

## Scope

This review closes the reward-aware/utilization-safe routing gap without
pretending that PFIS can quote issuer economics or execute a payment. The new
`POST /api/cards/portfolio/spend-routing` endpoint accepts one hypothetical
purchase amount, an optional category, and an explicit user priority:
`utilization_safety`, `rewards`, or `balanced`.

## Evidence path

1. Only active, user-owned credit-card accounts are considered, and the user's
   immutable ledger currency is returned as the request currency.
2. Current outstanding prefers the latest typed provider observation and falls
   back to the eligible ledger estimate. Credit limit prefers provider evidence
   and then the latest statement limit.
3. The hypothetical amount is applied to the immediate position and the
   bounded next-statement projection when available. Target headroom and hard
   limit headroom remain separate signed values; negative headroom is pressure,
   not authorization.
4. Reward rules are parsed defensively. Exact category rules outrank wildcard
   rules; invalid, out-of-range, or malformed rules never influence ranking.
5. Ranking is deterministic and stable by card ID after the explicit priority
   tie-breakers. A recommendation is emitted only when the hypothetical spend
   remains below the observed/estimated hard limit.

## Fail-closed boundaries

- Missing current position, credit limit, currency compatibility, or review-state
  balance evidence yields `needs_review` and no recommendation for that card.
- A proposed amount at or above the hard limit is `over_limit` and cannot be
  recommended, even when its explicit reward rate is highest.
- Crossing a user target is shown as `over_target`; it may remain eligible only
  when hard-limit headroom exists, and the selected priority decides whether a
  safer card wins.
- A missing projection is labeled as a current-balance proxy and lowers
  confidence; it is never described as an issuer statement forecast.
- Reward estimates apply only to the hypothetical purchase. They do not alter
  card payment plans, create ledger activity, or claim cashback/points will be
  awarded.

## Verification

- `tests/pytest/test_card_spend_routing.py` covers exact-category precedence,
  invalid-rule handling, deterministic reward/safety ranking, hard-limit
  pressure, no-active-card state, missing-evidence review, and user scoping.
- Focused result: 7 passed.
- Full backend result after this slice: 553 passed, 2 skipped.
- Ruff and targeted mypy checks are clean.

Verdict: `PASS_WITH_RISKS` for the explicit, read-only purchase-routing
decision surface. Provider cohort calibration, issuer reward catalogues, fees,
interest, and bank cash-path optimization remain separate release gates.
