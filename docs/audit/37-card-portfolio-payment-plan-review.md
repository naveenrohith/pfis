# Card portfolio payment-plan review

## Scope

This review closes the gap between the existing single-card due runway and a
portfolio decision surface. PFIS now exposes
`GET /api/cards/portfolio/payment-plan`, a read-only comparison of minimum-due
and total-due scenarios for every active credit card.

## Evidence path

1. Each active card is evaluated through the existing `CardDueRunwayService`.
   Statement total/minimum due, due date, planned payment intentions, funding
   mapping, confidence, and reason codes remain per-card evidence.
2. Cards with the same selected funding account are grouped.
3. One `BalanceForecastService` path is built per funding account through the
   latest eligible due date (bounded by the existing 180-day horizon).
4. The base forecast already contains existing planned payment intentions. The
   simulator subtracts only each strategy's `additional_payment_amount` on the
   corresponding due date, then evaluates the lower band for shortfall.

The result includes per-card scenarios, target/additional/effective totals,
funding-path coverage, first lower-band shortfall dates, confidence, evidence,
and explicit review states. It does not create payment intents or ledger rows.

## Fail-closed boundaries

- Missing statement targets remain unavailable and reduce target coverage.
- Missing payment-account mappings never become spendable cash; the strategy is
  `needs_payment_account` when that is the only missing input.
- Missing or stale funding anchors/forecast points remain `needs_review` or
  `unavailable`.
- Shared funding paths are replayed once rather than summed from independent
  per-card balances.
- Rewards, fees, issuer settlement timing, and live available credit are not
  simulated by the payment-plan comparison. Explicit reward rules are consumed
  only by the separate purchase spend-routing preview; they never change a
  bill-payment target.

## Verification

- `tests/pytest/test_card_portfolio_payment_plan.py`: two-card shared-bank
  coverage and missing-funding fail-closed behavior.
- Focused result: 2 passed.
- Ruff and targeted mypy checks are clean.

## Remaining scale gap

The endpoint is deterministic and issuer/funding-evidence grounded, but it is
not a payment optimizer. Future work can add explicit user constraints (cash
reserve, payment date preference, fee/interest rules, and issuer settlement
timing) behind separate reviewed contracts, then compare constrained plans
without turning assumptions into bank guarantees. Purchase rewards remain
deliberately separate because card bill payments do not earn the card's spend
reward rate.
