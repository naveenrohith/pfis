# Card Portfolio Upcoming-State Review

Status: `PASS_WITH_RISKS`  
Reviewed: 2026-08-10  
Scope: conservative multi-card next-state and issuer-due exposure

## Outcome

`GET /api/cards/portfolio/upcoming-state` composes the existing per-card
upcoming-state and position read models for every active credit card. It returns:

- the highest-priority portfolio state (limit pressure, target pressure, near-term
  due, review, monitoring, or no evidence);
- the earliest card-labelled dated event and a bounded event list;
- known issuer total due with the number of cards contributing and a completeness
  flag; and
- per-card due, projection, position, confidence, and review states.

An estimated outstanding total is returned only when every active card has an
eligible non-review position. Available credit is never totaled as a live
portfolio value, and the service never combines issuer facts into a synthetic
card or performs a payment.

Grounded Guidance recognizes explicit cross-card questions such as “what is
coming up across my cards?” and uses `current_card_cycle` with the same safety
labels.

## Evidence

- `tests/pytest/test_card_portfolio_upcoming.py` verifies two-card due aggregation,
  earliest card-labelled event, per-card preservation, and Guidance integration.
- Ruff and mypy pass for the new service, schema, route, and Guidance dispatch.
- The endpoint reuses `CardOverviewResponse` and `build_card_upcoming_state`; it
  creates no persistence or external side effects.

## Residual risks

1. Portfolio totals remain incomplete when any issuer omits a due or position;
   the response exposes coverage rather than filling the gap.
2. Purchase routing based on explicit reward rules and utilization priorities is
   now covered by the separate read-only spend-routing preview. Bank cash paths,
   fees, and card-payment execution remain outside that purchase surface.
3. Provider-backed issuer observations and representative cohorts remain release
   gates for intelligence scoring.

Verdict: `PASS_WITH_RISKS` for the multi-card upcoming-state read model.
