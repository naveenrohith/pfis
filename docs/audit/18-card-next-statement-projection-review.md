# Card next-statement projection review

Status: **PASS_WITH_RISKS**

## Reviewed boundary

PFIS now returns and renders an explainable next-statement card projection. The
read model keeps issuer-stated due, current balance position, and forecast as
separate concepts. It projects only inside a current, regular billing cycle and
requires a current balance anchor, credit limit, and at least three settled
non-payment events.

## Correctness and safety evidence

- Purchases, fees, interest, taxes, refunds, cashback, and reversals use the
  shared liability-sign and settlement rules. Card payments are excluded from
  future spend pace because the current balance anchor already includes them.
- Old or irregular statement cycles, missing current positions, missing limits,
  and thin activity fail closed without returning a projected amount.
- Available projections include a range, confidence capped below certainty,
  ruleset version, reason codes, exact evidence rows, and an actionable next
  state.
- When evidence exists, the projection blends current-cycle pace with prior
  settled cycles, subtracts user-planned payments before close, and adds active
  card-EMI schedule installments due before close. It also surfaces early or
  mature merchant-cadence candidates expected before close, adds their bounded
  total once, widens uncertainty by their untrusted portion, and keeps
  overlapping scheduled EMI rows from being counted twice. Each adjustment is
  separately labelled in the API and Cards workspace.
- Pending refund lifecycle rows now contribute a bounded
  `potential_pending_refund_total` to the lower range only. The central
  statement estimate and target-breach path remain unchanged until settlement,
 and the Cards UI labels the potential credit as estimate-only.
- Recurring merchant candidates now carry `expected_amount_low` and
  `expected_amount_high` when at least three settled observations support amount
  drift. The central estimate remains the observed average; only the bounded
 amount envelope widens the uncertainty range and is labelled as estimate
 evidence in the API and Cards UI.
- Recurring merchant candidates also carry `expected_date_low` and
  `expected_date_high` when at least three settled observations show interval
 movement. The central path uses the median cadence date; the window is timing
 evidence, not an issuer commitment.
- Month-based recurring dates now advance by calendar cadence with safe month-end
  clipping. This removes fixed-day drift from the central date without treating
  the result as an issuer due date.
- Prior settled statement cycles now contribute a conservative calendar
  day-of-cycle profile when at least two cycles share positive movement on a
  future cycle day. The profile is shrunk toward the current pace, reports its
  sample/coverage counts, and widens uncertainty by observed day-level
  variation; it never claims issuer certainty.
- The projection now exposes a bounded `daily_path` through the projected close.
  Each point carries central/range balance, utilization, target state, and
  known dated event labels, reusing the same path that drives target-breach
  timing.
- When a user utilization target exists, the projection compares both its
  central close and uncertainty upper bound with that target. It exposes
  projected headroom, projected excess, or an `at_risk` status when only the
  uncertainty range crosses the threshold. It also reports the first central
  path breach date when the target is crossed before close, including planned,
  scheduled, and recurring candidate events.
- The Cards workspace now also exposes an explicit refund lifecycle tracker. Pending refund
  rows remain visible until a recognized settled status, posted totals are
  bounded to 90 days, and unknown lifecycle states are held for review without
  being treated as restored credit.
- The UI labels the result as a pace-based estimate rather than issuer evidence
  and provides specific recovery copy for every unavailable state.
- Twelve focused projection tests, 47 financial-position/card/refund API tests,
  the full backend suite (525 passed, 2 skipped), frontend lint, 30 files/77
  frontend tests, TypeScript, production build, and the executable integration
  inventory pass.

## Residual risks and deliberate limits

1. The ruleset v9 now blends current-cycle net pace with at least two prior
   settled card cycles when available, subtracts explicit user-planned payments
  scheduled before the estimated close, and adds bounded merchant-cadence
   candidates, bounds unsettled refunds to the lower side of the range, widens
   for bounded merchant amount drift, exposes observed timing envelopes, and
   applies a bounded calendar day-of-cycle blend when history qualifies, and
   exposes the same central/range path used for target-breach timing, and
   separately reports hard credit-limit status and central breach timing. It still
   does not model unobserved future EMI components.
2. The uncertainty range combines a deterministic gross-activity band with
   historical pace deviation; it is not a
   statistically calibrated prediction interval. It is labelled accordingly.
3. Confidence and range quality have unit/regression evidence but no
   representative production-card cohort or backtest yet.
4. The forecast/runway/refund panels passed component and build gates, but a fresh
   multi-viewport browser capture was not recorded after the target-runway
   fields were added.

No high-severity correctness, ownership, mutation, or compatibility finding is
open within this read-only projection boundary.
